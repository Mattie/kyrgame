import asyncio
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from starlette.websockets import WebSocketState

from . import commands, constants, fixtures, models, repositories
from .env import load_env_file
from .gateway import RoomGateway
from .presence import PresenceService
from .rate_limit import RateLimiter
from .runtime import bootstrap_app, shutdown_app

logger = logging.getLogger(__name__)


class LogoResponse(BaseModel):
    message: str
    lines: list[str]


class SessionRequest(BaseModel):
    player_id: str
    resume_token: str | None = None
    allow_multiple: bool = False
    room_id: int | None = None


class SessionData(BaseModel):
    token: str
    player_id: str
    room_id: int
    first_login: bool = False
    resumed: bool = False
    replaced_sessions: int = 0


class SessionResponse(BaseModel):
    status: str
    session: SessionData


class LogoutResponse(BaseModel):
    status: str


class AdminRole(str, Enum):
    PLAYER = "player_admin"
    CONTENT = "content_admin"
    MESSAGES = "message_admin"


class AdminFlag(str, Enum):
    ALLOW_DELETE = "allow_delete_players"
    ALLOW_RENAME = "allow_player_rename"


@dataclass
class AdminGrant:
    roles: set[str]
    flags: set[str]


class PlayerAdminUpdate(BaseModel):
    altnam: str | None = None
    attnam: str | None = None
    flags: list[str] | None = None
    level: int | None = None
    gamloc: int | None = None
    pgploc: int | None = None
    gold: int | None = None
    spts: int | None = None
    hitpts: int | None = None
    gpobjs: list[int | str | None] | None = None
    npobjs: int | None = None
    gemidx: int | None = None
    stones: list[int | str] | None = None
    stumpi: int | None = None
    spouse: str | None = None
    clear_spouse: bool = False
    cap_gold: int | None = None
    cap_hitpts: int | None = None
    cap_spts: int | None = None

    model_config = ConfigDict(extra="forbid")


def _cors_origins_from_env() -> list[str]:
    configured = os.getenv("KYRGAME_CORS_ORIGINS")
    if not configured:
        return ["*"]
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def get_db_session(request: Request) -> OrmSession:
    session_factory = request.app.state.session_factory
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def _extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token:
            return token
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid token")


def _all_admin_roles() -> set[str]:
    return {role.value for role in AdminRole}


def _all_admin_flags() -> set[str]:
    return {flag.value for flag in AdminFlag}


def _load_admin_grants() -> dict[str, AdminGrant]:
    grants: dict[str, AdminGrant] = {}

    raw_map = os.getenv("KYRGAME_ADMIN_TOKENS")
    if raw_map:
        try:
            token_map = json.loads(raw_map)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise RuntimeError("KYRGAME_ADMIN_TOKENS must be valid JSON") from exc
        for token, settings in token_map.items():
            grants[token] = AdminGrant(
                roles=set(settings.get("roles", [])), flags=set(settings.get("flags", []))
            )

    default_token = os.getenv("KYRGAME_ADMIN_TOKEN")
    if default_token:
        grants.setdefault(default_token, AdminGrant(_all_admin_roles(), _all_admin_flags()))

    if not grants:
        logger.warning(
            "No admin tokens configured. Set KYRGAME_ADMIN_TOKEN or KYRGAME_ADMIN_TOKENS to enable admin access."
        )

    return grants


def require_admin(
    request: Request,
    roles: set[AdminRole] | None = None,
    flags: set[AdminFlag] | None = None,
):
    token = _extract_bearer_token(request)
    grants: dict[str, AdminGrant] = request.app.state.admin_grants
    grant = grants.get(token)
    if grant is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized admin token")

    required_roles = {role.value for role in roles or set()}
    if required_roles and not required_roles.issubset(grant.roles):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient admin role")

    required_flags = {flag.value for flag in flags or set()}
    if required_flags and not required_flags.issubset(grant.flags):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing admin privileges")

    return grant


def _validate_admin_token(
    app: FastAPI, token: str | None, roles: set[AdminRole] | None = None
) -> AdminGrant:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid token")

    grants: dict[str, AdminGrant] = app.state.admin_grants
    grant = grants.get(token)
    if grant is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized admin token")

    required_roles = {role.value for role in roles or set()}
    if required_roles and not required_roles.issubset(grant.roles):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient admin role")

    return grant


def require_player_admin(request: Request):
    return require_admin(request, roles={AdminRole.PLAYER})


def require_content_admin(request: Request):
    return require_admin(request, roles={AdminRole.CONTENT})


def require_message_admin(request: Request):
    return require_admin(request, roles={AdminRole.MESSAGES})


def require_any_admin_role(request: Request, roles: set[AdminRole]):
    grant = require_admin(request)
    allowed = {role.value for role in roles}
    if not allowed.intersection(grant.roles):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient admin role")
    return grant


def require_player_or_content_admin(request: Request):
    return require_any_admin_role(request, {AdminRole.PLAYER, AdminRole.CONTENT})


async def require_active_session(
    request: Request, db: Annotated[OrmSession, Depends(get_db_session)]
):
    token = _extract_bearer_token(request)
    repo = repositories.PlayerSessionRepository(db)
    session_record = repo.get_by_token(token)
    if not session_record:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session token")

    player = db.get(models.Player, session_record.player_id)
    if player is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session token")

    repo.mark_seen(token)
    db.commit()
    return session_record, player


def _player_model_from_record(record: models.Player) -> models.PlayerModel:
    return models.PlayerModel(
        uidnam=record.uidnam,
        plyrid=record.plyrid,
        altnam=record.altnam,
        attnam=record.attnam,
        gpobjs=record.gpobjs,
        nmpdes=record.nmpdes,
        modno=record.modno,
        level=record.level,
        gamloc=record.gamloc,
        pgploc=record.pgploc,
        flags=record.flags,
        gold=record.gold,
        npobjs=record.npobjs,
        obvals=record.obvals,
        nspells=record.nspells,
        spts=record.spts,
        hitpts=record.hitpts,
        offspls=record.offspls,
        defspls=record.defspls,
        othspls=record.othspls,
        charms=record.charms,
        spells=record.spells,
        gemidx=record.gemidx,
        stones=record.stones,
        macros=record.macros,
        stumpi=record.stumpi,
        spouse=record.spouse,
    )


def _player_level_caps(level: int) -> tuple[int, int]:
    max_hitpoints = max(0, level * 4)
    max_spellpoints = max(0, level * 2)
    return max_hitpoints, max_spellpoints


def _object_catalog_indexes(objects: list[models.GameObjectModel]):
    objects_by_id = {obj.id: obj for obj in objects}
    objects_by_name = {obj.name.lower(): obj for obj in objects}
    return objects_by_id, objects_by_name


