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

CREATE_BENCHMARK_TABLE = """
CREATE TABLE IF NOT EXISTS benchmark_reports (
    report_id TEXT PRIMARY KEY,
    timestamp REAL NOT NULL,
    report_json TEXT NOT NULL DEFAULT '{}'
);
"""

CREATE_STRATEGIES_TABLE = """
CREATE TABLE IF NOT EXISTS strategies (
    strategy_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT 'json',
    content_json TEXT NOT NULL DEFAULT '{}',
    tags_json TEXT NOT NULL DEFAULT '[]',
    version INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL DEFAULT (unixepoch()),
    updated_at REAL NOT NULL DEFAULT (unixepoch())
);
"""

CREATE_STRATEGY_VERSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS strategy_versions (
    version_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    content_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT (unixepoch()),
    FOREIGN KEY (strategy_id) REFERENCES strategies(strategy_id) ON DELETE CASCADE
);
"""

CREATE_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    strategy_id TEXT,
    strategy_version INTEGER,
    experiment_id TEXT,
    trace_id TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    error TEXT,
    metrics_json TEXT,
    created_at REAL NOT NULL DEFAULT (unixepoch()),
    started_at REAL,
    finished_at REAL,
    FOREIGN KEY (strategy_id) REFERENCES strategies(strategy_id) ON DELETE SET NULL
);
"""

CREATE_RUN_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    trace_id TEXT,
    event_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT (unixepoch()),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
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
    "CREATE INDEX IF NOT EXISTS idx_strategies_updated ON strategies(updated_at);",
    "CREATE INDEX IF NOT EXISTS idx_strategy_versions_strategy_id ON strategy_versions(strategy_id);",
    "CREATE INDEX IF NOT EXISTS idx_runs_strategy_id ON runs(strategy_id);",
    "CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);",
    "CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events(run_id);",
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
    ("event_json", "event_json TEXT"),
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
        "event_json": event.model_dump_json(exclude_none=True),
    }


