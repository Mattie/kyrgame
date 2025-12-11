import pytest

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
    spells = fixtures.load_spells()
    hotkiss = next(spell for spell in spells if spell.name == "hotkiss")

    player = _fresh_player()
    player.level = 5

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

    player.level = 6
    await engine.handle_command(
        "hero",
        18,
        command="drop",
        args=[str(11)],
        player_level=player.level,
        player=player,
    )

    assert player.stumpi == 12
    assert player.offspls & hotkiss.bitdef
    assert hotkiss.id in player.spells
    assert player.nspells == len(player.spells)

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
    assert messages.messages["BGEM01"] % "hero" in broadcast_texts


@pytest.mark.anyio
async def test_stump_wrong_item_resets_progress(engine_and_gateway):
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

    assert player.stumpi == 0
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
    assert messages.messages["BGEM03"] % "hero" in broadcast_texts


@pytest.mark.anyio
async def test_stump_requires_inventory(engine_and_gateway):
    engine, gateway = engine_and_gateway
    messages = fixtures.load_messages()

    player = _fresh_player()
    player.level = 5
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

    assert player.stumpi == 0
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
    assert messages.messages["BGEM06"] % "hero" in broadcast_texts


@pytest.mark.anyio
async def test_stump_level_gate_resets(engine_and_gateway):
    engine, gateway = engine_and_gateway
    messages = fixtures.load_messages()

    player = _fresh_player()
    player.level = 4

    await engine.handle_command(
        "hero",
        18,
        command="drop",
        args=["0"],
        player_level=player.level,
        player=player,
    )

    assert player.stumpi == 0
    assert "0" not in map(str, player.gpobjs)

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
    assert messages.messages["BGEM03"] % "hero" in broadcast_texts
