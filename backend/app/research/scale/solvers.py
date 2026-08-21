"""Exact and greedy witness-cover solvers for the scale study.

* ``brute_force_cover`` is the ground-truth oracle (v4 plan baseline B10). It is
  exponential in the number of *relevant* interventions, so it carries an
  explicit budget and reports whether it proved optimality.
* ``greedy_cover`` is the scalable path (proposition 3): pick the intervention
  minimising cost per newly covered witness.
* ``mincut_cover`` is the simple-path special case baseline (proposition 2, B8).

All three consume an already-enumerated witness universe so that solver
behaviour and enumeration behaviour can be measured independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from time import perf_counter

from app.research.scale.analysis import Witness, break_set
from app.research.scale.graph import Hypergraph

SolveStatus = str  # "optimal" | "feasible" | "budget_exhausted" | "unsatisfiable"


@dataclass
class SolveResult:
    status: SolveStatus
    selected: set[str]
    cost: float
    elapsed_ms: float
    subsets_examined: int = 0

    @property
    def proven_optimal(self) -> bool:
        return self.status == "optimal"


def _coverage_map(g: Hypergraph, witnesses: list[Witness]) -> list[set[str]]:
    return [break_set(g, w) for w in witnesses]


def brute_force_cover(
    g: Hypergraph,
    witnesses: list[Witness],
    *,
    max_subsets: int = 2_000_000,
) -> SolveResult:
    """Exhaustive minimum-cost cover over the relevant intervention set."""
    started = perf_counter()
    covers = _coverage_map(g, witnesses)
    if not covers:
        return SolveResult("optimal", set(), 0.0, (perf_counter() - started) * 1000)
    if any(not c for c in covers):
        return SolveResult(
            "unsatisfiable", set(), float("inf"), (perf_counter() - started) * 1000
        )

    relevant = sorted(set().union(*covers))
    n = len(relevant)
    examined = 0
    best: set[str] | None = None
    best_cost = float("inf")
    min_cost = min(g.interventions[i].cost for i in relevant)

    for size in range(1, n + 1):
        # Cost lower bound for any set of this size. Once it cannot beat the
        # incumbent, no larger set can either, so the incumbent is optimal.
        if best is not None and size * min_cost >= best_cost:
            break
        for combo in combinations(relevant, size):
            examined += 1
            if examined > max_subsets:
                elapsed = (perf_counter() - started) * 1000
                if best is not None:
                    return SolveResult("feasible", best, best_cost, elapsed, examined)
                return SolveResult(
                    "budget_exhausted", set(), float("inf"), elapsed, examined
                )
            cost = sum(g.interventions[i].cost for i in combo)
            if cost >= best_cost:
                continue
            chosen = set(combo)
            if all(chosen & c for c in covers):
                best, best_cost = chosen, cost

    elapsed = (perf_counter() - started) * 1000
    if best is None:
        return SolveResult("unsatisfiable", set(), float("inf"), elapsed, examined)
    return SolveResult("optimal", best, best_cost, elapsed, examined)


def exact_cover(
    g: Hypergraph,
    witnesses: list[Witness],
    *,
    max_nodes: int = 2_000_000,
) -> SolveResult:
    """Solve the binary witness-cover model with branch-and-bound.

    This is an independent exact path from ``brute_force_cover``. Each
    intervention is a binary variable and every witness contributes the ILP
    constraint ``sum(x_i for i in Break(W)) >= 1``. The implementation branches
    on one uncovered constraint at a time, which is sufficient for the bounded
    Phase 4 mechanism graphs without adding a native solver dependency.
    """
    started = perf_counter()
    covers = _coverage_map(g, witnesses)
    if not covers:
        return SolveResult("optimal", set(), 0.0, (perf_counter() - started) * 1000)
    if any(not cover for cover in covers):
        return SolveResult("unsatisfiable", set(), float("inf"), (perf_counter() - started) * 1000)

    best: set[str] | None = None
    best_cost = float("inf")
    examined = 0

    def search(selected: set[str], cost: float) -> None:
        nonlocal best, best_cost, examined
        examined += 1
        if examined > max_nodes or cost >= best_cost:
            return
        uncovered = [cover for cover in covers if not (selected & cover)]
        if not uncovered:
            best, best_cost = set(selected), cost
            return
        # The smallest constraint has the lowest branching factor. Stable cost
        # ordering makes replays deterministic for the same graph snapshot.
        branch = min(uncovered, key=lambda cover: (len(cover), sorted(cover)))
        for iid in sorted(branch, key=lambda item: (g.interventions[item].cost, item)):
            search(selected | {iid}, cost + g.interventions[iid].cost)
            if examined > max_nodes:
                return

    search(set(), 0.0)
    elapsed = (perf_counter() - started) * 1000
    if examined > max_nodes:
        return SolveResult(
            "feasible" if best is not None else "budget_exhausted",
            best or set(), best_cost, elapsed, examined,
        )
    if best is None:
        return SolveResult("unsatisfiable", set(), float("inf"), elapsed, examined)
    return SolveResult("optimal", best, best_cost, elapsed, examined)


def greedy_cover(g: Hypergraph, witnesses: list[Witness]) -> SolveResult:
    """Weighted set-cover greedy: minimise cost / newly-covered."""
    started = perf_counter()
    covers = _coverage_map(g, witnesses)
    if not covers:
        return SolveResult("optimal", set(), 0.0, (perf_counter() - started) * 1000)
    if any(not c for c in covers):
        return SolveResult(
            "unsatisfiable", set(), float("inf"), (perf_counter() - started) * 1000
        )

    uncovered = set(range(len(covers)))
    by_intervention: dict[str, set[int]] = {}
    for idx, c in enumerate(covers):
        for iid in c:
            by_intervention.setdefault(iid, set()).add(idx)

    selected: set[str] = set()
    total = 0.0
    while uncovered:
        best_iid, best_ratio, best_gain = None, float("inf"), 0
        for iid, idxs in by_intervention.items():
            if iid in selected:
                continue
            gain = len(idxs & uncovered)
            if gain == 0:
                continue
            ratio = g.interventions[iid].cost / gain
            if ratio < best_ratio:
                best_iid, best_ratio, best_gain = iid, ratio, gain
        if best_iid is None:
            return SolveResult(
                "unsatisfiable",
                selected,
                total,
                (perf_counter() - started) * 1000,
            )
        selected.add(best_iid)
        total += g.interventions[best_iid].cost
        uncovered -= by_intervention[best_iid]

    return SolveResult(
        "feasible", selected, total, (perf_counter() - started) * 1000
    )


def mincut_cover(g: Hypergraph, witnesses: list[Witness]) -> SolveResult:
    """Simple-path special case: cheapest single revoke/edge per sink chain.

    Not a general min-cut implementation; it is the deliberately weak
    ``containment-only`` style baseline used to show that the general model is
    needed. Selects, per sink, the cheapest intervention covering all witnesses
    rooted at that sink, if one exists.
    """
    started = perf_counter()
    if not witnesses:
        return SolveResult("optimal", set(), 0.0, (perf_counter() - started) * 1000)

    by_root: dict[str, list[set[str]]] = {}
    for w in witnesses:
        by_root.setdefault(w.root_qid, []).append(break_set(g, w))

    selected: set[str] = set()
    total = 0.0
    for _root, cover_list in by_root.items():
        common = set.intersection(*cover_list) if cover_list else set()
        if not common:
            return SolveResult(
                "unsatisfiable", selected, total, (perf_counter() - started) * 1000
            )
        cheapest = min(common, key=lambda i: g.interventions[i].cost)
        if cheapest not in selected:
            selected.add(cheapest)
            total += g.interventions[cheapest].cost

    return SolveResult(
        "feasible", selected, total, (perf_counter() - started) * 1000
    )


def verify_cover(g: Hypergraph, witnesses: list[Witness], x: set[str]) -> bool:
    """Independent check that ``x`` breaks every witness.

    Deliberately re-derives the break sets instead of reusing solver state, so a
    solver bug cannot make its own answer look correct.
    """
    for w in witnesses:
        if not (x & break_set(g, w)):
            return False
    return True
