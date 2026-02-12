from kyrgame.timing.runtime import RuntimeTickCoordinator


class _FakeHandle:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _FakeTickScheduler:
    def __init__(self) -> None:
        self.spell_calls = 0
        self.animation_calls = 0

    def register_spell_tick(self, callback):
        self.spell_calls += 1
        return _FakeHandle()

    def register_animation_tick(self, callback):
        self.animation_calls += 1
        return _FakeHandle()


async def _noop() -> None:
    return None


def test_runtime_tick_coordinator_registers_handlers_once_and_cancels_handles():
    scheduler = _FakeTickScheduler()
    coordinator = RuntimeTickCoordinator(
        tick_scheduler=scheduler,
        spell_tick=_noop,
        animation_tick=_noop,
    )

    coordinator.start()
    coordinator.start()

    assert scheduler.spell_calls == 1
    assert scheduler.animation_calls == 1
    assert set(coordinator.handles) == {"spell_tick", "animation_tick"}

    spell_handle = coordinator.handles["spell_tick"]
    animation_handle = coordinator.handles["animation_tick"]

    coordinator.stop()

    assert spell_handle.cancelled
    assert animation_handle.cancelled
    assert coordinator.handles == {}


def test_runtime_tick_coordinator_can_start_again_after_stop():
    scheduler = _FakeTickScheduler()
    coordinator = RuntimeTickCoordinator(
        tick_scheduler=scheduler,
        spell_tick=_noop,
        animation_tick=_noop,
    )

    coordinator.start()
    coordinator.stop()
    coordinator.start()

    assert scheduler.spell_calls == 2
    assert scheduler.animation_calls == 2
