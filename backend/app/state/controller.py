from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from uuid import uuid4

from app.provenance.ledger import ProvenanceLedger
from app.provenance.models import ArtifactState, LabelEnforcementRecord, TaintClass
from app.provenance.conservative_builder import build_conservative
from app.provenance.projection import ProvenanceGraph
from app.provenance.tight_builder import build_tight
from app.state import asymmetric_repair
from app.state.asymmetric_repair import RepairPlan
from app.state.reachability import TaintReport, classify as classify_graph
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
        """Three-way taint classification over the conservative graph.

        Arguments are included here because callers use this view to pick clean
        replay inputs and need every version accounted for; the availability
        rates in ``TaintReport`` exclude them.
        """
        conservative, _ = self.graphs()
        return classify_graph(conservative, sink_versions, include_arguments=True).classes

    def taint_report(self, sink_versions: set[str]) -> TaintReport:
        """Classification plus the L1 availability rates (v4 §3.7)."""
        conservative, _ = self.graphs()
        return classify_graph(conservative, sink_versions)

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

    def certify_and_retain(self, *, sink_versions: set[str], blocked_versions: set[str], candidate_versions: set[str] | None = None, checker: CertificateChecker | None = None, horizon_closure: str = "closed") -> RetentionResult:
        """Apply the v4 propose/veto retention rule to one committed snapshot.

        ``horizon_closure == "open"`` means new activity may still build a fresh
        path from a retained version to a sink, so 定理 5 does not hold and no
        retention certificate may be issued (v4 §5.3).
        """
        conservative, tight = self.graphs()
        tight_reachable = set().union(*(tight.ancestors(s) | {s} for s in sink_versions)) if sink_versions else set()
        conservative_reachable = set().union(*(conservative.ancestors(s) | {s} for s in sink_versions)) if sink_versions else set()
        candidates = candidate_versions or set(tight.versions)
        proposed = frozenset(v for v in candidates if v in tight.versions and v not in tight_reachable)
        vetoed = frozenset(v for v in proposed if v in conservative_reachable)
        allowed = proposed - vetoed
        checker = checker or CertificateChecker(self.ledger)
        certificate = checker.issue(conservative, run_id=self.run_id, sink_versions=sink_versions, blocked_versions=blocked_versions, scope="retention", horizon_closure=horizon_closure)
        if horizon_closure == "open" or not certificate.valid:
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

    def plan_repair(self, *, sink_versions: set[str], revoked_versions: set[str] | None = None) -> RepairPlan:
        """Compute the cost-minimising repair plan without writing anything."""
        conservative, tight = self.graphs()
        return asymmetric_repair.solve(
            conservative, tight,
            sink_versions=sink_versions,
            revoked_versions=revoked_versions,
            support_groups=self.ledger.list_support_groups(self.run_id),
        )

    def repair(self, *, sink_versions: set[str], revoked_versions: set[str], required_goals: set[str] | None = None,
               replay=None) -> dict:
        """Solve for a minimum-cost intervention set, apply it, and replay.

        Delegates the decision to ``asymmetric_repair.solve``: the plan comes from
        a witness cover over the real cost model, not from invalidating everything
        contaminated. Retention only survives when the plan's independent
        post-state check returned COVERED.

        Replay callbacks receive a tuple of clean input version IDs and must create
        new versions through the gateway; no invalidated version is reactivated.
        """
        plan = self.plan_repair(sink_versions=sink_versions, revoked_versions=revoked_versions)
        terminal = {ArtifactState.INVALIDATED, ArtifactState.QUARANTINED}
        with self.ledger.atomic():
            for version_id in sorted(plan.invalidate):
                if self.ledger.current_state(version_id) not in terminal:
                    self.apply_state(version_id, ArtifactState.INVALIDATED, "asymmetric_repair")
            for version_id in sorted(plan.retain):
                if self.ledger.current_state(version_id) is ArtifactState.ACTIVE:
                    self.apply_state(version_id, ArtifactState.RETAINED, "asymmetric_retention")
        replayed: list[object] = []
        if replay is not None and required_goals:
            classifications = self.classify(sink_versions)
            clean_inputs = tuple(sorted(
                version_id for version_id, taint in classifications.items()
                if taint is TaintClass.CLEAN
            ))
            for goal in sorted(required_goals):
                replayed.append(replay(goal, clean_inputs))
        return {
            "invalidated": sorted(plan.invalidate),
            "retained": sorted(plan.retain),
            "replayed": replayed,
            "required_goals": sorted(required_goals or set()),
            "plan": plan,
        }
