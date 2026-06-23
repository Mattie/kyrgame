import json

import httpx
import pytest
from sqlalchemy import select
from starlette.websockets import WebSocketState

from kyrgame import constants, fixtures, models
from kyrgame.webapp import create_app


ADMIN_MAP_ENV = "KYRGAME_ADMIN_TOKENS"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _FakeSocket:
    application_state = WebSocketState.CONNECTED

    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, message: dict):
        self.sent.append(message)


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
async def test_admin_player_routes_resolve_original_uid_alias(monkeypatch):
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
    alias = "Testaccountid"
    canonical = "Tester"

    async with app.router.lifespan_context(app):
        db = app.state.session_factory()
        try:
            player = fixtures.build_player().model_copy(
                update={
                    "uidnam": alias,
                    "plyrid": canonical,
                    "altnam": canonical,
                    "attnam": canonical,
                }
            )
            db.add(models.Player(**player.model_dump()))
            db.commit()
        finally:
            db.close()

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            alias_fetch = await client.get(
                f"/admin/players/{alias}",
                headers=_auth("player-token"),
            )
            assert alias_fetch.status_code == 200
            player = alias_fetch.json()["player"]
            assert player["plyrid"] == canonical
            assert player["uidnam"] == alias

            patch_resp = await client.patch(
                f"/admin/players/{alias}",
                headers=_auth("player-token"),
                json={"gold": 321},
            )
            assert patch_resp.status_code == 200
            assert patch_resp.json()["player"]["gold"] == 321

            replacement = patch_resp.json()["player"]
            replacement["gold"] = 432
            put_resp = await client.put(
                f"/admin/players/{alias}",
                headers=_auth("player-token"),
                json=replacement,
            )
            assert put_resp.status_code == 200
            assert put_resp.json()["player"]["gold"] == 432

            canonical_fetch = await client.get(
                f"/admin/players/{canonical}",
                headers=_auth("player-token"),
            )
            assert canonical_fetch.status_code == 200
            assert canonical_fetch.json()["player"]["gold"] == 432


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
async def test_admin_player_patch_updates_stored_honor_mode(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps({"player-token": {"roles": ["player_admin"]}}),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            patch_resp = await client.patch(
                "/admin/players/hero",
                headers=_auth("player-token"),
                json={"honor_mode": False},
            )
            fetch_resp = await client.get("/admin/players/hero", headers=_auth("player-token"))

        assert patch_resp.status_code == 200
        assert patch_resp.json()["player"]["honor_mode"] is False
        assert patch_resp.json()["player"]["effective_honor_mode"] is False
        assert fetch_resp.json()["player"]["honor_mode"] is False

        with app.state.session_factory() as db:
            player = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
            assert player is not None
            assert player.honor_mode is False


@pytest.mark.anyio
async def test_admin_player_patch_syncs_active_player_honor_mode(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps({"player-token": {"roles": ["player_admin"]}}),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        active_player = fixtures.build_player().model_copy(
            update={"plyrid": "hero", "honor_mode": True},
            deep=True,
        )
        app.state.active_players["hero"] = active_player
        app.state.active_player_sessions["token"] = active_player
        app.state.room_scripts.players["hero"] = active_player

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            patch_resp = await client.patch(
                "/admin/players/hero",
                headers=_auth("player-token"),
                json={"honor_mode": False},
            )

        assert patch_resp.status_code == 200
        assert active_player.honor_mode is False
        assert app.state.active_players["hero"] is active_player
        assert app.state.room_scripts.players["hero"] is active_player
        assert app.state.room_scripts.players["hero"].honor_mode is False


@pytest.mark.anyio
async def test_admin_player_rename_syncs_active_player_aliases(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "player-token": {
                    "roles": ["player_admin"],
                    "flags": ["allow_player_rename"],
                }
            }
        ),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        active_player = fixtures.build_player().model_copy(
            update={"plyrid": "hero", "gold": 12},
            deep=True,
        )
        app.state.active_players["hero"] = active_player
        app.state.active_player_sessions["token"] = active_player
        app.state.room_scripts.players["hero"] = active_player
        active_socket = _FakeSocket()
        app.state.session_connections["token"] = active_socket
        app.state.game_socket_players[active_socket] = "hero"
        await app.state.presence.set_location("hero", active_player.gamloc, "token")

        replacement = active_player.model_copy(
            update={"plyrid": "herox", "gold": 77},
            deep=True,
        )

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            rename_resp = await client.put(
                "/admin/players/hero",
                headers=_auth("player-token"),
                json=replacement.model_dump(),
            )

        assert rename_resp.status_code == 200
        assert active_player.plyrid == "herox"
        assert active_player.gold == 77
        assert "hero" not in app.state.active_players
        assert app.state.active_players["herox"] is active_player
        assert app.state.active_player_sessions["token"] is active_player
        assert app.state.game_socket_players[active_socket] == "herox"
        assert "hero" not in app.state.room_scripts.players
        assert app.state.room_scripts.players["herox"] is active_player
        assert await app.state.presence.sessions_for_player("hero") == set()
        assert await app.state.presence.sessions_for_player("herox") == {"token"}
        assert await app.state.presence.players_in_room(active_player.gamloc) == {"herox"}


@pytest.mark.anyio
async def test_admin_staged_honor_mode_is_effectively_forced_by_runtime_flag(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps({"player-token": {"roles": ["player_admin"]}}),
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path/'admin-force.db'}")
    monkeypatch.setenv("KYRGAME_RUN_MIGRATIONS", "0")
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1000")
    monkeypatch.setenv("KYRGAME_FORCE_HONOR_MODE", "1")

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            patch_resp = await client.patch(
                "/admin/players/hero",
                headers=_auth("player-token"),
                json={"honor_mode": False},
            )

        assert patch_resp.status_code == 200
        assert patch_resp.json()["player"]["honor_mode"] is False
        assert patch_resp.json()["player"]["effective_honor_mode"] is True

        with app.state.session_factory() as db:
            player = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
            assert player is not None
            assert player.honor_mode is False


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
            assert updated["level"] == 25
            assert updated["spts"] == 50


@pytest.mark.anyio
async def test_admin_mob_tracker_reports_legacy_animation_state(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "content-token": {
                    "roles": ["content_admin"],
                }
            }
        ),
    )
    monkeypatch.setenv("KYRGAME_TICK_SECONDS", "1.0")

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        app.state.tick_runtime.stop()
        state = app.state.animation_tick_system.state
        state.routine_index = 5
        state.dryad_location = 18
        state.brownie_location = 0
        state.brownie_path_index = 19
        state.elf_last_room = 52
        state.elf_reward_next = 1
        state.elf_hint_index = 4
        state.gem_counter = 7
        state.gem_last_attempt_room_id = 167
        state.gem_last_attempt_status = "spawned"
        state.gem_last_attempt_object_count = 2
        state.gem_last_spawn_room_id = 167
        state.gem_last_spawn_object_id = 11
        state.gem_last_spawn_object_name = "bloodstone"
        state.zar_location = 250
        state.zar_counter = 8
        state.zar_attack_index = 2
        app.state.location_index[302] = app.state.location_index[302].model_copy(
            update={"objects": [], "nlobjs": 0}
        )
        app.state.location_index[250] = app.state.location_index[250].model_copy(
            update={"objects": [52], "nlobjs": 1}
        )
        app.state.location_index[0] = app.state.location_index[0].model_copy(
            update={
                "objects": [obj for obj in app.state.location_index[0].objects if obj != 45],
                "nlobjs": len([obj for obj in app.state.location_index[0].objects if obj != 45]),
            }
        )
        room_18_objects = [*app.state.location_index[18].objects, 45]
        app.state.location_index[18] = app.state.location_index[18].model_copy(
            update={"objects": room_18_objects, "nlobjs": len(room_18_objects)}
        )
        room_19_objects = [*app.state.location_index[19].objects, 45]
        app.state.location_index[19] = app.state.location_index[19].model_copy(
            update={"objects": room_19_objects, "nlobjs": len(room_19_objects)}
        )
        app.state.location_index[251] = app.state.location_index[251].model_copy(
            update={"objects": [52], "nlobjs": 1}
        )

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            missing_auth = await client.get("/admin/mobs")
            assert missing_auth.status_code == 401

            resp = await client.get("/admin/mobs", headers=_auth("content-token"))

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["animation"]["next_routine"] == "browns"
        assert payload["animation"]["animation_tick_interval_seconds"] == 15.0
        assert payload["animation"]["brownie_routine_interval_seconds"] == 90.0
        assert payload["animation"]["brownie_full_path_interval_seconds"] == 3600.0
        assert payload["animation"]["gem_spawn_interval_seconds"] == 90.0
        assert payload["animation"]["next_gem_spawn_attempt_seconds"] == 60.0
        assert payload["animation"]["gem_counter"] == 7
        assert payload["animation"]["successful_spawns_until_random_gem"] == 4
        assert payload["animation"]["next_successful_gem_is_random"] is False
        assert payload["animation"]["last_gem_attempt_room_id"] == 167
        assert payload["animation"]["last_gem_attempt_status"] == "spawned"
        assert payload["animation"]["last_gem_attempt_object_count"] == 2
        assert payload["animation"]["last_gem_spawn_room_id"] == 167
        assert payload["animation"]["last_gem_spawn_object_id"] == 11
        assert payload["animation"]["last_gem_spawn_object_name"] == "bloodstone"

        mobs = {mob["id"]: mob for mob in payload["mobs"]}
        assert mobs["dryad"]["room_id"] == 18
        assert mobs["dryad"]["room"]["brief"] == app.state.location_index[18].brfdes
        assert mobs["dryad"]["tracker_room_id"] == 18
        assert mobs["dryad"]["object_rooms"] == [18, 19]
        assert mobs["dryad"]["copy_count"] == 2
        assert mobs["dryad"]["singleton_status"] == "duplicate"
        assert mobs["brownie"]["room_id"] == 0
        assert mobs["brownie"]["room"]["brief"] == "near a mystical willow tree"
        assert mobs["brownie"]["path_index"] == 19
        assert mobs["brownie"]["next_room_id"] == 129
        assert mobs["brownie"]["path_length"] == 40
        assert mobs["elf"]["room_id"] == 52
        assert mobs["elf"]["status"] == "last_seen"
        assert mobs["dragon"]["room_id"] == 250
        assert mobs["dragon"]["state_room_id"] == 250
        assert mobs["dragon"]["tracker_room_id"] == 250
        assert mobs["dragon"]["object_rooms"] == [250, 251]
        assert mobs["dragon"]["copy_count"] == 2
        assert mobs["dragon"]["singleton_status"] == "duplicate"
        assert mobs["dragon"]["counter"] == 8
        assert mobs["dragon"]["attack_index"] == 2
        assert mobs["dragon"]["next_attack"] == "claw"
        assert mobs["dragon"]["home_room_id"] == 302
        assert mobs["gem_spawner"]["status"] == "waiting"
        assert mobs["gem_spawner"]["room_id"] == 167
        assert mobs["gem_spawner"]["room"]["brief"] == app.state.location_index[167].brfdes
        assert mobs["gem_spawner"]["gem_counter"] == 7
        assert mobs["gem_spawner"]["next_attempt_seconds"] == 60.0
        assert mobs["gem_spawner"]["successful_spawns_until_random_gem"] == 4
        assert mobs["gem_spawner"]["last_attempt_room_id"] == 167
        assert mobs["gem_spawner"]["last_attempt_status"] == "spawned"
        assert mobs["gem_spawner"]["last_attempt_object_count"] == 2
        assert mobs["gem_spawner"]["last_spawn_room_id"] == 167
        assert mobs["gem_spawner"]["last_spawn_object_id"] == 11
        assert mobs["gem_spawner"]["last_spawn_object_name"] == "bloodstone"


