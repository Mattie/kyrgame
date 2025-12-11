import pytest

from kyrgame import fixtures
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
    return fixtures.build_player().model_copy(
        update={"gpobjs": [], "obvals": [], "npobjs": 0}, deep=True
    )


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
    return [
        message.get("payload", {}).get("text")
        for message in engine.gateway.messages
        if message.get("payload", {}).get("scope") == "direct"
        and message.get("payload", {}).get("player") == player_id
    ]


def _broadcast_texts(engine: RoomScriptEngine) -> list[str]:
    return [
        message.get("payload", {}).get("text")
        for message in engine.gateway.messages
        if message.get("payload", {}).get("scope") == "broadcast"
    ]


@pytest.mark.anyio
async def test_prayer_increments_rock_counter(engine, player):
    handled = await engine.handle_command(
        player.plyrid, 27, command="pray", args=["rock"], player=player
    )

    assert handled is True
    assert engine.yaml_engine.get_room_state(27).get("rockpr") == 1

    direct_texts = _direct_texts(engine, player.plyrid)
    broadcast_texts = _broadcast_texts(engine)

    assert "Your prayers are heard." in direct_texts[0]
    assert "mists around the rock" in broadcast_texts[0]


@pytest.mark.anyio
async def test_drop_sword_on_rock_requires_prior_prayer(engine, player):
    player.gpobjs.append(34)
    player.obvals.append(0)
    player.npobjs = 1
    engine.players[player.plyrid] = player

    handled_without_prayer = await engine.handle_command(
        player.plyrid, 27, command="drop", args=["sword", "rock"], player=player
    )
    assert handled_without_prayer is False
    assert 34 in player.gpobjs

    await engine.handle_command(player.plyrid, 27, command="pray", args=["rock"], player=player)

    handled = await engine.handle_command(
        player.plyrid, 27, command="drop", args=["sword", "rock"], player=player
    )

    assert handled is True
    assert 34 not in player.gpobjs

    room_objects = engine.yaml_engine.get_room_objects(27)
    assert 21 in room_objects

    direct_texts = _direct_texts(engine, player.plyrid)
    broadcast_texts = _broadcast_texts(engine)

    messages = fixtures.load_messages().messages
    assert messages["ROCK00"] in direct_texts
    assert messages["ROCK01"] % player.plyrid in broadcast_texts


@pytest.mark.anyio
async def test_drop_sword_on_rock_rejects_missing_sword(engine, player):
    await engine.handle_command(player.plyrid, 27, command="pray", args=["rock"], player=player)

    handled = await engine.handle_command(
        player.plyrid, 27, command="drop", args=["sword", "rock"], player=player
    )

    assert handled is True
    assert 21 not in engine.yaml_engine.get_room_objects(27)

    direct_texts = _direct_texts(engine, player.plyrid)
    broadcast_texts = _broadcast_texts(engine)

    messages = fixtures.load_messages().messages
    assert messages["ROCK02"] in direct_texts
    assert messages["ROCK01"] % player.plyrid in broadcast_texts
