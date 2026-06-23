from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SENSITIVE_PAYLOAD_KEYS = {
    "password",
    "admin_token",
    "token",
    "resume_token",
    "authorization",
}


def _safe_userid_filename(userid: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", userid.strip().lower()).strip("_")
    return normalized or "unknown"


def _redacted_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key.strip().lower() not in SENSITIVE_PAYLOAD_KEYS
    }


class TelemetryEventSink:
    def __init__(self, root: Path | None):
        self.root = root

    @classmethod
    def from_env(cls) -> "TelemetryEventSink":
        configured = os.getenv("KYRGAME_TELEMETRY_DIR")
        return cls(Path(configured) if configured else None)

    async def record(self, *, userid: str, event_type: str, payload: dict[str, Any]) -> None:
        if self.root is None:
            return

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "userid": userid,
            "event_type": event_type,
            "payload": _redacted_payload(payload),
        }
        try:
            await asyncio.to_thread(self._write_event, userid, event)
        except OSError:
            logger.warning(
                "Telemetry write failed for user %s event %s",
                userid,
                event_type,
                exc_info=True,
            )

    async def record_system(self, *, event_type: str, payload: dict[str, Any]) -> None:
        await self.record(userid="__system__", event_type=event_type, payload=payload)

    def _write_event(self, userid: str, event: dict[str, Any]) -> None:
        if self.root is None:
            return

        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{_safe_userid_filename(userid)}.jsonl"
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