@pytest.mark.anyio
async def test_admin_mob_tracker_keeps_object_room_display_during_tracker_drift(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps({"content-token": {"roles": ["content_admin"]}}),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        app.state.tick_runtime.stop()
        state = app.state.animation_tick_system.state
        state.dryad_location = 18
        state.zar_location = 250
        for room_id, location in list(app.state.location_index.items()):
            objects = [
                object_id for object_id in location.objects if object_id not in {45, 52}
            ]
            if objects != location.objects:
                app.state.location_index[room_id] = location.model_copy(
                    update={"objects": objects, "nlobjs": len(objects)}
                )
        app.state.location_index[0] = app.state.location_index[0].model_copy(
            update={"objects": [45], "nlobjs": 1}
        )
        app.state.location_index[251] = app.state.location_index[251].model_copy(
            update={"objects": [52], "nlobjs": 1}
        )

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/admin/mobs", headers=_auth("content-token"))

        assert resp.status_code == 200
        mobs = {mob["id"]: mob for mob in resp.json()["mobs"]}
        assert mobs["dryad"]["room_id"] == 0
        assert mobs["dryad"]["room"]["brief"] == app.state.location_index[0].brfdes
        assert mobs["dryad"]["object_room_id"] == 0
        assert mobs["dryad"]["tracker_room_id"] == 18
        assert mobs["dryad"]["singleton_status"] == "tracker_mismatch"
        assert mobs["dragon"]["room_id"] == 251
        assert mobs["dragon"]["room"]["brief"] == app.state.location_index[251].brfdes
        assert mobs["dragon"]["object_room_id"] == 251
        assert mobs["dragon"]["tracker_room_id"] == 250
        assert mobs["dragon"]["singleton_status"] == "tracker_mismatch"


@pytest.mark.anyio
async def test_admin_mob_tracker_keeps_last_gem_spawn_after_capacity_skip(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "content-token": {
                    "roles": ["content_admin"],
                }
            }
        ),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        app.state.tick_runtime.stop()
        state = app.state.animation_tick_system.state
        state.gem_counter = 7
        state.gem_last_attempt_room_id = 51
        state.gem_last_attempt_status = "skipped_capacity"
        state.gem_last_attempt_object_count = 4
        state.gem_last_spawn_room_id = 167
        state.gem_last_spawn_object_id = 11
        state.gem_last_spawn_object_name = "bloodstone"

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/admin/mobs", headers=_auth("content-token"))

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["animation"]["last_gem_attempt_status"] == "skipped_capacity"
        assert payload["animation"]["last_gem_attempt_room_id"] == 51
        assert payload["animation"]["last_gem_attempt_object_count"] == 4
        assert payload["animation"]["last_gem_spawn_room_id"] == 167
        assert payload["animation"]["last_gem_spawn_object_name"] == "bloodstone"

        gem_spawner = {mob["id"]: mob for mob in payload["mobs"]}["gem_spawner"]
        assert gem_spawner["room_id"] == 167
        assert gem_spawner["room"]["brief"] == app.state.location_index[167].brfdes
        assert gem_spawner["last_attempt_status"] == "skipped_capacity"
        assert gem_spawner["last_attempt_room_id"] == 51
        assert gem_spawner["last_attempt_object_count"] == 4
        assert gem_spawner["last_spawn_room_id"] == 167
        assert gem_spawner["last_spawn_object_name"] == "bloodstone"


