import asyncio

import asyncio

import httpx
import pytest

from kyrgame import constants, fixtures
from kyrgame.rooms import RoomScriptEngine
from kyrgame.scheduler import SchedulerService
from kyrgame.webapp import create_app


class FakeGateway:
    def __init__(self):
        self.messages = []

    async def broadcast(self, room_id: int, message: dict, sender=None):  # noqa: ARG002
        self.messages.append(message)


ADMIN_TOKEN = "test-admin-token"
ADMIN_HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


@pytest.mark.anyio
async def test_scheduler_triggers_one_shot_and_repeating_callbacks():
    scheduler = SchedulerService()
    await scheduler.start()

    events: list[str] = []
    scheduler.schedule(0.01, lambda: events.append("once"))
    scheduler.schedule(0.01, lambda: events.append("tick"), interval=0.02)

    await asyncio.sleep(0.07)
    await scheduler.stop()

    assert "once" in events
    assert len([event for event in events if event == "tick"]) >= 2


@pytest.mark.anyio
async def test_room_scripts_trigger_on_entry_and_cleanup_on_exit():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=fixtures.load_messages(),
    )
    await scheduler.start()

    await engine.enter_room(player_id="hero", room_id=0)
    await asyncio.sleep(0.02)

    await engine.exit_room(player_id="hero", room_id=0)
    await asyncio.sleep(0.02)
    await scheduler.stop()

    events = [msg for msg in gateway.messages if msg.get("room") == 0]
    assert any(event.get("payload", {}).get("event") == "player_enter" for event in events)

    state = engine.get_room_state(0)
    assert state.flags.get("entries") == 1
    assert not state.timers  # timers cleaned when last player exits


@pytest.mark.anyio
async def test_willow_routine_matches_legacy_prompts():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )

    await scheduler.start()
    await engine.enter_room(player_id="hero", room_id=0)
    player = fixtures.build_player().model_copy(update={"level": 1})
    await engine.handle_command("hero", 0, command="look", args=["willow"])
    await engine.handle_command("hero", 0, command=messages.messages["WILCMD"], player=player)
    await engine.handle_command("rogue", 0, command=messages.messages["WILCMD"], player_level=1)
    await scheduler.stop()

    assert player.level == 2

    direct_texts = [
        msg.get("payload", {}).get("text")
        for msg in gateway.messages
        if msg.get("payload", {}).get("scope") == "direct"
        and msg.get("payload", {}).get("player") == "hero"
    ]
    assert messages.messages["KID046"] in direct_texts
    assert messages.messages["LVL200"] in direct_texts

    broadcast_texts = [
        msg.get("payload", {})
        for msg in gateway.messages
        if msg.get("payload", {}).get("scope") == "broadcast"
        and "text" in msg.get("payload", {})
    ]
    assert any(
        payload.get("text") == messages.messages["GETLVL"] % player.altnam
        and payload.get("exclude_player") == "hero"
        for payload in broadcast_texts
    )

    rogue_texts = [
        msg.get("payload", {}).get("text")
        for msg in gateway.messages
        if msg.get("payload", {}).get("scope") == "direct"
        and msg.get("payload", {}).get("player") == "rogue"
    ]
    assert messages.messages["LVL200"] not in rogue_texts


@pytest.mark.anyio
async def test_multiple_players_receive_room_broadcasts_and_state_updates():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=fixtures.load_messages(),
    )
    await scheduler.start()

    await engine.enter_room(player_id="hero", room_id=1)
    await engine.enter_room(player_id="rogue", room_id=1)
    await asyncio.sleep(0.03)
    await scheduler.stop()

    state = engine.get_room_state(1)
    assert state.occupants == {"hero", "rogue"}
    assert state.flags.get("entries") == 2

    player_events = [
        msg for msg in gateway.messages if msg.get("payload", {}).get("event") == "player_enter"
    ]
    assert any(msg.get("payload", {}).get("player") == "hero" for msg in player_events)
    assert any(msg.get("payload", {}).get("player") == "rogue" for msg in player_events)


