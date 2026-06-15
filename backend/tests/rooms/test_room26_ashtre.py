import pytest

from kyrgame import constants, fixtures
from kyrgame.rooms import RoomScriptEngine
from kyrgame.scheduler import SchedulerService


class FakeGateway:
    def __init__(self):
        self.messages: list[dict] = []

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


def _direct_texts(engine: RoomScriptEngine, player_id: str) -> list[str]:
    # Check pending events from the engine (scope "target" for player-directed messages)
    return [
        event.get("text")
        for event in engine.pending_events
        if event.get("scope") == "target"
        and event.get("player") == player_id
    ]


def _broadcast_texts(engine: RoomScriptEngine) -> list[str]:
    # Check pending events from the engine (scope "room" for broadcasts)
    return [
        event.get("text")
        for event in engine.pending_events
        if event.get("scope") == "room"
    ]


def _broadcast_payloads(engine: RoomScriptEngine) -> list[dict]:
    return [event for event in engine.pending_events if event.get("scope") == "room"]


@pytest.mark.anyio
async def test_cry_at_ashes_spawns_shard_when_space(engine, player):
    handled = await engine.handle_command(
        player.plyrid, 26, command="cry", args=["ashes"], player=player
    )

    assert handled is True

    room_objects = engine.yaml_engine.get_room_objects(26)
    assert 43 in room_objects
    assert len(room_objects) == 4  # starts with 3 ash tree objects
    assert 43 in engine.get_room_objects(26)

    direct_texts = _direct_texts(engine, player.plyrid)
    broadcast_texts = _broadcast_texts(engine)
    broadcast_payloads = _broadcast_payloads(engine)

    messages = fixtures.load_messages().messages
    assert messages["ASHM00"] in direct_texts
    assert messages["ASHM01"] in broadcast_texts
    assert any(
        payload.get("message_id") == "ASHM01"
        and payload.get("exclude_player") == player.plyrid
        for payload in broadcast_payloads
    )
    room_objects_events = [
        payload for payload in broadcast_payloads if payload.get("event") == "room_objects"
    ]
    assert len(room_objects_events) == 1
    assert room_objects_events[0]["location"] == 26
    assert room_objects_events[0]["include_sender"] is True
    assert any(obj["id"] == 43 for obj in room_objects_events[0]["objects"])
    assert [event.get("message_id") for event in engine.pending_events[:2]] == [
        "ASHM00",
        "ASHM01",
    ]
    assert engine.pending_events[2].get("event") == "room_objects"


@pytest.mark.anyio
async def test_cry_at_ashes_persists_shard_through_live_room_object_setter(player, scheduler):
    live_room_objects = {26: [1, 2, 3]}
    setter_calls: list[tuple[int, list[int]]] = []

    def get_live_room_objects(room_id: int) -> list[int]:
        return list(live_room_objects.get(room_id, []))

    def set_live_room_objects(room_id: int, object_ids: list[int]) -> None:
        live_room_objects[room_id] = list(object_ids)
        setter_calls.append((room_id, list(object_ids)))

    engine = RoomScriptEngine(
        gateway=FakeGateway(),
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=fixtures.load_messages(),
        players=[player],
        room_scripts=fixtures.load_room_scripts(),
        objects=fixtures.load_objects(),
        spells=fixtures.load_spells(),
        room_objects_getter=get_live_room_objects,
        room_objects_setter=set_live_room_objects,
    )

    handled = await engine.handle_command(
        player.plyrid, 26, command="cry", args=["ashes"], player=player
    )

    assert handled is True
    assert setter_calls == [(26, [1, 2, 3, 43])]
    room_objects_events = [
        event for event in engine.pending_events if event.get("event") == "room_objects"
    ]
    assert len(room_objects_events) == 1
    assert [obj["id"] for obj in room_objects_events[0]["objects"]] == [1, 2, 3, 43]


@pytest.mark.anyio
async def test_cry_at_trees_respects_room_capacity(engine, player):
    engine.set_room_objects(26, list(range(constants.MXLOBS)))

    handled = await engine.handle_command(
        player.plyrid, 26, command="weep", args=["trees"], player=player
    )

    assert handled is True

    room_objects = engine.get_room_objects(26)
    assert len(room_objects) == constants.MXLOBS
    assert 43 not in room_objects

    direct_texts = _direct_texts(engine, player.plyrid)
    broadcast_texts = _broadcast_texts(engine)
    broadcast_payloads = _broadcast_payloads(engine)

    messages = fixtures.load_messages().messages
    assert messages["ASHM02"] not in direct_texts
    assert messages["ASHM02"] in broadcast_texts
    assert any(
        payload.get("message_id") == "ASHM02"
        and payload.get("include_sender") is True
        for payload in broadcast_payloads
    )
    assert not any(payload.get("event") == "room_objects" for payload in broadcast_payloads)