@pytest.mark.anyio
async def test_admin_drop_item_requires_admin_and_validates_room_capacity(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "content-token": {
                    "roles": ["content_admin"],
                },
                "player-token": {
                    "roles": ["player_admin"],
                }
            }
        ),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        app.state.tick_runtime.stop()
        full_room_objects = [0, 2, 3, 4, 5, 6]
        with app.state.session_factory() as db:
            location = db.get(models.Location, 7)
            assert location is not None
            location.objects = list(full_room_objects)
            location.nlobjs = len(full_room_objects)
            db.commit()

        app.state.location_index[7] = app.state.location_index[7].model_copy(
            update={"objects": list(full_room_objects), "nlobjs": len(full_room_objects)}
        )

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            missing_auth = await client.post(
                "/admin/rooms/7/objects/drop",
                json={"object_ref": "emerald"},
            )
            missing_room = await client.post(
                "/admin/rooms/9999/objects/drop",
                headers=_auth("content-token"),
                json={"object_ref": "emerald"},
            )
            full_room = await client.post(
                "/admin/rooms/7/objects/drop",
                headers=_auth("content-token"),
                json={"object_ref": "emerald"},
            )

        assert missing_auth.status_code == 401
        assert missing_room.status_code == 404
        assert full_room.status_code == 409
        assert "room is full" in full_room.text.lower()

        with app.state.session_factory() as db:
            refreshed = db.get(models.Location, 7)
            assert refreshed is not None
            assert refreshed.objects == full_room_objects
            assert refreshed.nlobjs == len(full_room_objects)
        assert app.state.location_index[7].objects == full_room_objects


