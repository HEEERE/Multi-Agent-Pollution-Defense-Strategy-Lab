from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import hashlib
import json
import time

from app.provenance.ledger import ProvenanceLedger
from app.provenance.projection import ProvenanceGraph
from app.verification.residual_checker import ResidualChecker


@dataclass(frozen=True)
class ReissuePolicy:
    """Bounded certificate reuse; it never relaxes the underlying checker."""

    ttl_seconds: float = 300.0
    max_reissues: int = 0

    def __post_init__(self) -> None:
        if self.ttl_seconds <= 0 or self.max_reissues < 0:
            raise ValueError("reissue policy requires positive TTL and non-negative limit")


@dataclass(frozen=True)
class Certificate:
    run_id: str
    snapshot_hash: str
    scope: str
    sink_versions: frozenset[str]
    blocked_versions: frozenset[str]
    status: str
    completeness: str
    certificate_kind: str = "action_safety"
    pre_snapshot_hash: str = ""
    post_state_hash: str = ""
    policy_hash: str = ""
    scope_hash: str = ""
    action_request_hash: str = ""
    horizon_closure: str = "closed"
    graph_role: str = "conservative"
    witness_hashes: tuple[str, ...] = ()
    selected_interventions: tuple[str, ...] = ()
    completeness_evidence: str = "full_enumeration"
    applied_state_transition_ids: tuple[str, ...] = ()
    retained_versions: tuple[str, ...] = ()
    issued_at: float = 0.0
    reissue_policy: ReissuePolicy | None = None
    reissue_count: int = 0

    @property
    def valid(self) -> bool:
        return self.status == "COVERED" and self.completeness == "EXHAUSTIVE"


class CertificateChecker:
    def __init__(self, ledger: ProvenanceLedger, *, budget: int = 200_000) -> None:
        self.ledger = ledger
        self.residual = ResidualChecker(budget=budget)

    def issue(self, graph: ProvenanceGraph, *, run_id: str, sink_versions: set[str], blocked_versions: set[str], scope: str = "action", horizon_closure: str = "closed", reissue_policy: ReissuePolicy | None = None) -> Certificate:
        if not graph.conservative:
            raise ValueError("safety certificates require the conservative graph")
        if horizon_closure not in {"closed", "open"}:
            raise ValueError("horizon_closure must be closed or open")
        snapshot = self.ledger.snapshot(run_id)
        result = self.residual.check(graph, sink_versions=sink_versions, blocked_versions=blocked_versions)
        completeness = "EXHAUSTIVE" if result.exhaustive else "BUDGET_EXHAUSTED"
        certificate_kind = (
            "retention" if scope == "retention"
            else "release" if scope == "release"
            else "declassify" if scope == "declassify"
            else "action_safety"
        )
        scope_hash = hashlib.sha256(json.dumps(sorted(sink_versions)).encode()).hexdigest()
        cert = Certificate(
            run_id, snapshot.snapshot_hash, scope, frozenset(sink_versions),
            frozenset(blocked_versions), result.status, completeness,
            certificate_kind=certificate_kind, pre_snapshot_hash=snapshot.snapshot_hash,
            post_state_hash=snapshot.snapshot_hash, scope_hash=scope_hash,
            completeness_evidence="full_enumeration" if result.exhaustive else "budget_bounded",
            horizon_closure=horizon_closure, issued_at=time.time(),
            reissue_policy=reissue_policy,
        )
        self.ledger.store_certificate(
            hashlib.sha256(json.dumps(cert.__dict__, sort_keys=True, default=str).encode()).hexdigest(),
            run_id, certificate_kind, snapshot.snapshot_hash, snapshot.snapshot_hash,
            cert.__dict__,
        )
        return cert

    def issue_release(self, graph: ProvenanceGraph, *, run_id: str,
                      release_versions: set[str], blocked_versions: set[str],
                      reissue_policy: ReissuePolicy | None = None,
                      horizon_closure: str = "closed") -> Certificate:
        """Issue a release certificate for an explicit version set only."""
        if not release_versions:
            raise ValueError("release scope cannot be empty")
        if not release_versions.issubset(graph.versions):
            raise ValueError("release scope contains versions outside the graph")
        return self.issue(
            graph,
            run_id=run_id,
            sink_versions=release_versions,
            blocked_versions=blocked_versions,
            scope="release",
            horizon_closure=horizon_closure,
            reissue_policy=reissue_policy,
        )

    def reissue(self, certificate: Certificate, graph: ProvenanceGraph) -> Certificate:
        """Reissue only while scope, snapshot, policy TTL and witness set hold."""
        policy = certificate.reissue_policy
        if certificate.certificate_kind != "release" or policy is None:
            raise ValueError("certificate is not reissuable")
        if certificate.reissue_count >= policy.max_reissues:
            raise ValueError("reissue limit exhausted")
        if time.time() > certificate.issued_at + policy.ttl_seconds:
            raise ValueError("reissue policy expired")
        if not self.verify(certificate, graph):
            raise ValueError("certificate no longer verifies")
        return replace(
            certificate,
            issued_at=time.time(),
            reissue_count=certificate.reissue_count + 1,
        )

    def verify(self, certificate: Certificate, graph: ProvenanceGraph) -> bool:
        current = self.ledger.snapshot(certificate.run_id)
        expected_snapshot = certificate.post_state_hash or certificate.snapshot_hash
        if current.snapshot_hash != expected_snapshot or not certificate.valid:
            return False
        if certificate.graph_role != "conservative":
            return False
        if certificate.horizon_closure == "open" and certificate.certificate_kind in {"recovery_safety", "retention", "release", "declassify"}:
            return False
        result = self.residual.check(graph, sink_versions=set(certificate.sink_versions), blocked_versions=set(certificate.blocked_versions))
        return result.status == "COVERED" and result.exhaustive
