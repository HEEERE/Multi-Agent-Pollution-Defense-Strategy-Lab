"""Tight graph builder — P0 under-approximation (v4 §3, axiom A).

Only structurally declared P0 derivations become edges. The result
under-approximates real influence, so it may **propose** that a version is
retainable but can never establish that one is safe.

Nothing under ``verification/`` may import this module: an independent checker
that shared the tight view could inherit its optimism. That boundary is
enforced by ``tests/test_research_isolation.py``.
"""

from __future__ import annotations

from app.provenance.ledger import ProvenanceLedger
from app.provenance.models import Derivation, ProvenanceLevel
from app.provenance.projection import ProvenanceGraph

TIGHT_RELATION_TYPES = frozenset({"derived_from", "generated", "supported_by", "authorized"})


def build_tight(ledger: ProvenanceLedger, run_id: str) -> ProvenanceGraph:
    """Build P0 only from explicitly structured derivation records."""
    graph = ProvenanceGraph(conservative=False)
    versions = {v: ledger.get_artifact(v) for v in ledger.version_ids(run_id)}
    graph.versions = {k: v for k, v in versions.items() if v is not None}
    graph.derivations = {
        d.relation_id: d for d in ledger.list_derivations(run_id)
        if d.relation_type in TIGHT_RELATION_TYPES
        and d.provenance_level is ProvenanceLevel.P0
    }
    for support in ledger.list_support_groups(run_id):
        members = tuple(v for v in support.member_version_ids if v in graph.versions)
        if (
            support.provenance_level is ProvenanceLevel.P0
            and support.goal_id in graph.versions
            and members
        ):
            graph.derivations[f"support:{support.support_id}"] = Derivation(
                f"support:{support.support_id}", run_id, support.goal_id,
                members, support.verifier_id, "supported_by",
                tuple("support" for _ in members), ProvenanceLevel.P0,
            )
    return graph
