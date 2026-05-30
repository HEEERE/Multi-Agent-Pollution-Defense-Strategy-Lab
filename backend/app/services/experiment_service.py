"""Experiment business logic — CRUD, metrics, and trace retrieval."""

import json

from fastapi import HTTPException

from app.event_store import get_event_store
from app.experiments.runner import ExperimentRunner
from app.schemas import ExperimentConfig, ExperimentRun


async def create_experiment(config: ExperimentConfig) -> ExperimentRun:
    store = await get_event_store()
    runner = ExperimentRunner(store)
    return await runner.run(config)


async def list_experiments(limit: int = 50, offset: int = 0) -> list[dict]:
    store = await get_event_store()
    return await store.list_experiments(limit=limit, offset=offset)


async def get_experiment(experiment_id: str) -> dict | None:
    store = await get_event_store()
    return await store.get_experiment(experiment_id)


async def delete_experiment(experiment_id: str) -> dict:
    store = await get_event_store()
    count = await store.delete_experiment(experiment_id)
    return {"deleted": count, "experiment_id": experiment_id}


async def get_experiment_trace(experiment_id: str) -> list:
    store = await get_event_store()
    exp = await store.get_experiment(experiment_id)
    if exp is None or not exp.get("trace_id"):
        return []
    return await store.get_events_by_trace(exp["trace_id"])


async def get_experiment_metrics(experiment_id: str) -> dict:
    store = await get_event_store()
    exp = await store.get_experiment(experiment_id)
    if exp is None or not exp.get("metrics_json"):
        raise HTTPException(status_code=404, detail="metrics not available")
    return json.loads(exp["metrics_json"])
