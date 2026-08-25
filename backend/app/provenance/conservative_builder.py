"""Conservative graph builder — P1 over-approximation (v4 §3, axiom A).

Every visible input reference becomes an influence edge, whether or not the
agent structurally declared it. The result over-approximates real influence,
which is what gives it veto authority: if this graph says a version is clean,
no tighter view can contradict it.

This is the *only* graph a safety conclusion may be drawn from.
"""

from __future__ import annotations

from app.provenance.ledger import ProvenanceLedger
from app.provenance.models import Derivation
from app.provenance.projection import ProvenanceGraph


def build_conservative(
    ledger: ProvenanceLedger,
    run_id: str,
    *,
    visible_inputs: dict[str, tuple[str, ...]] | None = None,
) -> ProvenanceGraph:
    """Build the P1 over-approximation from all visible input references."""
    graph = ProvenanceGraph(conservative=True)
    versions = {v: ledger.get_artifact(v) for v in ledger.version_ids(run_id)}
    graph.versions = {k: v for k, v in versions.items() if v is not None}
    for d in ledger.list_derivations(run_id):
        parents = set(d.parent_version_ids)
        if visible_inputs and d.child_version_id in visible_inputs:
            parents.update(visible_inputs[d.child_version_id])
        graph.derivations[d.relation_id] = Derivation(
            d.relation_id, d.run_id, d.child_version_id, tuple(sorted(parents)),
            d.activity_id, "conservative_influence", d.parent_roles,
            d.provenance_level, d.effect_class,
        )
    for support in ledger.list_support_groups(run_id):
        members = tuple(v for v in support.member_version_ids if v in graph.versions)
        if support.goal_id in graph.versions and members:
            graph.derivations[f"support:{support.support_id}"] = Derivation(
                f"support:{support.support_id}", run_id, support.goal_id,
                members, support.verifier_id, "supported_by",
                tuple("support" for _ in members), support.provenance_level,
            )
    return graph
