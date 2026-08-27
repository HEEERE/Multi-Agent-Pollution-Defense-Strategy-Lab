"""Independent reference Oracle for the formal mechanism cases.

This module intentionally imports graph data types only.  It does not import
the production witness enumerator, any optimizer, either checker, or runtime
code.  M-02 uses it as the bounded truth implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import inf

from app.research.scale.graph import Hypergraph, InterventionKind, VersionKind


@dataclass(frozen=True)
class ReferenceWitness:
    root_qid: str
    versions: frozenset[str]
    derivations: frozenset[str]

    def signature(self, low_sources: set[str]) -> tuple[str, tuple[str, ...]]:
        return self.root_qid, tuple(sorted(self.versions & low_sources))


@dataclass(frozen=True)
class ReferenceSolve:
    status: str
    selected: frozenset[str]
    cost: float
    subsets_examined: int


def authority_atoms(graph: Hypergraph) -> set[tuple[str, str]]:
    """Parent/child authority atoms, decomposing an AND hyperedge by parent."""
    return {
        (parent, derivation.child)
        for derivation in graph.derivations.values()
        for parent in derivation.parents
    }


def validation_issues(graph: Hypergraph) -> list[str]:
    issues: list[str] = []
    version_ids = set(graph.versions)
    logical_edges: set[tuple[tuple[str, ...], str, str]] = set()
    for derivation in graph.derivations.values():
        if derivation.child not in version_ids:
            issues.append(f"missing_child:{derivation.did}:{derivation.child}")
        missing = sorted(set(derivation.parents) - version_ids)
        if missing:
            issues.append(f"missing_parent:{derivation.did}:{','.join(missing)}")
        signature = (tuple(sorted(derivation.parents)), derivation.child, derivation.activity)
        if signature in logical_edges:
            issues.append(f"duplicate_derivation:{derivation.did}")
        logical_edges.add(signature)
    for sink in graph.sinks:
        if sink.version_id not in version_ids:
            issues.append(f"missing_sink_version:{sink.qid}")
    for support in graph.support.values():
        missing = sorted(set(support.members) - version_ids)
        if missing:
            issues.append(f"missing_support_member:{support.sid}:{','.join(missing)}")
        if support.goal not in graph.goals:
            issues.append(f"missing_support_goal:{support.sid}:{support.goal}")
    if _has_cycle(graph):
        issues.append("cycle")
    return sorted(issues)


def _has_cycle(graph: Hypergraph) -> bool:
    adjacency: dict[str, set[str]] = {version_id: set() for version_id in graph.versions}
    for derivation in graph.derivations.values():
        for parent in derivation.parents:
            if parent in adjacency and derivation.child in adjacency:
                adjacency[parent].add(derivation.child)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(version_id: str) -> bool:
        if version_id in visiting:
            return True
        if version_id in visited:
            return False
        visiting.add(version_id)
        for child in adjacency[version_id]:
            if visit(child):
                return True
        visiting.remove(version_id)
        visited.add(version_id)
        return False

    return any(visit(version_id) for version_id in sorted(adjacency))


def enumerate_reference_witnesses(graph: Hypergraph) -> list[ReferenceWitness]:
    """Enumerate proof trees with an implementation independent of analysis.py."""
    issues = validation_issues(graph)
    if "cycle" in issues:
        raise ValueError("reference witness enumeration requires an acyclic graph")
    low_sources = graph.low_integrity_sources
    incoming: dict[str, list] = {}
    for derivation in graph.derivations.values():
        incoming.setdefault(derivation.child, []).append(derivation)
    cache: dict[str, tuple[tuple[frozenset[str], frozenset[str]], ...]] = {}

    def proofs(version_id: str) -> tuple[tuple[frozenset[str], frozenset[str]], ...]:
        if version_id in cache:
            return cache[version_id]
        records = incoming.get(version_id, [])
        if not records:
            result = ((frozenset({version_id}), frozenset()),)
            cache[version_id] = result
            return result
        results: set[tuple[frozenset[str], frozenset[str]]] = set()
        for derivation in sorted(records, key=lambda item: item.did):
            combined = {(frozenset({version_id}), frozenset({derivation.did}))}
            for parent in derivation.parents:
                next_combined: set[tuple[frozenset[str], frozenset[str]]] = set()
                for versions, relations in combined:
                    for parent_versions, parent_relations in proofs(parent):
                        next_combined.add(
                            (versions | parent_versions, relations | parent_relations)
                        )
                combined = next_combined
            results.update(combined)
        result = tuple(sorted(results, key=lambda item: (sorted(item[0]), sorted(item[1]))))
        cache[version_id] = result
        return result

    witnesses: set[ReferenceWitness] = set()
    for sink in graph.sinks:
        for versions, derivations in proofs(sink.version_id):
            if versions & low_sources:
                witnesses.add(ReferenceWitness(sink.qid, versions, derivations))
    return sorted(
        witnesses,
        key=lambda witness: (
            witness.root_qid,
            sorted(witness.versions),
            sorted(witness.derivations),
        ),
    )


def reference_break_set(graph: Hypergraph, witness: ReferenceWitness) -> set[str]:
    proof_agents = {
        graph.versions[version_id].agent
        for version_id in witness.versions
        if version_id in graph.versions
        and graph.versions[version_id].agent
        and graph.versions[version_id].kind is not VersionKind.ARGUMENT
    }
    result: set[str] = set()
    for intervention in graph.interventions.values():
        if (
            intervention.kind is InterventionKind.REVOKE_VERSION
            and intervention.target in witness.versions
        ):
            result.add(intervention.iid)
        elif (
            intervention.kind is InterventionKind.DISABLE_EDGE
            and intervention.target in witness.derivations
        ):
            result.add(intervention.iid)
        elif (
            intervention.kind is InterventionKind.DENY_ACTION
            and intervention.target == witness.root_qid
        ):
            result.add(intervention.iid)
        elif (
            intervention.kind is InterventionKind.QUARANTINE_AGENT
            and intervention.target in proof_agents
        ):
            result.add(intervention.iid)
    return result


def reference_bruteforce_cover(
    graph: Hypergraph,
    witnesses: list[ReferenceWitness],
    *,
    max_subsets: int = 200_000,
) -> ReferenceSolve:
    covers = [reference_break_set(graph, witness) for witness in witnesses]
    if not covers:
        return ReferenceSolve("optimal", frozenset(), 0.0, 0)
    if any(not cover for cover in covers):
        return ReferenceSolve("unsatisfiable", frozenset(), inf, 0)
    relevant = sorted(set().union(*covers))
    best: frozenset[str] | None = None
    best_cost = inf
    examined = 0
    min_unit_cost = min(graph.interventions[iid].cost for iid in relevant)
    for size in range(len(relevant) + 1):
        if best is not None and size * min_unit_cost >= best_cost:
            break
        for candidate in combinations(relevant, size):
            examined += 1
            if examined > max_subsets:
                return ReferenceSolve(
                    "feasible" if best is not None else "budget_exhausted",
                    best or frozenset(),
                    best_cost,
                    examined,
                )
            selected = frozenset(candidate)
            cost = sum(graph.interventions[iid].cost for iid in selected)
            if cost >= best_cost:
                continue
            if all(selected & cover for cover in covers):
                best = selected
                best_cost = cost
    if best is None:
        return ReferenceSolve("unsatisfiable", frozenset(), inf, examined)
    return ReferenceSolve("optimal", best, best_cost, examined)


def residual_count(
    graph: Hypergraph,
    witnesses: list[ReferenceWitness],
    selected: set[str],
) -> int:
    return sum(
        1 for witness in witnesses if not (selected & reference_break_set(graph, witness))
    )
