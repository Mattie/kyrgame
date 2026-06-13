import asyncio

import pytest

from kyrgame import fixtures
from kyrgame.rooms import RoomScriptEngine
from kyrgame.scheduler import SchedulerService


class FakeGateway:
    def __init__(self):
        self.messages = []

    async def broadcast(self, room_id: int, message: dict, sender=None):  # noqa: ARG002
        self.messages.append(message)


@pytest.fixture
async def scheduler():
    service = SchedulerService()
    await service.start()
    yield service
    await service.stop()


@pytest.fixture
async def player():
    return fixtures.build_player().model_copy(deep=True)


@pytest.fixture
async def engine(player, scheduler):
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
        players=[player],
        room_scripts=fixtures.load_room_scripts(),
        objects=fixtures.load_objects(),
        spells=fixtures.load_spells(),
    )
    return engine


@pytest.mark.anyio
async def test_walk_thicket_damages_player_and_announces_burn(engine, player, scheduler):
    handled = await engine.handle_command(player.plyrid, 19, command="walk", args=["thicket"])
    await asyncio.sleep(0.01)

    assert handled is True
    assert player.hitpts == 2

    broadcast_texts = [
        event.get("text")
        for event in engine.pending_events
        if event.get("scope") == "room"
    ]
    assert any("burning in the flaming thicket" in text for text in broadcast_texts)


@pytest.mark.anyio
async def test_walk_thicket_surfaces_pain_even_without_inventory(engine, player, scheduler):
    empty_player = player.model_copy(update={"gpobjs": [], "obvals": [], "npobjs": 0})
    engine.players[player.plyrid] = empty_player
    player = empty_player

    await engine.handle_command(player.plyrid, 19, command="walk", args=["thicket"])
    await asyncio.sleep(0.01)

    target_texts = [
        event.get("text")
        for event in engine.pending_events
        if event.get("scope") == "target"
    ]
    assert any("...Ouch" in text for text in target_texts)


@pytest.mark.anyio
async def test_walk_thicket_uses_legacy_death_reset(engine, player, scheduler):
    player = player.model_copy(update={"hitpts": 10, "gamloc": 19, "pgploc": 19})
    engine.players[player.plyrid] = player

    handled = await engine.handle_command(
        player.plyrid, 19, command="walk", args=["thicket"], player=player
    )
    await asyncio.sleep(0.01)

    assert handled is True
    assert player.level == 1
    assert player.hitpts == 4
    assert player.gamloc == 0
    assert player.pgploc == 0

    target_texts = [
        event.get("text")
        for event in engine.pending_events
        if event.get("scope") == "target"
    ]
    room_events = [
        event for event in engine.pending_events if event.get("scope") == "room"
    ]
    system_events = [
        event for event in engine.pending_events if event.get("scope") == "system"
    ]
    messages = fixtures.load_messages().messages

    assert "...Ouch!" in target_texts
    assert messages["DIEMSG"] in target_texts
    assert any(
        "burning in the flaming thicket" in event.get("text", "")
        for event in room_events
    )
    assert any(event.get("message_id") == "KILLED" for event in room_events)
    assert all(
        event.get("exclude_player") == player.plyrid
        for event in room_events
        if event.get("message_id") != "KILLED"
        or event.get("text") == messages["KILLED"] % "Hero Alt"
    )
    assert any(
        event.get("event") == "room_transfer"
        and event.get("target_room") == 0
        and event.get("death_reset") is True
        for event in system_events
    )


@pytest.mark.anyio
async def test_unrelated_commands_pass_through(engine, player, scheduler):
    handled = await engine.handle_command(player.plyrid, 19, command="look", args=["around"])
    await asyncio.sleep(0.01)

    assert handled is False
    assert player.hitpts == 12