@pytest.mark.anyio
async def test_temple_room_schedules_prayer_prompt_and_prayer_command():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )

    await scheduler.start()
    await engine.enter_room(player_id="acolyte", room_id=7)
    await asyncio.sleep(0.06)

    await engine.handle_command("acolyte", 7, command="pray", player_level=5)
    await asyncio.sleep(0.02)
    await engine.exit_room("acolyte", 7)
    await scheduler.stop()

    prayer_prompts = [
        msg.get("payload", {}).get("text")
        for msg in gateway.messages
        if msg.get("payload", {}).get("scope") == "broadcast"
        and "text" in msg.get("payload", {})
    ]
    assert messages.messages["TMPRAY"] in prayer_prompts

    blessings = [
        msg.get("payload", {}).get("text")
        for msg in gateway.messages
        if msg.get("payload", {}).get("scope") == "direct"
        and msg.get("payload", {}).get("player") == "acolyte"
    ]
    assert messages.messages["TMPRAY"] in blessings
    assert any(
        msg.get("payload", {}).get("text")
        == "*** acolyte is praying to the Goddess Tashanna."
        and msg.get("payload", {}).get("exclude_player") == "acolyte"
        for msg in gateway.messages
    )

    assert not engine.get_room_state(7).timers


@pytest.mark.anyio
async def test_temple_marry_sets_spouse_and_uses_legacy_fanout():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    actor = fixtures.build_player().model_copy(
        update={
            "plyrid": "zthero",
            "altnam": "ZtHero",
            "attnam": "ZtHero",
            "gamloc": 7,
            "flags": int(constants.PlayerFlag.LOADED),
            "spouse": "",
        },
        deep=True,
    )
    target = fixtures.build_player().model_copy(
        update={
            "plyrid": "ztbeloved",
            "altnam": "ZtBeloved",
            "attnam": "ZtBeloved",
            "gamloc": 7,
            "flags": int(constants.PlayerFlag.LOADED | constants.PlayerFlag.FEMALE),
        },
        deep=True,
    )
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
        players=[actor, target],
    )

    handled = await engine.handle_command(
        "zthero", 7, command="marry", args=["ztbel"], player=actor
    )

    assert handled is True
    assert actor.flags & constants.PlayerFlag.MARRYD
    assert actor.spouse == "ztbeloved"
    payloads = [msg.get("payload", {}) for msg in gateway.messages]
    assert any(
        payload.get("scope") == "direct"
        and payload.get("player") == "zthero"
        and payload.get("message_id") == "MARRY4"
        and payload.get("text") == messages.messages["MARRY4"] % "ztbeloved"
        for payload in payloads
    )
    assert any(
        payload.get("scope") == "direct"
        and payload.get("player") == "ztbeloved"
        and payload.get("message_id") == "MARRY5"
        and payload.get("text") == messages.messages["MARRY5"] % ("ZtHero", "his")
        for payload in payloads
    )
    assert any(
        payload.get("scope") == "broadcast"
        and payload.get("message_id") == "MARRY6"
        and payload.get("exclude_players") == ["zthero", "ztbeloved"]
        and payload.get("text") == messages.messages["MARRY6"] % ("ZtHero", "his", "ZtBeloved")
        for payload in payloads
    )


@pytest.mark.anyio
async def test_temple_wed_rejects_existing_spouse_with_legacy_messages():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    actor = fixtures.build_player().model_copy(
        update={
            "plyrid": "zthero",
            "altnam": "ZtHero",
            "attnam": "ZtHero",
            "gamloc": 7,
            "flags": int(constants.PlayerFlag.LOADED | constants.PlayerFlag.MARRYD),
            "spouse": "ztjuliet",
        },
        deep=True,
    )
    target = fixtures.build_player().model_copy(
        update={
            "plyrid": "ztbeloved",
            "altnam": "ZtBeloved",
            "attnam": "ZtBeloved",
            "gamloc": 7,
            "flags": int(constants.PlayerFlag.LOADED),
        },
        deep=True,
    )
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
        players=[actor, target],
    )

    handled = await engine.handle_command(
        "zthero", 7, command="wed", args=["ztbeloved"], player=actor
    )

    assert handled is True
    assert actor.spouse == "ztjuliet"
    payloads = [msg.get("payload", {}) for msg in gateway.messages]
    assert any(
        payload.get("scope") == "direct"
        and payload.get("message_id") == "MARRY0"
        and payload.get("text") == messages.messages["MARRY0"] % "ztjuliet"
        for payload in payloads
    )
    assert any(
        payload.get("scope") == "broadcast"
        and payload.get("message_id") == "MARRY1"
        and payload.get("exclude_player") == "zthero"
        and payload.get("text") == messages.messages["MARRY1"] % "ZtHero"
        for payload in payloads
    )


