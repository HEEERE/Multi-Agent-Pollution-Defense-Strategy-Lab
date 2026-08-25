"""Sink reachability, Clean_E and the three-way taint classification (v4 §3.7).

The three-way split is the whole point of the asymmetric design: a contaminated
version that cannot reach any protected sink is *retainable*, because harm
happens at the sink, not in storage. Collapsing it into a single "contaminated"
class is what forces a defence to over-block.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.provenance.models import ArtifactKind, TaintClass
from app.provenance.projection import ProvenanceGraph
from app.state.costs import AppliedInterventions

EMPTY_APPLIED = AppliedInterventions(frozenset(), frozenset(), frozenset())


def _incoming(graph: ProvenanceGraph) -> dict[str, list]:
    index: dict[str, list] = {}
    for derivation in graph.derivations.values():
        index.setdefault(derivation.child_version_id, []).append(derivation)
    return index


def topological_order(graph: ProvenanceGraph) -> list[str]:
    """Parents before children (Kahn). Cycle members are appended last.

    A provenance ledger is a DAG by construction (A5), but the projection is
    rebuilt from records that could in principle be malformed. Appending any
    cycle rather than raising keeps Clean_E defined; the cycle members then fail
    the parent conjunction and come out *not clean*, which is the safe direction.
    """
    incoming = _incoming(graph)
    indegree: dict[str, int] = {v: 0 for v in graph.versions}
    children: dict[str, list[str]] = {}
    for version_id, derivations in incoming.items():
        parents = {p for d in derivations for p in d.parent_version_ids if p in graph.versions}
        indegree[version_id] = len(parents)
        for parent in parents:
            children.setdefault(parent, []).append(version_id)
    queue = sorted(v for v, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for child in sorted(children.get(current, ())):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
        queue.sort()
    order.extend(sorted(set(graph.versions) - set(order)))
    return order


def clean_e(graph: ProvenanceGraph, removed_versions: set[str] | None = None) -> dict[str, bool]:
    """Conservative causal cleanliness.

    A version is clean iff it is not removed, is not low integrity, and *every*
    parent of *every* incoming influence record is clean. On the conservative
    graph that conjunction ranges over one record per visible input, which is
    exactly the structural collapse the asymmetric mechanism exists to survive.
    """
    removed = removed_versions or set()
    incoming = _incoming(graph)
    out: dict[str, bool] = {}
    for version_id in topological_order(graph):
        if version_id in removed:
            out[version_id] = False
            continue
        artifact = graph.versions.get(version_id)
        if artifact is not None and artifact.integrity == "low":
            out[version_id] = False
            continue
        records = incoming.get(version_id, ())
        if not records:
            out[version_id] = True
            continue
        out[version_id] = all(
            out.get(parent, False)
            for record in records
            for parent in record.parent_version_ids
        )
    return out


def sink_reachable(
    graph: ProvenanceGraph,
    sink_versions: set[str],
    *,
    applied: AppliedInterventions | None = None,
) -> set[str]:
    """Versions that can still influence at least one live protected sink.

    Backward closure from the live sinks over derivation records. Backward, not
    forward: influence flows parent → child, so what matters is which versions
    the sink's argument depends on.
    """
    applied = applied or EMPTY_APPLIED
    incoming = _incoming(graph)
    seen: set[str] = set()
    stack = [
        s for s in sink_versions
        if s not in applied.removed_versions and s not in applied.denied_sinks
    ]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for record in incoming.get(current, ()):
            if record.relation_id in applied.removed_relations:
                continue
            for parent in record.parent_version_ids:
                if parent in applied.removed_versions or parent in seen:
                    continue
                stack.append(parent)
    return seen


@dataclass
class TaintReport:
    classes: dict[str, TaintClass] = field(default_factory=dict)
    members: dict[TaintClass, list[str]] = field(default_factory=dict)

    def of(self, taint: TaintClass) -> list[str]:
        return self.members.get(taint, [])

    @property
    def total(self) -> int:
        return len(self.classes)

    @property
    def clean_survival_rate(self) -> float:
        return len(self.of(TaintClass.CLEAN)) / self.total if self.total else 0.0

    @property
    def retention_rate(self) -> float:
        """Fraction rescued by the asymmetric mechanism (v4 theorem 5)."""
        return (
            len(self.of(TaintClass.CONTAMINATED_UNREACHABLE)) / self.total
            if self.total
            else 0.0
        )

    @property
    def asymmetric_available_rate(self) -> float:
        return self.clean_survival_rate + self.retention_rate


def classify(
    graph: ProvenanceGraph,
    sink_versions: set[str],
    *,
    applied: AppliedInterventions | None = None,
    include_arguments: bool = False,
) -> TaintReport:
    """Three-way taint classification over the conservative graph.

    ``include_arguments=False`` excludes sink arguments: they are the protected
    objects, not retention candidates, so counting them would inflate the
    availability rates.
    """
    applied = applied or EMPTY_APPLIED
    cleanliness = clean_e(graph, set(applied.removed_versions))
    reachable = sink_reachable(graph, sink_versions, applied=applied)
    report = TaintReport(members={taint: [] for taint in TaintClass})
    for version_id, artifact in graph.versions.items():
        if not include_arguments and artifact.kind is ArtifactKind.ARGUMENT:
            continue
        if cleanliness.get(version_id, False):
            taint = TaintClass.CLEAN
        elif version_id in reachable:
            taint = TaintClass.CONTAMINATED_REACHABLE
        else:
            taint = TaintClass.CONTAMINATED_UNREACHABLE
        report.classes[version_id] = taint
        report.members[taint].append(version_id)
    for members in report.members.values():
        members.sort()
    return report
