import json

import pytest

import app.settings_manager as settings_module


@pytest.mark.asyncio
async def test_init_removes_legacy_persisted_api_key(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "DB_PATH", tmp_path / "events.db")
    manager = settings_module.SettingsManager()
    conn = await manager._get_conn()
    await conn.execute(
        "INSERT INTO settings (category, key, value) VALUES (?, ?, ?)",
        ("llm", "llm.api_key", json.dumps("legacy-secret")),
    )
    await conn.commit()

    await manager.init()

    assert manager.get_value_sync("llm", "llm.api_key") is None
    cursor = await conn.execute(
        "SELECT COUNT(*) FROM settings WHERE category = 'llm' AND key = 'llm.api_key'"
    )
    assert (await cursor.fetchone())[0] == 0
    await manager.close()