@pytest.mark.anyio
async def test_temple_marry_self_and_missing_target_use_legacy_messages():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    actor = fixtures.build_player().model_copy(
        update={
            "plyrid": "zthero",
            "altnam": "ZtHero",
            "attnam": "ZtHero",
            "gamloc": 7,
            "flags": int(constants.PlayerFlag.LOADED),
            "spouse": "",
        },
        deep=True,
    )
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
        players=[actor],
    )

    self_handled = await engine.handle_command(
        "zthero", 7, command="marry", args=["zthero"], player=actor
    )
    missing_handled = await engine.handle_command(
        "zthero", 7, command="marry", args=["ztnobody"], player=actor
    )

    assert self_handled is True
    assert missing_handled is True
    assert not actor.flags & constants.PlayerFlag.MARRYD
    assert actor.spouse == ""
    payloads = [msg.get("payload", {}) for msg in gateway.messages]
    assert any(payload.get("message_id") == "MARRY2" for payload in payloads)
    assert any(payload.get("message_id") == "MARRY3" for payload in payloads)
    assert any(payload.get("message_id") == "MARRY7" for payload in payloads)
    assert any(payload.get("message_id") == "MARRY8" for payload in payloads)


@pytest.mark.anyio
async def test_temple_marry_honors_invisible_target_visibility_gate():
    scheduler = SchedulerService()
    messages = fixtures.load_messages()
    actor = fixtures.build_player().model_copy(
        update={
            "plyrid": "zthero",
            "altnam": "ZtHero",
            "attnam": "ZtHero",
            "gamloc": 7,
            "flags": int(constants.PlayerFlag.LOADED),
            "spouse": "",
        },
        deep=True,
    )
    target = fixtures.build_player().model_copy(
        update={
            "plyrid": "ztbeloved",
            "altnam": "ZtBeloved",
            "attnam": "ZtBeloved",
            "gamloc": 7,
            "flags": int(constants.PlayerFlag.LOADED | constants.PlayerFlag.INVISF),
        },
        deep=True,
    )
    gateway = FakeGateway()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
        players=[actor, target],
    )

    blocked = await engine.handle_command(
        "zthero", 7, command="marry", args=["ztbeloved"], player=actor
    )

    assert blocked is True
    assert not actor.flags & constants.PlayerFlag.MARRYD
    assert actor.spouse == ""
    assert any(
        msg.get("payload", {}).get("message_id") == "MARRY7" for msg in gateway.messages
    )

    actor.charms[constants.CharmSlot.INVISIBILITY] = 1
    gateway = FakeGateway()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
        players=[actor, target],
    )

    allowed = await engine.handle_command(
        "zthero", 7, command="marry", args=["ztbeloved"], player=actor
    )

    assert allowed is True
    assert actor.flags & constants.PlayerFlag.MARRYD
    assert actor.spouse == "ztbeloved"
    assert any(
        msg.get("payload", {}).get("message_id") == "MARRY4" for msg in gateway.messages
    )


@pytest.mark.anyio
async def test_temple_put_requires_exact_five_chants():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )
    player = fixtures.build_player().model_copy(
        update={"level": 8, "gpobjs": [18], "obvals": [0], "npobjs": 1}, deep=True
    )
    engine.get_room_state(7).flags["chantd"] = 6

    handled = await engine.handle_command(
        "hero", 7, command="put", args=["charm"], player=player
    )

    assert handled is False
    assert 18 in player.gpobjs


@pytest.mark.anyio
async def test_temple_chant_tashanna_broadcasts_room_message_text_and_counts():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )
    player = fixtures.build_player()

    for _ in range(5):
        handled = await engine.handle_command(
            "hero", 7, command="chant", args=["tashanna"], player=player
        )
        assert handled is True

    assert engine.get_room_state(7).flags["chantd"] == 5
    altar_payloads = [
        msg.get("payload", {})
        for msg in gateway.messages
        if msg.get("payload", {}).get("text", "").startswith("*** The altar")
    ]
    assert altar_payloads[0] == {
        "event": "room_message",
        "scope": "broadcast",
        "type": "room_message",
        "text": "*** The altar begins to glow dimly.",
    }
    assert [payload["text"] for payload in altar_payloads[1:]] == [
        "*** The altar glows even brighter!",
        "*** The altar glows even brighter!",
        "*** The altar glows even brighter!",
        "*** The altar glows even brighter!",
    ]


