import asyncio
import json
import socket
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import pytest
import uvicorn
import websockets
from sqlalchemy import select

from kyrgame import constants, models
from session_test_helpers import create_seeded_app as create_app


def _get_open_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return port


async def _recv_matching(ws, predicate, *, timeout: float = 2.0):
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        if predicate(message):
            return message


class _FixedRoomRng:
    def __init__(self, values: list[float]):
        self.values = values

    def random(self) -> float:
        return self.values.pop(0)


@dataclass(frozen=True)
class CommandStep:
    room_id: int
    command: str
    message_id: str | None = None


@dataclass(frozen=True)
class LevelStep:
    target_level: int
    room_id: int
    commands: tuple[str, ...]
    success_message_id: str
    setup: Callable[[models.Player], None] | None = None
    prerequisites: tuple[CommandStep, ...] = ()


PHYSICAL_KEY_OBJECT_ID = 14


def _inventory(record: models.Player, *object_ids: int) -> None:
    record.gpobjs = list(object_ids)
    record.obvals = [0] * len(object_ids)
    record.npobjs = len(object_ids)


def _set_level(record: models.Player, level: int) -> None:
    record.level = level
    record.nmpdes = constants.level_to_nmpdes(level)
    record.hitpts = max(record.hitpts, level * 4)
    record.spts = max(record.spts, level * 2)


def _birthstone_setup(record: models.Player) -> None:
    record.stones = [0, 1, 2, 3]
    record.gemidx = 0
    _inventory(record, 0, 1, 2, 3)


def _stump_setup(record: models.Player) -> None:
    record.stumpi = 0
    _inventory(record, 0)


def _heart_setup(record: models.Player) -> None:
    record.spouse = "Juliet"


LEVEL_STEPS = [
    LevelStep(2, 0, ("kneel",), "LVL200"),
    LevelStep(3, 7, ("say glory be to tashanna",), "LVL300"),
    LevelStep(
        4,
        24,
        ("offer ruby", "offer emerald", "offer garnet", "offer pearl"),
        "SILVM0",
        _birthstone_setup,
    ),
    LevelStep(5, 16, ("fear no evil",), "FEAR01"),
    LevelStep(
        6,
        18,
        (
            "drop ruby",
            "drop emerald",
            "drop garnet",
            "drop pearl",
            "drop aquamarine",
            "drop moonstone",
            "drop sapphire",
            "drop diamond",
            "drop amethyst",
            "drop onyx",
            "drop opal",
            "drop bloodstone",
        ),
        "BGEM00",
        _stump_setup,
    ),
    LevelStep(7, 101, ("offer heart and soul to tashanna",), "HNSYOU"),
    LevelStep(
        8,
        188,
        ("drop dagger orb",),
        "MISM04",
        prerequisites=(CommandStep(181, "imagine dagger", "DAGM00"),),
    ),
    LevelStep(
        9,
        7,
        (
            "chant tashanna",
            "chant tashanna",
            "chant tashanna",
            "chant tashanna",
            "chant tashanna",
            "put charm",
        ),
        "LVL9M0",
        prerequisites=(CommandStep(188, "think orb", "MISM01"),),
    ),
    LevelStep(
        10,
        7,
        (
            "chant tashanna",
            "chant tashanna",
            "chant tashanna",
            "chant tashanna",
            "chant tashanna",
            "put tiara",
        ),
        "LV10M0",
        prerequisites=(
            CommandStep(181, "imagine dagger", "DAGM00"),
            CommandStep(182, "toss dagger pool", "REFM00"),
            CommandStep(27, "pray rock"),
            CommandStep(27, "drop sword rock", "ROCK00"),
        ),
    ),
    LevelStep(
        11,
        201,
        ("aim wand tree",),
        "CTREM0",
        prerequisites=(
            CommandStep(199, "get tulip", "TULM00"),
            CommandStep(213, "cast zapher tulip", "SUNM00"),
        ),
    ),
    LevelStep(
        12,
        213,
        ("offer kyragem",),
        "SUNM03",
        prerequisites=(CommandStep(204, "break wand", "RABOM2"),),
    ),
    LevelStep(
        13,
        282,
        ("jump chasm",),
        "BODM01",
        prerequisites=(
            CommandStep(282, "cast abbracada", "SPM000"),
        ),
    ),
    LevelStep(14, 285, ("answer time",), "MINM01"),
    LevelStep(15, 288, ("offer heart Juliet",), "HEAR01", _heart_setup),
    LevelStep(16, 291, ("ignore time",), "SOUL01"),
    LevelStep(17, 295, ("devote",), "DEVM01"),
    LevelStep(18, 280, ("seek truth",), "TRUM02"),
    LevelStep(19, 252, ("sing",), "LEVL19"),
    LevelStep(20, 253, ("forget",), "LEVL20"),
    LevelStep(21, 257, ("believe in magic",), "LEVL21"),
    LevelStep(22, 255, ("offer love",), "LEVL22"),
    LevelStep(23, 264, ("wonder",), "LEVL23"),
    LevelStep(24, 293, ("believe in fantasy",), "LEVL24"),
    LevelStep(25, 302, ("answer cast the spells and cross the seas, heart, soul, mind, and body are the keys",), "YOUWIN"),
]


