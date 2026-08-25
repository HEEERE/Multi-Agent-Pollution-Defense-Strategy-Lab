"""Simple-path min-cut baseline (v4 proposition 2, baseline B8).

Picks, per sink, the cheapest single intervention that breaks *every* witness
rooted at that sink. Deliberately weak: it is the "one cut per path" view that
proposition 2 shows is only correct when the influence graph is a simple path, and
its failure on branching AND structure is the reason the general cover model
exists. Not a general max-flow implementation and not meant to be.
"""

from __future__ import annotations

from time import perf_counter

from app.provenance.projection import ProvenanceGraph
from app.state.costs import Intervention, surrogate_cost
from app.state.greedy_solver import SolveResult
from app.state.witness import Witness, break_set


def mincut_cover(
    graph: ProvenanceGraph,
    catalogue: dict[str, Intervention],
    witnesses: list[Witness],
) -> SolveResult:
    """Cheapest single cut per sink, or ``unsatisfiable`` when none exists."""
    started = perf_counter()
    if not witnesses:
        return SolveResult("optimal", set(), 0.0, (perf_counter() - started) * 1000)

    by_root: dict[str, list[set[str]]] = {}
    for witness in witnesses:
        by_root.setdefault(witness.root_version_id, []).append(
            break_set(graph, catalogue, witness)
        )

    selected: set[str] = set()
    for _root, covers in sorted(by_root.items()):
        common = set.intersection(*covers) if covers else set()
        if not common:
            # No single intervention breaks every witness at this sink: the
            # simple-path assumption does not hold here.
            return SolveResult(
                "unsatisfiable", selected, surrogate_cost(catalogue, selected),
                (perf_counter() - started) * 1000,
            )
        selected.add(min(common, key=lambda iid: (catalogue[iid].cost, iid)))

    return SolveResult(
        "feasible", selected, surrogate_cost(catalogue, selected),
        (perf_counter() - started) * 1000,
    )
