from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.demo_topology import init_event_store, rebuild_runtime_pipeline
from app.settings_manager import init_settings_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_settings_manager()
    await init_event_store()
    rebuild_runtime_pipeline()
    yield
