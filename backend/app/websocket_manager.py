from fastapi import WebSocket, WebSocketDisconnect


class WebSocketManager:
    def __init__(self) -> None:
        self.rooms: dict[str, set[WebSocket]] = {}

    async def connect(
        self, websocket: WebSocket, room_id: str = "global"
    ) -> None:
        await websocket.accept()
        self.rooms.setdefault(room_id, set()).add(websocket)

    def disconnect(
        self, websocket: WebSocket, room_id: str = "global"
    ) -> None:
        room = self.rooms.get(room_id, set())
        room.discard(websocket)
        if not room:
            self.rooms.pop(room_id, None)

    async def send_personal_message(
        self,
        websocket: WebSocket,
        payload,
        room_id: str = "global",
    ) -> None:
        try:
            if hasattr(payload, "model_dump"):
                await websocket.send_json(payload.model_dump(mode="json"))
            else:
                await websocket.send_json(payload)
        except (RuntimeError, WebSocketDisconnect):
            self.disconnect(websocket, room_id)

    async def broadcast(
        self, payload, room_id: str = "global"
    ) -> None:
        stale: list[tuple[WebSocket, str]] = []
        for conn in list(self.rooms.get(room_id, set())):
            try:
                if hasattr(payload, "model_dump"):
                    await conn.send_json(payload.model_dump(mode="json"))
                else:
                    await conn.send_json(payload)
            except (RuntimeError, WebSocketDisconnect):
                stale.append((conn, room_id))
        for conn, rid in stale:
            self.disconnect(conn, rid)

    async def broadcast_to_all_rooms(self, payload) -> None:
        for room_id in list(self.rooms.keys()):
            await self.broadcast(payload, room_id)


websocket_manager = WebSocketManager()