@pytest.mark.anyio
async def test_temple_five_chants_then_charm_levels_eligible_player():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )
    player = fixtures.build_player().model_copy(
        update={"level": 8, "gpobjs": [18], "obvals": [0], "npobjs": 1}, deep=True
    )

    for _ in range(5):
        await engine.handle_command("hero", 7, command="chant", args=["tashanna"], player=player)

    handled = await engine.handle_command(
        "hero", 7, command="put", args=["charm"], player=player
    )

    assert handled is True
    assert player.level == 9
    assert 18 not in player.gpobjs
    assert any(
        msg.get("payload", {}).get("scope") == "direct"
        and msg.get("payload", {}).get("message_id") == "LVL9M0"
        for msg in gateway.messages
    )


@pytest.mark.anyio
async def test_temple_six_chants_rejects_until_reset_allows_fresh_five_chants():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )
    player = fixtures.build_player().model_copy(
        update={"level": 8, "gpobjs": [18], "obvals": [0], "npobjs": 1}, deep=True
    )

    for _ in range(6):
        await engine.handle_command("hero", 7, command="chant", args=["tashanna"], player=player)

    handled = await engine.handle_command(
        "hero", 7, command="put", args=["charm"], player=player
    )

    assert handled is False
    assert player.level == 8
    assert 18 in player.gpobjs

    engine.get_room_state(7).flags["chantd"] = 0
    for _ in range(5):
        await engine.handle_command("hero", 7, command="chant", args=["tashanna"], player=player)

    handled = await engine.handle_command(
        "hero", 7, command="put", args=["charm"], player=player
    )

    assert handled is True
    assert player.level == 9
    assert 18 not in player.gpobjs


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("command", "args"),
    [
        ("say", ["glory", "be", "to", "tashanna"]),
        ("comment", ["glory", "be", "to", "tashanna"]),
        ("note", ["glory", "be", "to", "tashanna"]),
        ("chant", ["glory", "be", "to", "tashanna"]),
        ("put", ["glory", "be", "to", "tashanna"]),
        ("nonesuch", ["glory", "be", "to", "tashanna"]),
        ("say", ["the", "glory", "be", "to", "tashanna"]),
    ],
)
async def test_temple_phrase_commands_raise_level_three(command, args):
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )
    player = fixtures.build_player().model_copy(update={"level": 2}, deep=True)

    handled = await engine.handle_command(
        "hero",
        7,
        command=command,
        args=args,
        player_level=player.level,
        player=player,
    )

    assert handled is True
    assert player.level == 3
    direct_texts = [
        msg.get("payload", {}).get("text")
        for msg in gateway.messages
        if msg.get("payload", {}).get("scope") == "direct"
        and msg.get("payload", {}).get("player") == "hero"
    ]
    assert messages.messages["LVL300"] in direct_texts
    assert any(
        msg.get("payload", {}).get("text") == messages.messages["GETLVL"] % player.altnam
        and msg.get("payload", {}).get("exclude_player") == "hero"
        for msg in gateway.messages
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "args",
    [
        ["glory", "be", "tashanna"],
        ["glory", "be", "to", "tashanna", "please"],
    ],
)
async def test_temple_rejects_wrong_temple_phrase_remainders(args):
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )
    player = fixtures.build_player().model_copy(update={"level": 2}, deep=True)

    handled = await engine.handle_command(
        "hero",
        7,
        command="say",
        args=args,
        player_level=player.level,
        player=player,
    )

    assert handled is False
    assert player.level == 2
    direct_texts = [
        msg.get("payload", {}).get("text")
        for msg in gateway.messages
        if msg.get("payload", {}).get("scope") == "direct"
    ]
    assert messages.messages["LVL300"] not in direct_texts


@pytest.mark.anyio
async def test_temple_put_consumes_default_offering_after_fifth_chant():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )
    player = fixtures.build_player().model_copy(
        update={"gpobjs": [0], "obvals": [0], "npobjs": 1}, deep=True
    )
    engine.get_room_state(7).flags["chantd"] = 5

    handled = await engine.handle_command(
        "hero", 7, command="put", args=["ruby"], player=player
    )

    assert handled is True
    assert 0 not in player.gpobjs

    direct_texts = [
        msg.get("payload", {}).get("text")
        for msg in gateway.messages
        if msg.get("payload", {}).get("scope") == "direct"
        and msg.get("payload", {}).get("player") == "hero"
    ]
    assert messages.messages["OFFER0"] in direct_texts


