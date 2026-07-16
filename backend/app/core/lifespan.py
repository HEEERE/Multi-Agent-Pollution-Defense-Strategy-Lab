import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.demo_topology import init_event_store, rebuild_runtime_pipeline
from app.event_store import close_event_store, get_event_store
from app.services.run_service import run_worker
from app.settings_manager import close_settings_manager, init_settings_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_settings_manager()
    await init_event_store()

    # Running jobs are durable: requeue them after an unclean restart.
    store = await get_event_store()
    await store.requeue_interrupted_runs()

    rebuild_runtime_pipeline()
    stop_worker = asyncio.Event()
    worker_task = asyncio.create_task(run_worker(stop_worker))
    try:
        yield
    finally:
        stop_worker.set()
        worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await worker_task
        await close_event_store()
        await close_settings_manager()
