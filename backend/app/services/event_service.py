"""Event business logic — storage queries and broadcast."""

from app.event_store import get_event_store
from app.schemas import AgentEvent
from app.websocket_manager import websocket_manager


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


async def get_latest_events(limit: int = 100) -> list[AgentEvent]:
    store = await get_event_store()
    return await store.get_latest_events(limit=limit)


async def get_event(event_id: str) -> AgentEvent | None:
    store = await get_event_store()
    return await store.get_event(event_id)


async def broadcast_event(event: AgentEvent) -> AgentEvent:
    await websocket_manager.broadcast(event)
    return event
