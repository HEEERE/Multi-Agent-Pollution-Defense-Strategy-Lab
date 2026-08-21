from app.entities import VersionedMemory, VersionedRAG
from app.provenance import ProvenanceLedger
from app.provenance.models import ArtifactState, StateTransition


def test_memory_and_rag_are_versioned_and_hide_invalidated_versions():
    ledger = ProvenanceLedger()
    ledger.ensure_run("r1")
    rag = VersionedRAG(ledger, "r1")
    memory = VersionedMemory(ledger, "r1")
    source = rag.index("doc", "untrusted", integrity="low")
    stored = memory.write("note", "derived", parents=(source.version_id,), integrity="high")
    assert rag.retrieve("doc").version_id == source.version_id
    assert memory.read("note").version_id == stored.version_id
    ledger.transition_state(StateTransition("x", "r1", source.version_id, ArtifactState.ACTIVE, ArtifactState.QUARANTINED, 0, "test"))
    assert rag.retrieve("doc") is None
