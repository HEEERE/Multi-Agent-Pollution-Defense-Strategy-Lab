from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    benchmark,
    defense,
    events,
    experiments,
    health,
    honeypot,
    playbooks,
    policies,
    replay,
    runs,
    settings,
    strategies,
    tasks,
    traces,
    websocket,
)
from app.core.config import get_cors_origins
from app.core.lifespan import lifespan


def create_app() -> FastAPI:
    app = FastAPI(
        title="Multi-Agent Cascading Pollution Detection Platform",
        version="0.3.0",
        description="Research platform for simulating, observing, recording, and replaying "
        "Prompt Injection / RAG context poisoning / Tool pollution in multi-agent systems.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, tags=["health"])
    app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])
    app.include_router(events.router, prefix="/api/v1/events", tags=["events"])
    app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["tasks"])
    app.include_router(traces.router, prefix="/api/v1/traces", tags=["traces"])
    app.include_router(policies.router, prefix="/api/v1/policies", tags=["policies"])
    app.include_router(playbooks.router, prefix="/api/v1/playbooks", tags=["playbooks"])
    app.include_router(experiments.router, prefix="/api/v1/experiments", tags=["experiments"])
    app.include_router(strategies.router, prefix="/api/v1/strategies", tags=["strategies"])
    app.include_router(runs.router, prefix="/api/v1/runs", tags=["runs"])
    app.include_router(replay.router, prefix="/api/v1/replay", tags=["replay"])
    app.include_router(benchmark.router, prefix="/api/v1/benchmark", tags=["benchmark"])
    app.include_router(honeypot.router, prefix="/api/v1/honeypot", tags=["honeypot"])
    app.include_router(defense.router, prefix="/api/v1/defense", tags=["defense"])
    app.include_router(websocket.router)

    return app


app = create_app()
