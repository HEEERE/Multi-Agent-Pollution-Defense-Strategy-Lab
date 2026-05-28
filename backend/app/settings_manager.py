"""Runtime settings persistence layer.

Stores key-value settings in a SQLite table (same events.db, separate connection).
Seeds factory defaults on first run. In-memory cache for fast synchronous reads.
"""

import json
from pathlib import Path

import aiosqlite

from app.core.config import get_settings

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "events.db"

FACTORY_DEFAULTS: dict[str, dict[str, object]] = {
    "detectors": {
        "regex.enabled": True,
        "regex.action_policy": "block",
        "semantic.threshold": 0.65,
        "semantic.top_k": 5,
        "semantic.min_matches": 1,
        "semantic.auto_calibrate": True,
        "semantic.action_policy": "quarantine",
        "semantic.window_size": 50,
        "llm_intent.enabled": True,
        "llm_intent.self_consistency": True,
        "llm_intent.self_consistency_votes": 3,
        "llm_intent.action_policy": "quarantine",
        "pipeline.fusion_threshold": 0.82,
        "pipeline.short_circuit": True,
        "pipeline.log_all_detections": True,
        "pipeline.min_severity_for_llm": "warning",
        "honeypot.gray_zone_low": 0.50,
        "honeypot.gray_zone_high": 0.75,
    },
    "llm": {
        "llm.provider": "mimo",
        "llm.base_url": str(get_settings().mimo_base_url),
        "llm.model": get_settings().mimo_model,
        "llm.api_key": get_settings().mimo_api_key,
        "llm.temperature": get_settings().llm_temperature,
        "llm.max_tokens": get_settings().llm_max_tokens,
        "llm.request_timeout": get_settings().llm_request_timeout_seconds,
        "llm.enabled": get_settings().llm_enabled,
    },
    "agents": {
        "auditor.reputation_initial": 1.0,
        "auditor.reputation_recovery_rate": 0.02,
        "auditor.reputation_block_threshold": 0.30,
        "auditor.reputation_decay_interval": 60.0,
        "auditor.reputation_decay_rate": 0.05,
        "red_team.enabled": True,
        "red_team.attack_interval_seconds": 5.0,
        "red_team.max_attacks": 20,
        "honeypot.enabled": True,
        "honeypot.default_node": "Honeypot_Agent",
    },
    "system": {
        "system.cors_allowed_origins": "http://localhost:5173,http://127.0.0.1:5173",
        "system.event_retention_limit": 10000,
        "system.ws_ping_interval": 30,
    },
}

VALID_CATEGORIES = {"detectors", "llm", "agents", "system"}


class SettingsManager:
    """Singleton that owns the settings lifecycle: DB, cache, CRUD, seeding."""

    def __init__(self) -> None:
        self._conn: aiosqlite.Connection | None = None
        self._cache: dict[str, dict[str, object]] = {}
        self._ready = False

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(str(DB_PATH))
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute(
                "CREATE TABLE IF NOT EXISTS settings ("
                "  category TEXT NOT NULL,"
                "  key      TEXT NOT NULL,"
                "  value    TEXT NOT NULL,"
                "  updated_at REAL NOT NULL DEFAULT (unixepoch()),"
                "  description TEXT NOT NULL DEFAULT '',"
                "  PRIMARY KEY (category, key)"
                ")"
            )
            await self._conn.commit()
        return self._conn

    async def init(self) -> None:
        conn = await self._get_conn()
        cursor = await conn.execute("SELECT COUNT(*) FROM settings")
        row = await cursor.fetchone()
        count = row[0] if row else 0

        if count == 0:
            await self._seed_defaults(conn)
        else:
            await self._load_cache(conn)

        self._ready = True

    async def _seed_defaults(self, conn: aiosqlite.Connection) -> None:
        import time as _time
        now = _time.time()
        rows: list[tuple[str, str, str, float]] = []
        for category, kv in FACTORY_DEFAULTS.items():
            for key, value in kv.items():
                rows.append((category, key, json.dumps(value), now))
        await conn.executemany(
            "INSERT OR REPLACE INTO settings (category, key, value, updated_at) VALUES (?, ?, ?, ?)",
            rows,
        )
        await conn.commit()
        self._cache = {cat: dict(kv) for cat, kv in FACTORY_DEFAULTS.items()}

    async def _load_cache(self, conn: aiosqlite.Connection) -> None:
        cursor = await conn.execute("SELECT category, key, value FROM settings ORDER BY category, key")
        rows = await cursor.fetchall()
        self._cache = {}
        for category, key, value in rows:
            self._cache.setdefault(category, {})[key] = json.loads(value)

    def get_value_sync(self, category: str, key: str, default: object = None) -> object:
        if not self._ready:
            return default
        cat = self._cache.get(category, {})
        return cat.get(key, default)

    async def get_all(self) -> dict[str, dict[str, object]]:
        return {cat: dict(kv) for cat, kv in self._cache.items()}

    async def get_last_updated(self) -> float | None:
        conn = await self._get_conn()
        cursor = await conn.execute("SELECT MAX(updated_at) FROM settings")
        row = await cursor.fetchone()
        return row[0] if row and row[0] else None

    async def get_category(self, category: str) -> dict[str, object]:
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Unknown settings category: {category}")
        return dict(self._cache.get(category, {}))

    async def update_category(self, category: str, values: dict[str, object]) -> int:
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Unknown settings category: {category}")
        conn = await self._get_conn()
        import time as _time
        now = _time.time()
        updated = 0
        for key, value in values.items():
            self._cache.setdefault(category, {})[key] = value
            await conn.execute(
                "INSERT OR REPLACE INTO settings (category, key, value, updated_at) VALUES (?, ?, ?, ?)",
                (category, key, json.dumps(value), now),
            )
            updated += 1
        await conn.commit()
        return updated

    async def reset_category(self, category: str) -> dict[str, object]:
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Unknown settings category: {category}")
        defaults = FACTORY_DEFAULTS.get(category, {})
        conn = await self._get_conn()
        import time as _time
        now = _time.time()
        await conn.execute("DELETE FROM settings WHERE category = ?", (category,))
        rows = [(category, key, json.dumps(value), now) for key, value in defaults.items()]
        await conn.executemany(
            "INSERT INTO settings (category, key, value, updated_at) VALUES (?, ?, ?, ?)",
            rows,
        )
        await conn.commit()
        self._cache[category] = dict(defaults)
        return dict(defaults)


_settings_manager: SettingsManager | None = None


def get_settings_manager() -> SettingsManager:
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
    return _settings_manager


async def init_settings_manager() -> None:
    mgr = get_settings_manager()
    await mgr.init()
