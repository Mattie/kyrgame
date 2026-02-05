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


@pytest.mark.anyio
async def test_cry_at_ashes_spawns_shard_when_space(engine, player):
    handled = await engine.handle_command(
        player.plyrid, 26, command="cry", args=["ashes"], player=player
    )

    assert handled is True

    room_objects = engine.yaml_engine.get_room_objects(26)
    assert 43 in room_objects
    assert len(room_objects) == 4  # starts with 3 ash tree objects

    direct_texts = _direct_texts(engine, player.plyrid)
    broadcast_texts = _broadcast_texts(engine)

    messages = fixtures.load_messages().messages
    assert messages["ASHM00"] in direct_texts
    assert messages["ASHM01"] in broadcast_texts


@pytest.mark.anyio
async def test_cry_at_trees_respects_room_capacity(engine, player):
    engine.yaml_engine.room_objects[26] = list(range(constants.MXLOBS))

    handled = await engine.handle_command(
        player.plyrid, 26, command="weep", args=["trees"], player=player
    )

    assert handled is True

    room_objects = engine.yaml_engine.get_room_objects(26)
    assert len(room_objects) == constants.MXLOBS
    assert 43 not in room_objects

    direct_texts = _direct_texts(engine, player.plyrid)
    broadcast_texts = _broadcast_texts(engine)

    messages = fixtures.load_messages().messages
    assert messages["ASHM02"] in direct_texts
    assert messages["ASHM02"] in broadcast_texts