@pytest.mark.anyio
async def test_admin_drop_item_resolves_object_id_and_rejects_missing_object(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "content-token": {
                    "roles": ["content_admin"],
                }
            }
        ),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        app.state.tick_runtime.stop()
        with app.state.session_factory() as db:
            location = db.get(models.Location, 7)
            assert location is not None
            location.objects = []
            location.nlobjs = 0
            db.commit()

        app.state.location_index[7] = app.state.location_index[7].model_copy(
            update={"objects": [], "nlobjs": 0}
        )

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            from_id = await client.post(
                "/admin/rooms/7/objects/drop",
                headers=_auth("content-token"),
                json={"object_ref": 1},
            )
            missing_object = await client.post(
                "/admin/rooms/7/objects/drop",
                headers=_auth("content-token"),
                json={"object_ref": "missing catalog item"},
            )
            singleton_mob = await client.post(
                "/admin/rooms/7/objects/drop",
                headers=_auth("content-token"),
                json={"object_ref": "dryad"},
            )

        assert from_id.status_code == 200
        assert from_id.json()["object"] == {"id": 1, "name": "emerald"}
        assert missing_object.status_code == 422
        assert "catalog object" in missing_object.text
        assert singleton_mob.status_code == 409
        assert "moving mob singleton" in singleton_mob.text.lower()

        with app.state.session_factory() as db:
            refreshed = db.get(models.Location, 7)
            assert refreshed is not None
            assert refreshed.objects == [1]
            assert refreshed.nlobjs == 1
        assert app.state.location_index[7].objects == [1]