@pytest.mark.anyio
async def test_temple_put_consumes_level_item_before_failed_gate_for_legacy_parity():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )
    player = fixtures.build_player().model_copy(
        update={"level": 7, "gpobjs": [18], "obvals": [0], "npobjs": 1}, deep=True
    )
    engine.get_room_state(7).flags["chantd"] = 5

    handled = await engine.handle_command(
        "hero", 7, command="put", args=["charm"], player=player
    )

    assert handled is True
    assert player.level == 7
    assert 18 not in player.gpobjs

    direct_texts = [
        msg.get("payload", {}).get("text")
        for msg in gateway.messages
        if msg.get("payload", {}).get("scope") == "direct"
        and msg.get("payload", {}).get("player") == "hero"
    ]
    assert messages.messages["LVLM02"] in direct_texts


@pytest.mark.anyio
async def test_willow_kneel_above_gate_reports_too_high():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )
    player = fixtures.build_player().model_copy(update={"level": 2}, deep=True)

    handled = await engine.handle_command("hero", 0, command="kneel", player=player)

    assert handled is True
    assert player.level == 2

    direct_texts = [
        msg.get("payload", {}).get("text")
        for msg in gateway.messages
        if msg.get("payload", {}).get("scope") == "direct"
        and msg.get("payload", {}).get("player") == "hero"
    ]
    assert messages.messages["LVLM00"] in direct_texts
    assert messages.messages["LVL200"] not in direct_texts

    broadcast_texts = [
        msg.get("payload", {}).get("text")
        for msg in gateway.messages
        if msg.get("payload", {}).get("scope") == "broadcast"
        and "text" in msg.get("payload", {})
    ]
    assert messages.messages["LVLM01"] % player.altnam in broadcast_texts


@pytest.mark.anyio
async def test_fountain_routine_schedules_and_cleans_ambience():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
        objects=fixtures.load_objects(),
    )

    await scheduler.start()
    try:
        await engine.enter_room(player_id="hero", room_id=38)
        await asyncio.sleep(0.07)
        await engine.exit_room("hero", 38)
        await asyncio.sleep(0.02)
    finally:
        await scheduler.stop()

    room_message_texts = [
        msg.get("payload", {}).get("text")
        for msg in gateway.messages
        if msg.get("payload", {}).get("event") == "room_message"
        and msg.get("payload", {}).get("type") == "room_message"
        and msg.get("payload", {}).get("scope") == "broadcast"
    ]
    assert messages.messages["KRD038"] in room_message_texts
    assert not engine.get_room_state(38).timers


@pytest.mark.anyio
async def test_fountain_blessed_pinecone_cycle_consumes_inventory_and_spawns_scroll():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    room_objects = {44: []}
    picker_calls: list[tuple[int, int]] = []

    def pick_scroll_room(low: int, high: int) -> int:
        picker_calls.append((low, high))
        return 44

    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
        objects=fixtures.load_objects(),
        room_picker=pick_scroll_room,
        room_objects_getter=lambda room_id: list(room_objects.get(room_id, [])),
        room_objects_setter=lambda room_id, objects: room_objects.__setitem__(
            room_id, list(objects)
        ),
    )
    player = fixtures.build_player().model_copy(
        update={
            "gpobjs": [32, 32, 32],
            "obvals": [0, 0, 0],
            "npobjs": 3,
            "flags": int(constants.PlayerFlag.BLESSD),
        },
        deep=True,
    )

    for verb in ("drop", "throw", "toss"):
        handled = await engine.handle_command(
            "hero",
            38,
            command=verb,
            args=["pinecone", "in", "fountain"],
            player=player,
        )
        assert handled is True

    payloads = [msg.get("payload", {}) for msg in gateway.messages]
    direct_texts = [
        payload.get("text")
        for payload in payloads
        if payload.get("scope") == "direct" and payload.get("player") == "hero"
    ]
    assert messages.messages["MAGF00"] in direct_texts
    assert player.gpobjs == []
    assert player.obvals == []
    assert player.npobjs == 0
    assert engine.get_room_state(38).flags.get("scroll_count") == 0
    assert picker_calls == [(0, 168)]
    assert room_objects[44] == [35]
    assert any(
        msg.get("room") == 44
        and msg.get("payload", {}).get("event") == "room_objects"
        and msg.get("payload", {}).get("objects") == [{"id": 35, "name": "scroll"}]
        for msg in gateway.messages
    )


