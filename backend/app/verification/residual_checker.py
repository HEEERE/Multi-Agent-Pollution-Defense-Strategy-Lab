from __future__ import annotations

from dataclasses import dataclass

from app.provenance.projection import ProvenanceGraph
from app.verification.completeness import (
    Completeness,
    CompletenessEvidence,
    cheap_completeness,
)


@dataclass(frozen=True)
class ResidualResult:
    status: str
    residual_versions: frozenset[str]
    exhaustive: bool
    reason: str = ""
    condition: str = "none"
    """Which cheap sufficient condition proved the result: ``SC1``/``SC2``/``none``."""


class ResidualChecker:
    """Independent read-only residual checker over a supplied conservative graph.

    Order matters. The cheap sufficient conditions of v4 §4.2 run *before* the
    budget gate, because SC1 is O(|V|+|E|) and can prove the absence of any
    witness on a graph far too large to enumerate. Checking the budget first would
    return UNKNOWN on exactly the large graphs SC1 exists to settle.
    """

    def __init__(self, *, budget: int = 200_000) -> None:
        self.budget = budget

    def check(self, graph: ProvenanceGraph, *, sink_versions: set[str], blocked_versions: set[str] | None = None, blocked_relations: set[str] | None = None) -> ResidualResult:
        blocked_versions = blocked_versions or set()
        blocked_relations = blocked_relations or set()
        evidence = self.completeness(
            graph, sink_versions=sink_versions,
            blocked_versions=blocked_versions, blocked_relations=blocked_relations,
        )
        if evidence.proves_absence:
            return ResidualResult(
                "COVERED", frozenset(), True, "EXHAUSTIVE_NO_WITNESS", evidence.condition
            )
        if len(graph.versions) > self.budget:
            return ResidualResult("UNKNOWN", frozenset(), False, "BUDGET_EXHAUSTED")
        residual: set[str] = set()
        for sink in sink_versions:
            if sink in blocked_versions:
                continue
            stack = [sink]
            seen: set[str] = set()
            while stack:
                current = stack.pop()
                if current in seen or current in blocked_versions:
                    continue
                seen.add(current)
                artifact = graph.versions.get(current)
                if artifact and artifact.integrity == "low":
                    residual.add(current)
                for relation in graph.derivations.values():
                    if relation.relation_id in blocked_relations or relation.child_version_id != current:
                        continue
                    stack.extend(relation.parent_version_ids)
        if residual:
            return ResidualResult("UNSAFE", frozenset(residual), True, "RESIDUAL_WITNESS")
        return ResidualResult("COVERED", frozenset(), True, "EXHAUSTIVE_NO_WITNESS")

    def completeness(self, graph: ProvenanceGraph, *, sink_versions: set[str], blocked_versions: set[str] | None = None, blocked_relations: set[str] | None = None) -> CompletenessEvidence:
        """Evaluate SC1/SC2 alone, without running the residual walk.

        ``denied_sinks`` stays empty: a denied sink reaches this layer as a member
        of ``blocked_versions``, and passing it twice would let SC2 report
        domination for a sink that was merely removed.
        """
        return cheap_completeness(
            graph,
            set(sink_versions),
            removed_versions=set(blocked_versions or set()),
            removed_relations=set(blocked_relations or set()),
            denied_sinks=set(),
        )

    def status_for(self, result: ResidualResult) -> Completeness:
        """Map a residual result onto the v4 §4.2 completeness vocabulary."""
        if result.status == "UNSAFE":
            return Completeness.WITNESS_FOUND
        if result.status == "COVERED" and result.exhaustive:
            return Completeness.EXHAUSTIVE_NO_WITNESS
        return Completeness.BUDGET_EXHAUSTED
