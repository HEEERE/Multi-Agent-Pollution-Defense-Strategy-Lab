from __future__ import annotations

from app.entities.versioned import VersionedArtifactStore
from app.provenance.ledger import ProvenanceLedger
from app.provenance.models import ArtifactKind, ArtifactVersion


class VersionedRAG(VersionedArtifactStore):
    def __init__(self, ledger: ProvenanceLedger, run_id: str) -> None:
        super().__init__(ledger, run_id, ArtifactKind.RAG_CHUNK, "rag")

    def index(self, document_id: str, text: str, *, parents: tuple[str, ...] = (), integrity: str = "unknown", origin_principals: set[str] | None = None) -> ArtifactVersion:
        return self.put(document_id, text, parents=parents, integrity=integrity, origin_principals=origin_principals)

    def retrieve(self, document_id: str) -> ArtifactVersion | None:
        return self.get(document_id)
