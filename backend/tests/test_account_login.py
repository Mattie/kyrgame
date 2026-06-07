import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from starlette.websockets import WebSocketState

from kyrgame import models, repositories
from kyrgame.webapp import _load_account_admin_grants, _publish_scry_event, create_app


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class DummyScrySocket:
    application_state = WebSocketState.CONNECTED

    def __init__(self):
        self.messages: list[dict] = []

    async def send_json(self, payload: dict):
        self.messages.append(payload)


@pytest.fixture()
def account_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path/'account-login.db'}")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    monkeypatch.setenv("KYRGAME_TELEMETRY_DIR", str(tmp_path / "telemetry"))


@pytest.mark.anyio
async def test_register_creates_account_bound_to_first_login_player(account_env):
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/auth/register",
                json={"userid": "Willow", "password": "correct horse battery staple"},
            )

        assert response.status_code == 201
        session = response.json()["session"]
        assert session["player_id"] == "Willow"
        assert session["account_userid"] == "Willow"
        assert session["session_kind"] == "game"
        assert session["first_login"] is True
        assert session["lifecycle"] == {"state": "first_login_intro", "step": 2}
        assert [message["message_id"] for message in session["lifecycle_messages"]] == ["GOODPD"]

        with app.state.session_factory() as db:
            account = db.scalar(select(models.Account).where(models.Account.userid_norm == "willow"))
            player = db.scalar(select(models.Player).where(models.Player.plyrid == "Willow"))

        assert account is not None
        assert player is not None
        assert account.player_id == player.id
        assert account.password_hash != "correct horse battery staple"
        assert account.password_hash.startswith("$argon2")


@pytest.mark.anyio
async def test_login_reuses_account_character_without_manual_relink(account_env):
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            registered = await client.post(
                "/auth/register",
                json={"userid": "Mender", "password": "correct horse battery staple"},
            )
            first_token = registered.json()["session"]["token"]

            logged_in = await client.post(
                "/auth/login",
                json={"userid": "mender", "password": "correct horse battery staple"},
            )

        assert logged_in.status_code == 201
        session = logged_in.json()["session"]
        assert session["player_id"] == "Mender"
        assert session["account_userid"] == "Mender"
        assert session["token"] != first_token
        assert session["replaced_sessions"] == 1
        assert session["lifecycle"] == {"state": "first_login_intro", "step": 2}


@pytest.mark.anyio
async def test_account_login_honors_room_override_after_pending_intro(account_env):
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            registered = await client.post(
                "/auth/register",
                json={"userid": "Raven", "password": "correct horse battery staple"},
            )

            with app.state.session_factory() as db:
                player = db.scalar(select(models.Player).where(models.Player.plyrid == "Raven"))
                assert player is not None
                repositories.PlayerSessionRepository(db).deactivate_all(
                    player.id, session_kind="game"
                )
                db.commit()

            logged_in = await client.post(
                "/auth/login",
                json={
                    "userid": "raven",
                    "password": "correct horse battery staple",
                    "room_id": 7,
                },
            )

        assert registered.status_code == 201
        assert logged_in.status_code == 201
        session = logged_in.json()["session"]
        assert session["player_id"] == "Raven"
        assert session["room_id"] == 7
        assert session["lifecycle"] is None


