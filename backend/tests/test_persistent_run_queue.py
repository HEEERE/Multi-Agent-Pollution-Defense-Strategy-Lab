import json

import pytest

from app.event_store import EventStore


@pytest.mark.asyncio
async def test_sqlite_run_queue_claim_and_restart_recovery(tmp_path):
    store = EventStore(tmp_path / "queue.db")
    strategy = {
        "strategy_id": "strategy-1",
        "name": "queued strategy",
        "description": "",
        "format": "json",
        "content_json": json.dumps({"topology": {"nodes": []}}),
        "tags_json": "[]",
        "version": 1,
        "created_at": 1,
        "updated_at": 1,
    }
    await store.store_strategy(strategy)
    await store.store_strategy_version(
        {
            "version_id": "version-1",
            "strategy_id": "strategy-1",
            "version": 1,
            "content_json": strategy["content_json"],
            "created_at": 1,
        }
    )
    await store.store_run(
        {
            "run_id": "run-1",
            "strategy_id": "strategy-1",
            "strategy_version": 1,
            "status": "queued",
            "created_at": 1,
        }
    )

    claimed = await store.claim_next_queued_run()
    assert claimed["run_id"] == "run-1"
    assert claimed["status"] == "running"
    assert await store.claim_next_queued_run() is None

    assert await store.requeue_interrupted_runs() == 1
    recovered = await store.get_run("run-1")
    assert recovered["status"] == "queued"
    assert recovered["error"] == "requeued after server restart"
    assert (await store.get_strategy_version("strategy-1", 1))["version"] == 1
    await store.close()
