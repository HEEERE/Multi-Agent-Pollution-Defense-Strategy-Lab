"""Minimal witness enumeration and break sets (v4 §3.3, §4.2).

A *witness* is a minimal unauthorised authority-flow proof rooted at one
protected sink: one incoming record chosen per derived version, every parent of a
chosen AND record included, and at least one low-integrity version in the result.

Enumeration is lazy and budget-bounded. A caller that stops at the first witness
keeps it — building the whole list first would mean a budget stop loses
everything it had found, and a separation oracle only ever needs one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from app.provenance.models import ArtifactKind
from app.provenance.projection import ProvenanceGraph
from app.state.costs import Intervention, InterventionKind

WITNESS_CAP_DEFAULT = 200_000


@dataclass(frozen=True)
class Witness:
    """One minimal unauthorised authority derivation proof."""

    root_version_id: str
    versions: frozenset[str]
    relations: frozenset[str]

    def key(self) -> tuple:
        return (self.root_version_id, self.versions, self.relations)


@dataclass
class EnumerationResult:
    witnesses: list[Witness]
    exhaustive: bool
    """False when the cap was hit: ``witnesses`` is then a strict subset."""

    @property
    def count(self) -> int:
        return len(self.witnesses)


def low_integrity_versions(graph: ProvenanceGraph) -> set[str]:
    """Versions carrying a low-integrity label.

    Any low-integrity version counts, not only graph leaves. Online a version can
    be labelled low by the gateway while having high-integrity parents (untrusted
    tool output is the common case), and treating it as a contamination origin is
    the conservative direction.
    """
    return {
        version_id for version_id, artifact in graph.versions.items()
        if artifact.integrity == "low"
    }


def iter_witnesses(
    graph: ProvenanceGraph,
    sink_versions: set[str],
    *,
    blocked_versions: set[str] | None = None,
    blocked_relations: set[str] | None = None,
) -> Iterator[Witness]:
    """Yield minimal unauthorised proofs one at a time, cheapest sink first."""
    blocked_versions = blocked_versions or set()
    blocked_relations = blocked_relations or set()
    low = low_integrity_versions(graph) - blocked_versions

    incoming: dict[str, list] = {}
    for derivation in graph.derivations.values():
        if derivation.relation_id in blocked_relations:
            continue
        incoming.setdefault(derivation.child_version_id, []).append(derivation)

    seen: set[tuple] = set()

    def proofs(version_id: str):
        """Yield (versions, relations, touches_low) for ``version_id``."""
        if version_id in blocked_versions:
            return
        records = incoming.get(version_id, ())
        if not records:
            yield frozenset({version_id}), frozenset(), version_id in low
            return
        for record in records:
            # AND semantics: every parent of the chosen record must be proved.
            combos = [(frozenset({version_id}), frozenset({record.relation_id}), version_id in low)]
            for parent in record.parent_version_ids:
                merged = []
                for cv, cr, clow in combos:
                    for sv, sr, slow in proofs(parent):
                        merged.append((cv | sv, cr | sr, clow or slow))
                combos = merged
                if not combos:
                    break
            yield from combos

    for sink in sorted(sink_versions):
        if sink in blocked_versions:
            continue
        for versions, relations, touches_low in proofs(sink):
            if not touches_low:
                continue  # authorised: no low-integrity origin in this proof
            witness = Witness(sink, versions, relations)
            key = witness.key()
            if key in seen:
                continue
            seen.add(key)
            yield witness


def enumerate_witnesses(
    graph: ProvenanceGraph,
    sink_versions: set[str],
    *,
    cap: int = WITNESS_CAP_DEFAULT,
    blocked_versions: set[str] | None = None,
    blocked_relations: set[str] | None = None,
) -> EnumerationResult:
    """Collect up to ``cap`` witnesses.

    ``exhaustive=False`` means the universe is bounded, not that nothing was
    found. A truncated result must never be read as a safety result — that is the
    BUDGET_EXHAUSTED / EXHAUSTIVE_NO_WITNESS distinction of v4 §4.2.
    """
    out: list[Witness] = []
    truncated = False
    for witness in iter_witnesses(
        graph, sink_versions,
        blocked_versions=blocked_versions, blocked_relations=blocked_relations,
    ):
        if len(out) >= cap:
            truncated = True
            break
        out.append(witness)
    return EnumerationResult(out, not truncated)


def break_set(
    graph: ProvenanceGraph,
    catalogue: dict[str, Intervention],
    witness: Witness,
) -> set[str]:
    """Interventions that disable a necessary element of ``witness``.

    ``deny_action`` on the witness root counts, matching the action-scoped
    certificate. ``quarantine_agent`` counts when the agent owns any non-argument
    version in the proof: quarantining it removes that version, which breaks the
    proof. Revoking a sink argument does not count — that is a denial, not a
    revocation, and is priced accordingly.
    """
    out: set[str] = set()
    agents: set[str] = set()
    for version_id in witness.versions:
        artifact = graph.versions.get(version_id)
        if artifact is None or artifact.kind is ArtifactKind.ARGUMENT:
            continue
        agents |= set(artifact.origin_principals)
        iid = f"{InterventionKind.REVOKE_VERSION.value}:{version_id}"
        if iid in catalogue:
            out.add(iid)
    for relation_id in witness.relations:
        iid = f"{InterventionKind.DISABLE_EDGE.value}:{relation_id}"
        if iid in catalogue:
            out.add(iid)
    deny = f"{InterventionKind.DENY_ACTION.value}:{witness.root_version_id}"
    if deny in catalogue:
        out.add(deny)
    for agent in agents:
        iid = f"{InterventionKind.QUARANTINE_AGENT.value}:{agent}"
        if iid in catalogue:
            out.add(iid)
    return out


def coverage_map(
    graph: ProvenanceGraph,
    catalogue: dict[str, Intervention],
    witnesses: list[Witness],
) -> list[set[str]]:
    """One break set per witness — the set-cover constraint matrix."""
    return [break_set(graph, catalogue, witness) for witness in witnesses]


def verify_cover(
    graph: ProvenanceGraph,
    catalogue: dict[str, Intervention],
    witnesses: list[Witness],
    selected: set[str],
) -> bool:
    """Re-derive break sets and check ``selected`` breaks every witness.

    Deliberately re-derives instead of reusing solver state, so a solver bug
    cannot make its own answer look correct.
    """
    return all(selected & break_set(graph, catalogue, w) for w in witnesses)
