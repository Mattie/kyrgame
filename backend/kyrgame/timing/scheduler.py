from __future__ import annotations

from typing import Dict, Protocol

from kyrgame.scheduler import Callback, ScheduledHandle, SchedulerService


class SupportsSchedule(Protocol):
    def schedule(
        self,
        delay: float,
        callback: Callback,
        interval: float | None = None,
    ) -> ScheduledHandle: ...


def _default_tick_seconds() -> float:
    return 1.0


class TickScheduler:
    """Schedule recurring callbacks using MajorBBS-style tick units."""

    def __init__(
        self,
        scheduler: SupportsSchedule | SchedulerService,
        *,
        tick_seconds: float | None = None,
    ) -> None:
        self._scheduler = scheduler
        self._tick_seconds = tick_seconds if tick_seconds is not None else _default_tick_seconds()
        self._handles: Dict[str, ScheduledHandle] = {}

    @property
    def tick_seconds(self) -> float:
        return self._tick_seconds

    def ticks_to_seconds(self, ticks: float) -> float:
        """Convert legacy tick units into wall-clock seconds.

        MajorBBS rtkick() accepts a delay in seconds, so we map one tick unit to
        one second by default. That keeps KYRSPEL.C rtkick(30, splrtk) and
        KYRANIM.C rtkick(30/15, animat) aligned with their legacy cadence.
        """

        return ticks * self._tick_seconds

    def register_recurring(
        self,
        name: str,
        interval_ticks: float,
        callback: Callback,
    ) -> ScheduledHandle:
        interval_seconds = self.ticks_to_seconds(interval_ticks)
        handle = self._scheduler.schedule(
            interval_seconds, callback, interval=interval_seconds
        )
        self._handles[name] = handle
        return handle

    def register_spell_tick(self, callback: Callback) -> ScheduledHandle:
        """Register the spell tick handler.

        Mirrors KYRSPEL.C insrtk()/splrtk() rtkick(30, splrtk).
        Legacy reference: legacy/KYRSPEL.C lines 216-263.
        """

        return self.register_recurring("spell_tick", 30, callback)

    def register_animation_tick(self, callback: Callback) -> ScheduledHandle:
        """Register the animation tick handler.

        Mirrors KYRANIM.C inianm()/animat() rtkick(30/15, animat).
        Legacy reference: legacy/KYRANIM.C lines 89-151.
        """

        return self.register_recurring("animation_tick", 15, callback)

    def register_recurring_timer(
        self,
        name: str,
        interval_ticks: float,
        callback: Callback,
    ) -> ScheduledHandle:
        """Register a recurring timer beyond the spell/animation defaults.

        Prefer this when you want a descriptive timer name but do not want to
        add another dedicated helper (it wraps ``register_recurring``).
        """

        return self.register_recurring(name, interval_ticks, callback)

    def cancel(self, name: str) -> None:
        handle = self._handles.pop(name, None)
        if handle:
            handle.cancel()

    def cancel_all(self) -> None:
        for name in list(self._handles):
            self.cancel(name)
