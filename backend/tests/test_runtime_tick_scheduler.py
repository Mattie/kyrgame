import json

import pytest
from fastapi import FastAPI
from starlette.websockets import WebSocketState

from kyrgame import commands, constants, fixtures, models
from kyrgame.runtime import bootstrap_app, shutdown_app
from kyrgame.telemetry import TelemetryEventSink
from kyrgame.world.animation_tick_system import AnimationTickEvent


class _FixedAnimationRng:
    def __init__(self, *values: int) -> None:
        self._values = list(values)

    def randint(self, low: int, high: int) -> int:  # noqa: ARG002
        return self._values.pop(0)


class _FakeSocket:
    application_state = WebSocketState.CONNECTED

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self.application_state = WebSocketState.DISCONNECTED


@pytest.mark.anyio
async def test_bootstrap_initializes_tick_scheduler_and_shutdown_cancels_timers(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "0.25")

    app = FastAPI()
    await bootstrap_app(app)

    assert hasattr(app.state, "tick_scheduler")
    assert hasattr(app.state, "tick_runtime")
    assert hasattr(app.state, "animation_tick_system")
    assert app.state.tick_scheduler.tick_seconds == 0.25

    spell_handle = app.state.tick_runtime.handles["spell_tick"]
    animation_handle = app.state.tick_runtime.handles["animation_tick"]
    assert not spell_handle.cancelled
    assert not animation_handle.cancelled

    handle = app.state.tick_scheduler.register_recurring_timer(
        "test_tick", 1, lambda: None
    )
    assert not handle.cancelled

    await shutdown_app(app)

    assert spell_handle.cancelled
    assert animation_handle.cancelled
    assert handle.cancelled
    assert app.state.scheduler._task is None


