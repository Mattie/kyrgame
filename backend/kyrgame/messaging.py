from __future__ import annotations

from typing import Any


def build_direct_and_others_events(
    *,
    player_id: str,
    event: str,
    direct_text: str | None,
    others_text: str | None,
    direct_message_id: str | None = None,
    others_message_id: str | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build a paired direct+others message payload.

    This keeps Python room routines and YAML room scripts aligned when a player
    should see one message and the room should see another excluding that player.
    """

    payload = dict(extra_payload or {})
    events: list[dict[str, Any]] = []
    if direct_text is not None:
        events.append(
            {
                "scope": "direct",
                "event": event,
                "message_id": direct_message_id,
                "text": direct_text,
                "player": player_id,
                **payload,
            }
        )
    if others_text is not None:
        events.append(
            {
                "scope": "broadcast",
                "event": event,
                "message_id": others_message_id,
                "text": others_text,
                "player": player_id,
                "exclude_player": player_id,
                **payload,
            }
        )
    return events