@pytest.mark.anyio
async def test_admin_room_objects_lists_hidden_mobs_and_deletes_one_slot(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "content-token": {
                    "roles": ["content_admin"],
                },
                "player-token": {
                    "roles": ["player_admin"],
                }
            }
        ),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        app.state.tick_runtime.stop()
        room_objects = [51, 52, 1]
        with app.state.session_factory() as db:
            location = db.get(models.Location, 7)
            assert location is not None
            location.objects = list(room_objects)
            location.nlobjs = len(room_objects)
            db.commit()

        app.state.location_index[7] = app.state.location_index[7].model_copy(
            update={"objects": list(room_objects), "nlobjs": len(room_objects)}
        )
        broadcasts: list[tuple[int, dict, set | None]] = []

        async def _capture(room_id: int, message: dict, sender=None, exclude=None):  # noqa: ARG001
            broadcasts.append((room_id, message, exclude))
            return []

        app.state.gateway.broadcast = _capture

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            missing_auth = await client.get("/admin/rooms/7/objects")
            listed = await client.get(
                "/admin/rooms/7/objects",
                headers=_auth("content-token"),
            )
            missing_expected_object = await client.delete(
                "/admin/rooms/7/objects/1",
                headers=_auth("content-token"),
            )
            stale_delete = await client.delete(
                "/admin/rooms/7/objects/1?expected_object_id=51",
                headers=_auth("content-token"),
            )
            deleted = await client.delete(
                "/admin/rooms/7/objects/1?expected_object_id=52",
                headers=_auth("player-token"),
            )
            missing_slot = await client.delete(
                "/admin/rooms/7/objects/9?expected_object_id=51",
                headers=_auth("content-token"),
            )

        assert missing_auth.status_code == 401
        assert listed.status_code == 200
        assert listed.json()["room_objects"] == [
            {"id": 51, "name": "machine"},
            {"id": 52, "name": "dragon"},
            {"id": 1, "name": "emerald"},
        ]
        assert missing_expected_object.status_code == 422

        assert deleted.status_code == 200
        delete_payload = deleted.json()
        assert delete_payload["status"] == "deleted"
        assert delete_payload["slot_index"] == 1
        assert delete_payload["object"] == {"id": 52, "name": "dragon"}
        assert delete_payload["room_objects"] == [
            {"id": 51, "name": "machine"},
            {"id": 1, "name": "emerald"},
        ]
        assert delete_payload["announcement"] == {
            "message_id": None,
            "modeled_after_spell": "mower",
            "text": "***\rThe dragon at the village temple vanishes!\r",
        }
        assert stale_delete.status_code == 409
        assert "room object slot changed" in stale_delete.text.lower()

        assert missing_slot.status_code == 404
        with app.state.session_factory() as db:
            refreshed = db.get(models.Location, 7)
            assert refreshed is not None
            assert refreshed.objects == [51, 1]
            assert refreshed.nlobjs == 2
        assert app.state.location_index[7].objects == [51, 1]

        assert [room_id for room_id, _, _ in broadcasts] == [7, 7]
        assert broadcasts[0][1]["payload"] == {
            "scope": "room",
            "event": "room_message",
            "type": "room_message",
            "message_id": None,
            "text": "***\rThe dragon at the village temple vanishes!\r",
            "source": "admin_delete_item",
            "modeled_after_spell": "mower",
            "object_id": 52,
            "object_name": "dragon",
            "location": 7,
        }
        assert broadcasts[1][1]["payload"]["event"] == "room_objects"
        assert broadcasts[1][1]["payload"]["include_sender"] is True
        assert broadcasts[1][1]["payload"]["objects"] == [
            {"id": 51, "name": "machine"},
            {"id": 1, "name": "emerald"},
        ]


