import random

import pytest

from kyrgame import constants, fixtures
from kyrgame.rooms import RoomScriptEngine
from kyrgame.scheduler import SchedulerService


class FixedRandom:
    def __init__(self, value: float):
        self._value = value

    def random(self) -> float:
        return self._value

    def randrange(self, start: int, stop: int) -> int:  # pragma: no cover - parity helper
        return start


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
        if message.get("type") == "room_broadcast"
        and message.get("payload", {}).get("scope") == "direct"
        and message.get("payload", {}).get("player") == player_id
    ]


def _broadcast_texts(engine: RoomScriptEngine) -> list[str]:
    return [
        message.get("payload", {}).get("text")
        for message in engine.gateway.messages
        if message.get("type") == "room_broadcast"
        and message.get("payload", {}).get("scope") == "broadcast"
    ]


@pytest.mark.anyio
async def test_get_ruby_rewards_player_on_success(engine, player):
    engine.yaml_engine.rng = random.Random(1)

    handled = await engine.handle_command(
        player.plyrid, 20, command="get", args=["ruby"], player=player
    )

    assert handled is True
    assert 0 in player.gpobjs
    assert player.npobjs == len(player.gpobjs)
    assert player.hitpts == 12

    direct_texts = _direct_texts(engine, player.plyrid)
    broadcast_texts = _broadcast_texts(engine)

    messages = fixtures.load_messages().messages
    assert messages["RUBY00"] in direct_texts
    assert messages["RUBY01"] % player.plyrid in broadcast_texts


@pytest.mark.anyio
async def test_get_ruby_backfires_on_failed_roll(engine, player):
    engine.yaml_engine.rng = FixedRandom(0.9)

    handled = await engine.handle_command(
        player.plyrid, 20, command="get", args=["ruby"], player=player
    )

    assert handled is True
    assert player.gpobjs == []
    assert player.npobjs == 0
    assert player.hitpts == 4

    direct_texts = _direct_texts(engine, player.plyrid)
    broadcast_texts = _broadcast_texts(engine)
    messages = fixtures.load_messages().messages

    assert messages["RUBY02"] in direct_texts
    assert messages["RUBY03"] % player.plyrid in broadcast_texts


@pytest.mark.anyio
async def test_get_ruby_requires_inventory_space(engine, player):
    engine.yaml_engine.rng = FixedRandom(0.0)
    player = player.model_copy(
        update={
            "gpobjs": list(range(constants.MXPOBS)),
            "obvals": [0 for _ in range(constants.MXPOBS)],
            "npobjs": constants.MXPOBS,
        },
        deep=True,
    )
    engine.players[player.plyrid] = player

    handled = await engine.handle_command(
        player.plyrid, 20, command="get", args=["ruby"], player=player
    )

    assert handled is True
    assert len(player.gpobjs) == constants.MXPOBS
    assert player.hitpts == 4

    messages = fixtures.load_messages().messages
    direct_texts = _direct_texts(engine, player.plyrid)
    broadcast_texts = _broadcast_texts(engine)

    assert messages["RUBY02"] in direct_texts
    assert messages["RUBY03"] % player.plyrid in broadcast_texts


@pytest.mark.anyio
async def test_get_ruby_ignores_unrelated_commands(engine, player):
    handled = await engine.handle_command(
        player.plyrid, 20, command="look", args=["around"], player=player
    )

    assert handled is False
    assert player.gpobjs == []
    assert player.hitpts == 12
