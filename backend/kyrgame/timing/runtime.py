from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from kyrgame.scheduler import Callback, ScheduledHandle

from .scheduler import TickScheduler


@dataclass
class RuntimeTickCoordinator:
    """Register and manage recurring runtime tick systems.

    Runtime parity note: KYRSPEL.C `insrtk()` schedules `splrtk()` and KYRANIM.C
    `inianm()` schedules `animat()` through `rtkick`; this coordinator keeps those
    registrations centralized for startup/shutdown handling.
    Legacy refs: legacy/KYRSPEL.C lines 216-263, legacy/KYRANIM.C lines 89-151.
    """

    tick_scheduler: TickScheduler
    spell_tick: Callback
    animation_tick: Callback
    _handles: Dict[str, ScheduledHandle] = field(default_factory=dict, init=False)

    @property
    def handles(self) -> Dict[str, ScheduledHandle]:
        return self._handles

    def start(self) -> None:
        if self._handles:
            return

        self._handles["spell_tick"] = self.tick_scheduler.register_spell_tick(
            self.spell_tick
        )
        self._handles["animation_tick"] = (
            self.tick_scheduler.register_animation_tick(self.animation_tick)
        )

    def stop(self) -> None:
        for handle in self._handles.values():
            handle.cancel()
        self._handles.clear()