def _resolve_object_reference(
    raw: int | str,
    objects_by_id: dict[int, models.GameObjectModel],
    objects_by_name: dict[str, models.GameObjectModel],
    *,
    field_name: str,
) -> int:
    if isinstance(raw, int):
        object_id = raw
    else:
        trimmed = raw.strip()
        if not trimmed:
            raise HTTPException(status_code=422, detail=f"{field_name} cannot be blank")
        if trimmed.isdigit():
            object_id = int(trimmed)
        else:
            match = objects_by_name.get(trimmed.lower())
            if not match:
                raise HTTPException(status_code=422, detail=f"{field_name} must reference a catalog object")
            return match.id

    if object_id not in objects_by_id:
        raise HTTPException(status_code=422, detail=f"{field_name} must reference a catalog object")
    return object_id


def _normalize_obvals(obvals: list[int], target_length: int) -> list[int]:
    if len(obvals) >= target_length:
        return obvals[:target_length]
    return [*obvals, *([0] * (target_length - len(obvals)))]


def _apply_player_admin_update(
    player: models.PlayerModel,
    updates: PlayerAdminUpdate,
    *,
    objects: list[models.GameObjectModel],
) -> models.PlayerModel:
    data = player.model_dump()
    objects_by_id, objects_by_name = _object_catalog_indexes(objects)

    if updates.altnam is not None:
        data["altnam"] = updates.altnam[: constants.APNSIZ]
    if updates.attnam is not None:
        data["attnam"] = updates.attnam[: constants.APNSIZ]
    if updates.flags is not None:
        current_mask = data["flags"]
        # Legacy kyraedit only modifies select flags when editing players (KYRSYSP.C 477-482).
        editable_mask = int(constants.ADMIN_EDITABLE_PLAYER_FLAGS)
        new_mask = (current_mask & ~editable_mask) | constants.encode_player_flags(updates.flags)
        data["flags"] = new_mask

    if updates.gamloc is not None:
        data["gamloc"] = updates.gamloc
    if updates.pgploc is not None:
        data["pgploc"] = updates.pgploc

    level = updates.level if updates.level is not None else data["level"]
    data["level"] = level
    if updates.level is not None:
        # Legacy: kyraedit EDT002 sets nmpdes from level when editing players (KYRSYSP.C 129-146).
        data["nmpdes"] = constants.level_to_nmpdes(level)
    max_hitpoints, max_spellpoints = _player_level_caps(level)

    if updates.hitpts is not None:
        data["hitpts"] = updates.hitpts
    hit_cap = max_hitpoints if updates.cap_hitpts is None else min(max_hitpoints, updates.cap_hitpts)
    data["hitpts"] = max(0, min(data["hitpts"], hit_cap))

    if updates.spts is not None:
        data["spts"] = updates.spts
    spts_cap = max_spellpoints if updates.cap_spts is None else min(max_spellpoints, updates.cap_spts)
    data["spts"] = max(0, min(data["spts"], spts_cap))

    if updates.gold is not None:
        data["gold"] = updates.gold
    if updates.cap_gold is not None:
        data["gold"] = min(data["gold"], updates.cap_gold)
    data["gold"] = max(0, data["gold"])

    if updates.gpobjs is not None:
        if len(updates.gpobjs) > constants.MXPOBS:
            raise HTTPException(status_code=422, detail="gpobjs exceeds MXPOBS")
        resolved: list[int] = []
        seen_empty = False
        for slot in updates.gpobjs:
            if slot is None or (isinstance(slot, str) and not slot.strip()):
                seen_empty = True
                continue
            if seen_empty:
                raise HTTPException(
                    status_code=422, detail="gpobjs slots must be contiguous from slot 1"
                )
            resolved.append(
                _resolve_object_reference(
                    slot,
                    objects_by_id,
                    objects_by_name,
                    field_name="gpobjs",
                )
            )
        if updates.npobjs is not None and updates.npobjs != len(resolved):
            raise HTTPException(status_code=422, detail="npobjs must match gpobjs length")
        data["gpobjs"] = resolved
        data["npobjs"] = len(resolved)
        data["obvals"] = _normalize_obvals(data["obvals"], len(resolved))
    elif updates.npobjs is not None:
        if updates.npobjs < 0 or updates.npobjs > constants.MXPOBS:
            raise HTTPException(status_code=422, detail="npobjs must be within MXPOBS")
        gpobjs = list(data["gpobjs"])
        obvals = list(data["obvals"])
        if updates.npobjs > len(gpobjs):
            # Legacy kyraedit increments gpobjs with gmobjs[2]. (KYRSYSP.C EDT008 @ ~221-241)
            default_id = 2
            if default_id not in objects_by_id:
                raise HTTPException(status_code=422, detail="Default inventory object missing")
            for _ in range(len(gpobjs), updates.npobjs):
                gpobjs.append(default_id)
                obvals.append(0)
        elif updates.npobjs < len(gpobjs):
            gpobjs = gpobjs[: updates.npobjs]
            obvals = obvals[: updates.npobjs]
        data["gpobjs"] = gpobjs
        data["obvals"] = obvals
        data["npobjs"] = updates.npobjs

    if updates.stones is not None:
        if len(updates.stones) != constants.BIRTHSTONE_SLOTS:
            raise HTTPException(status_code=422, detail="stones must contain four entries")
        data["stones"] = [
            _resolve_object_reference(
                stone,
                objects_by_id,
                objects_by_name,
                field_name="stones",
            )
            for stone in updates.stones
        ]

    if updates.gemidx is not None:
        # Legacy kyraedit gemidx allows 0-4 inclusive. (KYRSYSP.C EDT022 @ ~296-305)
        if updates.gemidx < 0 or updates.gemidx > constants.BIRTHSTONE_SLOTS:
            raise HTTPException(status_code=422, detail="gemidx must be between 0 and 4")
        data["gemidx"] = updates.gemidx

    if updates.stumpi is not None:
        # Legacy kyraedit stumpi allows 0-12 inclusive. (KYRSYSP.C EDT023 @ ~307-317)
        if updates.stumpi < 0 or updates.stumpi > 12:
            raise HTTPException(status_code=422, detail="stumpi must be between 0 and 12")
        data["stumpi"] = updates.stumpi

    if updates.clear_spouse:
        data["spouse"] = ""
    elif updates.spouse is not None:
        data["spouse"] = updates.spouse[: constants.ALSSIZ]

    return models.PlayerModel(**data)


def _replace_cached_model(collection, new_model, *, key_attr: str = "id"):
    replaced = False
    for idx, existing in enumerate(collection):
        if getattr(existing, key_attr) == getattr(new_model, key_attr):
            collection[idx] = new_model
            replaced = True
            break
    if not replaced:
        collection.append(new_model)


def _set_player_in_cache(app: FastAPI, player: models.PlayerModel, *, original_alias: str | None = None):
    cache: list[models.PlayerModel] = app.state.fixture_cache["players"]
    lookup = original_alias or player.plyrid
    replaced = False
    for idx, existing in enumerate(cache):
        if existing.plyrid == lookup:
            cache[idx] = player
            replaced = True
            break
    if not replaced:
        cache.append(player)
    app.state.fixture_cache["summary"]["players"] = len(cache)