@pytest.mark.anyio
async def test_fountain_blessed_pinecone_scroll_respects_full_room_capacity():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    full_room = list(range(constants.MXLOBS))
    room_objects = {44: full_room.copy()}
    picker_calls: list[tuple[int, int]] = []

    def pick_scroll_room(low: int, high: int) -> int:
        picker_calls.append((low, high))
        return 44

    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
        objects=fixtures.load_objects(),
        room_picker=pick_scroll_room,
        room_objects_getter=lambda room_id: list(room_objects.get(room_id, [])),
        room_objects_setter=lambda room_id, objects: room_objects.__setitem__(
            room_id, list(objects)
        ),
    )
    player = fixtures.build_player().model_copy(
        update={
            "gpobjs": [32, 32, 32],
            "obvals": [0, 0, 0],
            "npobjs": 3,
            "flags": int(constants.PlayerFlag.BLESSD),
        },
        deep=True,
    )

    for _ in range(3):
        handled = await engine.handle_command(
            "hero",
            38,
            command="drop",
            args=["pinecone", "in", "fountain"],
            player=player,
        )
        assert handled is True

    payloads = [msg.get("payload", {}) for msg in gateway.messages]
    assert any(
        payload.get("scope") == "direct"
        and payload.get("player") == "hero"
        and payload.get("message_id") == "MAGF00"
        for payload in payloads
    )
    assert player.gpobjs == []
    assert player.obvals == []
    assert player.npobjs == 0
    assert picker_calls == [(0, 168)]
    assert room_objects[44] == full_room
    assert not any(
        msg.get("room") == 44
        and msg.get("payload", {}).get("event") == "room_objects"
        for msg in gateway.messages
    )


@pytest.mark.anyio
async def test_fountain_shard_cycle_consumes_shards_and_grants_object():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
        objects=fixtures.load_objects(),
    )
    player = fixtures.build_player().model_copy(
        update={
            "gpobjs": [43, 43, 43, 43, 43, 43],
            "obvals": [0, 0, 0, 0, 0, 0],
            "npobjs": 6,
        },
        deep=True,
    )

    for _ in range(6):
        handled = await engine.handle_command(
            "hero",
            38,
            command="toss",
            args=["shard", "in", "fountain"],
            player=player,
        )
        assert handled is True

    payloads = [msg.get("payload", {}) for msg in gateway.messages]
    assert player.gpobjs == [16]
    assert player.obvals == [0]
    assert player.npobjs == 1
    assert engine.get_room_state(38).flags.get("shard_count") == 0
    assert any(
        payload.get("scope") == "direct"
        and payload.get("player") == "hero"
        and payload.get("message_id") == "MAGF05"
        for payload in payloads
    )
    assert any(
        payload.get("scope") == "broadcast"
        and payload.get("message_id") == "MAGF03"
        and payload.get("exclude_player") == "hero"
        for payload in payloads
    )


@pytest.mark.anyio
async def test_fountain_default_gift_consumes_inventory_and_uses_generic_messages():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
        objects=fixtures.load_objects(),
    )
    player = fixtures.build_player().model_copy(
        update={"gpobjs": [0], "obvals": [10], "npobjs": 1},
        deep=True,
    )

    handled = await engine.handle_command(
        "hero",
        38,
        command="toss",
        args=["ruby", "in", "fountain"],
        player=player,
    )

    payloads = [msg.get("payload", {}) for msg in gateway.messages]
    assert handled is True
    assert player.gpobjs == []
    assert player.obvals == []
    assert player.npobjs == 0
    assert any(
        payload.get("scope") == "direct"
        and payload.get("player") == "hero"
        and payload.get("message_id") == "MAGF02"
        for payload in payloads
    )
    assert any(
        payload.get("scope") == "broadcast"
        and payload.get("message_id") == "MAGF03"
        and payload.get("exclude_player") == "hero"
        for payload in payloads
    )


