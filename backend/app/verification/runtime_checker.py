from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.provenance.models import ArtifactState
from app.provenance.projection import ProvenanceGraph


class RuntimeCheckStatus(StrEnum):
    COVERED = "COVERED"
    UNSAFE = "UNSAFE"
    UNSATISFIABLE = "UNSATISFIABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RuntimeWitness:
    sink_version_id: str
    low_integrity_versions: frozenset[str]
    path: tuple[str, ...]
    declared_break_set: frozenset[str] | None = None

    @property
    def break_versions(self) -> frozenset[str]:
        return frozenset(
            self.low_integrity_versions
            if self.declared_break_set is None else self.declared_break_set
        )


@dataclass(frozen=True)
class RuntimeCheckResult:
    status: RuntimeCheckStatus
    witnesses: tuple[RuntimeWitness, ...]
    exhaustive: bool
    completeness_evidence: str


class RuntimeWitnessChecker:
    """Independent conservative-path checker for the online graph."""

    def __init__(self, *, max_versions: int = 50_000) -> None:
        self.max_versions = max_versions

    def check(
        self,
        graph: ProvenanceGraph,
        *,
        sink_versions: set[str],
        blocked_versions: set[str] | None = None,
        uncoverable_versions: set[str] | None = None,
        break_sets: dict[str, frozenset[str]] | None = None,
    ) -> RuntimeCheckResult:
        """Classify the current witness search with explicit three-state semantics.

        ``uncoverable_versions`` is supplied by an intervention planner when it
        proves that a witness has an empty break set (for example an already
        executed external effect or a protected infrastructure root). It is
        deliberately separate from budget exhaustion: the former is a proven
        UNSATISFIABLE safety result, while the latter remains UNKNOWN.
        """
        blocked_versions = blocked_versions or set()
        uncoverable_versions = uncoverable_versions or set()
        break_sets = break_sets or {}
        if len(graph.versions) > self.max_versions:
            return RuntimeCheckResult(RuntimeCheckStatus.UNKNOWN, (), False, "BUDGET_EXHAUSTED")
        impossible = [
            sink for sink in sink_versions
            if sink in uncoverable_versions or sink in break_sets and not break_sets[sink]
        ]
        if impossible:
            witnesses = tuple(
                RuntimeWitness(sink, frozenset(), (sink,)) for sink in sorted(impossible)
            )
            return RuntimeCheckResult(
                RuntimeCheckStatus.UNSATISFIABLE,
                witnesses,
                True,
                "UNCOVERABLE_BREAK_SET",
            )
        witnesses: list[RuntimeWitness] = []
        for sink_id in sink_versions:
            # A denied/invalidated sink is a deliberate cut even when the
            # visible projection has already removed its artifact row.
            if sink_id in blocked_versions:
                continue
            if sink_id not in graph.versions:
                return RuntimeCheckResult(
                    RuntimeCheckStatus.UNKNOWN, (), False, "SINK_NOT_IN_GRAPH"
                )
            stack: list[tuple[str, tuple[str, ...], frozenset[str]]] = [(sink_id, (sink_id,), frozenset())]
            seen: set[tuple[str, frozenset[str]]] = set()
            while stack:
                current, path, low = stack.pop()
                if current in blocked_versions:
                    continue
                key = (current, low)
                if key in seen:
                    continue
                seen.add(key)
                artifact = graph.versions.get(current)
                if artifact is None:
                    continue
                next_low = low | ({current} if artifact.integrity == "low" else set())
                parents = graph.parents(current)
                if not parents:
                    if next_low:
                        witnesses.append(RuntimeWitness(sink_id, next_low, path, break_sets.get(sink_id)))
                    continue
                for parent in parents:
                    stack.append((parent, path + (parent,), next_low))
        unique = tuple({(w.sink_version_id, w.low_integrity_versions, w.path): w for w in witnesses}.values())
        if unique:
            return RuntimeCheckResult(RuntimeCheckStatus.UNSAFE, unique, True, "full_enumeration")
        return RuntimeCheckResult(RuntimeCheckStatus.COVERED, (), True, "full_enumeration")
