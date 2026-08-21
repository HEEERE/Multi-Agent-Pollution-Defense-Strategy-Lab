from __future__ import annotations

from dataclasses import dataclass, field

from app.provenance.ledger import ProvenanceLedger
from app.provenance.models import ArtifactState, ArtifactVersion, Derivation, ProvenanceLevel


@dataclass
class ProvenanceGraph:
    versions: dict[str, ArtifactVersion] = field(default_factory=dict)
    derivations: dict[str, Derivation] = field(default_factory=dict)
    conservative: bool = True

    def parents(self, version_id: str) -> set[str]:
        return {p for d in self.derivations.values() if d.child_version_id == version_id for p in d.parent_version_ids}

    def ancestors(self, version_id: str) -> set[str]:
        out: set[str] = set()
        stack = [version_id]
        while stack:
            current = stack.pop()
            for parent in self.parents(current):
                if parent not in out:
                    out.add(parent)
                    stack.append(parent)
        return out

    def visible(self, ledger: ProvenanceLedger) -> "ProvenanceGraph":
        """Return the API-safe projection, omitting unavailable state."""
        allowed = {
            version_id for version_id in self.versions
            if (ledger.current_state(version_id) or ArtifactState.ACTIVE).value not in {"quarantined", "invalidated"}
        }
        return ProvenanceGraph(
            versions={k: v for k, v in self.versions.items() if k in allowed},
            derivations={k: d for k, d in self.derivations.items() if d.child_version_id in allowed and all(p in allowed for p in d.parent_version_ids)},
            conservative=self.conservative,
        )


def build_conservative(ledger: ProvenanceLedger, run_id: str, *, visible_inputs: dict[str, tuple[str, ...]] | None = None) -> ProvenanceGraph:
    """Build the P1 over-approximation from all visible input references."""
    graph = ProvenanceGraph(conservative=True)
    graph.versions = {v: ledger.get_artifact(v) for v in _version_ids(ledger, run_id)}
    graph.versions = {k: v for k, v in graph.versions.items() if v is not None}
    for d in ledger.list_derivations(run_id):
        parents = set(d.parent_version_ids)
        if visible_inputs and d.child_version_id in visible_inputs:
            parents.update(visible_inputs[d.child_version_id])
        graph.derivations[d.relation_id] = Derivation(
            d.relation_id, d.run_id, d.child_version_id, tuple(sorted(parents)),
            d.activity_id, "conservative_influence", d.parent_roles,
            d.provenance_level, d.effect_class,
        )
    for support in ledger.list_support_groups(run_id):
        members = tuple(v for v in support.member_version_ids if v in graph.versions)
        if support.goal_id in graph.versions and members:
            graph.derivations[f"support:{support.support_id}"] = Derivation(
                f"support:{support.support_id}", run_id, support.goal_id,
                members, support.verifier_id, "supported_by",
                tuple("support" for _ in members), support.provenance_level,
            )
    return graph


def build_tight(ledger: ProvenanceLedger, run_id: str) -> ProvenanceGraph:
    """Build P0 only from explicitly structured derivation records."""
    graph = ProvenanceGraph(conservative=False)
    graph.versions = {v: ledger.get_artifact(v) for v in _version_ids(ledger, run_id)}
    graph.versions = {k: v for k, v in graph.versions.items() if v is not None}
    graph.derivations = {
        d.relation_id: d for d in ledger.list_derivations(run_id)
        if d.relation_type in {"derived_from", "generated", "supported_by", "authorized"}
        and d.provenance_level.value == "P0"
    }
    for support in ledger.list_support_groups(run_id):
        members = tuple(v for v in support.member_version_ids if v in graph.versions)
        if (
            support.provenance_level is ProvenanceLevel.P0
            and support.goal_id in graph.versions
            and members
        ):
            graph.derivations[f"support:{support.support_id}"] = Derivation(
                f"support:{support.support_id}", run_id, support.goal_id,
                members, support.verifier_id, "supported_by",
                tuple("support" for _ in members), ProvenanceLevel.P0,
            )
    return graph


def _version_ids(ledger: ProvenanceLedger, run_id: str) -> list[str]:
    rows = ledger._conn.execute("SELECT version_id FROM artifact_versions WHERE run_id=?", (run_id,)).fetchall()
    return [row[0] for row in rows]
