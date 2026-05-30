"""Event endpoints — query, sample, broadcast."""

from fastapi import APIRouter

from app.schemas import AgentEvent, EventSeverity, EventStatus, EventType
from app.services import event_service

router = APIRouter(tags=["events"])


@router.get("/sample", response_model=AgentEvent)
async def sample_event() -> AgentEvent:
    return AgentEvent(
        event_type=EventType.COMMUNICATION,
        source_node="Gateway",
        target_node="Task_Agent_A",
        payload_snippet="Initial benign task routed through the central gateway.",
        status=EventStatus.SAFE,
        action_taken="none",
        severity=EventSeverity.INFO,
    )


@router.post("/broadcast", response_model=AgentEvent)
async def broadcast_event(event: AgentEvent) -> AgentEvent:
    return await event_service.broadcast_event(event)


@router.get("")
async def query_events(
    trace_id: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[AgentEvent]:
    return await event_service.query_events(
        trace_id=trace_id, severity=severity, status=status, limit=limit, offset=offset
    )


@router.get("/latest")
async def latest_events(limit: int = 100) -> list[AgentEvent]:
    return await event_service.get_latest_events(limit=limit)


@router.get("/{event_id}", response_model=AgentEvent | None)
async def get_event(event_id: str) -> AgentEvent | None:
    return await event_service.get_event(event_id)
