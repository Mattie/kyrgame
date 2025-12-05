import json

import httpx
import pytest
from sqlalchemy import select

from kyrgame import fixtures, models
from kyrgame.webapp import create_app


ADMIN_MAP_ENV = "KYRGAME_ADMIN_TOKENS"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_admin_requires_roles_and_flags(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "player-token": {"roles": ["player_admin"]},
                "content-token": {"roles": ["content_admin"]},
            }
        ),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            missing_auth = await client.get("/admin/players")
            assert missing_auth.status_code == 401

            wrong_role = await client.get("/admin/players", headers=_auth("content-token"))
            assert wrong_role.status_code == 403

            forbidden_delete = await client.delete(
                "/admin/players/hero", headers=_auth("player-token")
            )
            assert forbidden_delete.status_code == 403


@pytest.mark.anyio
async def test_player_admin_crud_validates_payloads(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "player-token": {
                    "roles": ["player_admin"],
                    "flags": ["allow_delete_players", "allow_player_rename"],
                }
            }
        ),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    sample_player = fixtures.build_player().model_copy(deep=True)
    sample_player.gold += 50
    sample_player.hitpts += 1
    sample_player.altnam = "Updated Alt"

    renamed_player = sample_player.model_copy(update={"plyrid": "herox"})

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            update_resp = await client.put(
                "/admin/players/hero", headers=_auth("player-token"), json=sample_player.model_dump()
            )
            assert update_resp.status_code == 200
            updated_payload = update_resp.json()["player"]
            assert updated_payload["gold"] == sample_player.gold
            assert updated_payload["hitpts"] == sample_player.hitpts

            invalid_payload = sample_player.model_copy(update={"npobjs": 999}).model_dump()
            bad_update = await client.put(
                "/admin/players/hero", headers=_auth("player-token"), json=invalid_payload
            )
            assert bad_update.status_code == 422

            rename_resp = await client.put(
                "/admin/players/hero", headers=_auth("player-token"), json=renamed_player.model_dump()
            )
            assert rename_resp.status_code == 200
            assert rename_resp.json()["player"]["plyrid"] == "herox"

            new_player = sample_player.model_copy(
                update={
                    "plyrid": "builder",
                    "uidnam": "Builder",
                    "gpobjs": [],
                    "obvals": [],
                    "npobjs": 0,
                    "spells": [],
                    "nspells": 0,
                }
            )
            create_resp = await client.post(
                "/admin/players", headers=_auth("player-token"), json=new_player.model_dump()
            )
            assert create_resp.status_code == 201

            fetch_resp = await client.get(
                "/admin/players/builder", headers=_auth("player-token")
            )
            assert fetch_resp.status_code == 200
            assert fetch_resp.json()["player"]["plyrid"] == "builder"

            delete_resp = await client.delete(
                "/admin/players/builder", headers=_auth("player-token")
            )
            assert delete_resp.status_code == 200

            summary_resp = await client.get("/admin/fixtures", headers=_auth("player-token"))
            assert summary_resp.status_code == 200
            assert summary_resp.json()["players"] == 1


@pytest.mark.anyio
async def test_content_and_message_updates_refresh_caches(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "content-token": {
                    "roles": ["content_admin", "message_admin"],
                }
            }
        ),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    locations = fixtures.load_locations()
    target_location = locations[0]

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            invalid_location = target_location.model_copy(update={"nlobjs": target_location.nlobjs + 1})
            invalid_resp = await client.put(
                f"/admin/content/locations/{target_location.id}",
                headers=_auth("content-token"),
                json=invalid_location.model_dump(),
            )
            assert invalid_resp.status_code == 422

            updated_location = target_location.model_copy(update={"brfdes": "Edited location"})
            ok_resp = await client.put(
                f"/admin/content/locations/{target_location.id}",
                headers=_auth("content-token"),
                json=updated_location.model_dump(),
            )
            assert ok_resp.status_code == 200
            assert ok_resp.json()["location"]["brfdes"] == "Edited location"

            world_resp = await client.get("/world/locations")
            assert any(loc["brfdes"] == "Edited location" for loc in world_resp.json())

            bundle_resp = await client.get("/i18n/en-US/messages")
            assert bundle_resp.status_code == 200
            bundle_body = bundle_resp.json()
            bundle_body["messages"]["LEVEL6"] = "Edited banner"

            update_bundle = await client.put(
                "/admin/i18n/en-US",
                headers=_auth("content-token"),
                json=bundle_body,
            )
            assert update_bundle.status_code == 200

            verify_bundle = await client.get("/i18n/en-US/messages")
            assert verify_bundle.json()["messages"]["LEVEL6"] == "Edited banner"

            db = app.state.session_factory()
            try:
                row = db.scalar(select(models.Message).where(models.Message.id == "LEVEL6"))
                assert row is not None
                assert row.text == "Edited banner"
            finally:
                db.close()
