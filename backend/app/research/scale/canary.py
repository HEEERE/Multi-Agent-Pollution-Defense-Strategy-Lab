"""Post-repair attack and benign canary verification for Phase 4."""

from __future__ import annotations

from dataclasses import dataclass

from app.research.scale.analysis import Witness, break_set
from app.research.scale.baselines import RepairPolicy, apply_repair
from app.research.scale.graph import Hypergraph


@dataclass(frozen=True)
class CanaryResult:
    recurrent_attack_roots: frozenset[str]
    unavailable_benign_goals: frozenset[str]

    @property
    def passed(self) -> bool:
        return not self.recurrent_attack_roots and not self.unavailable_benign_goals


def verify_canaries(
    g: Hypergraph,
    witnesses: list[Witness],
    selected: set[str],
    *,
    repair_policy: RepairPolicy = RepairPolicy.SUPPORT_PRESERVING,
    benign_goal_ids: set[str] | None = None,
) -> CanaryResult:
    """Require no original attack witness and preserve verified benign support."""
    recurrent = {
        witness.root_qid
        for witness in witnesses
        if not (selected & break_set(g, witness))
    }
    active, _retained = apply_repair(g, selected, repair_policy)
    benign_goals = benign_goal_ids if benign_goal_ids is not None else set(g.required_goals)
    unavailable: set[str] = set()
    for goal_id in benign_goals:
        supports = [support for support in g.support_for(goal_id) if support.verified]
        if not any(set(support.members).issubset(active) for support in supports):
            unavailable.add(goal_id)
    return CanaryResult(frozenset(recurrent), frozenset(unavailable))
