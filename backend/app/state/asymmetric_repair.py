"""RAISE asymmetric repair (v4 §3.7, §4.1, §5.2–5.3, §6.6).

The one-directional propose/veto relationship, as a pure computation over two
graphs:

* the tight graph (P0) **proposes** retention candidates and nothing else;
* the conservative graph (P1) **vetoes**, and is the sole basis for safety;
* an independent checker re-verifies the post-state and can force a rollback.

``solve`` writes nothing. It returns a plan; the state authority applies it. That
separation is what keeps the optimiser out of the ledger and lets the plan be
tested without a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.provenance.models import ArtifactKind
from app.provenance.projection import ProvenanceGraph
from app.state.costs import (
    CostBreakdown,
    Intervention,
    apply_interventions,
    candidate_interventions,
    human_cost,
    surrogate_cost,
)
from app.state.greedy_solver import greedy_cover
from app.state.reachability import clean_e, sink_reachable
from app.state.witness import WITNESS_CAP_DEFAULT, enumerate_witnesses
from app.verification.residual_checker import ResidualChecker


@dataclass(frozen=True)
class RepairPlan:
    """What to invalidate, what to retain, and on what evidence."""

    status: str
    """``COVERED`` | ``UNSAFE`` | ``UNKNOWN`` | ``UNSATISFIABLE``"""

    selected: frozenset[str] = frozenset()
    invalidate: frozenset[str] = frozenset()
    retain: frozenset[str] = frozenset()
    proposed: frozenset[str] = frozenset()
    vetoed: frozenset[str] = frozenset()
    rolled_back: bool = False
    """True when retention was proposed and then withdrawn by the post-state check."""

    solver_status: str = ""
    witnesses: int = 0
    exhaustive: bool = True
    completeness_condition: str = "none"
    cost: CostBreakdown = field(default_factory=CostBreakdown)

    @property
    def retention_certified(self) -> bool:
        return self.status == "COVERED" and not self.rolled_back and bool(self.retain)


def _non_argument(graph: ProvenanceGraph) -> set[str]:
    return {
        version_id for version_id, artifact in graph.versions.items()
        if artifact.kind is not ArtifactKind.ARGUMENT
    }


def propose(
    tight: ProvenanceGraph,
    catalogue: dict[str, Intervention],
    selected: set[str],
    sink_versions: set[str],
) -> frozenset[str]:
    """Tight-graph (P0) retention proposal. Propose-only, never authoritative.

    A candidate is contaminated under the tight view yet cannot reach a sink
    there. Because the tight graph under-approximates influence, this set is
    optimistic by construction — hence the veto step.
    """
    applied = apply_interventions(tight, catalogue, selected)
    cleanliness = clean_e(tight, set(applied.removed_versions))
    reachable = sink_reachable(tight, sink_versions, applied=applied.versions_only())
    return frozenset(
        version_id for version_id in _non_argument(tight)
        if version_id not in applied.removed_versions
        and not cleanliness.get(version_id, False)
        and version_id not in reachable
    )


def veto(
    conservative: ProvenanceGraph,
    catalogue: dict[str, Intervention],
    selected: set[str],
    sink_versions: set[str],
    candidates: frozenset[str],
) -> frozenset[str]:
    """Conservative-graph (P1) veto. Sole authority over what survives.

    A candidate is struck if the over-approximating graph can still route it to a
    sink. One-directional: the conservative graph can remove a proposal but never
    add one, so a tight-graph bug cannot widen what is retained.
    """
    applied = apply_interventions(conservative, catalogue, selected)
    reachable = sink_reachable(conservative, sink_versions, applied=applied.versions_only())
    return frozenset(
        version_id for version_id in candidates
        if version_id in reachable or version_id in applied.removed_versions
    )


def _score(
    conservative: ProvenanceGraph,
    catalogue: dict[str, Intervention],
    selected: set[str],
    active: set[str],
    retained: set[str],
    ledger_support: list | None,
) -> CostBreakdown:
    """Fill in the four J(X) components for one plan."""
    non_argument = _non_argument(conservative)
    baseline_clean = clean_e(conservative, set())
    originally_clean = {v for v in non_argument if baseline_clean.get(v, False)}

    goals: set[str] = set()
    supported: set[str] = set()
    for support in ledger_support or ():
        goals.add(support.goal_id)
        if support.verified and all(m in active for m in support.member_version_ids):
            supported.add(support.goal_id)
    unsupported = goals - supported

    # Replay: per unsupported goal, one unit per distinct activity behind it.
    # Counted per goal rather than globally: two goals whose support was produced
    # by the same activity each need that activity re-run for their own branch.
    producing: dict[str, set[str]] = {}
    for derivation in conservative.derivations.values():
        producing.setdefault(derivation.child_version_id, set()).add(derivation.activity_id)
    replay = 0.0
    for goal_id in unsupported:
        activities: set[str] = set()
        for support in ledger_support or ():
            if support.goal_id != goal_id:
                continue
            for member in support.member_version_ids:
                activities |= producing.get(member, set())
        replay += float(len(activities))

    return CostBreakdown(
        op_cost=surrogate_cost(catalogue, selected),
        task_loss=float(len(unsupported)),
        replay_cost=replay,
        human_cost=human_cost(catalogue, selected),
        goals_total=len(goals),
        goals_supported=len(supported),
        versions_total=len(non_argument),
        versions_active=len(active),
        versions_retained=len(retained),
        benign_invalidated=len(originally_clean - active),
    )


def solve(
    conservative: ProvenanceGraph,
    tight: ProvenanceGraph,
    *,
    sink_versions: set[str],
    revoked_versions: set[str] | None = None,
    support_groups: list | None = None,
    checker: ResidualChecker | None = None,
    witness_cap: int = WITNESS_CAP_DEFAULT,
) -> RepairPlan:
    """Run the full six-step asymmetric mechanism and return a plan.

    1. enumerate witnesses on the conservative graph (the safety authority);
    2. cover them with the greedy solver over the surrogate cost;
    3. the tight graph proposes retention candidates;
    4. the conservative graph vetoes;
    5. an independent checker re-verifies the post-state;
    6. on anything short of COVERED, withdraw retention and fall back to
       conservative-only support-preserving repair.

    ``revoked_versions`` are forced into the intervention set before solving —
    an operator or upstream policy decision the solver may add to but not undo.
    """
    checker = checker or ResidualChecker()
    catalogue = candidate_interventions(conservative, sink_versions)

    # Step 1 — witnesses on the conservative graph only.
    enumeration = enumerate_witnesses(conservative, sink_versions, cap=witness_cap)

    # Step 2 — externally forced revocations are applied *before* greedy cover.
    # Appending them afterwards makes the greedy choose a second, unnecessary
    # cut from the same witness (and can randomly destroy a clean co-parent when
    # UUID ordering breaks a cost tie).
    selected: set[str] = set()
    forced_versions: set[str] = set()
    for version_id in revoked_versions or set():
        iid = f"revoke_version:{version_id}"
        if iid in catalogue:
            selected.add(iid)
            forced_versions.add(version_id)
    remaining = enumerate_witnesses(
        conservative,
        sink_versions,
        cap=witness_cap,
        blocked_versions=forced_versions,
    )
    solution = greedy_cover(conservative, catalogue, remaining.witnesses)
    selected.update(solution.selected)

    applied = apply_interventions(conservative, catalogue, selected)
    non_argument = _non_argument(conservative)
    cleanliness = clean_e(conservative, set(applied.removed_versions))
    clean_active = {v for v in non_argument if cleanliness.get(v, False)}

    if solution.status == "unsatisfiable":
        # No available intervention breaks some witness. Retention is not on the
        # table, and this is not a timeout: report it as its own state.
        cost = _score(conservative, catalogue, selected, clean_active, set(), support_groups)
        return RepairPlan(
            status="UNSATISFIABLE",
            selected=frozenset(selected),
            invalidate=frozenset(non_argument - clean_active),
            solver_status=solution.status,
            witnesses=enumeration.count,
            exhaustive=enumeration.exhaustive and remaining.exhaustive,
            cost=cost,
        )

    # Steps 3 and 4 — propose on tight, veto on conservative.
    proposed = propose(tight, catalogue, selected, sink_versions)
    vetoed = veto(conservative, catalogue, selected, sink_versions, proposed)
    retained = frozenset(
        v for v in proposed - vetoed
        if v in non_argument and v not in clean_active and v not in applied.removed_versions
    )

    # Step 5 — independent post-state re-verification on the conservative graph.
    post = checker.check(
        conservative,
        sink_versions=sink_versions,
        blocked_versions=set(applied.removed_versions) | set(applied.denied_sinks),
        blocked_relations=set(applied.removed_relations),
    )
    status = post.status if post.exhaustive or post.status == "UNSAFE" else "UNKNOWN"

    # Step 6 — withdraw retention unless the post-state is provably covered.
    rolled_back = status != "COVERED" and bool(retained)
    if status != "COVERED":
        retained = frozenset()

    active = clean_active | set(retained)
    cost = _score(conservative, catalogue, selected, active, set(retained), support_groups)
    return RepairPlan(
        status=status,
        selected=frozenset(selected),
        invalidate=frozenset(non_argument - active),
        retain=retained,
        proposed=proposed,
        vetoed=vetoed,
        rolled_back=rolled_back,
        solver_status=solution.status,
        witnesses=enumeration.count,
        exhaustive=enumeration.exhaustive and remaining.exhaustive,
        completeness_condition=post.condition,
        cost=cost,
    )
