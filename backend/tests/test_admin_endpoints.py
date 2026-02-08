import json

import httpx
import pytest
from sqlalchemy import select

from kyrgame import constants, fixtures, models
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


@pytest.mark.anyio
async def test_admin_player_patch_caps_and_spouse(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "player-token": {
                    "roles": ["player_admin"],
                    "flags": ["allow_player_rename", "allow_delete_players"],
                }
            }
        ),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            patch_payload = {
                "altnam": "Admin Hero",
                "attnam": "Heroine",
                "flags": ["FEMALE", "BRFSTF"],
                "level": 5,
                "hitpts": 40,
                "spts": 20,
                "gold": 999,
                "gamloc": 12,
                "pgploc": 12,
                "spouse": "seer",
                "cap_gold": 200,
                "cap_hitpts": 18,
                "cap_spts": 9,
            }

            patch_resp = await client.patch(
                "/admin/players/hero",
                headers=_auth("player-token"),
                json=patch_payload,
            )

            assert patch_resp.status_code == 200
            payload = patch_resp.json()["player"]
            assert payload["level"] == 5
            assert payload["nmpdes"] == 4
            assert payload["hitpts"] == 18  # capped by request cap then level scaling
            assert payload["spts"] == 9
            assert payload["gold"] == 200
            assert payload["gamloc"] == 12
            assert payload["pgploc"] == 12
            assert payload["altnam"] == "Admin Hero"
            assert payload["attnam"] == "Heroine"
            assert payload["spouse"] == "seer"

            clear_resp = await client.patch(
                "/admin/players/hero",
                headers=_auth("player-token"),
                json={"clear_spouse": True, "spts": 5, "cap_spts": 2},
            )

            assert clear_resp.status_code == 200
            cleared = clear_resp.json()["player"]
            assert cleared["spouse"] == ""
            assert cleared["spts"] == 2


@pytest.mark.anyio
async def test_admin_player_patch_preserves_non_editable_flags(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "player-token": {
                    "roles": ["player_admin"],
                    "flags": ["allow_player_rename", "allow_delete_players"],
                }
            }
        ),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            current_resp = await client.get("/admin/players/hero", headers=_auth("player-token"))
            assert current_resp.status_code == 200
            current_flags = current_resp.json()["player"]["flags"]
            editable_mask = int(constants.ADMIN_EDITABLE_PLAYER_FLAGS)

            patch_resp = await client.patch(
                "/admin/players/hero",
                headers=_auth("player-token"),
                json={"flags": ["BRFSTF"]},
            )

            assert patch_resp.status_code == 200
            updated_flags = patch_resp.json()["player"]["flags"]
            expected_flags = (current_flags & ~editable_mask) | constants.encode_player_flags(
                ["BRFSTF"]
            )
            assert updated_flags == expected_flags


@pytest.mark.anyio
async def test_admin_player_patch_inventory_and_gems(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "player-token": {
                    "roles": ["player_admin"],
                }
            }
        ),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    objects = fixtures.load_objects()
    object_names = [obj.name for obj in objects]

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            grow_resp = await client.patch(
                "/admin/players/hero",
                headers=_auth("player-token"),
                json={"npobjs": 3},
            )
            assert grow_resp.status_code == 200
            grown = grow_resp.json()["player"]
            assert grown["npobjs"] == 3
            assert grown["gpobjs"][-1] == 2
            assert len(grown["obvals"]) == 3
            assert grown["obvals"][-1] == 0

            slot_payload = {
                "gpobjs": [
                    object_names[0],
                    objects[1].id,
                    None,
                    None,
                    None,
                    None,
                ],
                "stones": [
                    objects[0].id,
                    objects[1].name,
                    objects[2].id,
                    objects[3].name,
                ],
                "gemidx": 2,
                "stumpi": 5,
            }
            slot_resp = await client.patch(
                "/admin/players/hero",
                headers=_auth("player-token"),
                json=slot_payload,
            )
            assert slot_resp.status_code == 200
            slotted = slot_resp.json()["player"]
            assert slotted["gpobjs"] == [objects[0].id, objects[1].id]
            assert slotted["npobjs"] == 2
            assert slotted["stones"] == [
                objects[0].id,
                objects[1].id,
                objects[2].id,
                objects[3].id,
            ]
            assert slotted["gemidx"] == 2
            assert slotted["stumpi"] == 5

            invalid_resp = await client.patch(
                "/admin/players/hero",
                headers=_auth("player-token"),
                json={"gpobjs": [object_names[0], None, "not-a-real-object"]},
            )
            assert invalid_resp.status_code == 422

            too_many = await client.patch(
                "/admin/players/hero",
                headers=_auth("player-token"),
                json={"npobjs": constants.MXPOBS + 1},
            )
            assert too_many.status_code == 422


@pytest.mark.anyio
async def test_admin_player_patch_charms(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "player-token": {
                    "roles": ["player_admin"],
                }
            }
        ),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            update_resp = await client.patch(
                "/admin/players/hero",
                headers=_auth("player-token"),
                json={"charms": [0, 0, 0, 0, 7, 0]},
            )
            assert update_resp.status_code == 200
            updated = update_resp.json()["player"]
            assert updated["charms"] == [0, 0, 0, 0, 7, 0]

            invalid_resp = await client.patch(
                "/admin/players/hero",
                headers=_auth("player-token"),
                json={"charms": [1, 2]},
            )
            assert invalid_resp.status_code == 422


@pytest.mark.anyio
async def test_admin_player_patch_grants_all_spells(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "player-token": {
                    "roles": ["player_admin"],
                }
            }
        ),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    spells = fixtures.load_spells()
    expected_off = 0
    expected_def = 0
    expected_oth = 0
    for spell in spells:
        if spell.sbkref == constants.OFFENS:
            expected_off |= spell.bitdef
        elif spell.sbkref == constants.DEFENS:
            expected_def |= spell.bitdef
        else:
            expected_oth |= spell.bitdef

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            update_resp = await client.patch(
                "/admin/players/hero",
                headers=_auth("player-token"),
                json={"grant_all_spells": True},
            )
            assert update_resp.status_code == 200
            updated = update_resp.json()["player"]
            assert updated["offspls"] == expected_off
            assert updated["defspls"] == expected_def
            assert updated["othspls"] == expected_oth