def _remove_player_from_cache(app: FastAPI, alias: str):
    cache: list[models.PlayerModel] = app.state.fixture_cache["players"]
    app.state.fixture_cache["players"] = [player for player in cache if player.plyrid != alias]
    app.state.fixture_cache["summary"]["players"] = len(app.state.fixture_cache["players"])


async def _disconnect_sessions(app: FastAPI, tokens: list[str]):
    connections = app.state.session_connections
    for token in tokens:
        socket = connections.pop(token, None)
        previous_room = await app.state.presence.remove(token)
        if previous_room is not None and socket is not None:
            await app.state.gateway.unregister(previous_room, socket)
        if socket is not None and socket.application_state == WebSocketState.CONNECTED:
            await socket.close(code=status.WS_1008_POLICY_VIOLATION)


def _update_message_cache(app: FastAPI, bundle: models.MessageBundleModel):
    cache = app.state.fixture_cache
    cache["message_bundles"][bundle.locale] = bundle
    if bundle.locale == fixtures.DEFAULT_LOCALE:
        cache["messages"] = bundle
        app.state.command_vocabulary = commands.CommandVocabulary(cache["commands"], bundle)
    cache["summary"]["messages"] = len(bundle.messages)


def _persist_message_bundle(db: OrmSession, bundle: models.MessageBundleModel):
    db.query(models.Message).delete()
    db.add_all([models.Message(id=key, text=value) for key, value in bundle.messages.items()])
    db.commit()


class FixtureProvider:
    def __init__(self, scope: Request | WebSocket):
        self.scope = scope

    @property
    def cache(self):
        return self.scope.app.state.fixture_cache

    @property
    def gateway(self) -> RoomGateway:
        return self.scope.app.state.gateway

    @property
    def presence(self) -> PresenceService:
        return self.scope.app.state.presence

    @property
    def room_scripts(self):
        return self.scope.app.state.room_scripts

    @property
    def location_index(self):
        return self.scope.app.state.location_index

    @property
    def message_bundles(self):
        return self.scope.app.state.fixture_cache["message_bundles"]

    @property
    def players(self):
        return self.scope.app.state.fixture_cache["players"]

    @property
    def content_mappings(self):
        return self.scope.app.state.fixture_cache["content_mappings"]

    @property
    def command_dispatcher(self) -> commands.CommandDispatcher:
        return self.scope.app.state.command_dispatcher

    @property
    def command_vocabulary(self) -> commands.CommandVocabulary:
        return self.scope.app.state.command_vocabulary


def get_request_provider(request: Request) -> FixtureProvider:
    return FixtureProvider(request)


def get_websocket_provider(websocket: WebSocket) -> FixtureProvider:
    return FixtureProvider(websocket)


def _persist_player_from_template(
    db: OrmSession, alias: str, template: models.PlayerModel, room_id: int | None
) -> models.Player:
    data = template.model_dump()
    data.update(
        {
            "uidnam": alias[: constants.UIDSIZ],
            "plyrid": alias[: constants.ALSSIZ],
            "altnam": alias[: constants.APNSIZ],
            "attnam": alias[: constants.APNSIZ],
            "spouse": (data.get("spouse") or alias)[: constants.ALSSIZ],
            "gamloc": room_id if room_id is not None else template.gamloc,
            "pgploc": room_id if room_id is not None else template.pgploc,
        }
    )
    player = models.Player(**data)
    db.add(player)
    db.flush([player])
    return player


def _session_payload(
    token: str,
    player: models.Player,
    room_id: int,
    *,
    first_login: bool = False,
    resumed: bool = False,
    replaced_sessions: int = 0,
):
    return {
        "token": token,
        "player_id": player.plyrid,
        "room_id": room_id,
        "first_login": first_login,
        "resumed": resumed,
        "replaced_sessions": replaced_sessions,
    }


auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.get("/logo", response_model=LogoResponse)
async def fetch_logo():
    lines = [
        " _  __                 _           _     _      ",
        "| |/ /___  _   _  ___ | |__   __ _| |__ (_) ___ ",
        "| ' // _ \\| | | |/ _ \\| '_ \\ / _` | '_ \\| |/ __|",
        "| . \\ (_) | |_| | (_) | | | | (_| | | | | | (__ ",
        "|_|\\_\\___/ \\__, |\\___/|_| |_|\\__,_|_| |_|_|\\___|",
        "             |___/                                   ",
    ]
    return {"message": "Welcome to Kyrandia", "lines": lines}


@auth_router.post("/session", response_model=SessionResponse)
async def start_session(
    payload: SessionRequest,
    request: Request,
    db: Annotated[OrmSession, Depends(get_db_session)],
):
    # Rate limiting for session creation (5 per second per IP to allow for test suites)
    if not hasattr(request.app.state, 'session_rate_limiters'):
        request.app.state.session_rate_limiters = {}
    
    client_ip = request.client.host if request.client else "unknown"
    if client_ip not in request.app.state.session_rate_limiters:
        request.app.state.session_rate_limiters[client_ip] = RateLimiter(max_events=5, window_seconds=1.0)
    
    if not request.app.state.session_rate_limiters[client_ip].allow():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many session creation attempts. Please try again later."
        )
    
    template = request.app.state.fixture_cache["player_template"]
    repo = repositories.PlayerSessionRepository(db)

    player = db.scalar(select(models.Player).where(models.Player.plyrid == payload.player_id))
    first_login = False
    if player is None:
        player = _persist_player_from_template(db, payload.player_id, template, payload.room_id)
        first_login = True
    elif payload.room_id is not None:
        player.gamloc = payload.room_id
        player.pgploc = payload.room_id

    room_id = payload.room_id if payload.room_id is not None else player.gamloc

    replaced_tokens: list[str] = []
    resumed = False
    status_code = status.HTTP_201_CREATED

    if payload.resume_token:
        existing = repo.get_by_token(payload.resume_token)
        if not existing or existing.player_id != player.id:
            raise HTTPException(status_code=404, detail="Session not found or expired")
        repo.mark_seen(payload.resume_token)
        db.commit()
        room_id = existing.room_id
        token = existing.session_token
        resumed = True
        status_code = status.HTTP_200_OK
    else:
        if not payload.allow_multiple:
            # Use lock to prevent race condition during session replacement
            if not hasattr(request.app.state, 'session_replacement_lock'):
                request.app.state.session_replacement_lock = asyncio.Lock()
            
            async with request.app.state.session_replacement_lock:
                replaced_tokens = repo.deactivate_all(player.id)
                token = secrets.token_urlsafe(24)
                repo.create_session(player_id=player.id, session_token=token, room_id=room_id)
                db.commit()
        else:
            token = secrets.token_urlsafe(24)
            repo.create_session(player_id=player.id, session_token=token, room_id=room_id)
            db.commit()

    if not payload.allow_multiple and not payload.resume_token:
        # Commit happened inside the lock, now clean up old connections
        session_connections = request.app.state.session_connections
        for old_token in replaced_tokens:
            old_socket = session_connections.pop(old_token, None)
            previous_room = await request.app.state.presence.room_for_session(old_token)
            if previous_room is not None and old_socket is not None:
                await request.app.state.gateway.unregister(previous_room, old_socket)
            if old_socket is not None and old_socket.application_state == WebSocketState.CONNECTED:
                # Use WS_1008_POLICY_VIOLATION for concurrent session replacement
                await old_socket.close(code=status.WS_1008_POLICY_VIOLATION)
            await request.app.state.presence.remove(old_token)

    await request.app.state.presence.set_location(player.plyrid, room_id, token)

    body = {
        "status": "recovered" if resumed else "created",
        "session": _session_payload(
            token,
            player,
            room_id,
            first_login=first_login,
            resumed=resumed,
            replaced_sessions=len(replaced_tokens),
        ),
    }
    return JSONResponse(content=body, status_code=status_code)


