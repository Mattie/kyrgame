from dataclasses import dataclass

from kyrgame.timing.scheduler import TickScheduler


@dataclass
class _FakeHandle:
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True


class _FakeScheduler:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def schedule(self, delay: float, callback, interval: float | None = None):
        self.calls.append({"delay": delay, "callback": callback, "interval": interval})
        return _FakeHandle()


def test_tick_scheduler_maps_ticks_to_seconds():
    scheduler = _FakeScheduler()
    service = TickScheduler(scheduler)

    assert service.ticks_to_seconds(30) == 30.0

    half_speed = TickScheduler(scheduler, tick_seconds=0.5)
    assert half_speed.ticks_to_seconds(30) == 15.0


def test_tick_scheduler_registers_spell_and_animation_ticks():
    scheduler = _FakeScheduler()
    service = TickScheduler(scheduler)

    spell_tick = lambda: None
    animation_tick = lambda: None

    service.register_spell_tick(spell_tick)
    service.register_animation_tick(animation_tick)

    assert scheduler.calls[0]["delay"] == 30.0
    assert scheduler.calls[0]["interval"] == 30.0
    assert scheduler.calls[0]["callback"] is spell_tick
    assert scheduler.calls[1]["delay"] == 15.0
    assert scheduler.calls[1]["interval"] == 15.0
    assert scheduler.calls[1]["callback"] is animation_tick


def test_tick_scheduler_registers_custom_recurring_timer():
    scheduler = _FakeScheduler()
    service = TickScheduler(scheduler)

    effect_tick = lambda: None

    service.register_recurring_timer("mob_tick", 12, effect_tick)

    assert scheduler.calls[0]["delay"] == 12.0
    assert scheduler.calls[0]["interval"] == 12.0
    assert scheduler.calls[0]["callback"] is effect_tick