@pytest.mark.anyio
async def test_admin_drop_item_persists_and_broadcasts_live_room_objects(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "content-token": {
                    "roles": ["content_admin"],
                }
            }
        ),
    )

    class _FailingTelemetrySink:
        async def record_system(self, *, event_type, payload):  # noqa: ARG002
            raise OSError("telemetry path unavailable")

    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with app.router.lifespan_context(app):
        app.state.tick_runtime.stop()
        with app.state.session_factory() as db:
            location = db.get(models.Location, 7)
            assert location is not None
            location.objects = []
            location.nlobjs = 0
            db.commit()

        app.state.location_index[7] = app.state.location_index[7].model_copy(
            update={"objects": [], "nlobjs": 0}
        )
        app.state.telemetry_sink = _FailingTelemetrySink()
        broadcasts: list[tuple[int, dict, set | None]] = []

        async def _capture(room_id: int, message: dict, sender=None, exclude=None):  # noqa: ARG001
            broadcasts.append((room_id, message, exclude))
            return []

        app.state.gateway.broadcast = _capture

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/admin/rooms/7/objects/drop",
                headers=_auth("content-token"),
                json={"object_ref": "emerald"},
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "dropped"
        assert payload["room_id"] == 7
        assert payload["object"] == {"id": 1, "name": "emerald"}
        assert payload["room_objects"] == [{"id": 1, "name": "emerald"}]
        assert payload["announcement"] == {
            "message_id": None,
            "modeled_after_message_id": "ASHM01",
            "text": "***\r\nAn emerald suddenly appears near the altar!",
        }

        with app.state.session_factory() as db:
            refreshed = db.get(models.Location, 7)
            assert refreshed is not None
            assert refreshed.objects == [1]
            assert refreshed.nlobjs == 1
        assert app.state.location_index[7].objects == [1]
        cached_location = next(
            location for location in app.state.fixture_cache["locations"] if location.id == 7
        )
        assert cached_location.objects == [1]

        assert [room_id for room_id, _, _ in broadcasts] == [7, 7]
        assert broadcasts[0][1]["payload"] == {
            "scope": "room",
            "event": "room_message",
            "type": "room_message",
            "message_id": None,
            "text": "***\r\nAn emerald suddenly appears near the altar!",
            "source": "admin_drop_item",
            "modeled_after_message_id": "ASHM01",
            "object_id": 1,
            "object_name": "emerald",
            "location": 7,
        }
        assert broadcasts[1][1]["payload"]["event"] == "room_objects"
        assert broadcasts[1][1]["payload"]["include_sender"] is True
        assert broadcasts[1][1]["payload"]["objects"] == [{"id": 1, "name": "emerald"}]


