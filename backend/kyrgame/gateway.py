import asyncio
from collections import defaultdict
from typing import Dict, Set

from fastapi import WebSocket
from starlette.websockets import WebSocketState


class RoomGateway:
    """Minimal fan-out gateway for room-level WebSocket traffic."""

    def __init__(self):
        self.rooms: Dict[int, Set[WebSocket]] = defaultdict(set)
        self.connections: Dict[WebSocket, int] = {}
        self._lock = asyncio.Lock()

    async def register(self, room_id: int, websocket: WebSocket, announce: bool = True):
        is_new_connection = websocket not in self.connections
        if is_new_connection and websocket.application_state != WebSocketState.CONNECTED:
            await websocket.accept()

        async with self._lock:
            previous_room = self.connections.get(websocket)
            if previous_room == room_id:
                return previous_room

            if previous_room is not None and previous_room in self.rooms:
                self.rooms[previous_room].discard(websocket)
                if not self.rooms[previous_room]:
                    del self.rooms[previous_room]

            self.connections[websocket] = room_id
            self.rooms[room_id].add(websocket)

        if announce:
            message_type = "room_welcome" if is_new_connection else "room_change"
            await websocket.send_json({"type": message_type, "room": room_id})
        return previous_room

    async def unregister(self, room_id: int, websocket: WebSocket):
        async with self._lock:
            if room_id in self.rooms and websocket in self.rooms[room_id]:
                self.rooms[room_id].remove(websocket)
                if not self.rooms[room_id]:
                    del self.rooms[room_id]
            self.connections.pop(websocket, None)

    async def broadcast(self, room_id: int, message: dict, sender: WebSocket | None = None):
        async with self._lock:
            recipients = list(self.rooms.get(room_id, set()))
        for connection in recipients:
            if sender is not None and connection is sender:
                continue
            if connection.application_state != WebSocketState.CONNECTED:
                continue
            await connection.send_json(message)

    async def direct(self, room_id: int, player_id: str, message: dict):
        await self.broadcast(room_id, {"player": player_id, **message})

    async def close_all(self):
        async with self._lock:
            rooms = list(self.rooms.items())
            self.rooms.clear()
            self.connections.clear()
        for _, sockets in rooms:
            for socket in sockets:
                if socket.application_state == WebSocketState.CONNECTED:
                    await socket.close()
