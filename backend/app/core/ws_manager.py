import uuid
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """In-memory per-restaurant WebSocket fan-out. Single-process only -- fine for
    Phase 2's scale; a multi-process deployment would need Redis pub/sub to fan events
    out across workers (Celery/Redis are already in the stack for that future upgrade).
    """

    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, set[WebSocket]] = {}

    async def connect(self, restaurant_id: uuid.UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(restaurant_id, set()).add(websocket)

    def disconnect(self, restaurant_id: uuid.UUID, websocket: WebSocket) -> None:
        connections = self._connections.get(restaurant_id)
        if connections:
            connections.discard(websocket)
            if not connections:
                self._connections.pop(restaurant_id, None)

    async def broadcast(self, restaurant_id: uuid.UUID, event: dict[str, Any]) -> None:
        connections = self._connections.get(restaurant_id)
        if not connections:
            return
        dead: list[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_json(event)
            except Exception:
                dead.append(connection)
        for connection in dead:
            self.disconnect(restaurant_id, connection)


manager = ConnectionManager()