@pytest.mark.anyio
async def test_fountain_offerings_accept_legacy_inventory_prefixes():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
        objects=fixtures.load_objects(),
    )
    player = fixtures.build_player().model_copy(
        update={
            "gpobjs": [32, 43],
            "obvals": [0, 0],
            "npobjs": 2,
            "flags": int(constants.PlayerFlag.BLESSD),
        },
        deep=True,
    )

    pinecone_handled = await engine.handle_command(
        "hero",
        38,
        command="toss",
        args=["pine", "in", "fountain"],
        player=player,
    )
    shard_handled = await engine.handle_command(
        "hero",
        38,
        command="toss",
        args=["shar", "in", "fountain"],
        player=player,
    )

    payloads = [msg.get("payload", {}) for msg in gateway.messages]
    assert pinecone_handled is True
    assert shard_handled is True
    assert player.gpobjs == []
    assert player.obvals == []
    assert player.npobjs == 0
    assert any(
        payload.get("scope") == "direct"
        and payload.get("player") == "hero"
        and payload.get("message_id") == "MAGF04"
        for payload in payloads
    )
    assert any(
        payload.get("scope") == "direct"
        and payload.get("player") == "hero"
        and payload.get("message_id") == "MAGF06"
        for payload in payloads
    )


@pytest.mark.anyio
async def test_fountain_requires_inventory_and_in_fountain_target():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    room_objects = {44: []}
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
        objects=fixtures.load_objects(),
        room_picker=lambda low, high: 44,
        room_objects_getter=lambda room_id: list(room_objects.get(room_id, [])),
        room_objects_setter=lambda room_id, objects: room_objects.__setitem__(
            room_id, list(objects)
        ),
    )
    player = fixtures.build_player().model_copy(
        update={
            "gpobjs": [32],
            "obvals": [0],
            "npobjs": 1,
            "flags": int(constants.PlayerFlag.BLESSD),
        },
        deep=True,
    )

    assert (
        await engine.handle_command(
            "hero", 38, command="toss", args=["pinecone"], player=player
        )
        is False
    )
    assert player.gpobjs == [32]

    for bad_args in (
        ["pinecone", "near", "fountain"],
        ["pinecone", "in", "pond"],
        ["pinecone", "in", "fountain", "now"],
    ):
        assert (
            await engine.handle_command(
                "hero", 38, command="drop", args=bad_args, player=player
            )
            is False
        )
        assert player.gpobjs == [32]
        assert player.obvals == [0]
        assert player.npobjs == 1

    player = player.model_copy(update={"gpobjs": [], "obvals": [], "npobjs": 0})
    assert (
        await engine.handle_command(
            "hero",
            38,
            command="drop",
            args=["pinecone", "in", "fountain"],
            player=player,
        )
        is False
    )
    assert room_objects[44] == []
    assert not any(
        msg.get("payload", {}).get("event") == "room_objects"
        for msg in gateway.messages
    )


@pytest.mark.anyio
async def test_fountain_blessing_phrase_sets_blessd_flag():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )
    player = fixtures.build_player().model_copy(update={"flags": 0}, deep=True)

    handled = await engine.handle_command(
        "hero",
        38,
        command="offer",
        args=["true", "love", "to", "tashanna"],
        player=player,
    )

    assert handled is True
    assert player.flags & constants.PlayerFlag.BLESSD
    assert any(
        payload.get("scope") == "direct"
        and payload.get("player") == "hero"
        and "The Goddess blesses you." in payload.get("text", "")
        for payload in (msg.get("payload", {}) for msg in gateway.messages)
    )


@pytest.mark.anyio
async def test_temple_default_offering_uses_actor_excluding_room_message():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )
    player = fixtures.build_player().model_copy(
        update={"gpobjs": [0], "obvals": [0], "npobjs": 1}, deep=True
    )
    engine.get_room_state(7).flags["chantd"] = 5

    handled = await engine.handle_command(
        "hero", 7, command="put", args=["ruby"], player=player
    )

    assert handled is True
    payloads = [msg.get("payload", {}) for msg in gateway.messages]
    assert any(
        payload.get("scope") == "direct"
        and payload.get("player") == "hero"
        and payload.get("message_id") == "OFFER0"
        for payload in payloads
    )
    assert any(
        payload.get("scope") == "broadcast"
        and payload.get("message_id") == "OFFER1"
        and payload.get("exclude_player") == "hero"
        for payload in payloads
    )


