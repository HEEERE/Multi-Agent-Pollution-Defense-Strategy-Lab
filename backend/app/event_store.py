import json
from collections.abc import AsyncGenerator
from pathlib import Path

import aiosqlite

from app.schemas import AgentEvent, EventSeverity, EventStatus, TraceSummary

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "events.db"

CREATE_EVENTS_TABLE = """
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
);
"""

CREATE_EXPERIMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    trace_id TEXT,
    metrics_json TEXT,
    started_at REAL,
    completed_at REAL,
    error_message TEXT
);
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_events_trace_id ON events(trace_id);",
    "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_events_severity ON events(severity);",
    "CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);",
    "CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type);",
    "CREATE INDEX IF NOT EXISTS idx_experiments_status ON experiments(status);",
    "CREATE INDEX IF NOT EXISTS idx_experiments_started_at ON experiments(started_at);",
]


MIGRATION_COLUMNS: list[tuple[str, str]] = [
    ("event_category", "event_category TEXT"),
    ("risk_tags", "risk_tags TEXT NOT NULL DEFAULT '[]'"),
    ("trust_level", "trust_level TEXT NOT NULL DEFAULT 'unknown'"),
    ("contamination_score", "contamination_score REAL NOT NULL DEFAULT 0.0"),
    ("policy_decision", "policy_decision TEXT"),
    ("policy_id", "policy_id TEXT"),
    ("edge_kind", "edge_kind TEXT"),
    ("artifact_refs", "artifact_refs TEXT NOT NULL DEFAULT '[]'"),
]


async def _ensure_column(conn: aiosqlite.Connection, table: str, column: str, ddl: str) -> None:
    cursor = await conn.execute(f"PRAGMA table_info({table})")
    rows = await cursor.fetchall()
    columns = {row["name"] for row in rows}
    if column not in columns:
        await conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _parse_json_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _event_to_row(event: AgentEvent) -> dict:
    return {
        "event_id": event.event_id,
        "trace_id": event.trace_id,
        "parent_event_id": event.parent_event_id,
        "timestamp": event.timestamp,
        "event_type": event.event_type.value,
        "source_node": event.source_node,
        "target_node": event.target_node,
        "payload_snippet": event.payload_snippet,
        "status": event.status.value,
        "action_taken": event.action_taken.value,
        "severity": event.severity.value,
        "monitor_level": event.monitor_level.value,
        "metadata": json.dumps(event.metadata, ensure_ascii=False),
        "event_category": event.event_category,
        "risk_tags": json.dumps(event.risk_tags, ensure_ascii=False),
        "trust_level": event.trust_level,
        "contamination_score": event.contamination_score,
        "policy_decision": event.policy_decision,
        "policy_id": event.policy_id,
        "edge_kind": event.edge_kind,
        "artifact_refs": json.dumps(event.artifact_refs, ensure_ascii=False),
    }


def _row_to_event(row: aiosqlite.Row) -> AgentEvent:
    return AgentEvent(
        event_id=row["event_id"],
        trace_id=row["trace_id"],
        parent_event_id=row["parent_event_id"],
        timestamp=row["timestamp"],
        event_type=row["event_type"],
        source_node=row["source_node"],
        target_node=row["target_node"],
        payload_snippet=row["payload_snippet"],
        status=row["status"],
        action_taken=row["action_taken"],
        severity=row["severity"],
        monitor_level=row["monitor_level"],
        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        event_category=row["event_category"] if "event_category" in row.keys() else None,
        risk_tags=_parse_json_list(row["risk_tags"]) if "risk_tags" in row.keys() else [],
        trust_level=row["trust_level"] if "trust_level" in row.keys() else "unknown",
        contamination_score=row["contamination_score"] if "contamination_score" in row.keys() else 0.0,
        policy_decision=row["policy_decision"] if "policy_decision" in row.keys() else None,
        policy_id=row["policy_id"] if "policy_id" in row.keys() else None,
        edge_kind=row["edge_kind"] if "edge_kind" in row.keys() else None,
        artifact_refs=_parse_json_list(row["artifact_refs"]) if "artifact_refs" in row.keys() else [],
    )


