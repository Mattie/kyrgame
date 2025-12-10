import asyncio

import asyncio

import httpx
import pytest

from kyrgame import fixtures
from kyrgame.rooms import RoomScriptEngine
from kyrgame.scheduler import SchedulerService
from kyrgame.webapp import DEFAULT_ADMIN_TOKEN, create_app


class FakeGateway:
    def __init__(self):
        self.messages = []

    async def broadcast(self, room_id: int, message: dict, sender=None):  # noqa: ARG002
        self.messages.append({"room": room_id, "scope": "broadcast", **message})

    async def direct(self, room_id: int, player_id: str, message: dict):
        self.messages.append({"room": room_id, "scope": "direct", "player": player_id, **message})


ADMIN_HEADERS = {"Authorization": f"Bearer {DEFAULT_ADMIN_TOKEN}"}


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

    events = [msg for msg in gateway.messages if msg["room"] == 0]
    assert any(event["event"] == "player_enter" for event in events)

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
    await engine.handle_command("hero", 0, command="look", args=["willow"])
    await engine.handle_command("hero", 0, command=messages.messages["WILCMD"], player_level=3)
    await engine.handle_command("rogue", 0, command=messages.messages["WILCMD"], player_level=1)
    await scheduler.stop()

    direct_texts = [
        msg["text"]
        for msg in gateway.messages
        if msg.get("scope") == "direct" and msg.get("player") == "hero"
    ]
    assert messages.messages["KID046"] in direct_texts
    assert messages.messages["LVL200"] in direct_texts

    broadcast_texts = [
        msg["text"]
        for msg in gateway.messages
        if msg.get("scope") == "broadcast" and "text" in msg
    ]
    assert messages.messages["GETLVL"] % "hero" in broadcast_texts

    rogue_texts = [
        msg["text"]
        for msg in gateway.messages
        if msg.get("scope") == "direct" and msg.get("player") == "rogue"
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

    player_events = [msg for msg in gateway.messages if msg["event"] == "player_enter"]
    assert any(msg["player"] == "hero" for msg in player_events)
    assert any(msg["player"] == "rogue" for msg in player_events)


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
        msg["text"]
        for msg in gateway.messages
        if msg["scope"] == "broadcast" and "text" in msg
    ]
    assert messages.messages["TMPRAY"] in prayer_prompts

    blessings = [
        msg["text"]
        for msg in gateway.messages
        if msg.get("scope") == "direct" and msg.get("player") == "acolyte"
    ]
    assert messages.messages["PRAYER"] in blessings

    assert not engine.get_room_state(7).timers


@pytest.mark.anyio
async def test_fountain_routine_tracks_donations_and_schedules_ambience():
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
    await engine.enter_room(player_id="hero", room_id=38)
    await asyncio.sleep(0.07)

    # Legacy: pinecone requires 3 donations to trigger MAGF00/MAGF01
    await engine.handle_command("hero", 38, command="toss", args=["pinecone"])
    await engine.handle_command("hero", 38, command="toss", args=["pinecone"])
    await engine.handle_command("hero", 38, command="toss", args=["pinecone"])
    
    # Legacy: shard requires 6 donations to trigger MAGF05
    for _ in range(6):
        await engine.handle_command("hero", 38, command="toss", args=["shard"])
    
    await asyncio.sleep(0.02)
    await engine.exit_room("hero", 38)
    await scheduler.stop()

    ambient_texts = [
        msg["text"]
        for msg in gateway.messages
        if msg.get("event") == "ambient" and msg.get("scope") == "broadcast"
    ]
    assert messages.messages["KRD038"] in ambient_texts

    direct_texts = [
        msg["text"]
        for msg in gateway.messages
        if msg.get("scope") == "direct" and msg.get("player") == "hero"
    ]
    # After 3 pinecones, should get success message
    assert messages.messages["MAGF00"] in direct_texts
    # After 6 shards, should get success message  
    assert messages.messages["MAGF05"] in direct_texts

    assert not engine.get_room_state(38).timers


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
    await engine.handle_command(
        "hero",
        101,
        command="offer",
        args=["heart", "and", "soul", "to", "tashanna"],
        player_level=8,
    )
    await asyncio.sleep(0.02)
    await scheduler.stop()

    direct_texts = [
        msg["text"]
        for msg in gateway.messages
        if msg.get("scope") == "direct" and msg.get("player") == "hero"
    ]
    assert messages.messages["HNSYOU"] in direct_texts

    broadcast_texts = [
        msg["text"]
        for msg in gateway.messages
        if msg.get("scope") == "broadcast" and "text" in msg
    ]
    assert messages.messages["HNSOTH"] % "hero" in broadcast_texts


@pytest.mark.anyio
async def test_admin_endpoint_reloads_room_scripts_without_restart():
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