@pytest.mark.anyio
async def test_temple_prayer_uses_sndutl_actor_excluding_room_message():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )
    player = fixtures.build_player()

    handled = await engine.handle_command("hero", 7, command="pray", player=player)

    assert handled is True
    payloads = [msg.get("payload", {}) for msg in gateway.messages]
    assert any(
        payload.get("scope") == "direct"
        and payload.get("player") == "hero"
        and payload.get("message_id") == "TMPRAY"
        for payload in payloads
    )
    assert any(
        payload.get("scope") == "broadcast"
        and payload.get("text")
        == f"*** {player.altnam} is praying to the Goddess Tashanna."
        and payload.get("exclude_player") == "hero"
        for payload in payloads
    )


@pytest.mark.anyio
async def test_spring_rose_pickup_uses_actor_excluding_room_message():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )
    player = fixtures.build_player()

    handled = await engine.handle_command(
        "hero", 32, command="get", args=["rose"], player=player
    )

    assert handled is True
    payloads = [msg.get("payload", {}) for msg in gateway.messages]
    assert any(
        payload.get("scope") == "broadcast"
        and payload.get("message_id") == "GROSE2"
        and payload.get("exclude_player") == "hero"
        for payload in payloads
    )


@pytest.mark.anyio
async def test_fountain_donation_messages_exclude_actor_from_room_text():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )
    player = fixtures.build_player().model_copy(
        update={"gpobjs": [32], "obvals": [0], "npobjs": 1, "flags": 0},
        deep=True,
    )

    handled = await engine.handle_command(
        "hero",
        38,
        command="toss",
        args=["pinecone", "in", "fountain"],
        player=player,
    )

    assert handled is True
    assert player.gpobjs == []
    assert engine.get_room_state(38).flags.get("scroll_count", 0) == 0
    payloads = [msg.get("payload", {}) for msg in gateway.messages]
    assert any(
        payload.get("scope") == "broadcast"
        and payload.get("message_id") == "MAGF07"
        and payload.get("exclude_player") == "hero"
        for payload in payloads
    )


@pytest.mark.anyio
async def test_heart_and_soul_offering_awards_willowisp_spell():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )

    await scheduler.start()
    await engine.enter_room(player_id="hero", room_id=101)
    player = fixtures.build_player().model_copy(update={"level": 6})
    await engine.handle_command(
        "hero",
        101,
        command="offer",
        args=["heart", "and", "soul", "to", "tashanna"],
        player=player,
    )
    await asyncio.sleep(0.02)
    await scheduler.stop()

    assert player.level == 7
    assert player.othspls & constants.SBD062_WILLOWISP

    direct_texts = [
        msg.get("payload", {}).get("text")
        for msg in gateway.messages
        if msg.get("payload", {}).get("scope") == "direct"
        and msg.get("payload", {}).get("player") == "hero"
    ]
    assert messages.messages["HNSYOU"] in direct_texts

    broadcast_texts = [
        msg.get("payload", {}).get("text")
        for msg in gateway.messages
        if msg.get("payload", {}).get("scope") == "broadcast"
        and "text" in msg.get("payload", {})
    ]
    assert messages.messages["HNSOTH"] % player.altnam in broadcast_texts


@pytest.mark.anyio
async def test_heart_and_soul_above_gate_reports_too_high():
    scheduler = SchedulerService()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
    )
    player = fixtures.build_player().model_copy(update={"level": 7}, deep=True)

    handled = await engine.handle_command(
        "hero",
        101,
        command="offer",
        args=["heart", "and", "soul", "to", "tashanna"],
        player=player,
    )

    assert handled is True
    assert player.level == 7

    direct_texts = [
        msg.get("payload", {}).get("text")
        for msg in gateway.messages
        if msg.get("payload", {}).get("scope") == "direct"
        and msg.get("payload", {}).get("player") == "hero"
    ]
    assert messages.messages["LVLM00"] in direct_texts
    assert messages.messages["HNSYOU"] not in direct_texts


@pytest.mark.anyio
async def test_admin_endpoint_reloads_room_scripts_without_restart(monkeypatch):
    monkeypatch.setenv("KYRGAME_ADMIN_TOKEN", ADMIN_TOKEN)
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/admin/reload-scripts", headers=ADMIN_HEADERS)
            second = await client.post("/admin/reload-scripts", headers=ADMIN_HEADERS)

            assert first.status_code == 200
            assert second.status_code == 200

            first_count = first.json()["reloads"]
            second_count = second.json()["reloads"]

            assert second_count == first_count + 1
