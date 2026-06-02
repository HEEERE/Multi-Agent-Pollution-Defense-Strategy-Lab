from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.demo_topology import init_event_store, rebuild_runtime_pipeline
from app.event_store import get_event_store
from app.settings_manager import init_settings_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_settings_manager()
    await init_event_store()

    # Mark any runs left in queued/running from a prior crash as failed
    store = await get_event_store()
    conn = await store._get_conn()
    await conn.execute(
        "UPDATE runs SET status = 'failed', error = 'server restarted', "
        "finished_at = unixepoch() WHERE status IN ('queued', 'running')"
    )
    await conn.commit()

    rebuild_runtime_pipeline()
    yield
