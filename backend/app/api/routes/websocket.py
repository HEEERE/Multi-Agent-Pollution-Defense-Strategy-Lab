"""WebSocket endpoint for real-time event streaming."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.schemas import AgentEvent, EventSeverity, EventStatus, EventType
from app.core.auth import websocket_is_authenticated
from app.websocket_manager import websocket_manager

router = APIRouter()


@router.websocket("/ws/events")
async def events_websocket(websocket: WebSocket) -> None:
    if not websocket_is_authenticated(websocket):
        await websocket.close(code=4401, reason="authentication required")
        return
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


@router.websocket("/ws/runs/{run_id}")
async def run_events_websocket(websocket: WebSocket, run_id: str) -> None:
    if not websocket_is_authenticated(websocket):
        await websocket.close(code=4401, reason="authentication required")
        return
    await websocket_manager.connect(websocket, room_id=run_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket, room_id=run_id)
