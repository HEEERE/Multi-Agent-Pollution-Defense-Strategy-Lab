import json
import tempfile
from pathlib import Path

import aiosqlite
import pytest

from app.event_store import (
    MIGRATION_COLUMNS,
    EventStore,
    _ensure_column,
    _event_to_row,
    _parse_json_list,
    _row_to_event,
)
from app.schemas import AgentEvent, EventType


@pytest.fixture
def temp_db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_new_database_starts_successfully(temp_db_path):
    store = EventStore(db_path=temp_db_path)
    try:
        conn = await store._get_conn()
        cursor = await conn.execute("PRAGMA table_info(events)")
        rows = await cursor.fetchall()
        columns = {row["name"] for row in rows}
        for col_name, _ in MIGRATION_COLUMNS:
            assert col_name in columns, f"Column {col_name} missing"
        assert "event_id" in columns
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_old_schema_simulated_migration(temp_db_path):
    conn = await aiosqlite.connect(temp_db_path)
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            parent_event_id TEXT,
            timestamp REAL NOT NULL,
            event_type TEXT NOT NULL,
            source_node TEXT NOT NULL,
            target_node TEXT NOT NULL,
            payload_snippet TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'safe',
            action_taken TEXT NOT NULL DEFAULT 'none',
            severity TEXT NOT NULL DEFAULT 'info',
            monitor_level INTEGER NOT NULL DEFAULT 0,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL DEFAULT (unixepoch())
        )
    """)
    await conn.commit()
    await conn.close()

    store = EventStore(db_path=temp_db_path)
    try:
        conn = await store._get_conn()
        for col_name, col_ddl in MIGRATION_COLUMNS:
            await _ensure_column(conn, "events", col_name, col_ddl)
        await conn.commit()

        cursor = await conn.execute("PRAGMA table_info(events)")
        columns = {row["name"] for row in await cursor.fetchall()}
        for col_name, _ in MIGRATION_COLUMNS:
            assert col_name in columns
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_write_read_new_fields_roundtrip(temp_db_path):
    store = EventStore(db_path=temp_db_path)
    try:
        event = AgentEvent(
            event_id="evt_test",
            trace_id="trace_test",
            event_type=EventType.INPUT,
            source_node="gw",
            target_node="agent_a",
            payload_snippet="test",
            event_category="prompt_injection",
            risk_tags=["prompt_injection", "test_tag"],
            trust_level="untrusted",
            contamination_score=0.85,
            policy_decision="quarantine",
            policy_id="deny-untrusted-memory-write",
            edge_kind="message",
            artifact_refs=["doc_001", "doc_002"],
        )
        await store.store_event(event)
        loaded = await store.get_event("evt_test")
        assert loaded is not None
        assert loaded.event_category == "prompt_injection"
        assert loaded.risk_tags == ["prompt_injection", "test_tag"]
        assert loaded.trust_level == "untrusted"
        assert loaded.contamination_score == 0.85
        assert loaded.policy_decision == "quarantine"
        assert loaded.policy_id == "deny-untrusted-memory-write"
        assert loaded.edge_kind == "message"
        assert loaded.artifact_refs == ["doc_001", "doc_002"]
    finally:
        await store.close()


def test_old_event_json_still_deserializes():
    old_json = {
        "event_id": "old_evt",
        "trace_id": "old_trace",
        "parent_event_id": None,
        "timestamp": 1000.0,
        "event_type": "input",
        "source_node": "gw",
        "target_node": "agent_a",
        "payload_snippet": "hello",
        "status": "safe",
        "action_taken": "none",
        "severity": "info",
        "monitor_level": 0,
        "metadata": {},
    }
    event = AgentEvent(**old_json)
    assert event.event_id == "old_evt"
    assert event.risk_tags == []
    assert event.trust_level == "unknown"
    assert event.contamination_score == 0.0
    assert event.event_category is None
    assert event.policy_decision is None
    assert event.policy_id is None
    assert event.edge_kind is None
    assert event.artifact_refs == []


def test_parse_json_list():
    assert _parse_json_list('["a", "b"]') == ["a", "b"]
    assert _parse_json_list("") == []
    assert _parse_json_list(None) == []
    assert _parse_json_list("not json") == []
    assert _parse_json_list("[]") == []
