"""M-layer baseline matrix (v4 plan section 9.5, necessary tier).

Every baseline is a *strategy*: given a snapshot and its witness universe it
returns an intervention set plus a repair policy. All strategies are then scored
on identical metrics so the comparison is apples to apples, which is the whole
point of the matrix.

Implemented here:

===========  ==========================================================
B0           No defense. Establishes that the attack is real.
source-only  Revoke the injected entry points only. Weak baseline.
node-quar    Quarantine the agents that own contaminated state. Coarse.
B8 min-cut   Cheapest single cut per sink. Simple-path special case.
cont-greedy  Greedy witness cover ignoring repair cost. Ablation.
B7 rollback  Dependency rollback: cut, then wipe all descendants.
B9' naive    Self-built composition: argument gate + node treatment +
             dependency rollback, run in sequence. **Go/No-Go primary.**
B10 exact    Brute-force minimum-cost cover. Optimality reference.
RAISE-*      Recovery-aware cover with support-preserving repair, in
             conservative-only and asymmetric variants.
===========  ==========================================================

B9' deliberately depends on no external paper reproduction: the v4 plan makes it
the Go/No-Go basis precisely because a baseline assembled from unverifiable
reproductions cannot carry that weight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.research.scale.analysis import (
    Witness,
    break_set,
    clean_e,
    enumerate_witnesses,
    removed_versions,
    sink_reachable,
)
from app.research.scale.graph import (
    Hypergraph,
    Integrity,
    InterventionKind,
    VersionKind,
)
from app.research.scale.solvers import (
    exact_cover,
    greedy_cover,
    mincut_cover,
)


class RepairPolicy(StrEnum):
    NONE = "none"
    """Leave state as-is beyond the intervention itself."""

    DESCENDANT_WIPE = "descendant_wipe"
    """Invalidate every descendant of a revoked root (dependency rollback)."""

    FULL_RESET = "full_reset"
    """Invalidate all derived state."""

    SUPPORT_PRESERVING = "support_preserving"
    """Invalidate versions lacking a clean causal proof, but keep any goal that
    retains a verified clean support group."""

    ASYMMETRIC = "asymmetric"
    """Support-preserving, plus retain contaminated versions that cannot reach any
    protected sink (v4 plan section 3.7)."""


@dataclass
class Outcome:
    """Scored result of one strategy on one snapshot."""

    name: str
    selected: set[str] = field(default_factory=set)
    repair: RepairPolicy = RepairPolicy.NONE

    # safety
    residual_witnesses: int = 0
    escaped: bool = False

    # cost components of the real J(X)
    op_cost: float = 0.0
    task_loss: float = 0.0
    replay_cost: float = 0.0
    human_cost: float = 0.0

    # state accounting
    versions_total: int = 0
    versions_active: int = 0
    versions_invalidated: int = 0
    versions_retained: int = 0
    benign_invalidated: int = 0
    """Clean versions destroyed by the strategy. The over-blocking measure."""

    goals_total: int = 0
    goals_supported: int = 0

    solver_status: str = ""
    exhaustive: bool = True

    def j(self, lam: float = 2.0, mu: float = 1.0, nu: float = 1.0) -> float:
        """Real J(X). Weights are frozen by the caller before results are seen."""
        return (
            self.op_cost
            + lam * self.task_loss
            + mu * self.replay_cost
            + nu * self.human_cost
        )

    @property
    def task_utility(self) -> float:
        return self.goals_supported / self.goals_total if self.goals_total else 1.0

    @property
    def benign_preservation(self) -> float:
        """Fraction of originally-clean state still available."""
        denom = self.versions_total
        return (denom - self.benign_invalidated) / denom if denom else 1.0


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def _supported_goals(
    g: Hypergraph, active: set[str], *, require_verified: bool = True
) -> set[str]:
    """Goals with at least one fully-active support group."""
    out: set[str] = set()
    for gid in g.goals:
        for s in g.support_for(gid):
            if require_verified and not s.verified:
                continue
            if all(m in active for m in s.members):
                out.add(gid)
                break
    return out


def _descendants(g: Hypergraph, roots: set[str]) -> set[str]:
    """Forward closure: everything derived from any root."""
    out: set[str] = set()
    stack = list(roots)
    while stack:
        cur = stack.pop()
        for d in g.outgoing(cur):
            if d.child not in out:
                out.add(d.child)
                stack.append(d.child)
    return out


def apply_repair(
    g: Hypergraph, selected: set[str], policy: RepairPolicy
) -> tuple[set[str], set[str]]:
    """Return (active, retained) version sets after intervention and repair."""
    revoked = removed_versions(g, selected)
    non_arg = {
        v.vid for v in g.versions.values() if v.kind is not VersionKind.ARGUMENT
    }

    if policy is RepairPolicy.NONE:
        return non_arg - revoked, set()

    if policy is RepairPolicy.FULL_RESET:
        # Only sources survive a full reset.
        return {v for v in non_arg if g.versions[v].is_source} - revoked, set()

    if policy is RepairPolicy.DESCENDANT_WIPE:
        dead = revoked | _descendants(g, revoked)
        return non_arg - dead, set()

    ce = clean_e(g, revoked)
    clean_active = {v for v in non_arg if ce.get(v, False)}

    if policy is RepairPolicy.SUPPORT_PRESERVING:
        return clean_active, set()

    # ASYMMETRIC: additionally retain contaminated-but-sink-unreachable state.
    reach = sink_reachable(g, removed_versions=revoked)
    retained = {
        v for v in non_arg - clean_active - revoked if v not in reach
    }
    return clean_active | retained, retained


def score(
    g: Hypergraph,
    witnesses: list[Witness],
    name: str,
    selected: set[str],
    policy: RepairPolicy,
    *,
    solver_status: str = "",
    exhaustive: bool = True,
) -> Outcome:
    """Score one strategy. Identical metric code for every baseline."""
    active, retained = apply_repair(g, selected, policy)
    non_arg = {
        v.vid for v in g.versions.values() if v.kind is not VersionKind.ARGUMENT
    }

    residual = [w for w in witnesses if not (selected & break_set(g, w))]

    # Benign over-blocking: versions that were clean before any intervention but
    # are unavailable afterwards.
    baseline_clean = clean_e(g, set())
    originally_clean = {v for v in non_arg if baseline_clean.get(v, False)}
    benign_lost = len(originally_clean - active)

    supported = _supported_goals(g, active)
    goals_total = len(g.goals)
    task_loss = sum(
        g.goals[gid].value for gid in g.goals if gid not in supported
    )

    # Replay: each unsupported required goal needs its activities re-run.
    replay = 0.0
    for gid in g.required_goals:
        if gid in supported:
            continue
        acts = {
            g.activity_of(m)
            for s in g.support_for(gid)
            for m in s.members
            if g.activity_of(m)
        }
        replay += float(len(acts))

    op = sum(g.interventions[i].cost for i in selected)
    # Agent quarantine and action denial need sign-off; version revocation does
    # not. This is what makes blunt strategies expensive in human terms.
    human = sum(
        1.0
        for i in selected
        if g.interventions[i].kind
        in (InterventionKind.QUARANTINE_AGENT, InterventionKind.DENY_ACTION)
    )

    return Outcome(
        name=name,
        selected=set(selected),
        repair=policy,
        residual_witnesses=len(residual),
        escaped=bool(residual),
        op_cost=op,
        task_loss=task_loss,
        replay_cost=replay,
        human_cost=human,
        versions_total=len(non_arg),
        versions_active=len(active),
        versions_invalidated=len(non_arg - active),
        versions_retained=len(retained),
        benign_invalidated=benign_lost,
        goals_total=goals_total,
        goals_supported=len(supported),
        solver_status=solver_status,
        exhaustive=exhaustive,
    )


# ---------------------------------------------------------------------------
# strategies
# ---------------------------------------------------------------------------


def _iid_for(g: Hypergraph, kind: InterventionKind, target: str) -> str | None:
    for i in g.interventions.values():
        if i.kind is kind and i.target == target:
            return i.iid
    return None


def b0_no_defense(g: Hypergraph, witnesses: list[Witness]) -> Outcome:
    return score(g, witnesses, "B0-no-defense", set(), RepairPolicy.NONE)


def source_only(g: Hypergraph, witnesses: list[Witness]) -> Outcome:
    """Revoke the injected entry points and nothing else."""
    sel = {
        iid
        for src in g.low_integrity_sources
        if (iid := _iid_for(g, InterventionKind.REVOKE_VERSION, src))
    }
    return score(g, witnesses, "source-only", sel, RepairPolicy.NONE)


def node_quarantine(g: Hypergraph, witnesses: list[Witness]) -> Outcome:
    """Quarantine every agent owning a version in some witness."""
    agents = {
        g.versions[v].agent
        for w in witnesses
        for v in w.versions
        if v in g.versions
        and g.versions[v].agent
        and g.versions[v].kind is not VersionKind.ARGUMENT
    }
    sel = {
        iid
        for a in agents
        if (iid := _iid_for(g, InterventionKind.QUARANTINE_AGENT, a))
    }
    return score(g, witnesses, "node-quarantine", sel, RepairPolicy.NONE)


def b8_min_cut(g: Hypergraph, witnesses: list[Witness]) -> Outcome:
    res = mincut_cover(g, witnesses)
    return score(
        g,
        witnesses,
        "B8-min-cut",
        res.selected,
        RepairPolicy.NONE,
        solver_status=res.status,
    )


def containment_only_greedy(g: Hypergraph, witnesses: list[Witness]) -> Outcome:
    """Greedy cover with no repair. Ablation isolating the repair term."""
    res = greedy_cover(g, witnesses)
    return score(
        g,
        witnesses,
        "containment-only-greedy",
        res.selected,
        RepairPolicy.NONE,
        solver_status=res.status,
    )


def b7_dependency_rollback(g: Hypergraph, witnesses: list[Witness]) -> Outcome:
    """Cut, then wipe every descendant of the revoked roots."""
    res = greedy_cover(g, witnesses)
    return score(
        g,
        witnesses,
        "B7-dependency-rollback",
        res.selected,
        RepairPolicy.DESCENDANT_WIPE,
        solver_status=res.status,
    )


def b9_prime_naive_compose(g: Hypergraph, witnesses: list[Witness]) -> Outcome:
    """Self-built naive composition: gate, then node treatment, then rollback.

    Each stage is applied in sequence without any joint optimisation, which is
    precisely what "naive composition" means: three defences that individually
    work, stacked without accounting for each other's cost.
    """
    selected: set[str] = set()

    # Stage 1 -- argument gate: deny any sink whose argument is influenced by a
    # low-integrity origin.
    for s in g.sinks:
        rooted = [w for w in witnesses if w.root_qid == s.qid]
        if rooted:
            iid = _iid_for(g, InterventionKind.DENY_ACTION, s.qid)
            if iid:
                selected.add(iid)

    # Stage 2 -- node treatment: quarantine agents still implicated in any
    # witness the gate did not already break.
    remaining = [w for w in witnesses if not (selected & break_set(g, w))]
    agents = {
        g.versions[v].agent
        for w in remaining
        for v in w.versions
        if v in g.versions
        and g.versions[v].agent
        and g.versions[v].kind is not VersionKind.ARGUMENT
    }
    for a in agents:
        iid = _iid_for(g, InterventionKind.QUARANTINE_AGENT, a)
        if iid:
            selected.add(iid)

    # Stage 3 -- rollback: revoke the injected sources, then wipe descendants.
    for src in g.low_integrity_sources:
        iid = _iid_for(g, InterventionKind.REVOKE_VERSION, src)
        if iid:
            selected.add(iid)

    return score(
        g,
        witnesses,
        "B9'-naive-compose",
        selected,
        RepairPolicy.DESCENDANT_WIPE,
        solver_status="composed",
    )


def b10_exact(
    g: Hypergraph, witnesses: list[Witness], *, budget: int = 300_000
) -> Outcome:
    res = exact_cover(g, witnesses, max_nodes=budget)
    return score(
        g,
        witnesses,
        "B10-exact-oracle",
        res.selected,
        RepairPolicy.NONE,
        solver_status=res.status,
    )


def raise_conservative(g: Hypergraph, witnesses: list[Witness]) -> Outcome:
    """Greedy cover plus support-preserving repair, conservative graph only."""
    res = greedy_cover(g, witnesses)
    return score(
        g,
        witnesses,
        "RAISE-conservative",
        res.selected,
        RepairPolicy.SUPPORT_PRESERVING,
        solver_status=res.status,
    )


def raise_asymmetric(g: Hypergraph, witnesses: list[Witness]) -> Outcome:
    """Greedy cover plus asymmetric retention (the v4 mechanism)."""
    res = greedy_cover(g, witnesses)
    return score(
        g,
        witnesses,
        "RAISE-asymmetric",
        res.selected,
        RepairPolicy.ASYMMETRIC,
        solver_status=res.status,
    )


def full_reset(g: Hypergraph, witnesses: list[Witness]) -> Outcome:
    """Cut, then discard all derived state. The blunt upper bound on safety."""
    res = greedy_cover(g, witnesses)
    return score(
        g,
        witnesses,
        "full-reset",
        res.selected,
        RepairPolicy.FULL_RESET,
        solver_status=res.status,
    )


#: Registry in report order. B9' is the Go/No-Go primary.
STRATEGIES = {
    "B0-no-defense": b0_no_defense,
    "source-only": source_only,
    "node-quarantine": node_quarantine,
    "B8-min-cut": b8_min_cut,
    "containment-only-greedy": containment_only_greedy,
    "full-reset": full_reset,
    "B7-dependency-rollback": b7_dependency_rollback,
    "B9'-naive-compose": b9_prime_naive_compose,
    "B10-exact-oracle": b10_exact,
    "RAISE-conservative": raise_conservative,
    "RAISE-asymmetric": raise_asymmetric,
}


def run_all(
    g: Hypergraph, *, witness_cap: int = 20_000
) -> tuple[dict[str, Outcome], bool]:
    """Score every strategy on one snapshot.

    Returns (outcomes, enumeration_was_exhaustive). A non-exhaustive universe
    means safety numbers are lower bounds only.
    """
    enum = enumerate_witnesses(g, cap=witness_cap)
    out: dict[str, Outcome] = {}
    for name, fn in STRATEGIES.items():
        o = fn(g, enum.witnesses)
        o.exhaustive = enum.exhaustive
        out[name] = o
    return out, enum.exhaustive