@pytest.mark.anyio
async def test_solo_level_journey_reaches_level_25_with_in_game_commands(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    monkeypatch.setenv("KYRGAME_WS_COMMAND_RATE_LIMIT_MAX_EVENTS", "1000")
    monkeypatch.setenv("KYRGAME_WS_COMMAND_RATE_LIMIT_WINDOW_SECONDS", "1")

    app = create_app()
    host = "127.0.0.1"
    port = _get_open_port()
    player_id = "journey"

    config = uvicorn.Config(app, host=host, port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    async def start_step(client: httpx.AsyncClient, step: LevelStep) -> str:
        app.state.session_rate_limiters = {}
        response = await client.post(
            "/auth/session", json={"player_id": player_id, "room_id": step.room_id}
        )
        response.raise_for_status()
        return response.json()["session"]["token"]

    async def run_command(ws, command: str, final_message_id: str | None = None) -> None:
        await ws.send(json.dumps({"type": "command", "command": command}))
        saw_ack = False
        saw_final = final_message_id is None
        seen: list[dict] = []
        while not (saw_ack and saw_final):
            try:
                message = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            except TimeoutError as exc:
                raise AssertionError(
                    f"Timed out after {command!r}; "
                    f"saw_ack={saw_ack}, saw_final={saw_final}, "
                    f"expected_message_id={final_message_id!r}, seen={seen}"
                ) from exc
            seen.append(message)
            payload = message.get("payload", {})
            if (
                message.get("type") == "command_response"
                and payload.get("verb") == command.split()[0]
            ):
                saw_ack = True
            if payload.get("message_id") == final_message_id:
                saw_final = True

    async def run_single_command_session(
        client: httpx.AsyncClient,
        room_id: int,
        command: str,
        message_id: str | None,
    ) -> None:
        app.state.session_rate_limiters = {}
        response = await client.post(
            "/auth/session", json={"player_id": player_id, "room_id": room_id}
        )
        response.raise_for_status()
        token = response.json()["session"]["token"]
        uri = f"ws://{host}:{port}/ws/rooms/{room_id}?token={token}"
        async with websockets.connect(uri) as ws:
            await _recv_matching(
                ws,
                lambda msg: msg.get("payload", {}).get("event") == "location_update",
            )
            await run_command(ws, command, message_id)

    try:
        async with httpx.AsyncClient(base_url=f"http://{host}:{port}") as client:
            await client.post("/auth/session", json={"player_id": player_id, "room_id": 0})
            app.state.room_scripts.yaml_engine.rng = _FixedRoomRng([0.75])

            for step in LEVEL_STEPS:
                with app.state.session_factory() as db:
                    record = db.scalar(select(models.Player).where(models.Player.plyrid == player_id))
                    assert record is not None
                    assert record.level == step.target_level - 1
                    _set_level(record, step.target_level - 1)
                    # This journey compresses many legacy play sessions into one test loop;
                    # splrtk() would clear command fatigue between these level beats.
                    record.macros = 0
                    if step.setup:
                        step.setup(record)
                    db.commit()
                if step.room_id == 7:
                    # Legacy animat clears chantd after the altar glow window.
                    # Source: legacy/KYRANIM.C:140-143.
                    app.state.room_scripts.get_room_state(7).flags["chantd"] = 0

                if step.target_level == 6:
                    for index, command in enumerate(step.commands):
                        with app.state.session_factory() as db:
                            record = db.scalar(
                                select(models.Player).where(models.Player.plyrid == player_id)
                            )
                            assert record is not None
                            assert record.level == 5
                            assert record.stumpi == index
                            _inventory(record, index)
                            db.commit()
                        message_id = step.success_message_id if index == 11 else "BGEM02"
                        await run_single_command_session(
                            client, step.room_id, command, message_id
                        )

                    with app.state.session_factory() as db:
                        record = db.scalar(
                            select(models.Player).where(models.Player.plyrid == player_id)
                        )
                        assert record is not None
                        assert record.level == step.target_level
                    continue

                for prerequisite in step.prerequisites:
                    await run_single_command_session(
                        client,
                        prerequisite.room_id,
                        prerequisite.command,
                        prerequisite.message_id,
                    )

                token = await start_step(client, step)
                uri = f"ws://{host}:{port}/ws/rooms/{step.room_id}?token={token}"
                async with websockets.connect(uri) as ws:
                    await _recv_matching(
                        ws,
                        lambda msg: msg.get("payload", {}).get("event") == "location_update",
                    )
                    for command in step.commands[:-1]:
                        await run_command(ws, command)
                    await run_command(ws, step.commands[-1], step.success_message_id)

                with app.state.session_factory() as db:
                    record = db.scalar(select(models.Player).where(models.Player.plyrid == player_id))
                    assert record is not None
                    assert record.level == step.target_level
                    if step.target_level == 13:
                        assert PHYSICAL_KEY_OBJECT_ID not in record.gpobjs

            with app.state.session_factory() as db:
                record = db.scalar(select(models.Player).where(models.Player.plyrid == player_id))
                assert record is not None
                assert record.level == 25
                assert record.gamloc == 302
                assert PHYSICAL_KEY_OBJECT_ID not in record.gpobjs
                assert record.nspells == len(record.spells)
                expected_spell_ids = list(record.spells[: record.nspells])

            resume = await client.post("/auth/session", json={"player_id": player_id})
            resume.raise_for_status()
            resumed = resume.json()["session"]
            assert resumed["room_id"] == 302
            uri = f"ws://{host}:{port}/ws/rooms/{resumed['room_id']}?token={resumed['token']}"
            async with websockets.connect(uri) as ws:
                location = await _recv_matching(
                    ws,
                    lambda msg: msg.get("payload", {}).get("event") == "location_update",
                )
                assert location["payload"]["location"] == 302
                await ws.send(json.dumps({"type": "command", "command": "spells"}))
                spells = await _recv_matching(
                    ws,
                    lambda msg: msg.get("type") == "command_response"
                    and msg.get("payload", {}).get("level") == 25,
                )
                assert spells["payload"]["level"] == 25
                assert spells["payload"]["memorized_spell_ids"] == expected_spell_ids
    finally:
        server.should_exit = True
        await server_task
