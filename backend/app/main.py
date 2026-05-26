from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.demo_topology import init_event_store, run_agent_to_tool, run_gateway_to_agent
from app.event_store import get_event_store
from app.event_store import EventStore
from app.experiments.runner import ExperimentRunner
from app.playbooks import PLAYBOOKS, list_playbooks, run_playbook
from app.replay.engine import ReplayEngine
from app.schemas import (
    AgentEvent,
    EventSeverity,
    EventStatus,
    EventType,
    ExperimentConfig,
    ExperimentRun,
    ReplaySession,
    ReplayState,
)
from app.benchmark.runner import BenchmarkRunner
from app.llm.factory import get_llm_client
from app.schemas import BenchmarkReport
from app.websocket_manager import websocket_manager

_benchmark_reports: dict[str, BenchmarkReport] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_event_store()
    yield


app = FastAPI(
    title="Multi-Agent Cascading Pollution Detection Platform",
    version="0.2.0",
    description="Research platform for simulating, observing, recording, and replaying "
    "Prompt Injection / RAG context poisoning / Tool pollution in multi-agent systems.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health & config ──────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "multi-agent-pollution-defense-platform"}


@app.get("/api/platform/config")
async def platform_config() -> dict[str, str | bool]:
    settings = get_settings()
    return {
        "llm_provider": "mimo",
        "llm_base_url": str(settings.mimo_base_url),
        "llm_model": settings.mimo_model,
        "llm_enabled": settings.llm_enabled,
        "llm_ready": settings.llm_ready,
    }


# ── Event endpoints ──────────────────────────────────────────

@app.get("/api/events/sample", response_model=AgentEvent)
async def sample_event() -> AgentEvent:
    return AgentEvent(
        event_type=EventType.COMMUNICATION,
        source_node="Gateway",
        target_node="Agent_A",
        payload_snippet="Initial benign task routed through the central gateway.",
        status=EventStatus.SAFE,
        action_taken="none",
        severity=EventSeverity.INFO,
    )


@app.post("/api/events/broadcast", response_model=AgentEvent)
async def broadcast_event(event: AgentEvent) -> AgentEvent:
    await websocket_manager.broadcast(event)
    return event


@app.get("/api/events")
async def query_events(
    trace_id: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[AgentEvent]:
    store = await get_event_store()
    return await store.query_events(
        trace_id=trace_id, severity=severity, status=status, limit=limit, offset=offset
    )


@app.get("/api/events/latest")
async def latest_events(limit: int = 100) -> list[AgentEvent]:
    store = await get_event_store()
    return await store.get_latest_events(limit=limit)


@app.get("/api/events/{event_id}", response_model=AgentEvent | None)
async def get_event(event_id: str) -> AgentEvent | None:
    store = await get_event_store()
    return await store.get_event(event_id)


# ── Trace endpoints ──────────────────────────────────────────

@app.get("/api/traces")
async def list_traces(limit: int = 50, offset: int = 0) -> list[dict]:
    store = await get_event_store()
    trace_ids = await store.get_trace_ids(limit=limit, offset=offset)
    summaries = []
    for tid in trace_ids:
        summary = await store.get_trace_summary(tid)
        if summary:
            summaries.append(summary.model_dump())
    return summaries


@app.get("/api/traces/{trace_id}")
async def get_trace(trace_id: str) -> list[AgentEvent]:
    store = await get_event_store()
    return await store.get_events_by_trace(trace_id)


@app.get("/api/traces/{trace_id}/summary")
async def get_trace_summary(trace_id: str) -> dict:
    store = await get_event_store()
    summary = await store.get_trace_summary(trace_id)
    if summary is None:
        return {"error": "trace not found", "trace_id": trace_id}
    return summary.model_dump()


@app.delete("/api/traces/{trace_id}")
async def delete_trace(trace_id: str) -> dict:
    store = await get_event_store()
    count = await store.delete_trace(trace_id)
    return {"deleted": count, "trace_id": trace_id}


# ── Demo task endpoints ──────────────────────────────────────

@app.post("/api/tasks/demo", response_model=AgentEvent | None)
async def submit_demo_task(
    payload: str = "Summarize the customer support context.",
) -> AgentEvent | None:
    return await run_gateway_to_agent(payload)


@app.post("/api/tasks/tool-demo", response_model=AgentEvent | None)
async def submit_tool_demo(
    payload: str = "Search the shared incident notes.",
) -> AgentEvent | None:
    return await run_agent_to_tool(payload)


# ── Playbook endpoints ───────────────────────────────────────

@app.get("/api/playbooks")
async def get_playbooks() -> list[dict[str, str]]:
    return list_playbooks()


@app.post("/api/playbooks/{playbook_id}/run", response_model=list[AgentEvent])
async def run_named_playbook(playbook_id: str, delay_seconds: float = 0.85) -> list[AgentEvent]:
    if playbook_id not in PLAYBOOKS:
        return []
    return await run_playbook(playbook_id, delay_seconds)


# ── Experiment endpoints ─────────────────────────────────────

@app.post("/api/experiments", response_model=ExperimentRun)
async def create_experiment(config: ExperimentConfig) -> ExperimentRun:
    store = await get_event_store()
    runner = ExperimentRunner(store)
    return await runner.run(config)


@app.get("/api/experiments")
async def list_experiments(limit: int = 50, offset: int = 0) -> list[dict]:
    store = await get_event_store()
    return await store.list_experiments(limit=limit, offset=offset)


@app.get("/api/experiments/{experiment_id}")
async def get_experiment(experiment_id: str) -> dict | None:
    store = await get_event_store()
    return await store.get_experiment(experiment_id)


@app.get("/api/experiments/{experiment_id}/trace")
async def get_experiment_trace(experiment_id: str) -> list[AgentEvent]:
    store = await get_event_store()
    exp = await store.get_experiment(experiment_id)
    if exp is None or not exp.get("trace_id"):
        return []
    return await store.get_events_by_trace(exp["trace_id"])


@app.get("/api/experiments/{experiment_id}/metrics")
async def get_experiment_metrics(experiment_id: str) -> dict:
    store = await get_event_store()
    exp = await store.get_experiment(experiment_id)
    if exp is None or not exp.get("metrics_json"):
        return {"error": "metrics not available"}
    import json
    return json.loads(exp["metrics_json"])


@app.delete("/api/experiments/{experiment_id}")
async def delete_experiment(experiment_id: str) -> dict:
    store = await get_event_store()
    count = await store.delete_experiment(experiment_id)
    return {"deleted": count, "experiment_id": experiment_id}


# ── Replay endpoints ─────────────────────────────────────────

_replay_sessions: dict[str, ReplayEngine] = {}


@app.post("/api/replay/{trace_id}/start")
async def start_replay(trace_id: str) -> dict:
    store = await get_event_store()
    events = await store.get_events_by_trace(trace_id)
    if not events:
        return {"error": "trace not found"}
    session_id = f"replay_{trace_id}"
    engine = ReplayEngine(events)
    _replay_sessions[session_id] = engine
    engine.play()
    return {
        "session_id": session_id,
        "total_events": len(events),
        "state": "playing",
    }


@app.post("/api/replay/{session_id}/pause")
async def pause_replay(session_id: str) -> dict:
    engine = _replay_sessions.get(session_id)
    if engine is None:
        return {"error": "session not found"}
    engine.pause()
    return engine.get_state().model_dump()


@app.post("/api/replay/{session_id}/resume")
async def resume_replay(session_id: str) -> dict:
    engine = _replay_sessions.get(session_id)
    if engine is None:
        return {"error": "session not found"}
    engine.play()
    return engine.get_state().model_dump()


@app.post("/api/replay/{session_id}/step")
async def step_replay(session_id: str) -> dict:
    engine = _replay_sessions.get(session_id)
    if engine is None:
        return {"error": "session not found"}
    event = engine.step_forward()
    state = engine.get_state()
    result = state.model_dump()
    result["event"] = event.model_dump() if event else None
    return result


@app.post("/api/replay/{session_id}/seek")
async def seek_replay(session_id: str, position: int = 0) -> dict:
    engine = _replay_sessions.get(session_id)
    if engine is None:
        return {"error": "session not found"}
    engine.seek(position)
    return engine.get_state().model_dump()


@app.post("/api/replay/{session_id}/speed")
async def speed_replay(session_id: str, multiplier: float = 1.0) -> dict:
    engine = _replay_sessions.get(session_id)
    if engine is None:
        return {"error": "session not found"}
    engine.set_speed(multiplier)
    return engine.get_state().model_dump()


@app.get("/api/replay/{session_id}/state")
async def get_replay_state(session_id: str) -> dict:
    engine = _replay_sessions.get(session_id)
    if engine is None:
        return {"error": "session not found"}
    return engine.get_state().model_dump()


# ── Benchmark ────────────────────────────────────────────────

@app.post("/api/benchmark/run")
async def run_benchmark() -> dict:
    runner = BenchmarkRunner(llm_client=get_llm_client(), event_store=get_event_store())
    report = await runner.run()
    _benchmark_reports[report.report_id] = report
    return report.model_dump(mode="json")


@app.get("/api/benchmark/reports")
async def list_benchmark_reports() -> list[dict]:
    return [
        {"report_id": r.report_id, "timestamp": r.timestamp,
         "total_payloads": r.total_payloads, "overall_recall": r.overall_recall,
         "overall_fpr": r.overall_fpr}
        for r in _benchmark_reports.values()
    ]


@app.get("/api/benchmark/reports/{report_id}")
async def get_benchmark_report(report_id: str) -> dict | None:
    report = _benchmark_reports.get(report_id)
    if report is None:
        return None
    return report.model_dump(mode="json")


# ── WebSocket ────────────────────────────────────────────────

@app.websocket("/ws/events")
async def events_websocket(websocket: WebSocket) -> None:
    await websocket_manager.connect(websocket)
    await websocket_manager.send_personal_message(
        websocket,
        AgentEvent(
            event_type=EventType.INPUT,
            source_node="Backend",
            target_node="Dashboard",
            payload_snippet="WebSocket stream connected.",
            status=EventStatus.SAFE,
            action_taken="none",
            severity=EventSeverity.INFO,
        ),
    )

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)
