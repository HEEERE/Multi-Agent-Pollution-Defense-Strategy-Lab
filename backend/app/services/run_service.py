import asyncio
import json
from time import time

from fastapi import HTTPException

from app.event_store import get_event_store
from app.schemas import ExperimentStatus, RunRead, RunStatus, new_id
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

    return RunRead(
        run_id=run_id,
        strategy_id=strategy["strategy_id"],
        strategy_version=strategy.get("version", 1),
        status=RunStatus.QUEUED,
        created_at=now,
    )


async def _execute_strategy_run(
    run_id: str, strategy: dict, *, requeue_on_cancel: bool = False
) -> None:
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

        current = await store.get_run(run_id)
        if current and current.get("status") == "cancelled":
            return

        if result.status == ExperimentStatus.FAILED:
            await store.update_run(
                run_id,
                {
                    "status": "failed",
                    "experiment_id": result.experiment_id,
                    "trace_id": result.trace_id,
                    "error": result.error_message or "experiment failed",
                    "finished_at": time(),
                },
            )
            return

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
        current = await store.get_run(run_id)
        cancelled_by_user = current and current.get("status") == "cancelled"
        if requeue_on_cancel and not cancelled_by_user:
            await store.update_run(
                run_id,
                {
                    "status": "queued",
                    "started_at": None,
                    "finished_at": None,
                    "error": "requeued during server shutdown",
                },
            )
        elif not cancelled_by_user:
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


async def run_worker(stop_event: asyncio.Event) -> None:
    """Process durable SQLite-backed run jobs until shutdown."""
    store = await get_event_store()
    while not stop_event.is_set():
        queued = await store.claim_next_queued_run()
        if queued is None:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=0.25)
            except TimeoutError:
                pass
            continue

        run_id = queued["run_id"]
        strategy_id = queued.get("strategy_id")
        version = queued.get("strategy_version") or 1
        strategy = await store.get_strategy(strategy_id) if strategy_id else None
        snapshot = (
            await store.get_strategy_version(strategy_id, version)
            if strategy_id
            else None
        )
        if strategy is None or snapshot is None:
            await store.update_run(
                run_id,
                {
                    "status": "failed",
                    "error": "strategy snapshot not found",
                    "finished_at": time(),
                },
            )
            continue
        strategy["version"] = version
        strategy["content_json"] = snapshot["content_json"]

        task = asyncio.create_task(
            _execute_strategy_run(run_id, strategy, requeue_on_cancel=True)
        )
        _running_tasks[run_id] = task
        try:
            await task
        except asyncio.CancelledError:
            if stop_event.is_set():
                raise


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
    events = [json.loads(row["event_json"]) if row.get("event_json") else {} for row in rows]
    # The event store intentionally keeps the committed/audit payload. The
    # public API must apply the same provenance state labels as WebSocket
    # transport before returning it to an operator-facing client.
    from app.provenance import ProvenanceLedger
    ledger = ProvenanceLedger(store.db_path.with_name("provenance.db"))
    try:
        has_provenance = bool(ledger.list_artifacts(run_id))
        if not has_provenance:
            return events
        for event in events:
            metadata = event.get("metadata") or {}
            refs = event.get("artifact_refs") or metadata.get("artifact_refs") or []
            refs = list(refs)
            own = event.get("event_id")
            if own:
                refs.append(f"event_{own}")
            unavailable = False
            retained = False
            for ref in refs:
                if ledger.get_artifact(str(ref)) is None:
                    unavailable = True
                    continue
                state = ledger.current_state(str(ref))
                if state is not None and state.value in {"quarantined", "invalidated"}:
                    unavailable = True
                if state is not None and state.value == "retained":
                    retained = True
            if unavailable or retained:
                event["payload_snippet"] = (
                    "[REDACTED: unavailable provenance]"
                    if unavailable else "[REDACTED: retained label required]"
                )
                event["metadata"] = {
                    **metadata,
                    "projection_filtered": True,
                    "confidentiality": "unavailable" if unavailable else "restricted",
                    "retained_label": retained,
                }
        return events
    finally:
        ledger.close()


async def cancel_run(run_id: str) -> dict:
    task = _running_tasks.get(run_id)
    if task and not task.done():
        store = await get_event_store()
        await store.update_run(
            run_id, {"status": "cancelled", "finished_at": time()}
        )
        task.cancel()
        return {"run_id": run_id, "status": "cancelled"}

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