@pytest.mark.anyio
async def test_admin_login_uses_yaml_allowlist_and_stays_out_of_public_activity(
    monkeypatch, tmp_path, account_env
):
    allowlist_path = tmp_path / "admin-allowlist.yaml"
    allowlist_path.write_text(
        """
admins:
  opal:
    roles: [player_admin, content_admin]
    flags: [allow_delete_players]
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("KYRGAME_ADMIN_ALLOWLIST_PATH", str(allowlist_path))

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            registered = await client.post(
                "/auth/register",
                json={
                    "userid": "Opal",
                    "password": "correct horse battery staple",
                    "session_kind": "admin",
                },
            )
            token = registered.json()["session"]["token"]
            admin_resp = await client.get("/admin/players", headers=_auth(token))
            activity_resp = await client.get("/public/player-activity")

        assert registered.status_code == 201
        session = registered.json()["session"]
        assert session["account_userid"] == "Opal"
        assert session["session_kind"] == "admin"
        assert session["admin_grants"] == {
            "roles": ["content_admin", "player_admin"],
            "flags": ["allow_delete_players"],
        }
        assert admin_resp.status_code == 200
        assert activity_resp.status_code == 200
        payload = activity_resp.json()
        assert "Opal" not in [player["player_id"] for player in payload["active"]]
        assert "Opal" not in [player["player_id"] for player in payload["recent"]]


@pytest.mark.anyio
async def test_allowlisted_game_session_token_cannot_use_admin_endpoints(
    monkeypatch, tmp_path, account_env
):
    allowlist_path = tmp_path / "admin-allowlist.yaml"
    allowlist_path.write_text(
        """
admins:
  opal:
    roles: [player_admin]
    flags: [allow_delete_players]
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("KYRGAME_ADMIN_ALLOWLIST_PATH", str(allowlist_path))

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            registered = await client.post(
                "/auth/register",
                json={
                    "userid": "Opal",
                    "password": "correct horse battery staple",
                    "session_kind": "game",
                },
            )
            token = registered.json()["session"]["token"]
            admin_resp = await client.get("/admin/players", headers=_auth(token))

        assert registered.status_code == 201
        assert registered.json()["session"]["session_kind"] == "game"
        assert registered.json()["session"]["admin_grants"] == {"roles": [], "flags": []}
        assert admin_resp.status_code == 403


@pytest.mark.anyio
async def test_non_allowlisted_admin_login_cannot_use_admin_endpoints(account_env):
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            registered = await client.post(
                "/auth/register",
                json={
                    "userid": "Visitor",
                    "password": "correct horse battery staple",
                    "session_kind": "admin",
                },
            )
            token = registered.json()["session"]["token"]
            admin_resp = await client.get("/admin/players", headers=_auth(token))

        assert registered.status_code == 201
        assert registered.json()["session"]["admin_grants"] == {"roles": [], "flags": []}
        assert admin_resp.status_code == 403


def test_admin_allowlist_filters_non_string_roles_and_flags(monkeypatch, tmp_path):
    allowlist_path = tmp_path / "admin-allowlist.yaml"
    allowlist_path.write_text(
        """
admins:
  Opal:
    roles:
      - player_admin
      - {bad: value}
      - 42
      - " content_admin "
    flags: allow_delete_players
  Broken:
    roles:
      nested: value
    flags:
      - [bad]
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("KYRGAME_ADMIN_ALLOWLIST_PATH", str(allowlist_path))

    grants = _load_account_admin_grants()

    assert grants["opal"].roles == {"player_admin", "content_admin"}
    assert grants["opal"].flags == {"allow_delete_players"}
    assert grants["broken"].roles == set()
    assert grants["broken"].flags == set()


@pytest.mark.anyio
async def test_telemetry_records_player_input_output_events(monkeypatch, tmp_path, account_env):
    from kyrgame.telemetry import TelemetryEventSink

    monkeypatch.setenv("KYRGAME_TELEMETRY_DIR", str(tmp_path / "telemetry"))
    sink = TelemetryEventSink.from_env()

    await sink.record(
        userid="Hero/../../bad",
        event_type="input",
        payload={"command": "look", "password": "must-not-log"},
    )
    await sink.record(
        userid="Hero/../../bad",
        event_type="output",
        payload={"type": "command_response", "summary": "You are here."},
    )

    log_files = sorted((tmp_path / "telemetry").rglob("*.jsonl"))
    assert len(log_files) == 1
    assert log_files[0].name == "hero_bad.jsonl"
    lines = [json.loads(line) for line in log_files[0].read_text(encoding="utf-8").splitlines()]
    assert [line["event_type"] for line in lines] == ["input", "output"]
    assert lines[0]["payload"] == {"command": "look"}


@pytest.mark.anyio
async def test_telemetry_record_offloads_disk_write_to_worker_thread(monkeypatch, tmp_path):
    from kyrgame import telemetry
    from kyrgame.telemetry import TelemetryEventSink

    to_thread_calls = []

    async def fake_to_thread(func, *args, **kwargs):
        to_thread_calls.append((func, args, kwargs))
        return func(*args, **kwargs)

    monkeypatch.setattr(telemetry, "asyncio", SimpleNamespace(to_thread=fake_to_thread), raising=False)
    sink = TelemetryEventSink(tmp_path / "telemetry")

    await sink.record(userid="Hero", event_type="input", payload={"command": "look"})

    assert len(to_thread_calls) == 1
    log_file = tmp_path / "telemetry" / "hero.jsonl"
    assert log_file.exists()


@pytest.mark.anyio
async def test_scry_publish_streams_to_matching_subscribers(account_env):
    app = create_app()
    hero_socket = DummyScrySocket()
    other_socket = DummyScrySocket()
    app.state.scry_subscribers = {
        "Hero": {hero_socket},
        "Other": {other_socket},
    }

    await _publish_scry_event(app, "Hero", {"direction": "output", "type": "room_welcome"})

    assert hero_socket.messages == [
        {
            "type": "scry_event",
            "player_id": "Hero",
            "event": {"direction": "output", "type": "room_welcome"},
        }
    ]
    assert other_socket.messages == []
