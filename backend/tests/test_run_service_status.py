import json

import pytest

from app.schemas import ExperimentRun, ExperimentStatus
from app.services import run_service


class FakeStore:
    def __init__(self):
        self.updates: list[dict] = []

    async def update_run(self, run_id: str, updates: dict) -> None:
        self.updates.append({"run_id": run_id, **updates})

    async def get_run(self, run_id: str) -> dict:
        return {"run_id": run_id, "status": "running"}


@pytest.mark.asyncio
async def test_failed_experiment_marks_outer_run_failed(monkeypatch):
    store = FakeStore()

    async def get_store():
        return store

    class FailedRunner:
        def __init__(self, event_store):
            assert event_store is store

        async def run(self, config):
            return ExperimentRun(
                experiment_id="exp_failed",
                name=config.name,
                status=ExperimentStatus.FAILED,
                error_message="simulation crashed",
            )

    monkeypatch.setattr(run_service, "get_event_store", get_store)
    monkeypatch.setattr("app.experiments.runner.ExperimentRunner", FailedRunner)

    strategy = {
        "strategy_id": "strategy_1",
        "version": 1,
        "content_json": json.dumps({"name": "failing-run", "topology": {}}),
    }
    await run_service._execute_strategy_run("run_1", strategy)

    assert store.updates[-1]["status"] == "failed"
    assert store.updates[-1]["experiment_id"] == "exp_failed"
    assert store.updates[-1]["error"] == "simulation crashed"
