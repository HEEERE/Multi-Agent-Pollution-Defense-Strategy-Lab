from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    auth,
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
from app.core.auth import require_api_auth
from app.core.config import get_cors_origins
from app.core.lifespan import lifespan


def create_app() -> FastAPI:
    app = FastAPI(
        title="Multi-Agent Cascading Pollution Detection Platform",
        version="0.4.0",
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

    protected = [Depends(require_api_auth)]
    app.include_router(health.router, tags=["health"])
    app.include_router(auth.router)
    protected_routers = [
        (settings.router, "/api/v1/settings", ["settings"]),
        (events.router, "/api/v1/events", ["events"]),
        (tasks.router, "/api/v1/tasks", ["tasks"]),
        (traces.router, "/api/v1/traces", ["traces"]),
        (policies.router, "/api/v1/policies", ["policies"]),
        (playbooks.router, "/api/v1/playbooks", ["playbooks"]),
        (experiments.router, "/api/v1/experiments", ["experiments"]),
        (strategies.router, "/api/v1/strategies", ["strategies"]),
        (runs.router, "/api/v1/runs", ["runs"]),
        (replay.router, "/api/v1/replay", ["replay"]),
        (benchmark.router, "/api/v1/benchmark", ["benchmark"]),
        (honeypot.router, "/api/v1/honeypot", ["honeypot"]),
        (defense.router, "/api/v1/defense", ["defense"]),
    ]
    for router, prefix, tags in protected_routers:
        app.include_router(
            router, prefix=prefix, tags=tags, dependencies=protected
        )
    app.include_router(websocket.router)

    return app


app = create_app()