@pytest.mark.anyio
async def test_bootstrap_uses_default_tick_seconds_when_env_missing(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.delenv("KYRGAME_TICK_SECONDS", raising=False)

    app = FastAPI()
    await bootstrap_app(app)

    assert app.state.tick_scheduler.tick_seconds == 1.0

    await shutdown_app(app)


@pytest.mark.anyio
async def test_spell_tick_callback_fans_out_altname_expiry_and_syncs_live_players(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "999")

    app = FastAPI()
    await bootstrap_app(app)
    app.state.tick_runtime.stop()

    with app.state.session_factory() as session:
        hero = session.query(models.Player).filter(models.Player.plyrid == "hero").one()
        hero.gamloc = 7
        hero.pgploc = 7
        hero.altnam = "Some willowisp"
        hero.attnam = "willowisp"
        hero.flags = int(
            constants.PlayerFlag.LOADED
            | constants.PlayerFlag.INVISF
            | constants.PlayerFlag.PEGASU
            | constants.PlayerFlag.WILLOW
            | constants.PlayerFlag.PDRAGN
        )
        hero.charms = [0, 0, 0, 0, 0, 1]
        witness = fixtures.build_player().model_copy(
            update={
                "uidnam": "witness-user",
                "plyrid": "witness",
                "altnam": "Witness",
                "attnam": "Witness",
                "gamloc": 7,
                "pgploc": 7,
                "modno": 2,
            }
        )
        session.add(models.Player(**witness.model_dump()))
        session.commit()

    hero_socket = _FakeSocket()
    shadow_socket = _FakeSocket()
    witness_socket = _FakeSocket()
    live_hero = fixtures.build_player().model_copy(
        update={
            "plyrid": "hero",
            "altnam": "Some willowisp",
            "attnam": "willowisp",
            "gamloc": 7,
            "pgploc": 7,
            "flags": int(
                constants.PlayerFlag.LOADED
                | constants.PlayerFlag.INVISF
                | constants.PlayerFlag.PEGASU
                | constants.PlayerFlag.WILLOW
                | constants.PlayerFlag.PDRAGN
            ),
            "charms": [0, 0, 0, 0, 0, 1],
        }
    )
    shadow_hero = models.PlayerModel(**live_hero.model_dump())
    live_witness = fixtures.build_player().model_copy(
        update={
            "plyrid": "witness",
            "altnam": "Witness",
            "attnam": "Witness",
            "gamloc": 7,
            "pgploc": 7,
        }
    )
    app.state.session_connections = {
        "hero-token": hero_socket,
        "shadow-hero-token": shadow_socket,
        "witness-token": witness_socket,
    }
    app.state.active_player_sessions = {
        "hero-token": live_hero,
        "shadow-hero-token": shadow_hero,
        "witness-token": live_witness,
    }
    app.state.active_players = {"hero": live_hero, "witness": live_witness}
    await app.state.presence.set_location("hero", 7, "hero-token")
    await app.state.presence.set_location("hero", 7, "shadow-hero-token")
    await app.state.presence.set_location("witness", 7, "witness-token")
    await app.state.gateway.register(7, hero_socket, announce=False)
    await app.state.gateway.register(7, shadow_socket, announce=False)
    await app.state.gateway.register(7, witness_socket, announce=False)

    await app.state.spell_tick_callback()

    for socket in (hero_socket, shadow_socket):
        assert any(
            message.get("type") == "command_response"
            and message.get("payload", {}).get("message_id") == "BASMSG5"
            for message in socket.sent
        )
        assert not any(
            message.get("payload", {}).get("message_id") == "RET2NM"
            for message in socket.sent
        )

    ret2nm = next(
        message
        for message in witness_socket.sent
        if message.get("type") == "room_broadcast"
        and message.get("payload", {}).get("message_id") == "RET2NM"
    )
    assert "Some willowisp" in ret2nm["payload"]["text"]
    assert "hero" in ret2nm["payload"]["text"]

    occupants_refresh = next(
        message
        for message in witness_socket.sent
        if message.get("type") == "command_response"
        and message.get("payload", {}).get("event") == "room_occupants"
    )
    hero_detail = next(
        detail
        for detail in occupants_refresh["payload"]["occupant_details"]
        if detail["player_id"] == "hero"
    )
    assert hero_detail["flags"] == int(constants.PlayerFlag.LOADED)

    with app.state.session_factory() as session:
        refreshed = session.query(models.Player).filter(models.Player.plyrid == "hero").one()
        assert refreshed.altnam == "hero"
        assert refreshed.attnam == "hero"
        assert refreshed.flags == int(constants.PlayerFlag.LOADED)
        assert refreshed.charms[constants.ALTNAM] == 0

    for player_state in (live_hero, shadow_hero, app.state.active_players["hero"]):
        assert player_state.altnam == "hero"
        assert player_state.attnam == "hero"
        assert player_state.flags == int(constants.PlayerFlag.LOADED)
        assert player_state.charms[constants.ALTNAM] == 0

    vocabulary = commands.CommandVocabulary(
        app.state.fixture_cache["commands"], app.state.fixture_cache["messages"]
    )
    state = commands.GameState(
        player=live_hero,
        locations=app.state.location_index,
        objects={obj.id: obj for obj in app.state.fixture_cache["objects"]},
        messages=app.state.fixture_cache["messages"],
        content_mappings=app.state.fixture_cache["content_mappings"],
        presence=app.state.presence,
    )
    parsed = vocabulary.parse_text("say hello")
    result = await commands.CommandDispatcher(
        commands.build_default_registry(vocabulary)
    ).dispatch_parsed(parsed, state)
    room_text = next(event["text"] for event in result.events if event.get("scope") == "room")
    assert "hero" in room_text
    assert "Some willowisp" not in room_text

    await shutdown_app(app)


@pytest.mark.anyio
async def test_spell_tick_callback_skips_room_broadcast_for_offline_altname_expiry(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "999")

    app = FastAPI()
    await bootstrap_app(app)
    app.state.tick_runtime.stop()

    with app.state.session_factory() as session:
        hero = session.query(models.Player).filter(models.Player.plyrid == "hero").one()
        hero.gamloc = 7
        hero.pgploc = 7
        hero.altnam = "Some willowisp"
        hero.attnam = "willowisp"
        hero.flags = int(constants.PlayerFlag.LOADED | constants.PlayerFlag.WILLOW)
        hero.charms = [0, 0, 0, 0, 0, 1]
        witness = fixtures.build_player().model_copy(
            update={
                "uidnam": "witness-user",
                "plyrid": "witness",
                "altnam": "Witness",
                "attnam": "Witness",
                "gamloc": 7,
                "pgploc": 7,
                "modno": 2,
            }
        )
        session.add(models.Player(**witness.model_dump()))
        session.commit()

    witness_socket = _FakeSocket()
    live_witness = fixtures.build_player().model_copy(
        update={
            "plyrid": "witness",
            "altnam": "Witness",
            "attnam": "Witness",
            "gamloc": 7,
            "pgploc": 7,
        }
    )
    app.state.session_connections = {"witness-token": witness_socket}
    app.state.active_player_sessions = {"witness-token": live_witness}
    app.state.active_players = {"witness": live_witness}
    await app.state.presence.set_location("witness", 7, "witness-token")
    await app.state.gateway.register(7, witness_socket, announce=False)

    await app.state.spell_tick_callback()

    assert not any(
        message.get("payload", {}).get("message_id") == "RET2NM"
        for message in witness_socket.sent
    )
    assert not any(
        message.get("payload", {}).get("event") == "room_occupants"
        for message in witness_socket.sent
    )

    with app.state.session_factory() as session:
        refreshed = session.query(models.Player).filter(models.Player.plyrid == "hero").one()
        assert refreshed.altnam == "hero"
        assert refreshed.attnam == "hero"
        assert refreshed.flags == int(constants.PlayerFlag.LOADED)
        assert refreshed.charms[constants.ALTNAM] == 0

    await shutdown_app(app)


@pytest.mark.anyio
async def test_spell_tick_callback_syncs_nonexpired_timer_decrements_to_live_players(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "999")

    app = FastAPI()
    await bootstrap_app(app)
    app.state.tick_runtime.stop()

    with app.state.session_factory() as session:
        hero = session.query(models.Player).filter(models.Player.plyrid == "hero").one()
        hero.gamloc = 7
        hero.pgploc = 7
        hero.altnam = "Some willowisp"
        hero.attnam = "willowisp"
        hero.flags = int(constants.PlayerFlag.LOADED | constants.PlayerFlag.WILLOW)
        hero.spts = 3
        hero.level = 4
        hero.charms = [0, 0, 0, 0, 0, 4]
        session.commit()

    live_hero = fixtures.build_player().model_copy(
        update={
            "plyrid": "hero",
            "altnam": "Some willowisp",
            "attnam": "willowisp",
            "gamloc": 7,
            "pgploc": 7,
            "flags": int(constants.PlayerFlag.LOADED | constants.PlayerFlag.WILLOW),
            "spts": 3,
            "level": 4,
            "charms": [0, 0, 0, 0, 0, 4],
        }
    )
    app.state.active_players = {"hero": live_hero}
    app.state.active_player_sessions = {"hero-token": live_hero}

    await app.state.spell_tick_callback()

    with app.state.session_factory() as session:
        refreshed = session.query(models.Player).filter(models.Player.plyrid == "hero").one()
        assert refreshed.altnam == "Some willowisp"
        assert refreshed.flags == int(constants.PlayerFlag.LOADED | constants.PlayerFlag.WILLOW)
        assert refreshed.spts == 5
        assert refreshed.charms[constants.ALTNAM] == 3

    assert live_hero.altnam == "Some willowisp"
    assert live_hero.flags == int(constants.PlayerFlag.LOADED | constants.PlayerFlag.WILLOW)
    assert live_hero.spts == 5
    assert live_hero.charms[constants.ALTNAM] == 3

    await shutdown_app(app)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "flag",
    [
        constants.PlayerFlag.INVISF,
        constants.PlayerFlag.PEGASU,
        constants.PlayerFlag.WILLOW,
        constants.PlayerFlag.PDRAGN,
    ],
)
async def test_spell_tick_callback_clears_each_legacy_transformation_flag(monkeypatch, flag):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "999")

    app = FastAPI()
    await bootstrap_app(app)
    app.state.tick_runtime.stop()

    with app.state.session_factory() as session:
        hero = session.query(models.Player).filter(models.Player.plyrid == "hero").one()
        hero.gamloc = 7
        hero.pgploc = 7
        hero.altnam = "Some transformed shape"
        hero.attnam = "transformed shape"
        hero.flags = int(constants.PlayerFlag.LOADED | flag)
        hero.charms = [0, 0, 0, 0, 0, 1]
        session.commit()

    await app.state.spell_tick_callback()

    with app.state.session_factory() as session:
        refreshed = session.query(models.Player).filter(models.Player.plyrid == "hero").one()
        assert refreshed.altnam == "hero"
        assert refreshed.attnam == "hero"
        assert refreshed.flags == int(constants.PlayerFlag.LOADED)
        assert refreshed.charms[constants.ALTNAM] == 0

    await shutdown_app(app)


