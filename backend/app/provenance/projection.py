"""Read-only typed graph projection.

This module holds the graph *type* only. The two builders live in
``conservative_builder.py`` (P1 over-approximation, the sole basis for safety
conclusions) and ``tight_builder.py`` (P0 under-approximation, propose-only).
Keeping them apart is what makes the v4 §11.1 static dependency boundary
enforceable: a module may depend on the graph type without gaining access to
the tight builder.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.provenance.ledger import ProvenanceLedger
from app.provenance.models import ArtifactState, ArtifactVersion, Derivation


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
