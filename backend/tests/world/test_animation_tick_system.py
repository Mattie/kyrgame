import pytest

from kyrgame.world.animation_tick_system import (
    AnimationTickEvent,
    AnimationTickSystem,
    InMemoryAnimationTickPersistence,
)


def test_animation_tick_rotates_routines_in_legacy_order():
    seen: list[str] = []

    system = AnimationTickSystem(
        persistence=InMemoryAnimationTickPersistence(),
        routine_handlers={
            "dryads": lambda state: seen.append("dryads"),
            "elves": lambda state: seen.append("elves"),
            "gemakr": lambda state: seen.append("gemakr"),
            "zarapp": lambda state: seen.append("zarapp"),
            "browns": lambda state: seen.append("browns"),
        },
        mob_updater=lambda state: None,
    )

    for _ in range(8):
        system.tick()

    assert seen == [
        "dryads",
        "elves",
        "gemakr",
        "gemakr",
        "zarapp",
        "browns",
        "dryads",
        "elves",
    ]


def test_animation_tick_clears_global_timed_flags_after_dispatching_events():
    persistence = InMemoryAnimationTickPersistence()
    system = AnimationTickSystem(persistence=persistence)

    system.set_timed_flag("sesame")
    system.set_timed_flag("chantd")
    system.set_timed_flag("rockpr")

    result = system.tick()

    assert result.timed_events == [
        AnimationTickEvent(flag="sesame", room_id=185, message_id="WALM05"),
        AnimationTickEvent(flag="chantd", room_id=7, message_text="***\rThe altar stops glowing.\r"),
        AnimationTickEvent(flag="rockpr", room_id=27, message_text="***\rThe mists settle down.\r"),
    ]
    assert system.state.timed_flags["sesame"] == 0
    assert system.state.timed_flags["chantd"] == 0
    assert system.state.timed_flags["rockpr"] == 0


def test_animation_tick_updates_mobs_every_tick_and_persists_state():
    calls: list[int] = []
    persistence = InMemoryAnimationTickPersistence()

    def _mob_update(state):
        calls.append(state.zar_counter)
        state.zar_counter += 1

    system = AnimationTickSystem(
        persistence=persistence,
        mob_updater=_mob_update,
    )

    system.tick()
    system.tick()

    assert calls == [0, 1]

    reloaded = AnimationTickSystem(
        persistence=persistence,
        mob_updater=lambda state: None,
    )
    assert reloaded.state.zar_counter == 2
    assert reloaded.state.routine_index == 2


def test_animation_tick_uses_initial_state_from_persistence_for_multiplayer_bootstrap():
    persistence = InMemoryAnimationTickPersistence()
    persistence.save(
        {
            "routine_index": 4,
            "zar_counter": 11,
            "timed_flags": {"sesame": 1},
        }
    )

    system = AnimationTickSystem(persistence=persistence)

    assert system.state.routine_index == 4
    assert system.state.zar_counter == 11
    assert system.state.timed_flags["sesame"] == 1
