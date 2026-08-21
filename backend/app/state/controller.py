from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from uuid import uuid4

from app.provenance.ledger import ProvenanceLedger
from app.provenance.models import ArtifactState, LabelEnforcementRecord, TaintClass
from app.provenance.projection import ProvenanceGraph, build_conservative, build_tight
from app.verification import Certificate, CertificateChecker, RuntimeCheckStatus, RuntimeWitnessChecker


@dataclass(frozen=True)
class ResidualCheck:
    status: str
    residual_versions: frozenset[str]
    exhaustive: bool


@dataclass(frozen=True)
class RetentionResult:
    certificate: Certificate
    proposed: frozenset[str]
    vetoed: frozenset[str]
    retained: frozenset[str]


class StateController:
    """Runtime state authority; graph reads are projections, state writes are transitions."""

    def __init__(self, ledger: ProvenanceLedger, run_id: str) -> None:
        self.ledger = ledger
        self.run_id = run_id

    def graphs(self, visible_inputs: dict[str, tuple[str, ...]] | None = None) -> tuple[ProvenanceGraph, ProvenanceGraph]:
        return build_conservative(self.ledger, self.run_id, visible_inputs=visible_inputs), build_tight(self.ledger, self.run_id)

    def classify(self, sink_versions: set[str]) -> dict[str, TaintClass]:
        conservative, _ = self.graphs()
        reachable: set[str] = set()
        for sink in sink_versions:
            reachable.add(sink)
            reachable.update(conservative.ancestors(sink))
        low_sources = {version_id for version_id, artifact in conservative.versions.items() if artifact.integrity == "low"}
        contaminated: set[str] = set()
        for version_id in conservative.versions:
            if (conservative.ancestors(version_id) | {version_id}) & low_sources:
                contaminated.add(version_id)
        out: dict[str, TaintClass] = {}
        for version_id, artifact in conservative.versions.items():
            if version_id in contaminated:
                out[version_id] = TaintClass.CONTAMINATED_REACHABLE if version_id in reachable else TaintClass.CONTAMINATED_UNREACHABLE
            else:
                out[version_id] = TaintClass.CLEAN
        return out

    def runtime_check(
        self,
        *,
        sink_versions: set[str],
        blocked_versions: set[str] | None = None,
        uncoverable_versions: set[str] | None = None,
    ):
        """Run the independent online checker over the conservative graph.

        Keeping this orchestration on the state authority makes it difficult
        for callers to accidentally certify a tight-graph result. The checker
        remains read-only and its UNKNOWN/UNSATISFIABLE states are preserved.
        """
        checker = RuntimeWitnessChecker()
        conservative, _ = self.graphs()
        return checker.check(
            conservative,
            sink_versions=sink_versions,
            blocked_versions=blocked_versions,
            uncoverable_versions=uncoverable_versions,
        )

    def apply_state(self, version_id: str, state: ArtifactState, reason: str, action_id: str | None = None):
        artifact = self.ledger.get_artifact(version_id)
        if artifact is None:
            raise KeyError(version_id)
        from_state = self.ledger.current_state(version_id) or ArtifactState.ACTIVE
        from app.provenance.models import StateTransition
        return self.ledger.transition_state(StateTransition(f"st_{uuid4().hex[:16]}", self.run_id, version_id, from_state, state, 0, reason, action_id))

    def certify_and_retain(self, *, sink_versions: set[str], blocked_versions: set[str], candidate_versions: set[str] | None = None, checker: CertificateChecker | None = None) -> RetentionResult:
        """Apply the v4 propose/veto retention rule to one committed snapshot."""
        conservative, tight = self.graphs()
        tight_reachable = set().union(*(tight.ancestors(s) | {s} for s in sink_versions)) if sink_versions else set()
        conservative_reachable = set().union(*(conservative.ancestors(s) | {s} for s in sink_versions)) if sink_versions else set()
        candidates = candidate_versions or set(tight.versions)
        proposed = frozenset(v for v in candidates if v in tight.versions and v not in tight_reachable)
        vetoed = frozenset(v for v in proposed if v in conservative_reachable)
        allowed = proposed - vetoed
        checker = checker or CertificateChecker(self.ledger)
        certificate = checker.issue(conservative, run_id=self.run_id, sink_versions=sink_versions, blocked_versions=blocked_versions, scope="retention")
        if not certificate.valid:
            return RetentionResult(certificate, proposed, vetoed, frozenset())
        with self.ledger.atomic():
            for version_id in allowed:
                self.apply_state(version_id, ArtifactState.RETAINED, "asymmetric_retention")
            # Rebuild after transitions so the check covers the committed state.
            post_graph, _ = self.graphs()
            post = checker.residual.check(post_graph, sink_versions=sink_versions, blocked_versions=blocked_versions)
        if post.status != "COVERED" or not post.exhaustive:
            with self.ledger.atomic():
                for version_id in allowed:
                    self.apply_state(version_id, ArtifactState.INVALIDATED, "post_state_verification_failed")
            return RetentionResult(certificate, proposed, vetoed, frozenset())
        post_snapshot = self.ledger.snapshot(self.run_id)
        certificate = replace(certificate, post_state_hash=post_snapshot.snapshot_hash,
                              retained_versions=tuple(sorted(allowed)))
        # ``issue`` records the pre-state diagnostic certificate. Retention is
        # only authoritative after the atomic state transition and post-state
        # check, so persist a second, final certificate carrying the committed
        # post-state hash and retained set.
        import hashlib, json
        final_hash = hashlib.sha256(
            json.dumps(certificate.__dict__, sort_keys=True, default=str).encode()
        ).hexdigest()
        with self.ledger.atomic():
            for version_id in allowed:
                artifact = self.ledger.get_artifact(version_id)
                self.ledger.append_label_enforcement(LabelEnforcementRecord(
                    enforcement_id=f"label_{uuid4().hex[:16]}", run_id=self.run_id,
                    version_id=version_id, certificate_hash=final_hash,
                    confidentiality=artifact.confidentiality if artifact else "restricted",
                ))
        self.ledger.store_certificate(
            final_hash,
            self.run_id,
            certificate.certificate_kind,
            certificate.pre_snapshot_hash,
            certificate.post_state_hash,
            certificate.__dict__,
        )
        return RetentionResult(certificate, proposed, vetoed, frozenset(allowed))

    def recheck_retained(self, retained_versions: set[str], sink_versions: set[str]) -> frozenset[str]:
        conservative, _ = self.graphs()
        reachable = set().union(*(conservative.ancestors(s) | {s} for s in sink_versions)) if sink_versions else set()
        invalidated = frozenset(retained_versions & reachable)
        for version_id in invalidated:
            self.apply_state(version_id, ArtifactState.INVALIDATED, "retained_reachability_changed")
        return invalidated

    def repair(self, *, sink_versions: set[str], revoked_versions: set[str], required_goals: set[str] | None = None,
               replay=None) -> dict:
        """Apply support-preserving invalidation and optionally replay clean slices.

        Replay callbacks receive a tuple of clean input version IDs and must create
        new versions through the gateway; no invalidated version is reactivated.
        """
        classifications = self.classify(sink_versions)
        invalidated: set[str] = set()
        retained: set[str] = set()
        for version_id, taint in classifications.items():
            if version_id in revoked_versions or taint is TaintClass.CONTAMINATED_REACHABLE:
                if self.ledger.current_state(version_id) not in {ArtifactState.INVALIDATED, ArtifactState.QUARANTINED}:
                    self.apply_state(version_id, ArtifactState.INVALIDATED, "support_preserving_repair")
                invalidated.add(version_id)
            elif taint is TaintClass.CONTAMINATED_UNREACHABLE:
                retained.add(version_id)
        replayed: list[object] = []
        if replay is not None and required_goals:
            clean_inputs = tuple(sorted(version_id for version_id, taint in classifications.items() if taint is TaintClass.CLEAN))
            for goal in sorted(required_goals):
                replayed.append(replay(goal, clean_inputs))
        return {
            "invalidated": sorted(invalidated),
            "retained": sorted(retained),
            "replayed": replayed,
            "required_goals": sorted(required_goals or set()),
        }
