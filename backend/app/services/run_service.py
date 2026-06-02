import asyncio
import json
from time import time

from fastapi import HTTPException

from app.event_store import get_event_store
from app.schemas import RunRead, RunStatus, new_id
from app.strategy.compiler import compile_strategy

_running_tasks: dict[str, asyncio.Task] = {}


async def create_run_from_strategy(strategy: dict) -> RunRead:
    store = await get_event_store()
    now = time()
    run_id = new_id()

    run = {
        "run_id": run_id,
        "strategy_id": strategy["strategy_id"],
        "strategy_version": strategy.get("version", 1),
        "experiment_id": None,
        "trace_id": None,
        "status": "queued",
        "error": None,
        "metrics_json": None,
        "created_at": now,
        "started_at": None,
        "finished_at": None,
    }
    await store.store_run(run)

    task = asyncio.create_task(_execute_strategy_run(run_id, strategy))
    _running_tasks[run_id] = task

    return RunRead(
        run_id=run_id,
        strategy_id=strategy["strategy_id"],
        strategy_version=strategy.get("version", 1),
        status=RunStatus.QUEUED,
        created_at=now,
    )


async def _execute_strategy_run(run_id: str, strategy: dict) -> None:
    store = await get_event_store()
    try:
        await store.update_run(
            run_id, {"status": "running", "started_at": time()}
        )

        content = json.loads(strategy.get("content_json", "{}"))
        config = compile_strategy(
            content,
            run_id=run_id,
            strategy_id=strategy["strategy_id"],
            strategy_version=strategy.get("version", 1),
        )

        from app.experiments.runner import ExperimentRunner

        runner = ExperimentRunner(store)
        result = await runner.run(config)

        await store.update_run(
            run_id,
            {
                "status": "completed",
                "experiment_id": result.experiment_id,
                "trace_id": result.trace_id,
                "metrics_json": result.metrics.model_dump_json()
                if result.metrics
                else None,
                "finished_at": time(),
            },
        )

    except asyncio.CancelledError:
        await store.update_run(
            run_id, {"status": "cancelled", "finished_at": time()}
        )
        raise

    except Exception as exc:
        await store.update_run(
            run_id,
            {
                "status": "failed",
                "error": str(exc),
                "finished_at": time(),
            },
        )

    finally:
        _running_tasks.pop(run_id, None)


async def get_run(run_id: str) -> RunRead:
    store = await get_event_store()
    row = await store.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")

    metrics = {}
    if row.get("metrics_json"):
        try:
            metrics = json.loads(row["metrics_json"])
        except (json.JSONDecodeError, TypeError):
            pass

    return RunRead(
        run_id=row["run_id"],
        strategy_id=row.get("strategy_id"),
        strategy_version=row.get("strategy_version"),
        experiment_id=row.get("experiment_id"),
        trace_id=row.get("trace_id"),
        status=RunStatus(row["status"]),
        error=row.get("error"),
        metrics=metrics,
        created_at=row.get("created_at", 0),
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
    )


async def get_run_metrics(run_id: str) -> dict:
    store = await get_event_store()
    row = await store.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    if not row.get("metrics_json"):
        raise HTTPException(status_code=404, detail="metrics not available")
    try:
        return json.loads(row["metrics_json"])
    except (json.JSONDecodeError, TypeError):
        return {}


async def get_run_events(
    run_id: str, limit: int = 200, offset: int = 0
) -> list[dict]:
    store = await get_event_store()
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    rows = await store.get_run_events(run_id, limit=limit, offset=offset)
    return [
        json.loads(row["event_json"]) if row.get("event_json") else {}
        for row in rows
    ]


async def cancel_run(run_id: str) -> dict:
    task = _running_tasks.get(run_id)
    if task and not task.done():
        task.cancel()
        return {"run_id": run_id, "status": "cancelling"}

    store = await get_event_store()
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.get("status") in ("queued", "running"):
        await store.update_run(
            run_id, {"status": "cancelled", "finished_at": time()}
        )
        return {"run_id": run_id, "status": "cancelled"}

    raise HTTPException(
        status_code=409, detail="run cannot be cancelled"
    )
