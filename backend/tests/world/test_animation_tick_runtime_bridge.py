from kyrgame.world.animation_tick_system import (
    AnimationTickEvent,
    AnimationTickRuntimeBridge,
    AnimationTickSystem,
    InMemoryAnimationTickPersistence,
)


def test_bridge_syncs_room_flags_dispatches_event_and_clears_room_state():
    room_state = {185: {"sesame": 1}, 27: {"rockpr": 0}, 7: {"chantd": 0}}
    dispatched: list[AnimationTickEvent] = []

    system = AnimationTickSystem(persistence=InMemoryAnimationTickPersistence())

    bridge = AnimationTickRuntimeBridge(
        system=system,
        room_flag_getter=lambda room_id, key: int(room_state.get(room_id, {}).get(key, 0)),
        room_flag_setter=lambda room_id, key, value: room_state.setdefault(room_id, {}).__setitem__(key, value),
        message_lookup=lambda key: {"WALM05": "***\rThe golden glow of the wall suddenly fades away!"}.get(key),
        event_dispatcher=dispatched.append,
    )

    import asyncio

    asyncio.run(bridge())

    assert dispatched == [
        AnimationTickEvent(flag="sesame", room_id=185, message_id="WALM05")
    ]
    assert room_state[185]["sesame"] == 0


def test_bridge_resolves_message_text_from_message_id():
    system = AnimationTickSystem(persistence=InMemoryAnimationTickPersistence())
    bridge = AnimationTickRuntimeBridge(
        system=system,
        room_flag_getter=lambda room_id, key: 0,
        room_flag_setter=lambda room_id, key, value: None,
        message_lookup=lambda key: {"WALM05": "fade"}.get(key),
        event_dispatcher=lambda event: None,
    )

    assert (
        bridge.resolve_event_text(AnimationTickEvent(flag="sesame", room_id=185, message_id="WALM05"))
        == "fade"
    )
