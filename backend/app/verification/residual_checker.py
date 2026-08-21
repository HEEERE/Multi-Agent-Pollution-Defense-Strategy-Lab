from __future__ import annotations

from dataclasses import dataclass

from app.provenance.projection import ProvenanceGraph


@dataclass(frozen=True)
class ResidualResult:
    status: str
    residual_versions: frozenset[str]
    exhaustive: bool
    reason: str = ""


class ResidualChecker:
    """Independent read-only residual checker over a supplied conservative graph."""

    def __init__(self, *, budget: int = 200_000) -> None:
        self.budget = budget

    def check(self, graph: ProvenanceGraph, *, sink_versions: set[str], blocked_versions: set[str] | None = None, blocked_relations: set[str] | None = None) -> ResidualResult:
        blocked_versions = blocked_versions or set()
        blocked_relations = blocked_relations or set()
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
