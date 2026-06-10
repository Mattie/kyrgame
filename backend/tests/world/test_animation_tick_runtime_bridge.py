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


def test_bridge_audit_failures_do_not_block_animation_dispatch():
    room_state = {185: {"sesame": 1}, 27: {"rockpr": 0}, 7: {"chantd": 0}}
    dispatched: list[AnimationTickEvent] = []

    def _fail_audit(event_type, payload):  # noqa: ARG001
        raise OSError("audit log unavailable")

    bridge = AnimationTickRuntimeBridge(
        system=AnimationTickSystem(persistence=InMemoryAnimationTickPersistence()),
        room_flag_getter=lambda room_id, key: int(room_state.get(room_id, {}).get(key, 0)),
        room_flag_setter=lambda room_id, key, value: room_state.setdefault(room_id, {}).__setitem__(key, value),
        message_lookup=lambda key: {"WALM05": "fade"}.get(key),
        event_dispatcher=dispatched.append,
        audit_recorder=_fail_audit,
    )

    import asyncio

    asyncio.run(bridge())

    assert dispatched == [
        AnimationTickEvent(flag="sesame", room_id=185, message_id="WALM05")
    ]
    assert room_state[185]["sesame"] == 0


def test_bridge_records_brownie_audit_when_dispatch_fails_before_audit_event():
    system = AnimationTickSystem(
        persistence=InMemoryAnimationTickPersistence(),
        routine_handlers={
            "browns": lambda state: [
                AnimationTickEvent(flag="browns", room_id=71, message_id="BMSG00"),
                AnimationTickEvent(
                    flag="browns",
                    room_id=71,
                    payload={
                        "audit_only": True,
                        "audit": {
                            "branch": "gold",
                            "room_id": 71,
                            "path_index_before": 0,
                            "path_index_after": 1,
                        },
                    },
                ),
            ]
        },
    )
    system.state.routine_index = 5
    audit_records: list[tuple[str, dict]] = []

    def _fail_dispatch(event):  # noqa: ARG001
        raise RuntimeError("socket closed")

    bridge = AnimationTickRuntimeBridge(
        system=system,
        room_flag_getter=lambda room_id, key: 0,
        room_flag_setter=lambda room_id, key, value: None,
        message_lookup=lambda key: "",
        event_dispatcher=_fail_dispatch,
        audit_recorder=lambda event_type, payload: audit_records.append((event_type, dict(payload))),
    )

    import asyncio
    import pytest

    with pytest.raises(RuntimeError, match="socket closed"):
        asyncio.run(bridge())

    assert audit_records[0][0] == "animation.tick"
    assert audit_records[0][1]["dispatch_failure_count"] == 1
    assert audit_records[1] == (
        "animation.brownie_step",
        {
            "branch": "gold",
            "room_id": 71,
            "path_index_before": 0,
            "path_index_after": 1,
            "trigger_source": "scheduled",
            "dispatch_status": "failure",
            "dispatch_failure_count": 1,
        },
    )
