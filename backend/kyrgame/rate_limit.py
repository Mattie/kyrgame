import time
from collections import deque


class RateLimiter:
    """Simple sliding window limiter for websocket commands."""

    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: deque[float] = deque()

    def allow(self, now: float | None = None) -> bool:
        now = now or time.monotonic()
        window_start = now - self.window_seconds

        while self._events and self._events[0] < window_start:
            self._events.popleft()

        if len(self._events) >= self.max_events:
            return False

        self._events.append(now)
        return True
