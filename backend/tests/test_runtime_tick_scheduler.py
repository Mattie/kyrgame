import pytest
from fastapi import FastAPI
from starlette.websockets import WebSocketState

from kyrgame import fixtures, models
from kyrgame.runtime import bootstrap_app, shutdown_app
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
