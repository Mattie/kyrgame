import asyncio
from collections import defaultdict
from typing import Dict, Set

from fastapi import WebSocket
from starlette.websockets import WebSocketState


class RoomGateway:
    """Minimal fan-out gateway for room-level WebSocket traffic."""

    def __init__(self):
        self.rooms: Dict[int, Set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def register(self, room_id: int, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.rooms[room_id].add(websocket)
        await websocket.send_json({"type": "room_welcome", "room": room_id})

    async def unregister(self, room_id: int, websocket: WebSocket):
        async with self._lock:
            if room_id in self.rooms and websocket in self.rooms[room_id]:
                self.rooms[room_id].remove(websocket)
                if not self.rooms[room_id]:
                    del self.rooms[room_id]

    async def broadcast(self, room_id: int, message: dict, sender: WebSocket | None = None):
        async with self._lock:
            recipients = list(self.rooms.get(room_id, set()))
        for connection in recipients:
            if sender is not None and connection is sender:
                continue
            if connection.application_state != WebSocketState.CONNECTED:
                continue
            await connection.send_json(message)

    async def close_all(self):
        async with self._lock:
            rooms = list(self.rooms.items())
            self.rooms.clear()
        for _, sockets in rooms:
            for socket in sockets:
                if socket.application_state == WebSocketState.CONNECTED:
                    await socket.close()