@pytest.mark.anyio
async def test_admin_elf_trigger_requires_admin_and_active_player(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "content-token": {
                    "roles": ["content_admin"],
                }
            }
        ),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        app.state.tick_runtime.stop()
        original_state = app.state.animation_tick_system.state
        original_state.elf_last_room = None
        original_state.elf_reward_next = 0
        original_state.elf_hint_index = 0

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            missing_auth = await client.post(
                "/admin/mobs/elf/trigger",
                json={"player_id": "hero", "room_id": 7},
            )
            assert missing_auth.status_code == 401

            no_player = await client.post(
                "/admin/mobs/elf/trigger",
                headers=_auth("content-token"),
                json={"player_id": "hero", "room_id": 7},
            )

        assert no_player.status_code == 200
        assert no_player.json()["status"] == "no_active_player"
        assert original_state.elf_last_room is None
        assert original_state.elf_reward_next == 0
        assert original_state.elf_hint_index == 0


@pytest.mark.anyio
async def test_admin_elf_trigger_uses_session_scoped_active_player(monkeypatch, tmp_path):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "content-token": {
                    "roles": ["content_admin"],
                }
            }
        ),
    )
    monkeypatch.setenv("KYRGAME_TELEMETRY_DIR", str(tmp_path / "telemetry"))

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        app.state.tick_runtime.stop()
        state = app.state.animation_tick_system.state
        state.elf_last_room = None
        state.elf_reward_next = 0
        state.elf_hint_index = 0

        active_player = fixtures.build_player().model_copy(update={"gamloc": 7, "pgploc": 7})
        app.state.active_players.clear()
        app.state.active_player_sessions["hero-token"] = active_player
        target_socket = _FakeSocket()
        app.state.session_connections["hero-token"] = target_socket
        await app.state.presence.set_location("hero", 7, "hero-token")

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/admin/mobs/elf/trigger",
                headers=_auth("content-token"),
                json={"player_id": "hero", "room_id": 7},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "triggered"
        assert response.json()["outcome"] == "hint"
        assert state.elf_last_room == 7
        lines = [
            json.loads(line)
            for line in (tmp_path / "telemetry" / "system.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        admin_events = [
            line for line in lines if line["event_type"] == "animation.admin_trigger"
        ]
        assert admin_events == [
            {
                "event_type": "animation.admin_trigger",
                "payload": {
                    "trigger_source": "admin",
                    "routine_name": "elves",
                    "room_id": 7,
                    "player_id": "hero",
                    "outcome": "hint",
                    "event_count": 3,
                },
                "timestamp": admin_events[0]["timestamp"],
                "userid": "__system__",
            }
        ]


@pytest.mark.anyio
async def test_admin_elf_trigger_ignores_system_audit_failures(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "content-token": {
                    "roles": ["content_admin"],
                }
            }
        ),
    )

    class _FailingTelemetrySink:
        async def record_system(self, *, event_type, payload):  # noqa: ARG002
            raise OSError("telemetry path unavailable")

    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with app.router.lifespan_context(app):
        app.state.tick_runtime.stop()
        state = app.state.animation_tick_system.state
        state.elf_last_room = None
        state.elf_reward_next = 0
        state.elf_hint_index = 0
        app.state.telemetry_sink = _FailingTelemetrySink()

        active_player = fixtures.build_player().model_copy(update={"gamloc": 7, "pgploc": 7})
        app.state.active_players.clear()
        app.state.active_player_sessions["hero-token"] = active_player
        await app.state.presence.set_location("hero", 7, "hero-token")

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/admin/mobs/elf/trigger",
                headers=_auth("content-token"),
                json={"player_id": "hero", "room_id": 7},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "triggered"
        assert response.json()["outcome"] == "hint"
        assert state.elf_last_room == 7


