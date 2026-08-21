from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.provenance.ledger import ProvenanceLedger
from app.provenance.models import ArtifactKind, ArtifactState, ArtifactVersion, Derivation


@dataclass
class VersionedArtifactStore:
    ledger: ProvenanceLedger
    run_id: str
    kind: ArtifactKind
    namespace: str

    def put(self, key: str, value: object, *, parents: tuple[str, ...] = (), integrity: str = "unknown", origin_principals: set[str] | None = None) -> ArtifactVersion:
        import hashlib
        import json
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
        version = ArtifactVersion(
            version_id=f"{self.namespace}_{uuid4().hex[:16]}", artifact_id=f"{self.namespace}:{key}",
            run_id=self.run_id, kind=self.kind, value_hash=hashlib.sha256(raw).hexdigest(),
            origin_principals=frozenset(origin_principals or set()), integrity=integrity,
            metadata={"key": key, "value": value},
        )
        self.ledger.append_artifact(version)
        if parents:
            self.ledger.append_derivation(Derivation(
                relation_id=f"rel_{uuid4().hex[:16]}", run_id=self.run_id,
                child_version_id=version.version_id, parent_version_ids=parents,
                activity_id=f"{self.namespace}.put", relation_type="generated",
            ))
        return version

    def get(self, key: str) -> ArtifactVersion | None:
        rows = self.ledger._conn.execute(
            "SELECT version_id FROM artifact_versions WHERE run_id=? AND artifact_id=? ORDER BY created_seq DESC",
            (self.run_id, f"{self.namespace}:{key}"),
        ).fetchall()
        for row in rows:
            version = self.ledger.get_artifact(row[0])
            if version is not None and self.ledger.current_state(version.version_id) not in {ArtifactState.QUARANTINED, ArtifactState.INVALIDATED}:
                return version
        return None

    def visible(self) -> list[ArtifactVersion]:
        return [v for v in self.ledger.list_artifacts(self.run_id) if v.kind is self.kind and self.ledger.current_state(v.version_id) not in {ArtifactState.QUARANTINED, ArtifactState.INVALIDATED}]
