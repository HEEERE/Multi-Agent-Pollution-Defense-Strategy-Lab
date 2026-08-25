"""Weighted set-cover greedy over the witness universe (v4 proposition 3).

Minimises the *additive surrogate* Ĉ(X), picking the intervention with the best
cost-per-newly-covered-witness ratio. Additivity is what buys the standard
``H(m)`` approximation guarantee; the real J(X) is not additive, which is why the
surrogate is named as one rather than passed off as the objective.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

from app.provenance.projection import ProvenanceGraph
from app.state.costs import Intervention, surrogate_cost
from app.state.witness import Witness, coverage_map


@dataclass
class SolveResult:
    status: str
    """``optimal`` | ``feasible`` | ``budget_exhausted`` | ``unsatisfiable``"""

    selected: set[str] = field(default_factory=set)
    cost: float = 0.0
    elapsed_ms: float = 0.0
    nodes_examined: int = 0

    @property
    def proven_optimal(self) -> bool:
        return self.status == "optimal"

    @property
    def feasible(self) -> bool:
        return self.status in {"optimal", "feasible"}


def greedy_cover(
    graph: ProvenanceGraph,
    catalogue: dict[str, Intervention],
    witnesses: list[Witness],
) -> SolveResult:
    """Cover every witness, minimising cost per newly covered witness.

    An empty universe is ``optimal`` with an empty set: nothing to cover. A
    witness with an empty break set makes the instance ``unsatisfiable`` — no
    available intervention can break it. That is a genuinely different answer
    from "ran out of budget", and conflating the two is the failure mode v4 §4.2
    calls out.
    """
    started = perf_counter()
    covers = coverage_map(graph, catalogue, witnesses)
    if not covers:
        return SolveResult("optimal", set(), 0.0, (perf_counter() - started) * 1000)
    if any(not cover for cover in covers):
        return SolveResult(
            "unsatisfiable", set(), float("inf"), (perf_counter() - started) * 1000
        )

    uncovered = set(range(len(covers)))
    by_intervention: dict[str, set[int]] = {}
    for index, cover in enumerate(covers):
        for iid in cover:
            by_intervention.setdefault(iid, set()).add(index)

    selected: set[str] = set()
    while uncovered:
        best_iid: str | None = None
        best_key: tuple[float, float, int, str] | None = None
        for iid, indices in by_intervention.items():
            if iid in selected:
                continue
            gain = len(indices & uncovered)
            if gain == 0:
                continue
            cost = catalogue[iid].cost
            # Ties on the ratio are broken by absolute cost, then by coverage,
            # then by iid. Fully ordered on purpose: the same snapshot must yield
            # the same plan on every replay, and an unordered tie-break makes the
            # cover depend on dict iteration order.
            key = (cost / gain, cost, -gain, iid)
            if best_key is None or key < best_key:
                best_iid, best_key = iid, key
        if best_iid is None:
            return SolveResult(
                "unsatisfiable", selected, surrogate_cost(catalogue, selected),
                (perf_counter() - started) * 1000,
            )
        selected.add(best_iid)
        uncovered -= by_intervention[best_iid]

    return SolveResult(
        "feasible", selected, surrogate_cost(catalogue, selected),
        (perf_counter() - started) * 1000,
    )