@auth_router.get("/session", response_model=SessionResponse)
async def validate_session(
    session_context: Annotated[tuple[models.PlayerSession, models.Player], Depends(require_active_session)]
):
    session_record, player = session_context
    return {
        "status": "active",
        "session": _session_payload(
            session_record.session_token, player, session_record.room_id, first_login=False
        ),
    }


@auth_router.post("/logout", response_model=LogoutResponse)
async def logout(
    session_context: Annotated[tuple[models.PlayerSession, models.Player], Depends(require_active_session)],
    db: Annotated[OrmSession, Depends(get_db_session)],
    request: Request,
):
    session_record, _ = session_context
    repo = repositories.PlayerSessionRepository(db)
    repo.deactivate(session_record.session_token)
    db.commit()
    
    connections = request.app.state.session_connections
    active_socket = connections.pop(session_record.session_token, None)
    
    # Always clean up presence, even if socket operations fail
    try:
        if active_socket is not None and active_socket.application_state == WebSocketState.CONNECTED:
            await request.app.state.gateway.unregister(session_record.room_id, active_socket)
            await active_socket.close(code=status.WS_1000_NORMAL_CLOSURE)
    finally:
        await request.app.state.presence.remove(session_record.session_token)
    
    return LogoutResponse(status="logged_out")


commands_router = APIRouter(tags=["commands"])


@commands_router.get("/commands")
async def list_commands(provider: Annotated[FixtureProvider, Depends(get_request_provider)]):
    return [command.model_dump() for command in provider.cache["commands"]]


world_router = APIRouter(prefix="/world", tags=["world"])


@world_router.get("/locations")
async def list_locations(provider: Annotated[FixtureProvider, Depends(get_request_provider)]):
    # Return locations from location_index (runtime state) not fixture cache (static initial state)
    # This ensures frontend gets current object lists after pickups/drops
    return [location.model_dump() for location in provider.location_index.values()]


objects_router = APIRouter(tags=["objects"])


@objects_router.get("/objects")
async def list_objects(provider: Annotated[FixtureProvider, Depends(get_request_provider)]):
    return [game_object.model_dump() for game_object in provider.cache["objects"]]


spells_router = APIRouter(tags=["spells"])


@spells_router.get("/spells")
async def list_spells(provider: Annotated[FixtureProvider, Depends(get_request_provider)]):
    return [spell.model_dump() for spell in provider.cache["spells"]]


content_router = APIRouter(prefix="/content", tags=["content"])


@content_router.get("/lookup")
async def lookup_content(
    type: str, id: int, provider: Annotated[FixtureProvider, Depends(get_request_provider)]
):
    try:
        mapping = provider.content_mappings[f"{type}s"]
        message_id = mapping[str(id)]
    except KeyError:
        raise HTTPException(status_code=404, detail="Content mapping not found")

    text = provider.cache["messages"].messages.get(message_id)
    if text is None:
        raise HTTPException(status_code=404, detail="Message not available")
    return {"id": id, "message_id": message_id, "text": text}


i18n_router = APIRouter(prefix="/i18n", tags=["i18n"])


@i18n_router.get("/locales")
async def list_locales(provider: Annotated[FixtureProvider, Depends(get_request_provider)]):
    return sorted(provider.message_bundles.keys())


@i18n_router.get("/{locale}/messages")
async def fetch_message_bundle(
    locale: str, provider: Annotated[FixtureProvider, Depends(get_request_provider)]
):
    try:
        bundle = provider.message_bundles[locale]
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Locale {locale} not available")
    return bundle.model_dump()


admin_router = APIRouter(prefix="/admin", tags=["admin"])


players_router = APIRouter(prefix="/players", tags=["players"])


@admin_router.get("/fixtures")
async def fixture_summary(
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    admin: Annotated[AdminGrant, Depends(require_player_or_content_admin)],
):
    return provider.cache["summary"]


@admin_router.post("/reload-scripts")
async def reload_room_scripts(
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    admin: Annotated[AdminGrant, Depends(require_content_admin)],
):
    scripts = provider.room_scripts
    scripts.reload_scripts()
    return {"status": "ok", "reloads": scripts.reloads}


@admin_router.get("/players")
async def admin_list_players(
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    admin: Annotated[AdminGrant, Depends(require_player_admin)],
):
    return {"players": [player.model_dump() for player in provider.players]}