class EventStore:
    def __init__(self, db_path: str | Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(str(self.db_path))
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL;")
            await self._conn.execute("PRAGMA foreign_keys=ON;")
            await self._conn.execute(CREATE_EVENTS_TABLE)
            await self._conn.execute(CREATE_EXPERIMENTS_TABLE)
            for col_name, col_ddl in MIGRATION_COLUMNS:
                await _ensure_column(self._conn, "events", col_name, col_ddl)
            for idx in INDEXES:
                await self._conn.execute(idx)
            await self._conn.commit()
        return self._conn

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ── Event CRUD ────────────────────────────────────────────

    async def store_event(self, event: AgentEvent) -> None:
        conn = await self._get_conn()
        row = _event_to_row(event)
        columns = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        await conn.execute(
            f"INSERT OR REPLACE INTO events ({columns}) VALUES ({placeholders})",
            list(row.values()),
        )
        await conn.commit()

    async def store_events(self, events: list[AgentEvent]) -> None:
        conn = await self._get_conn()
        for event in events:
            row = _event_to_row(event)
            columns = ", ".join(row.keys())
            placeholders = ", ".join("?" for _ in row)
            await conn.execute(
                f"INSERT OR REPLACE INTO events ({columns}) VALUES ({placeholders})",
                list(row.values()),
            )
        await conn.commit()

    async def get_event(self, event_id: str) -> AgentEvent | None:
        conn = await self._get_conn()
        cursor = await conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
        row = await cursor.fetchone()
        return _row_to_event(row) if row else None

    async def get_events_by_trace(self, trace_id: str) -> list[AgentEvent]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT * FROM events WHERE trace_id = ? ORDER BY timestamp ASC",
            (trace_id,),
        )
        return [_row_to_event(row) for row in await cursor.fetchall()]

    async def get_trace_ids(self, limit: int = 50, offset: int = 0) -> list[str]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT DISTINCT trace_id FROM events ORDER BY trace_id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [row["trace_id"] for row in await cursor.fetchall()]

    async def get_trace_summary(self, trace_id: str) -> TraceSummary | None:
        events = await self.get_events_by_trace(trace_id)
        if not events:
            return None
        status_counts: dict[str, int] = {}
        severity_counts: dict[str, int] = {}
        nodes: set[str] = set()
        for e in events:
            s = e.status.value
            status_counts[s] = status_counts.get(s, 0) + 1
            sv = e.severity.value
            severity_counts[sv] = severity_counts.get(sv, 0) + 1
            nodes.add(e.source_node)
            nodes.add(e.target_node)
        return TraceSummary(
            trace_id=trace_id,
            event_count=len(events),
            start_time=events[0].timestamp,
            end_time=events[-1].timestamp,
            status_counts=status_counts,
            severity_counts=severity_counts,
            nodes_involved=sorted(nodes),
        )

    async def get_latest_events(self, limit: int = 100) -> list[AgentEvent]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        return [_row_to_event(row) for row in await cursor.fetchall()]

    async def query_events(
        self,
        trace_id: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AgentEvent]:
        conn = await self._get_conn()
        clauses: list[str] = []
        params: list[str] = []
        if trace_id:
            clauses.append("trace_id = ?")
            params.append(trace_id)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor = await conn.execute(
            f"SELECT * FROM events {where} ORDER BY timestamp ASC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return [_row_to_event(row) for row in await cursor.fetchall()]

    async def delete_trace(self, trace_id: str) -> int:
        conn = await self._get_conn()
        cursor = await conn.execute("DELETE FROM events WHERE trace_id = ?", (trace_id,))
        await conn.commit()
        return cursor.rowcount

    async def event_count(self, trace_id: str | None = None) -> int:
        conn = await self._get_conn()
        if trace_id:
            cursor = await conn.execute(
                "SELECT COUNT(*) as cnt FROM events WHERE trace_id = ?", (trace_id,)
            )
        else:
            cursor = await conn.execute("SELECT COUNT(*) as cnt FROM events")
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    # ── Experiment persistence ────────────────────────────────

    async def store_experiment(self, experiment: dict) -> None:
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO experiments
               (experiment_id, name, config_json, status, trace_id,
                metrics_json, started_at, completed_at, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                experiment.get("experiment_id"),
                experiment.get("name"),
                experiment.get("config_json", "{}"),
                experiment.get("status", "pending"),
                experiment.get("trace_id"),
                experiment.get("metrics_json"),
                experiment.get("started_at"),
                experiment.get("completed_at"),
                experiment.get("error_message"),
            ),
        )
        await conn.commit()

    async def get_experiment(self, experiment_id: str) -> dict | None:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_experiments(self, limit: int = 50, offset: int = 0) -> list[dict]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT * FROM experiments ORDER BY started_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def delete_experiment(self, experiment_id: str) -> int:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "DELETE FROM experiments WHERE experiment_id = ?", (experiment_id,)
        )
        await conn.commit()
        return cursor.rowcount

    async def update_experiment(self, experiment_id: str, updates: dict) -> None:
        conn = await self._get_conn()
        sets = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [experiment_id]
        await conn.execute(f"UPDATE experiments SET {sets} WHERE experiment_id = ?", values)
        await conn.commit()


_event_store: EventStore | None = None


async def get_event_store() -> EventStore:
    global _event_store
    if _event_store is None:
        _event_store = EventStore()
        await _event_store._get_conn()
    return _event_store


async def close_event_store() -> None:
    global _event_store
    if _event_store is not None:
        await _event_store.close()
        _event_store = None
