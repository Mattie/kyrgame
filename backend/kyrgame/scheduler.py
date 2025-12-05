import asyncio
import contextlib
import heapq
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional


Callback = Callable[[], Awaitable[None] | None]


@dataclass(order=True)
class _ScheduledItem:
    run_at: float
    order: int
    callback: Callback = field(compare=False)
    interval: Optional[float] = field(default=None, compare=False)
    cancelled: bool = field(default=False, compare=False)


class ScheduledHandle:
    def __init__(self, item: _ScheduledItem, owner: "SchedulerService"):
        self._item = item
        self._owner = owner

    def cancel(self):
        self._owner.cancel(self)

    @property
    def cancelled(self) -> bool:
        return self._item.cancelled


class SchedulerService:
    """Lightweight scheduler for timed callbacks and repeating timers."""

    def __init__(self, clock: Callable[[], float] | None = None):
        self.clock = clock or time.monotonic
        self._items: List[_ScheduledItem] = []
        self._order = 0
        self._wakeup = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._stopped = False

    async def start(self):
        if self._task is not None:
            return
        self._stopped = False
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._stopped = True
        self._wakeup.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def schedule(self, delay: float, callback: Callback, interval: float | None = None) -> ScheduledHandle:
        run_at = self.clock() + delay
        self._order += 1
        item = _ScheduledItem(run_at=run_at, order=self._order, callback=callback, interval=interval)
        handle = ScheduledHandle(item, owner=self)
        heapq.heappush(self._items, item)
        self._wakeup.set()
        return handle

    def cancel(self, handle: ScheduledHandle):
        handle._item.cancelled = True
        self._wakeup.set()

    async def _run(self):
        while not self._stopped:
            await self._process_once()

    async def _process_once(self):
        if not self._items:
            self._wakeup.clear()
            await self._wakeup.wait()
        self._wakeup.clear()

        while self._items and not self._stopped:
            now = self.clock()
            next_item = self._items[0]
            if next_item.cancelled:
                heapq.heappop(self._items)
                continue
            if next_item.run_at > now:
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=next_item.run_at - now)
                except asyncio.TimeoutError:
                    self._wakeup.clear()
                else:
                    self._wakeup.clear()
                    continue
            item = heapq.heappop(self._items)
            if item.cancelled:
                continue
            result = item.callback()
            if asyncio.iscoroutine(result):
                await result
            if item.interval is not None and not item.cancelled:
                item.run_at = self.clock() + item.interval
                heapq.heappush(self._items, item)
        if not self._items:
            self._wakeup.clear()
