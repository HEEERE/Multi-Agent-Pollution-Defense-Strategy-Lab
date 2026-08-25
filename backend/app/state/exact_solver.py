"""Branch-and-bound exact minimum-cost witness cover (v4 baseline B10).

Each intervention is a binary variable; every witness contributes the constraint
``Σ x_i for i in Break(W) ≥ 1``. Branching happens on one uncovered constraint at
a time, which is enough for the bounded action-boundary graphs without pulling in
a native MIP dependency.

Carries an explicit node budget and reports whether optimality was *proved*. A
``feasible`` answer with an exhausted budget is not an optimality claim.
"""

from __future__ import annotations

from time import perf_counter

from app.provenance.projection import ProvenanceGraph
from app.state.costs import Intervention, surrogate_cost
from app.state.greedy_solver import SolveResult
from app.state.witness import Witness, coverage_map

MAX_NODES_DEFAULT = 300_000


def exact_cover(
    graph: ProvenanceGraph,
    catalogue: dict[str, Intervention],
    witnesses: list[Witness],
    *,
    max_nodes: int = MAX_NODES_DEFAULT,
) -> SolveResult:
    """Minimum-cost cover, or the best found before the node budget ran out."""
    started = perf_counter()
    covers = coverage_map(graph, catalogue, witnesses)
    if not covers:
        return SolveResult("optimal", set(), 0.0, (perf_counter() - started) * 1000)
    if any(not cover for cover in covers):
        return SolveResult(
            "unsatisfiable", set(), float("inf"), (perf_counter() - started) * 1000
        )

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
        # Smallest constraint first: lowest branching factor. Stable cost ordering
        # makes a replay of the same snapshot deterministic.
        branch = min(uncovered, key=lambda cover: (len(cover), sorted(cover)))
        for iid in sorted(branch, key=lambda item: (catalogue[item].cost, item)):
            search(selected | {iid}, cost + catalogue[iid].cost)
            if examined > max_nodes:
                return

    search(set(), 0.0)
    elapsed = (perf_counter() - started) * 1000
    if examined > max_nodes:
        if best is None:
            return SolveResult("budget_exhausted", set(), float("inf"), elapsed, examined)
        return SolveResult("feasible", best, surrogate_cost(catalogue, best), elapsed, examined)
    if best is None:
        return SolveResult("unsatisfiable", set(), float("inf"), elapsed, examined)
    return SolveResult("optimal", best, surrogate_cost(catalogue, best), elapsed, examined)
