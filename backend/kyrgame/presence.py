import asyncio
from collections import defaultdict
from typing import Dict, Set


class PresenceService:
    """Track player-to-room membership for active websocket sessions."""

    def __init__(self):
        self.player_rooms: Dict[str, int] = {}
        self.room_players: Dict[int, Set[str]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def set_location(self, player_id: str, room_id: int) -> int | None:
        """Record that a player is now in ``room_id`` and return the previous room."""

        async with self._lock:
            previous = self.player_rooms.get(player_id)
            if previous == room_id:
                return previous

            if previous is not None and previous in self.room_players:
                room_set = self.room_players[previous]
                room_set.discard(player_id)
                if not room_set:
                    del self.room_players[previous]

            self.player_rooms[player_id] = room_id
            self.room_players[room_id].add(player_id)
            return previous

    async def remove(self, player_id: str) -> int | None:
        """Remove presence tracking for ``player_id`` and return the last room."""

        async with self._lock:
            previous = self.player_rooms.pop(player_id, None)
            if previous is not None and previous in self.room_players:
                room_set = self.room_players[previous]
                room_set.discard(player_id)
                if not room_set:
                    del self.room_players[previous]
            return previous

    def room_for_player(self, player_id: str) -> int | None:
        return self.player_rooms.get(player_id)

    def players_in_room(self, room_id: int) -> Set[str]:
        return set(self.room_players.get(room_id, set()))