@admin_router.get("/players/{player_id}")
async def admin_get_player(
    player_id: str,
    db: Annotated[OrmSession, Depends(get_db_session)],
    admin: Annotated[AdminGrant, Depends(require_player_admin)],
):
    record = db.scalar(select(models.Player).where(models.Player.plyrid == player_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Player not found")
    model = _player_model_from_record(record)
    return {"player": model.model_dump()}


@admin_router.post("/players", status_code=status.HTTP_201_CREATED)
async def admin_create_player(
    player: models.PlayerModel,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    db: Annotated[OrmSession, Depends(get_db_session)],
    admin: Annotated[AdminGrant, Depends(require_player_admin)],
):
    existing = db.scalar(select(models.Player).where(models.Player.plyrid == player.plyrid))
    if existing:
        raise HTTPException(status_code=409, detail="Player alias already exists")

    db.add(models.Player(**player.model_dump()))
    db.commit()
    _set_player_in_cache(provider.scope.app, player)
    return {"status": "created", "player": player.model_dump()}


@admin_router.put("/players/{player_id}")
async def admin_update_player(
    player_id: str,
    player: models.PlayerModel,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    db: Annotated[OrmSession, Depends(get_db_session)],
    admin: Annotated[AdminGrant, Depends(require_player_admin)],
):
    record = db.scalar(select(models.Player).where(models.Player.plyrid == player_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Player not found")

    if player.plyrid != player_id and AdminFlag.ALLOW_RENAME.value not in admin.flags:
        raise HTTPException(status_code=403, detail="Rename not permitted for this admin token")

    if player.plyrid != player_id:
        conflict = db.scalar(select(models.Player).where(models.Player.plyrid == player.plyrid))
        if conflict and conflict.id != record.id:
            raise HTTPException(status_code=409, detail="Player alias already exists")

    for field, value in player.model_dump().items():
        setattr(record, field, value)

    db.commit()
    updated = _player_model_from_record(record)
    _set_player_in_cache(provider.scope.app, updated, original_alias=player_id if player.plyrid != player_id else None)
    return {"status": "updated", "player": updated.model_dump()}


@admin_router.patch("/players/{player_id}")
async def admin_patch_player(
    player_id: str,
    updates: PlayerAdminUpdate,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    db: Annotated[OrmSession, Depends(get_db_session)],
    admin: Annotated[AdminGrant, Depends(require_player_admin)],
):
    record = db.scalar(select(models.Player).where(models.Player.plyrid == player_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Player not found")

    current = _player_model_from_record(record)
    updated = _apply_player_admin_update(
        current,
        updates,
        objects=provider.cache["objects"],
    )

    for field, value in updated.model_dump().items():
        setattr(record, field, value)

    db.commit()
    _set_player_in_cache(provider.scope.app, updated)
    return {"status": "updated", "player": updated.model_dump()}


@admin_router.delete("/players/{player_id}")
async def admin_delete_player(
    player_id: str,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    db: Annotated[OrmSession, Depends(get_db_session)],
    admin: Annotated[AdminGrant, Depends(require_player_admin)],
):
    if AdminFlag.ALLOW_DELETE.value not in admin.flags:
        raise HTTPException(status_code=403, detail="Delete not permitted for this admin token")

    record = db.scalar(select(models.Player).where(models.Player.plyrid == player_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Player not found")

    session_repo = repositories.PlayerSessionRepository(db)
    tokens = session_repo.deactivate_all(record.id)

    db.delete(record)
    db.commit()

    await _disconnect_sessions(provider.scope.app, tokens)
    _remove_player_from_cache(provider.scope.app, player_id)
    return {"status": "deleted", "player_id": player_id}


@admin_router.put("/content/locations/{location_id}")
async def admin_update_location(
    location_id: int,
    location: models.LocationModel,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    db: Annotated[OrmSession, Depends(get_db_session)],
    admin: Annotated[AdminGrant, Depends(require_content_admin)],
):
    if location.id != location_id:
        raise HTTPException(status_code=400, detail="Location id mismatch")

    record = db.get(models.Location, location_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Location not found")

    for field, value in location.model_dump().items():
        setattr(record, field, value)
    db.commit()

    _replace_cached_model(provider.cache["locations"], location)
    provider.scope.app.state.location_index[location_id] = location
    return {"status": "updated", "location": location.model_dump()}


@admin_router.put("/content/objects/{object_id}")
async def admin_update_object(
    object_id: int,
    payload: models.GameObjectModel,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    db: Annotated[OrmSession, Depends(get_db_session)],
    admin: Annotated[AdminGrant, Depends(require_content_admin)],
):
    if payload.id != object_id:
        raise HTTPException(status_code=400, detail="Object id mismatch")

    record = db.get(models.GameObject, object_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Object not found")

    record.name = payload.name
    record.objdes = payload.objdes
    record.auxmsg = payload.auxmsg
    record.flags = ",".join(payload.flags)
    record.objrou = payload.objrou
    db.commit()

    _replace_cached_model(provider.cache["objects"], payload)
    return {"status": "updated", "object": payload.model_dump()}


@admin_router.put("/content/spells/{spell_id}")
async def admin_update_spell(
    spell_id: int,
    payload: models.SpellModel,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    db: Annotated[OrmSession, Depends(get_db_session)],
    admin: Annotated[AdminGrant, Depends(require_content_admin)],
):
    if payload.id != spell_id:
        raise HTTPException(status_code=400, detail="Spell id mismatch")

    record = db.get(models.Spell, spell_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Spell not found")

    record.name = payload.name
    record.sbkref = payload.sbkref
    record.bitdef = payload.bitdef
    record.level = payload.level
    record.splrou = payload.splrou
    db.commit()

    _replace_cached_model(provider.cache["spells"], payload)
    return {"status": "updated", "spell": payload.model_dump()}


@admin_router.put("/i18n/{locale}")
async def admin_update_message_bundle(
    locale: str,
    payload: models.MessageBundleModel,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    db: Annotated[OrmSession, Depends(get_db_session)],
    admin: Annotated[AdminGrant, Depends(require_message_admin)],
):
    if payload.locale != locale:
        raise HTTPException(status_code=400, detail="Locale does not match payload")

    _update_message_cache(provider.scope.app, payload)
    if locale == fixtures.DEFAULT_LOCALE:
        _persist_message_bundle(db, payload)

    return {"status": "updated", "bundle": payload.model_dump()}


@players_router.get("/example")
async def example_player(provider: Annotated[FixtureProvider, Depends(get_request_provider)]):
    return provider.cache["player_template"].model_dump()


@players_router.post("/echo")
async def echo_player(player: models.PlayerModel):
    return {"player": player.model_dump()}


def _format_room_occupants(occupants: list[str], messages: models.MessageBundleModel | None):
    """Format the occupant list shown when entering a room.

    Mirrors ``locogps`` from the legacy engine, which lists other visible players
    in the room using the KUTM11/KUTM12 strings.【F:legacy/KYRUTIL.C†L271-L314】
    """

    if not occupants:
        return None, None

    catalog = messages.messages if messages else {}
    message_id = None

    if len(occupants) == 1:
        suffix = catalog.get("KUTM11", "is here.")
        message_id = "KUTM11" if "KUTM11" in catalog else None
        return f"{occupants[0]} {suffix}", message_id

    suffix = catalog.get("KUTM12", "are here.")
    message_id = "KUTM12" if "KUTM12" in catalog else None
    if len(occupants) == 2:
        names = f"{occupants[0]} and {occupants[1]}"
    else:
        names = ", ".join(occupants[:-1]) + f", and {occupants[-1]}"
    return f"{names} {suffix}", message_id


async def _room_occupants_event(
    presence: PresenceService,
    player_id: str,
    room_id: int,
    messages: models.MessageBundleModel | None,
):
    occupants = await presence.players_in_room(room_id)
    others = sorted(occupant for occupant in occupants if occupant != player_id)
    text, message_id = _format_room_occupants(others, messages)
    if not others or not text:
        return None

    return {
        "scope": "player",
        "event": "room_occupants",
        "type": "room_occupants",
        "location": room_id,
        "occupants": others,
        "text": text,
        "message_id": message_id,
    }


def _entrance_room_message(player_id: str, room_id: int) -> dict:
    """Legacy-style entrance broadcast when a player appears in a room.

    Mirrors ``entrgp`` in ``KYRUTIL.C`` when a player logs in or is placed into
    the world with the APPEARCLOUDMIST text from ``KYRANDIA.C``.【F:legacy/KYRUTIL.C†L236-L260】【F:legacy/KYRANDIA.C†L135-L211】
    """

    return {
        "scope": "room",
        "event": "room_message",
        "type": "room_message",
        "player": player_id,
        "from": None,
        "to": room_id,
        "direction": None,
        "text": f"*** {player_id} has just appeared in a cloud of mists!",
        "message_id": None,
        "command_id": None,
    }


def create_app() -> FastAPI:
    env_path = os.getenv("KYRGAME_ENV_FILE")
    load_env_file(Path(env_path) if env_path else None)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await bootstrap_app(app)
        yield
        await shutdown_app(app)

    app = FastAPI(title="Kyrgame API", lifespan=lifespan)

    app.state.admin_grants = _load_admin_grants()

    cors_origins = _cors_origins_from_env()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router)
    app.include_router(commands_router)
    app.include_router(world_router)
    app.include_router(objects_router)
    app.include_router(spells_router)
    app.include_router(content_router)
    app.include_router(i18n_router)
    app.include_router(admin_router)
    app.include_router(players_router)

    gateway: RoomGateway | None = None
    app.state.session_connections = {}
    app.state.active_players = {}

    @app.websocket("/ws/admin/kyraedit")
    async def kyraedit_socket(
        websocket: WebSocket, provider: Annotated[FixtureProvider, Depends(get_websocket_provider)]
    ):
        """Minimal kyraedit-style editor flow for admins.

        Mirrors the single-session guard and return-to-room behavior in the
        legacy ``kyraedit`` state machine.【F:legacy/KYRSYSP.C†L78-L155】【F:legacy/KYRSYSP.C†L342-L379】
        """

        admin_token = websocket.headers.get("Authorization", "")
        if admin_token.lower().startswith("bearer "):
            admin_token = admin_token.split(" ", 1)[1]
        else:
            admin_token = websocket.query_params.get("admin_token")

        try:
            _validate_admin_token(provider.scope.app, admin_token, roles={AdminRole.PLAYER})
        except HTTPException as exc:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=exc.detail)
            return

        session_token = websocket.query_params.get("session_token")
        db_session = provider.scope.app.state.session_factory()
        try:
            repo = repositories.PlayerSessionRepository(db_session)
            session_record = repo.get_by_token(session_token or "")
            if not session_record:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid session token")
                return

            player = db_session.get(models.Player, session_record.player_id)
            if not player:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Player not found")
                return

            current_room = session_record.room_id
            player_id = player.plyrid
        finally:
            db_session.close()

        if not hasattr(provider.scope.app.state, "kyraedit_lock"):
            provider.scope.app.state.kyraedit_lock = asyncio.Lock()
        if not hasattr(provider.scope.app.state, "kyraedit_session"):
            provider.scope.app.state.kyraedit_session = None

        async with provider.scope.app.state.kyraedit_lock:
            active = provider.scope.app.state.kyraedit_session
            if active:
                await websocket.close(
                    code=status.WS_1013_TRY_AGAIN_LATER, reason="Another kyraedit session is active"
                )
                return
            provider.scope.app.state.kyraedit_session = session_token

        await websocket.accept()

        await provider.presence.remove(session_token)
        await provider.gateway.broadcast(
            current_room,
            {
                "type": "room_broadcast",
                "room": current_room,
                "payload": {"event": "player_leave", "player": player_id},
            },
        )

        await websocket.send_json({"type": "kyraedit_prompt", "detail": "Enter player id"})

        try:
            while True:
                incoming = await websocket.receive_json()
                if incoming.get("type") == "select_player":
                    target_id = (incoming.get("player_id") or "").strip()
                    if not target_id:
                        await websocket.send_json(
                            {"type": "kyraedit_error", "detail": "Player id required"}
                        )
                        continue

                    db = provider.scope.app.state.session_factory()
                    try:
                        record = db.scalar(select(models.Player).where(models.Player.plyrid == target_id))
                        if record:
                            payload = _player_model_from_record(record)
                        else:
                            cached = next(
                                (p for p in provider.players if p.plyrid == target_id), None
                            )
                            if cached:
                                payload = cached
                            else:
                                await websocket.send_json(
                                    {"type": "kyraedit_error", "detail": "Player not found"}
                                )
                                continue
                        await websocket.send_json({"type": "kyraedit_record", "player": payload.model_dump()})
                    finally:
                        db.close()
                elif incoming.get("type") == "exit":
                    await websocket.send_json({"type": "kyraedit_exit", "room": current_room})
                    break
                else:
                    await websocket.send_json({"type": "kyraedit_error", "detail": "Unknown command"})
        finally:
            await provider.presence.set_location(player_id, current_room, session_token)
            await provider.gateway.broadcast(
                current_room,
                {
                    "type": "room_broadcast",
                    "room": current_room,
                    "payload": {"event": "player_enter", "player": player_id},
                },
            )
            await provider.gateway.broadcast(
                current_room,
                {
                    "type": "room_broadcast",
                    "room": current_room,
                    "payload": _entrance_room_message(player_id, current_room),
                },
            )

            occupant_event = await _room_occupants_event(
                provider.presence, player_id, current_room, provider.message_bundles.get("en-US")
            )
            if occupant_event:
                await provider.gateway.broadcast(
                    current_room,
                    {"type": "room_broadcast", "room": current_room, "payload": occupant_event},
                )

            async with provider.scope.app.state.kyraedit_lock:
                provider.scope.app.state.kyraedit_session = None

    @app.websocket("/ws/rooms/{room_id}")
    async def room_socket(
        websocket: WebSocket,
        room_id: int,
        provider: Annotated[FixtureProvider, Depends(get_websocket_provider)],
    ):
        nonlocal gateway
        if gateway is None:
            gateway = provider.gateway

        session_token = websocket.query_params.get("token")
        if not session_token:
            # Missing token - reject connection during handshake
            await websocket.send_denial_response(
                Response(status_code=status.HTTP_403_FORBIDDEN, content="Missing token")
            )
            return

        db_session = provider.scope.app.state.session_factory()
        player_state: models.PlayerModel | None = None
        try:
            session_repo = repositories.PlayerSessionRepository(db_session)
            session_record = session_repo.get_by_token(session_token)
            if not session_record:
                # Invalid or expired token - reject connection during handshake
                await websocket.send_denial_response(
                    Response(status_code=status.HTTP_401_UNAUTHORIZED, content="Invalid or expired token")
                )
                return

            player = db_session.get(models.Player, session_record.player_id)
            if not player:
                # Player not found - reject connection during handshake
                await websocket.send_denial_response(
                    Response(status_code=status.HTTP_404_NOT_FOUND, content="Player not found")
                )
                return

            session_repo.mark_seen(session_token)
            db_session.commit()
            player_id = player.plyrid
            current_room = session_record.room_id
            player_state = _player_model_from_record(player)
            player_state.gamloc = current_room
            player_state.pgploc = current_room
        except Exception as e:
            # Database or other error during validation - reject connection during handshake
            logger.error(f"WebSocket connection error during validation: {type(e).__name__}")
            await websocket.send_denial_response(
                Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content="Service temporarily unavailable")
            )
            try:
                db_session.rollback()
            except Exception:
                pass  # Ignore rollback errors as we're already in error handling
            return
        finally:
            db_session.close()

        if player_state is None:
            await websocket.send_denial_response(
                Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content="Unable to load player state")
            )
            return

        # All validation passed - now accept the WebSocket connection
        await websocket.accept()

        session_connections = provider.scope.app.state.session_connections
        existing_socket = session_connections.get(session_token)
        if existing_socket is not None and existing_socket.application_state == WebSocketState.CONNECTED:
            await gateway.unregister(current_room, existing_socket)
            await existing_socket.close(code=status.WS_1013_TRY_AGAIN_LATER)
        session_connections[session_token] = websocket

        limiter = RateLimiter(max_events=2, window_seconds=0.5)

        # Create a persistent database session for this WebSocket connection
        persistent_session = provider.scope.app.state.session_factory()
        
        active_players = provider.scope.app.state.active_players

        def lookup_player(player_alias: str) -> models.PlayerModel | None:
            active_player = active_players.get(player_alias)
            if active_player:
                return active_player
            record = persistent_session.scalar(
                select(models.Player).where(models.Player.plyrid == player_alias)
            )
            if record is None:
                return None
            return _player_model_from_record(record)

        state = commands.GameState(
            player=player_state,
            locations=provider.location_index,
            objects={obj.id: obj for obj in provider.cache["objects"]},
            messages=provider.message_bundles.get("en-US"),
            content_mappings=provider.content_mappings,
            db_session=persistent_session,
            presence=provider.presence,
            player_lookup=lookup_player,
        )

        active_players[player_id] = player_state
        await provider.presence.set_location(player_id, current_room, session_token)
        await gateway.register(current_room, websocket)

        # Immediately send the player their current room description to mirror move command behavior.
        location = state.locations.get(current_room)
        if location is not None:
            description_id, long_description = commands._location_description(state, location)
            await websocket.send_json(
                {
                    "type": "command_response",
                    "room": current_room,
                    "payload": {
                        "scope": "player",
                        "event": "location_update",
                        "type": "location_update",
                        "location": location.id,
                        "description": location.brfdes,
                        "description_id": description_id,
                        "long_description": long_description,
                        "message_id": description_id,
                    },
                }
            )
            await websocket.send_json(
                {
                    "type": "command_response",
                    "room": current_room,
                    "payload": {
                        "scope": "player",
                        "event": "location_description",
                        "type": "location_description",
                        "location": location.id,
                        "message_id": description_id,
                        "text": long_description or location.brfdes,
                    },
                }
            )
            await websocket.send_json(
                {
                    "type": "command_response",
                    "room": current_room,
                    "payload": commands._room_objects_event(
                        location, state.objects or {}, None, description_id
                    ),
                }
            )

        occupants_event = await _room_occupants_event(
            provider.presence, player_id, current_room, state.messages
        )
        if occupants_event:
            await websocket.send_json(
                {
                    "type": "command_response",
                    "room": current_room,
                    "payload": occupants_event,
                }
            )

        await gateway.broadcast(
            current_room,
            {
                "type": "room_broadcast",
                "room": current_room,
                "payload": {"event": "player_enter", "player": player_id},
            },
            sender=websocket,
        )
        await gateway.broadcast(
            current_room,
            {
                "type": "room_broadcast",
                "room": current_room,
                "payload": _entrance_room_message(player_id, current_room),
            },
            sender=websocket,
        )

        try:
            while True:
                payload = await websocket.receive_json()
                meta = payload.get("meta") or None
                if not limiter.allow():
                    await websocket.send_json(
                        {"type": "rate_limited", "detail": "Too many commands, slow down."}
                    )
                    continue

                if payload.get("type") != "command":
                    await websocket.send_json({"type": "noop", "room": current_room})
                    continue

                command_text = payload.get("command", "")
                args = payload.get("args", {}) or {}
                tokens = command_text.strip().split()
                verb = tokens[0].lower() if tokens else ""
                if verb and verb not in commands.CommandVocabulary.chat_aliases:
                    tokens = commands.normalize_tokens(tokens)
                    verb = tokens[0].lower() if tokens else ""
                arg_list = tokens[1:]
                parsed = None
                parse_error = None
                try:
                    if args and command_text == "move" and args.get("direction"):
                        parsed = commands.ParsedCommand(
                            verb="move",
                            args={"direction": args.get("direction")},
                        )
                    elif args and command_text == "chat":
                        say_id = provider.command_vocabulary._lookup_command_id("say")
                        parsed = commands.ParsedCommand(
                            verb="chat",
                            args={"text": args.get("text", ""), "mode": "say"},
                            command_id=say_id,
                            message_id=commands._command_message_id(say_id),
                        )
                    else:
                        parsed = provider.command_vocabulary.parse_text(command_text)
                except commands.UnknownCommandError as exc:  # type: ignore[attr-defined]
                    parse_error = exc

                if tokens and provider.room_scripts:
                    # Legacy kyra() runs the room routine before the command table.【F:legacy/KYRCMDS.C†L1251-L1257】
                    handled = await provider.room_scripts.handle_command(
                        player_id,
                        current_room,
                        command=verb,
                        args=arg_list,
                        player=state.player,
                    )
                    if handled:
                        ack_payload = {
                            "type": "command_response",
                            "room": current_room,
                            "payload": {
                                "command_id": getattr(parsed, "command_id", None)
                                if parsed
                                else None,
                                "message_id": getattr(parsed, "message_id", None)
                                if parsed
                                else None,
                                "verb": verb,
                            },
                        }
                        if meta:
                            ack_payload["meta"] = meta
                        await websocket.send_json(ack_payload)
                        
                        # Process pending events from room script engine
                        pending_events = provider.room_scripts.get_and_clear_pending_events()
                        transfer_event = None
                        for event in list(pending_events):
                            if event.get("event") == "room_transfer":
                                transfer_event = event
                                pending_events.remove(event)

                        for event in pending_events:
                            scope = event.get("scope", "player")
                            if scope == "room":
                                envelope = {"type": "room_broadcast", "room": current_room, "payload": event}
                                if meta:
                                    envelope["meta"] = meta
                                excluded_player = event.get("exclude_player")
                                excluded_sockets = set()
                                if excluded_player:
                                    for token in await provider.presence.sessions_for_player(
                                        excluded_player
                                    ):
                                        target_socket = session_connections.get(token)
                                        if target_socket:
                                            excluded_sockets.add(target_socket)
                                await gateway.broadcast(
                                    current_room, envelope, sender=websocket, exclude=excluded_sockets
                                )
                            elif scope == "target":
                                target_id = event.get("player")
                                if not target_id:
                                    continue
                                envelope = {"type": "command_response", "room": current_room, "payload": event}
                                if meta:
                                    envelope["meta"] = meta
                                for token in await provider.presence.sessions_for_player(target_id):
                                    target_socket = session_connections.get(token)
                                    if not target_socket:
                                        continue
                                    if target_socket.application_state != WebSocketState.CONNECTED:
                                        continue
                                    await target_socket.send_json(envelope)
                            else:
                                envelope = {"type": "command_response", "room": current_room, "payload": event}
                                if meta:
                                    envelope["meta"] = meta
                                await websocket.send_json(envelope)

                        if transfer_event:
                            target_room = int(transfer_event.get("target_room", current_room))
                            leave_text = transfer_event.get("leave_text")
                            arrive_text = transfer_event.get("arrive_text")
                            if leave_text:
                                await gateway.broadcast(
                                    current_room,
                                    {
                                        "type": "room_broadcast",
                                        "room": current_room,
                                        "payload": {
                                            "scope": "room",
                                            "event": "room_message",
                                            "type": "room_message",
                                            "player": player_id,
                                            "from": current_room,
                                            "to": None,
                                            "direction": None,
                                            "text": leave_text,
                                            "message_id": None,
                                        },
                                    },
                                    sender=websocket,
                                )

                            if target_room != current_room:
                                await gateway.register(target_room, websocket, announce=False)
                                await provider.presence.set_location(
                                    player_id, target_room, session_token
                                )
                                with provider.scope.app.state.session_factory() as db:
                                    repo = repositories.PlayerSessionRepository(db)
                                    repo.set_room(session_token, target_room)
                                    repo.mark_seen(session_token)
                                    db.commit()
                                current_room = target_room

                                location = state.locations.get(current_room)
                                if location is not None:
                                    description_id, long_description = commands._location_description(
                                        state, location
                                    )
                                    await websocket.send_json(
                                        {
                                            "type": "command_response",
                                            "room": current_room,
                                            "payload": {
                                                "scope": "player",
                                                "event": "location_update",
                                                "type": "location_update",
                                                "location": location.id,
                                                "description": location.brfdes,
                                                "description_id": description_id,
                                                "long_description": long_description,
                                                "message_id": description_id,
                                            },
                                        }
                                    )
                                    await websocket.send_json(
                                        {
                                            "type": "command_response",
                                            "room": current_room,
                                            "payload": {
                                                "scope": "player",
                                                "event": "location_description",
                                                "type": "location_description",
                                                "location": location.id,
                                                "message_id": description_id,
                                                "text": long_description or location.brfdes,
                                            },
                                        }
                                    )
                                    await websocket.send_json(
                                        {
                                            "type": "command_response",
                                            "room": current_room,
                                            "payload": commands._room_objects_event(
                                                location, state.objects or {}, None, description_id
                                            ),
                                        }
                                    )

                                occupant_event = await _room_occupants_event(
                                    provider.presence, player_id, current_room, state.messages
                                )
                                if occupant_event:
                                    await websocket.send_json(
                                        {
                                            "type": "command_response",
                                            "room": current_room,
                                            "payload": occupant_event,
                                        }
                                    )

                            if arrive_text:
                                await gateway.broadcast(
                                    current_room,
                                    {
                                        "type": "room_broadcast",
                                        "room": current_room,
                                        "payload": {
                                            "scope": "room",
                                            "event": "room_message",
                                            "type": "room_message",
                                            "player": player_id,
                                            "from": None,
                                            "to": current_room,
                                            "direction": None,
                                            "text": arrive_text,
                                            "message_id": None,
                                        },
                                    },
                                    sender=websocket,
                                )
                        
                        continue

                if parse_error:
                    await websocket.send_json(
                        {
                            "type": "command_error",
                            "room": current_room,
                            "payload": {
                                "command_id": getattr(parsed, "command_id", None)
                                if parsed
                                else None,
                                "message_id": getattr(parse_error, "message_id", None),
                                "detail": str(parse_error),
                            },
                        }
                    )
                    continue

                try:
                    result = await provider.command_dispatcher.dispatch_parsed(parsed, state)
                except commands.CommandError as exc:  # type: ignore[attr-defined]
                    await websocket.send_json(
                        {
                            "type": "command_error",
                            "room": current_room,
                            "payload": {
                                "command_id": getattr(parsed, "command_id", None)
                                if parsed
                                else None,
                                "message_id": getattr(exc, "message_id", None),
                                "detail": str(exc),
                            },
                        }
                    )
                    continue

                target_room = state.player.gamloc
                occupant_event = None
                if target_room != current_room:
                    await gateway.register(target_room, websocket, announce=False)
                    await provider.presence.set_location(player_id, target_room, session_token)
                    with provider.scope.app.state.session_factory() as db:
                        repo = repositories.PlayerSessionRepository(db)
                        repo.set_room(session_token, target_room)
                        repo.mark_seen(session_token)
                        db.commit()
                    current_room = target_room
                    occupant_event = await _room_occupants_event(
                        provider.presence, player_id, current_room, state.messages
                    )

                if occupant_event:
                    result.events.append(occupant_event)

                ack_payload = {
                    "type": "command_response",
                    "room": current_room,
                    "payload": {
                        "command_id": parsed.command_id,
                        "message_id": parsed.message_id
                        or commands._command_message_id(parsed.command_id),
                        "verb": parsed.verb,
                    },
                }
                if meta:
                    ack_payload["meta"] = meta
                await websocket.send_json(ack_payload)

                for event in result.events:
                    scope = event.get("scope", "player")
                    if scope == "room":
                        envelope = {"type": "room_broadcast", "room": current_room, "payload": event}
                        if meta:
                            envelope["meta"] = meta
                        excluded_player = event.get("exclude_player")
                        excluded_sockets = set()
                        if excluded_player:
                            for token in await provider.presence.sessions_for_player(
                                excluded_player
                            ):
                                target_socket = session_connections.get(token)
                                if target_socket:
                                    excluded_sockets.add(target_socket)
                        await gateway.broadcast(
                            current_room, envelope, sender=websocket, exclude=excluded_sockets
                        )
                    elif scope == "target":
                        target_id = event.get("player")
                        if not target_id:
                            continue
                        envelope = {"type": "command_response", "room": current_room, "payload": event}
                        if meta:
                            envelope["meta"] = meta
                        for token in await provider.presence.sessions_for_player(target_id):
                            target_socket = session_connections.get(token)
                            if not target_socket:
                                continue
                            if target_socket.application_state != WebSocketState.CONNECTED:
                                continue
                            await target_socket.send_json(envelope)
                    else:
                        envelope = {"type": "command_response", "room": current_room, "payload": event}
                        if meta:
                            envelope["meta"] = meta
                        await websocket.send_json(envelope)
        except WebSocketDisconnect:
            await provider.presence.remove(session_token)
            await gateway.unregister(current_room, websocket)
        finally:
            active_players.pop(player_id, None)
            if session_connections.get(session_token) is websocket:
                session_connections.pop(session_token, None)
            # Close the persistent database session
            if persistent_session:
                persistent_session.close()

    return app


_DIRECTION_FIELDS = {
    "north": "gi_north",
    "south": "gi_south",
    "east": "gi_east",
    "west": "gi_west",
}


def _resolve_room_from_direction(current_room: int, direction: str | None, locations):
    if not direction or direction not in _DIRECTION_FIELDS:
        raise ValueError(f"Unknown direction: {direction}")

    try:
        location = locations[current_room]
    except KeyError:
        raise ValueError(f"Unknown room id: {current_room}") from None

    target_id = getattr(location, _DIRECTION_FIELDS[direction])
    if target_id < 0 or target_id not in locations:
        raise ValueError(f"No exit {direction} from location {current_room}")
    return target_id