@pytest.mark.anyio
async def test_admin_elf_trigger_reuses_legacy_hint_gold_flow(monkeypatch):
    monkeypatch.setenv(
        ADMIN_MAP_ENV,
        json.dumps(
            {
                "content-token": {
                    "roles": ["content_admin"],
                }
            }
        ),
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        app.state.tick_runtime.stop()
        state = app.state.animation_tick_system.state
        state.elf_last_room = None
        state.elf_reward_next = 0
        state.elf_hint_index = 0

        with app.state.session_factory() as db:
            record = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
            assert record is not None
            record.gamloc = 7
            record.pgploc = 7
            record.gold = 10
            db.commit()
            active_player = fixtures.build_player().model_copy(
                update={"gamloc": 7, "pgploc": 7, "gold": 10}
            )

        app.state.active_players["hero"] = active_player
        target_socket = _FakeSocket()
        app.state.session_connections["hero-token"] = target_socket
        await app.state.presence.set_location("hero", 7, "hero-token")
        broadcasts: list[tuple[int, dict, set | None]] = []

        async def _capture(room_id: int, message: dict, sender=None, exclude=None):  # noqa: ARG001
            broadcasts.append((room_id, message, exclude))

        app.state.gateway.broadcast = _capture

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            hint_resp = await client.post(
                "/admin/mobs/elf/trigger",
                headers=_auth("content-token"),
                json={"player_id": "hero", "room_id": 7},
            )
            gold_resp = await client.post(
                "/admin/mobs/elf/trigger",
                headers=_auth("content-token"),
                json={"player_id": "hero", "room_id": 7},
            )

        assert hint_resp.status_code == 200
        assert hint_resp.json()["status"] == "triggered"
        assert hint_resp.json()["outcome"] == "hint"
        assert hint_resp.json()["room_id"] == 7
        assert hint_resp.json()["player_id"] == "hero"
        assert hint_resp.json()["snapshot"]["mobs"][2]["id"] == "elf"
        assert hint_resp.json()["snapshot"]["mobs"][2]["room_id"] == 7

        assert gold_resp.status_code == 200
        assert gold_resp.json()["status"] == "triggered"
        assert gold_resp.json()["outcome"] == "gold"
        assert state.elf_last_room == 7
        assert state.elf_reward_next == 0
        assert state.elf_hint_index == 1

        message_ids = [
            event["payload"].get("message_id")
            for _, event, _ in broadcasts
            if event.get("type") == "room_broadcast"
        ]
        assert message_ids == [
            "EMSG00",
            "EMSG03",
            "EMSG04",
            "EMSG00",
            "EMSG02",
            "EMSG04",
        ]

        hint_payload = broadcasts[1][1]["payload"]
        assert hint_payload["message_id"] == "EMSG03"
        assert "secretly" in hint_payload["text"]
        assert "target_player" not in hint_payload
        assert "target_message_id" not in hint_payload
        assert "target_text" not in hint_payload
        assert target_socket in broadcasts[1][2]

        gold_payload = broadcasts[4][1]["payload"]
        assert gold_payload["message_id"] == "EMSG02"
        assert "target_player" not in gold_payload
        assert "target_message_id" not in gold_payload
        assert "target_text" not in gold_payload
        assert target_socket in broadcasts[4][2]

        target_messages = [
            message
            for message in target_socket.sent
            if message.get("payload", {}).get("animation_flag") == "elves"
        ]
        assert [
            message["payload"].get("message_id") for message in target_messages
        ] == ["EHINT0", "EMSG01"]
        assert "The elf whispers to you" in target_messages[0]["payload"]["text"]
        assert "hands you" in target_messages[1]["payload"]["text"]

        with app.state.session_factory() as db:
            refreshed = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
            assert refreshed is not None
            assert refreshed.gold == active_player.gold
            assert refreshed.gold > 10
