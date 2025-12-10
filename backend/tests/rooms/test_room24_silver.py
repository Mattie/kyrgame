import pytest

from kyrgame import fixtures
from kyrgame.rooms import RoomScriptEngine
from kyrgame.scheduler import SchedulerService


class FakeGateway:
    def __init__(self):
        self.messages = []

    async def broadcast(self, room_id: int, message: dict, sender=None):  # noqa: ARG002
        self.messages.append({"room": room_id, "scope": "broadcast", **message})

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
    )
    try:
        yield engine, gateway
    finally:
        await scheduler.stop()


def _fresh_player():
    return fixtures.build_player().model_copy(
        update={
            "gpobjs": [1, 2, 3, 4],
            "obvals": [0, 0, 0, 0],
            "npobjs": 4,
            "spells": [],
            "nspells": 0,
            "offspls": 0,
            "defspls": 0,
            "othspls": 0,
            "gemidx": 0,
            "stones": [1, 2, 3, 4],
        },
        deep=True,
    )


@pytest.mark.anyio
async def test_silver_sequence_awards_hotseat_when_ready(engine_and_gateway):
    engine, gateway = engine_and_gateway
    messages = fixtures.load_messages()
    spells = fixtures.load_spells()
    hotseat = next(spell for spell in spells if spell.name == "hotseat")

    player = _fresh_player()
    player.level = 4

    for stone in player.stones:
        await engine.handle_command(
            "hero",
            24,
            command="offer",
            args=[str(stone)],
            player_level=player.level,
            player=player,
        )

    assert player.gemidx == len(player.stones)
    assert player.defspls & hotseat.bitdef
    assert hotseat.id in player.spells
    assert player.nspells == len(player.spells)
    assert player.npobjs == len(player.gpobjs) == 0

    direct_texts = [
        msg.get("text")
        for msg in gateway.messages
        if msg.get("scope") == "direct" and msg.get("player") == "hero"
    ]
    assert messages.messages["SILVM0"] in direct_texts

    broadcast_texts = [
        msg.get("text")
        for msg in gateway.messages
        if msg.get("scope") == "broadcast" and msg.get("room") == 24 and "text" in msg
    ]
    assert messages.messages["SILVM1"] % "hero" in broadcast_texts


@pytest.mark.anyio
async def test_silver_wrong_offering_resets_progress(engine_and_gateway):
    engine, gateway = engine_and_gateway
    messages = fixtures.load_messages()

    player = _fresh_player()
    player.level = 5

    await engine.handle_command(
        "hero",
        24,
        command="offer",
        args=[str(player.stones[0])],
        player_level=player.level,
        player=player,
    )
    assert player.gemidx == 1

    player.gpobjs.append(99)
    player.obvals.append(0)
    player.npobjs = len(player.gpobjs)

    await engine.handle_command(
        "hero",
        24,
        command="offer",
        args=["99"],
        player_level=player.level,
        player=player,
    )

    assert player.gemidx == 0
    assert "99" not in map(str, player.gpobjs)

    direct_texts = [
        msg.get("text")
        for msg in gateway.messages
        if msg.get("scope") == "direct" and msg.get("player") == "hero"
    ]
    assert messages.messages["SILVM4"] in direct_texts


@pytest.mark.anyio
async def test_silver_level_gate_blocks_reward_and_resets(engine_and_gateway):
    engine, _ = engine_and_gateway

    player = _fresh_player()
    player.level = 2

    for stone in player.stones:
        await engine.handle_command(
            "hero",
            24,
            command="offer",
            args=[str(stone)],
            player_level=player.level,
            player=player,
        )

    assert player.defspls == 0
    assert player.spells == []
    assert player.gemidx == 0


@pytest.mark.anyio
async def test_silver_prayer_keeps_progression(engine_and_gateway):
    engine, gateway = engine_and_gateway
    messages = fixtures.load_messages()

    player = _fresh_player()
    player.level = 4
    player.gemidx = 2

    await engine.handle_command(
        "hero", 24, command="pray", args=[], player_level=player.level, player=player
    )

    assert player.gemidx == 2

    direct_texts = [
        msg.get("text")
        for msg in gateway.messages
        if msg.get("scope") == "direct" and msg.get("player") == "hero"
    ]
    assert messages.messages["SAPRAY"] in direct_texts

    broadcast_texts = [
        msg.get("text")
        for msg in gateway.messages
        if msg.get("scope") == "broadcast" and msg.get("room") == 24 and "text" in msg
    ]
    assert "praying to the Goddess Tashanna" in broadcast_texts[-1]
