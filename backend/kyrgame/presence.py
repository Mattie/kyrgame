import asyncio
from collections import defaultdict
from typing import Dict, Set


class PresenceService:
    """Track player-to-room membership for active websocket sessions."""

    def __init__(self):
        self.session_rooms: Dict[str, int] = {}
        self.session_players: Dict[str, str] = {}
        self.room_sessions: Dict[int, Set[str]] = defaultdict(set)
        self.player_sessions: Dict[str, Set[str]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def set_location(
        self, player_id: str, room_id: int, session_token: str | None = None
    ) -> int | None:
        """Record that a player is now in ``room_id`` and return the previous room."""

        token = session_token or player_id
        async with self._lock:
            previous = self.session_rooms.get(token)
            if previous == room_id:
                return previous

            if previous is not None and previous in self.room_sessions:
                room_set = self.room_sessions[previous]
                room_set.discard(token)
                if not room_set:
                    del self.room_sessions[previous]

            self.session_rooms[token] = room_id
            self.session_players[token] = player_id
            self.room_sessions[room_id].add(token)
            self.player_sessions[player_id].add(token)
            return previous

    async def remove(self, session_token: str) -> int | None:
        """Remove presence tracking for ``session_token`` and return the last room."""

        async with self._lock:
            previous = self.session_rooms.pop(session_token, None)
            player_id = self.session_players.pop(session_token, None)
            if previous is not None and previous in self.room_sessions:
                room_set = self.room_sessions[previous]
                room_set.discard(session_token)
                if not room_set:
                    del self.room_sessions[previous]
            if player_id is not None and player_id in self.player_sessions:
                token_set = self.player_sessions[player_id]
                token_set.discard(session_token)
                if not token_set:
                    del self.player_sessions[player_id]
            return previous

    def room_for_player(self, player_id: str) -> int | None:
        tokens = self.player_sessions.get(player_id)
        if not tokens:
            return None
        token = next(iter(tokens))
        return self.session_rooms.get(token)

    def players_in_room(self, room_id: int) -> Set[str]:
        return {
            self.session_players[token] for token in self.room_sessions.get(room_id, set())
        }