def _row_to_event(row: aiosqlite.Row) -> AgentEvent:
    if "event_json" in row.keys() and row["event_json"]:
        return AgentEvent.model_validate_json(row["event_json"])
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
            await self._conn.execute(CREATE_BENCHMARK_TABLE)
            await self._conn.execute(CREATE_STRATEGIES_TABLE)
            await self._conn.execute(CREATE_STRATEGY_VERSIONS_TABLE)
            await self._conn.execute(CREATE_RUNS_TABLE)
            await self._conn.execute(CREATE_RUN_EVENTS_TABLE)
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
            "SELECT trace_id FROM events GROUP BY trace_id ORDER BY MAX(timestamp) DESC LIMIT ? OFFSET ?",
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

    # ── Benchmark persistence ──────────────────────────────────

    async def store_benchmark_report(self, report: dict) -> None:
        conn = await self._get_conn()
        import json as _json
        await conn.execute(
            "INSERT OR REPLACE INTO benchmark_reports (report_id, timestamp, report_json) VALUES (?, ?, ?)",
            (report["report_id"], report["timestamp"], _json.dumps(report, ensure_ascii=False)),
        )
        await conn.commit()

    async def get_benchmark_reports(self) -> list[dict]:
        conn = await self._get_conn()
        import json as _json
        cursor = await conn.execute(
            "SELECT * FROM benchmark_reports ORDER BY timestamp DESC"
        )
        rows = await cursor.fetchall()
        return [_json.loads(row["report_json"]) for row in rows]

    async def get_benchmark_report(self, report_id: str) -> dict | None:
        conn = await self._get_conn()
        import json as _json
        cursor = await conn.execute(
            "SELECT * FROM benchmark_reports WHERE report_id = ?", (report_id,)
        )
        row = await cursor.fetchone()
        return _json.loads(row["report_json"]) if row else None

    # ── Strategy persistence ────────────────────────────────────

    async def store_strategy(self, strategy: dict) -> None:
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO strategies
               (strategy_id, name, description, format, content_json,
                tags_json, version, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                strategy["strategy_id"],
                strategy["name"],
                strategy.get("description", ""),
                strategy.get("format", "json"),
                strategy["content_json"],
                strategy.get("tags_json", "[]"),
                strategy.get("version", 1),
                strategy["created_at"],
                strategy["updated_at"],
            ),
        )
        await conn.commit()

    async def get_strategy(self, strategy_id: str) -> dict | None:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT * FROM strategies WHERE strategy_id = ?", (strategy_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_strategies(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT * FROM strategies ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def delete_strategy(self, strategy_id: str) -> int:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "DELETE FROM strategies WHERE strategy_id = ?", (strategy_id,)
        )
        await conn.commit()
        return cursor.rowcount

    async def update_strategy(self, strategy_id: str, updates: dict) -> None:
        conn = await self._get_conn()
        sets = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [strategy_id]
        await conn.execute(
            f"UPDATE strategies SET {sets} WHERE strategy_id = ?", values
        )
        await conn.commit()

    # ── Strategy version persistence ────────────────────────────

    async def store_strategy_version(self, version: dict) -> None:
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO strategy_versions
               (version_id, strategy_id, version, content_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                version["version_id"],
                version["strategy_id"],
                version["version"],
                version["content_json"],
                version["created_at"],
            ),
        )
        await conn.commit()

    async def get_strategy_versions(self, strategy_id: str) -> list[dict]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT * FROM strategy_versions WHERE strategy_id = ? ORDER BY version DESC",
            (strategy_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_strategy_version(
        self, strategy_id: str, version: int
    ) -> dict | None:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT * FROM strategy_versions WHERE strategy_id = ? AND version = ?",
            (strategy_id, version),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    # ── Run persistence ────────────────────────────────────

    async def store_run(self, run: dict) -> None:
        conn = await self._get_conn()
        await conn.execute(
            """INSERT INTO runs
               (run_id, strategy_id, strategy_version, experiment_id,
                 trace_id, status, error, metrics_json,
                 created_at, started_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(run_id) DO UPDATE SET
                 strategy_id=COALESCE(excluded.strategy_id, runs.strategy_id),
                 strategy_version=COALESCE(excluded.strategy_version, runs.strategy_version),
                 experiment_id=COALESCE(excluded.experiment_id, runs.experiment_id),
                 trace_id=COALESCE(excluded.trace_id, runs.trace_id),
                 status=excluded.status,
                 error=excluded.error,
                 metrics_json=COALESCE(excluded.metrics_json, runs.metrics_json),
                 started_at=COALESCE(excluded.started_at, runs.started_at),
                 finished_at=COALESCE(excluded.finished_at, runs.finished_at)""",
            (
                run["run_id"],
                run.get("strategy_id"),
                run.get("strategy_version"),
                run.get("experiment_id"),
                run.get("trace_id"),
                run.get("status", "queued"),
                run.get("error"),
                run.get("metrics_json"),
                run.get("created_at"),
                run.get("started_at"),
                run.get("finished_at"),
            ),
        )
        await conn.commit()

    async def get_run(self, run_id: str) -> dict | None:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_runs(
        self,
        strategy_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        conn = await self._get_conn()
        if strategy_id:
            cursor = await conn.execute(
                "SELECT * FROM runs WHERE strategy_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (strategy_id, limit, offset),
            )
        else:
            cursor = await conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return [dict(row) for row in await cursor.fetchall()]

    async def update_run(self, run_id: str, updates: dict) -> None:
        conn = await self._get_conn()
        sets = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [run_id]
        await conn.execute(
            f"UPDATE runs SET {sets} WHERE run_id = ?", values
        )
        await conn.commit()

    async def requeue_interrupted_runs(self) -> int:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "UPDATE runs SET status = 'queued', started_at = NULL, finished_at = NULL, "
            "error = 'requeued after server restart' WHERE status = 'running'"
        )
        await conn.commit()
        return cursor.rowcount

    async def claim_next_queued_run(self) -> dict | None:
        """Atomically claim the oldest queued run for a single worker."""
        conn = await self._get_conn()
        try:
            await conn.execute("BEGIN IMMEDIATE")
            cursor = await conn.execute(
                "SELECT run_id FROM runs WHERE status = 'queued' "
                "ORDER BY created_at ASC LIMIT 1"
            )
            row = await cursor.fetchone()
            if row is None:
                await conn.commit()
                return None
            run_id = row["run_id"]
            await conn.execute(
                "UPDATE runs SET status = 'running', started_at = unixepoch(), error = NULL "
                "WHERE run_id = ? AND status = 'queued'",
                (run_id,),
            )
            await conn.commit()
            return await self.get_run(run_id)
        except Exception:
            await conn.rollback()
            raise

    # ── Run event persistence ────────────────────────────────────

    async def store_run_event(self, run_event: dict) -> None:
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO run_events
               (run_id, event_id, trace_id, event_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                run_event["run_id"],
                run_event["event_id"],
                run_event.get("trace_id"),
                run_event.get("event_json", "{}"),
                run_event.get("created_at"),
            ),
        )
        await conn.commit()

    async def get_run_events(
        self, run_id: str, limit: int = 200, offset: int = 0
    ) -> list[dict]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT * FROM run_events WHERE run_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?",
            (run_id, limit, offset),
        )
        return [dict(row) for row in await cursor.fetchall()]


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
