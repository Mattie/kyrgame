import pytest

from kyrgame import constants
from kyrgame import fixtures
from kyrgame.rooms import RoomScriptEngine
from kyrgame.scheduler import SchedulerService


class FakeGateway:
    def __init__(self):
        self.messages = []

    async def broadcast(self, room_id: int, message: dict, sender=None):  # noqa: ARG002
        payload = message.get("payload", {})
        self.messages.append(
            {
                "room": room_id,
                "scope": payload.get("scope", "broadcast"),
                "player": payload.get("player"),
                **payload,
            }
        )

    async def direct(self, room_id: int, player_id: str, message: dict):
        self.messages.append({"room": room_id, "scope": "direct", "player": player_id, **message})


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def engine_and_gateway():
    scheduler = SchedulerService()
    await scheduler.start()
    gateway = FakeGateway()
    messages = fixtures.load_messages()
    engine = RoomScriptEngine(
        gateway=gateway,
        scheduler=scheduler,
        locations=fixtures.load_locations(),
        messages=messages,
        room_scripts=fixtures.load_room_scripts(),
        objects=fixtures.load_objects(),
        spells=fixtures.load_spells(),
    )
    try:
        yield engine, gateway
    finally:
        await scheduler.stop()


def _fresh_player():
    return fixtures.build_player().model_copy(
        update={
            "gpobjs": list(range(12)),
            "obvals": [0] * 12,
            "npobjs": 12,
            "spells": [],
            "nspells": 0,
            "offspls": 0,
            "defspls": 0,
            "othspls": 0,
            "stumpi": 0,
        },
        deep=True,
    )


@pytest.mark.anyio
async def test_stump_sequence_awards_hotkiss(engine_and_gateway):
    engine, gateway = engine_and_gateway
    messages = fixtures.load_messages()
    player = _fresh_player()
    player.level = 5
    player.flags = int(constants.PlayerFlag.LOADED)

    for obj_id in range(11):
        await engine.handle_command(
            "hero",
            18,
            command="drop",
            args=[str(obj_id)],
            player_level=player.level,
            player=player,
        )

    assert player.stumpi == 11
    assert player.npobjs == len(player.gpobjs) == 1

    await engine.handle_command(
        "hero",
        18,
        command="drop",
        args=[str(11)],
        player_level=player.level,
        player=player,
    )

    assert player.stumpi == 12
    assert player.level == 6
    assert player.offspls & constants.SBD032_FIREBOLT2 == constants.SBD032_FIREBOLT2
    assert player.spells == []
    assert player.nspells == 0

    direct_texts = [
        msg.get("text")
        for msg in gateway.messages
        if msg.get("scope") == "direct" and msg.get("player") == "hero"
    ]
    assert messages.messages["BGEM00"] in direct_texts

    broadcast_texts = [
        msg.get("text")
        for msg in gateway.messages
        if msg.get("scope") == "broadcast" and msg.get("room") == 18 and "text" in msg
    ]
    assert messages.messages["BGEM01"] % player.altnam in broadcast_texts


@pytest.mark.anyio
async def test_stump_broadcast_message_goes_only_to_others(engine_and_gateway):
    engine, gateway = engine_and_gateway
    messages = fixtures.load_messages()
    player = _fresh_player()
    player.level = 5

    await engine.enter_room("hero", 18)
    await engine.enter_room("ally", 18)

    await engine.handle_command(
        "hero",
        18,
        command="drop",
        args=["0"],
        player_level=player.level,
        player=player,
    )

    direct_for_hero = [
        msg.get("text")
        for msg in gateway.messages
        if msg.get("scope") == "direct" and msg.get("player") == "hero"
    ]
    assert messages.messages["BGEM03"] % player.altnam not in direct_for_hero

    broadcast_for_others = [
        msg
        for msg in gateway.messages
        if msg.get("scope") == "broadcast"
        and msg.get("text") == (messages.messages["BGEM03"] % player.altnam)
    ]
    assert broadcast_for_others
    assert all(msg.get("exclude_player") == "hero" for msg in broadcast_for_others)


@pytest.mark.anyio
async def test_stump_wrong_item_preserves_progress(engine_and_gateway):
    engine, gateway = engine_and_gateway
    messages = fixtures.load_messages()

    player = _fresh_player()
    player.level = 5

    await engine.handle_command(
        "hero",
        18,
        command="offer",
        args=[str(0)],
        player_level=player.level,
        player=player,
    )

    player.gpobjs.append(99)
    player.obvals.append(0)
    player.npobjs = len(player.gpobjs)

    await engine.handle_command(
        "hero",
        18,
        command="offer",
        args=["99"],
        player_level=player.level,
        player=player,
    )

    assert player.stumpi == 1
    assert "99" not in map(str, player.gpobjs)

    direct_texts = [
        msg.get("text")
        for msg in gateway.messages
        if msg.get("scope") == "direct" and msg.get("player") == "hero"
    ]
    assert messages.messages["BGEM04"] in direct_texts

    broadcast_texts = [
        msg.get("text")
        for msg in gateway.messages
        if msg.get("scope") == "broadcast" and msg.get("room") == 18 and "text" in msg
    ]
    assert messages.messages["BGEM03"] % player.altnam in broadcast_texts

    await engine.handle_command(
        "hero",
        18,
        command="offer",
        args=[str(1)],
        player_level=player.level,
        player=player,
    )
    assert player.stumpi == 2


@pytest.mark.anyio
async def test_stump_requires_inventory_preserves_progress(engine_and_gateway):
    engine, gateway = engine_and_gateway
    messages = fixtures.load_messages()

    player = _fresh_player()
    player.level = 5
    player.stumpi = 1
    player.gpobjs.remove(0)
    player.obvals.pop(0)
    player.npobjs = len(player.gpobjs)

    await engine.handle_command(
        "hero",
        18,
        command="drop",
        args=["0"],
        player_level=player.level,
        player=player,
    )

    assert player.stumpi == 1
    assert "0" not in map(str, player.gpobjs)

    direct_texts = [
        msg.get("text")
        for msg in gateway.messages
        if msg.get("scope") == "direct" and msg.get("player") == "hero"
    ]
    assert messages.messages["BGEM05"] in direct_texts

    broadcast_texts = [
        msg.get("text")
        for msg in gateway.messages
        if msg.get("scope") == "broadcast" and msg.get("room") == 18 and "text" in msg
    ]
    assert messages.messages["BGEM06"] % player.altnam in broadcast_texts


@pytest.mark.anyio
async def test_stump_wrong_level_preserves_progress(engine_and_gateway):
    engine, gateway = engine_and_gateway
    messages = fixtures.load_messages()

    player = _fresh_player()
    player.level = 4
    player.stumpi = 1

    await engine.handle_command(
        "hero",
        18,
        command="drop",
        args=["1"],
        player_level=player.level,
        player=player,
    )

    assert player.stumpi == 1
    assert "1" not in map(str, player.gpobjs)

    direct_texts = [
        msg.get("text")
        for msg in gateway.messages
        if msg.get("scope") == "direct" and msg.get("player") == "hero"
    ]
    assert messages.messages["BGEM04"] in direct_texts

    broadcast_texts = [
        msg.get("text")
        for msg in gateway.messages
        if msg.get("scope") == "broadcast" and msg.get("room") == 18 and "text" in msg
    ]
    assert messages.messages["BGEM03"] % player.altnam in broadcast_texts
