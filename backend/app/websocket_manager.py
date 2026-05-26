from fastapi import WebSocket

from app.schemas import AgentEvent


class WebSocketManager:
    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)

    async def send_personal_message(self, websocket: WebSocket, event: AgentEvent) -> None:
        await websocket.send_json(event.model_dump(mode="json"))

    async def broadcast(self, event: AgentEvent) -> None:
        stale_connections: list[WebSocket] = []

        for connection in self.active_connections:
            try:
                await connection.send_json(event.model_dump(mode="json"))
            except RuntimeError:
                stale_connections.append(connection)

        for connection in stale_connections:
            self.disconnect(connection)


websocket_manager = WebSocketManager()
