"""Cheap sufficient conditions for exhaustiveness (v4 搂4.2).

Both conditions are *sound but incomplete*: when one holds, no witness can remain
and the answer is EXHAUSTIVE_NO_WITNESS without enumerating anything. When
neither holds, nothing is proved 鈥?enumeration still has to run.

Independence is structural. This module takes the residual view as three plain
sets and imports nothing from ``state/``: not the enumerator, not a solver, not
the cost model. The walks below are their own implementation, so a bug in the
optimiser cannot be laundered into a completeness claim. Enforced by
``tests/test_research_isolation.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.provenance.projection import ProvenanceGraph


class Completeness(StrEnum):
    EXHAUSTIVE_NO_WITNESS = "EXHAUSTIVE_NO_WITNESS"
    """Proved: the residual graph admits no witness at all."""

    WITNESS_FOUND = "WITNESS_FOUND"
    """At least one residual witness exists."""

    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    """Enumeration stopped early. Nothing is proved either way."""


@dataclass(frozen=True)
class CompletenessEvidence:
    status: Completeness
    condition: str = "none"
    """``SC1`` | ``SC2`` | ``enumeration`` | ``none``."""

    @property
    def proves_absence(self) -> bool:
        return self.status is Completeness.EXHAUSTIVE_NO_WITNESS


def _low_integrity(graph: ProvenanceGraph) -> set[str]:
    return {
        version_id for version_id, artifact in graph.versions.items()
        if artifact.integrity == "low"
    }


def _live_sinks(
    sink_versions: set[str], removed_versions: set[str], denied_sinks: set[str]
) -> list[str]:
    return sorted(s for s in sink_versions if s not in denied_sinks and s not in removed_versions)


def _backward_closure(
    graph: ProvenanceGraph,
    roots: list[str],
    removed_versions: set[str],
    removed_relations: set[str],
) -> set[str]:
    """Own backward walk. Not shared with the enumerator, by design."""
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for derivation in graph.derivations.values():
            if derivation.child_version_id != current:
                continue
            if derivation.relation_id in removed_relations:
                continue
            for parent in derivation.parent_version_ids:
                if parent in removed_versions or parent in seen:
                    continue
                stack.append(parent)
    return seen


def sc1_layer_cut(
    graph: ProvenanceGraph,
    sink_versions: set[str],
    *,
    removed_versions: set[str] | None = None,
    removed_relations: set[str] | None = None,
    denied_sinks: set[str] | None = None,
) -> bool:
    """SC1: no live low-integrity version can still reach any live sink.

    Sound because any residual witness would place a live low-integrity version
    inside some live sink's backward closure. An empty intersection therefore
    proves no witness remains. Two linear passes, no enumeration.
    """
    removed_versions = removed_versions or set()
    removed_relations = removed_relations or set()
    live = _live_sinks(sink_versions, removed_versions, denied_sinks or set())
    if not live:
        return True  # every sink denied or removed: nothing left to protect
    closure = _backward_closure(graph, live, removed_versions, removed_relations)
    return not (closure & (_low_integrity(graph) - removed_versions))


def sc2_sink_domination(
    graph: ProvenanceGraph,
    sink_versions: set[str],
    *,
    removed_versions: set[str] | None = None,
    removed_relations: set[str] | None = None,
    denied_sinks: set[str] | None = None,
) -> bool:
    """SC2: every live sink has all of its incoming records disabled.

    A sink whose every inbound derivation is cut has no proof rooted at it, so no
    witness can be rooted there either. A sink with no inbound records at all is
    *not* dominated 鈥?it may itself carry a low-integrity label.
    """
    removed_relations = removed_relations or set()
    for sink in _live_sinks(sink_versions, removed_versions or set(), denied_sinks or set()):
        incoming = [d for d in graph.derivations.values() if d.child_version_id == sink]
        if incoming and all(d.relation_id in removed_relations for d in incoming):
            continue
        return False
    return True


def cheap_completeness(
    graph: ProvenanceGraph,
    sink_versions: set[str],
    *,
    removed_versions: set[str] | None = None,
    removed_relations: set[str] | None = None,
    denied_sinks: set[str] | None = None,
) -> CompletenessEvidence:
    """Try SC1 then SC2. ``condition='none'`` means enumeration must run."""
    kwargs = {
        "removed_versions": removed_versions,
        "removed_relations": removed_relations,
        "denied_sinks": denied_sinks,
    }
    if sc1_layer_cut(graph, sink_versions, **kwargs):
        return CompletenessEvidence(Completeness.EXHAUSTIVE_NO_WITNESS, "SC1")
    if sc2_sink_domination(graph, sink_versions, **kwargs):
        return CompletenessEvidence(Completeness.EXHAUSTIVE_NO_WITNESS, "SC2")
    return CompletenessEvidence(Completeness.BUDGET_EXHAUSTED, "none")