@pytest.mark.anyio
async def test_animation_tick_callback_syncs_room_flags_and_clears_one_shots(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")

    app = FastAPI()
    await bootstrap_app(app)

    app.state.room_scripts.yaml_engine.get_room_state(185)["sesame"] = 1
    await app.state.animation_tick_callback()

    assert app.state.room_scripts.yaml_engine.get_room_state(185)["sesame"] == 0

    await shutdown_app(app)


@pytest.mark.anyio
async def test_animation_tick_callback_clears_hardcoded_temple_chantd(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")

    app = FastAPI()
    await bootstrap_app(app)

    app.state.room_scripts.get_room_state(7).flags["chantd"] = 6
    broadcasts: list[tuple[int, dict]] = []

    async def _capture(room_id: int, message: dict, sender=None, exclude=None):  # noqa: ARG001
        broadcasts.append((room_id, message))

    app.state.gateway.broadcast = _capture

    await app.state.animation_tick_callback()

    assert app.state.room_scripts.get_room_state(7).flags["chantd"] == 0
    temple_messages = [
        message["payload"]
        for room_id, message in broadcasts
        if room_id == 7 and message.get("payload", {}).get("animation_flag") == "chantd"
    ]
    assert temple_messages == [
        {
            "event": "room_message",
            "scope": "room",
            "type": "room_message",
            "message_id": None,
            "text": "***\rThe altar stops glowing.\r",
            "animation_flag": "chantd",
        }
    ]

    await shutdown_app(app)


@pytest.mark.anyio
async def test_animation_tick_callback_records_system_audit_for_brownie_step(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1.0")

    app = FastAPI()
    app.state.telemetry_sink = TelemetryEventSink(tmp_path / "telemetry")
    await bootstrap_app(app)
    app.state.tick_runtime.stop()

    active_player = fixtures.build_player().model_copy(
        update={
            "plyrid": "hero",
            "altnam": "Hero",
            "gamloc": 71,
            "pgploc": 71,
            "gold": 9,
            "gpobjs": [0, 1],
            "obvals": [10, 20],
            "npobjs": 2,
        }
    )
    app.state.active_player_sessions = {"hero-token": active_player}
    app.state.active_players = {}
    app.state.animation_tick_system.state.routine_index = 5
    app.state.animation_tick_system.state.brownie_path_index = 0

    await app.state.animation_tick_callback()
    await app.state.animation_tick_callback()

    lines = [
        json.loads(line)
        for line in (tmp_path / "telemetry" / "system.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    tick_events = [line for line in lines if line["event_type"] == "animation.tick"]
    brownie_events = [line for line in lines if line["event_type"] == "animation.brownie_step"]

    assert [event["payload"]["trigger_source"] for event in tick_events] == [
        "scheduled",
        "scheduled",
    ]
    assert tick_events[0]["payload"]["routine_name"] == "browns"
    assert tick_events[0]["payload"]["routine_index_before"] == 5
    assert tick_events[0]["payload"]["routine_index_after"] == 0
    assert tick_events[0]["payload"]["expected_interval_seconds"] == 15.0
    assert tick_events[0]["payload"]["observed_elapsed_seconds"] is None
    assert isinstance(tick_events[1]["payload"]["observed_elapsed_seconds"], float)
    assert tick_events[0]["payload"]["dispatch_failure_count"] == 0
    assert tick_events[0]["payload"]["routine_event_count"] == 3

    assert len(brownie_events) == 1
    brownie_payload = brownie_events[0]["payload"]
    assert brownie_payload["trigger_source"] == "scheduled"
    assert brownie_payload["dispatch_status"] == "success"
    assert brownie_payload["branch"] == "gold"
    assert brownie_payload["room_id"] == 71
    assert brownie_payload["target_player"] == "hero"
    assert brownie_payload["active_player_ids"] == ["hero"]
    assert brownie_payload["gold_before"] == 9
    assert brownie_payload["gold_after"] == 0
    assert brownie_payload["message_ids"] == ["BMSG00", "BMSG02", "BMSG07"]
    assert "authorization" not in brownie_payload
    assert "admin_token" not in brownie_payload

    await shutdown_app(app)


@pytest.mark.anyio
async def test_animation_npcs_only_affect_active_players(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "999")

    app = FastAPI()
    await bootstrap_app(app)
    app.state.tick_runtime.stop()

    with app.state.session_factory() as session:
        player = session.query(models.Player).first()
        assert player is not None
        player.gamloc = 50
        player.gold = 5
        player_id = player.id
        session.commit()

    app.state.animation_rng = _FixedAnimationRng(50, 7)
    app.state.animation_tick_system.state.routine_index = 1
    app.state.animation_tick_system.state.elf_reward_next = 1
    broadcasts: list[tuple[int, dict]] = []

    async def _capture(room_id: int, message: dict, sender=None, exclude=None):  # noqa: ARG001
        broadcasts.append((room_id, message))

    app.state.gateway.broadcast = _capture

    await app.state.animation_tick_callback()

    assert broadcasts == []
    with app.state.session_factory() as session:
        refreshed = session.query(models.Player).filter(models.Player.id == player_id).one()
        assert refreshed.gold == 5

    await shutdown_app(app)


@pytest.mark.anyio
async def test_animation_npcs_find_session_scoped_active_players(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "999")

    app = FastAPI()
    await bootstrap_app(app)
    app.state.tick_runtime.stop()

    with app.state.session_factory() as session:
        player = session.query(models.Player).filter(models.Player.plyrid == "hero").one()
        player.gamloc = 7
        player.pgploc = 7
        player.gold = 5
        session.commit()

    active_player = fixtures.build_player().model_copy(
        update={"gamloc": 7, "pgploc": 7, "gold": 5}
    )
    app.state.active_players = {}
    app.state.active_player_sessions = {"hero-token": active_player}
    app.state.animation_rng = _FixedAnimationRng(7, 4)
    app.state.animation_tick_system.state.routine_index = 1
    app.state.animation_tick_system.state.elf_reward_next = 1
    broadcasts: list[tuple[int, dict]] = []

    async def _capture(room_id: int, message: dict, sender=None, exclude=None):  # noqa: ARG001
        broadcasts.append((room_id, message))

    app.state.gateway.broadcast = _capture

    await app.state.animation_tick_callback()

    assert [
        event["payload"].get("message_id")
        for _, event in broadcasts
        if event.get("type") == "room_broadcast"
    ] == ["EMSG00", "EMSG02", "EMSG04"]
    assert active_player.gold == 9

    with app.state.session_factory() as session:
        refreshed = session.query(models.Player).filter(models.Player.plyrid == "hero").one()
        assert refreshed.gold == 9

    await shutdown_app(app)


@pytest.mark.anyio
async def test_animation_dispatch_keeps_target_only_payload_out_of_room_broadcast(
    monkeypatch,
):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "999")

    app = FastAPI()
    await bootstrap_app(app)
    app.state.tick_runtime.stop()

    target_socket = _FakeSocket()
    app.state.session_connections = {}
    app.state.session_connections["hero-token"] = target_socket
    await app.state.presence.set_location("hero", 7, "hero-token")
    broadcasts: list[tuple[int, dict, set | None]] = []

    async def _capture(room_id: int, message: dict, sender=None, exclude=None):  # noqa: ARG001
        broadcasts.append((room_id, message, exclude))

    app.state.gateway.broadcast = _capture

    await app.state.dispatch_animation_event(
        AnimationTickEvent(
            flag="browns",
            room_id=7,
            message_id="BMSG02",
            message_text="The brownie picks Hero's pocket.",
            payload={
                "target_player": "hero",
                "target_message_id": "BMSG01",
                "target_text": "The brownie steals all your gold!",
            },
        )
    )

    assert target_socket.sent == [
        {
            "type": "command_response",
            "room": 7,
            "payload": {
                "event": "room_message",
                "scope": "target",
                "type": "room_message",
                "message_id": "BMSG01",
                "text": "The brownie steals all your gold!",
                "animation_flag": "browns",
                "player": "hero",
            },
        }
    ]

    assert len(broadcasts) == 1
    room_id, room_message, excluded_sockets = broadcasts[0]
    assert room_id == 7
    assert target_socket in excluded_sockets
    room_payload = room_message["payload"]
    assert room_payload["message_id"] == "BMSG02"
    assert room_payload["text"] == "The brownie picks Hero's pocket."
    assert room_payload["animation_flag"] == "browns"
    assert "target_player" not in room_payload
    assert "target_message_id" not in room_payload
    assert "target_text" not in room_payload

    await shutdown_app(app)


@pytest.mark.anyio
async def test_animation_move_refresh_deduplicates_room_occupants(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "999")

    app = FastAPI()
    await bootstrap_app(app)
    app.state.tick_runtime.stop()

    target_socket = _FakeSocket()
    target_player = fixtures.build_player().model_copy(
        update={"plyrid": "hero", "altnam": "Hero", "attnam": "Hero", "gamloc": 12}
    )
    app.state.session_connections = {"hero-token": target_socket}
    app.state.active_players = {}
    app.state.active_player_sessions = {"hero-token": target_player}
    app.state.active_players["hero"] = target_player
    await app.state.presence.set_location("hero", 12, "hero-token")
    await app.state.presence.set_location("hero ", 7, "hero-stale-token")
    await app.state.presence.set_location("Necro", 7, "necro-token")
    await app.state.presence.set_location("Necro ", 7, "necro-stale-token")

    async def _capture(room_id: int, message: dict, sender=None, exclude=None):  # noqa: ARG001
        return None

    app.state.gateway.broadcast = _capture

    await app.state.dispatch_animation_event(
        AnimationTickEvent(
            flag="zarapp",
            room_id=12,
            message_id="ZMSG14",
            message_text="Zar's magic carries Hero away.",
            payload={
                "target_player": "hero",
                "target_message_id": "ZMSG13",
                "target_text": "You vanish in a flash.",
                "move_player_to": 7,
            },
        )
    )

    occupant_envelope = next(
        message
        for message in target_socket.sent
        if message.get("payload", {}).get("event") == "room_occupants"
    )
    assert occupant_envelope["payload"]["occupants"] == ["Necro"]
    assert occupant_envelope["payload"]["text"] == "Necro is here."

    await shutdown_app(app)


@pytest.mark.anyio
async def test_animation_tick_gemakr_updates_room_objects_and_broadcasts_spawn(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")

    app = FastAPI()
    await bootstrap_app(app)

    app.state.animation_rng.seed(7)
    app.state.animation_tick_system.state.routine_index = 2

    with app.state.session_factory() as session:
        location = session.query(models.Location).filter(models.Location.id == 44).one()
        location.objects = []
        location.nlobjs = 0
        session.commit()
    app.state.location_index[44] = app.state.location_index[44].model_copy(
        update={"objects": [], "nlobjs": 0}
    )

    broadcasts: list[tuple[int, dict]] = []

    async def _capture(room_id: int, message: dict, sender=None, exclude=None):
        broadcasts.append((room_id, message))

    app.state.gateway.broadcast = _capture

    await app.state.animation_tick_callback()

    spawned_room = broadcasts[0][0]
    payload = broadcasts[0][1]["payload"]
    assert 44 <= spawned_room <= 168
    assert payload["spawn_source"] == "gemakr"
    assert payload["spawned_object_id"] == 2
    assert payload["event"] == "room_objects"
    assert payload["type"] == "room_objects"
    assert payload["location"] == spawned_room
    assert payload["objects"][-1] == {"id": 2}

    with app.state.session_factory() as session:
        refreshed = session.query(models.Location).filter(models.Location.id == spawned_room).one()
        assert refreshed.objects[-1] == 2
        assert refreshed.nlobjs == len(refreshed.objects)

    await shutdown_app(app)
