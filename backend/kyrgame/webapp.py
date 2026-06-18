import asyncio
import json
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Sequence

import yaml
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, literal, select
from sqlalchemy.orm import Session as OrmSession
from starlette.websockets import WebSocketState

from . import accounts, commands, constants, fixtures, models, modern_features, repositories, spellbook
from .env import load_env_file
from .gateway import RoomGateway
from .honor_mode import HonorModePolicy
from .player_lifecycle import apply_death_recovery_plan, initialize_player_for_first_login
from .player_titles import legacy_title_for_level
from .presence import PresenceService
from .rate_limit import RateLimiter
from .runtime import bootstrap_app, shutdown_app
from .session_state import (
    player_model_from_record,
    sync_active_player_state_from_db,
)
from .world.animation_tick_system import AnimationTickSystem, BrownieRoutine, ZarDragonRoutine
from .telemetry import TelemetryEventSink

logger = logging.getLogger(__name__)
DEFAULT_WS_COMMAND_RATE_LIMIT_MAX_EVENTS = 2
DEFAULT_WS_COMMAND_RATE_LIMIT_WINDOW_SECONDS = 0.5
WS_COMMAND_RATE_LIMIT_MAX_EVENTS_ENV = "KYRGAME_WS_COMMAND_RATE_LIMIT_MAX_EVENTS"
WS_COMMAND_RATE_LIMIT_WINDOW_SECONDS_ENV = "KYRGAME_WS_COMMAND_RATE_LIMIT_WINDOW_SECONDS"
GAME_VERSION = "7.20"
RECENT_PUBLIC_PLAYER_LIMIT = 5
PUBLIC_ACTIVE_PLAYER_LIMIT = 25
PUBLIC_RECENT_PLAYER_SCAN_LIMIT = 40
PUBLIC_LEADERBOARD_LIMIT = 50
PUBLIC_PLAYER_ID_LOOKUP_RATE_LIMIT_MAX_EVENTS = 30
PUBLIC_PLAYER_ID_LOOKUP_RATE_LIMIT_WINDOW_SECONDS = 60.0
SESSION_RATE_LIMIT_MAX_EVENTS = 5
SESSION_RATE_LIMIT_WINDOW_SECONDS = 1.0
REMEMBERED_SESSION_EXPIRATION_HOURS = 24 * 30
HTTP_RATE_LIMIT_MAX_CLIENT_KEYS = 1024
HTTP_RATE_LIMIT_MAX_CLIENT_KEYS_ENV = "KYRGAME_HTTP_RATE_LIMIT_MAX_CLIENT_KEYS"
TRUST_PROXY_HEADERS_ENV = "KYRGAME_TRUST_PROXY_HEADERS"
RECENT_PUBLIC_PLAYER_WINDOW = timedelta(days=7)
WIZARD_SYMBOL_MALE = "\U0001f9d9\u200d\u2642\ufe0f"
WIZARD_SYMBOL_FEMALE = "\U0001f9d9\u200d\u2640\ufe0f"
# Legacy case 1 explicitly reserves Sysop and rejects duplicate Player-IDs
# (legacy/KYRANDIA.C:260-264). The added creature names protect the visible
# NPC/object namespace now that the browser decorates those names inline.
RESERVED_PLAYER_IDS = frozenset({"sysop", "zar", "dragon", "dryad", "elf", "brownie"})
PLAYER_ID_PATTERN = re.compile(r"^[A-Za-z]{3,9}$")
FIRST_LOGIN_INTRO_STATE = "first_login_intro"
FIRST_LOGIN_ENTRY_STATE = "first_login_entry"
FIRST_LOGIN_ENTRY_STEP = 6
FIRST_LOGIN_PENDING_STATES = frozenset(
    {FIRST_LOGIN_INTRO_STATE, FIRST_LOGIN_ENTRY_STATE}
)
SESSION_KIND_GAME = "game"
SESSION_KIND_ADMIN = "admin"
VALID_SESSION_KINDS = frozenset({SESSION_KIND_GAME, SESSION_KIND_ADMIN})
# Legacy kyrand() cases 2-5 emit one intro page per submitted line.
# See legacy/KYRANDIA.C:276-293 and legacy/Dist/ELWKYRM.MSG:25-28.
FIRST_LOGIN_INTRO_MESSAGES = {
    2: "INTROA",
    3: "INTROB",
    4: "INTROC",
    5: "INTROD",
}


class LogoResponse(BaseModel):
    message: str
    lines: list[str]


class SessionRequest(BaseModel):
    player_id: str
    resume_token: str | None = None
    room_id: int | None = None
    create_player: bool = False
    gender: str | None = None
    background: str | None = None
    honor_mode: bool | None = None


class AccountAuthRequest(BaseModel):
    userid: str
    password: str
    room_id: int | None = None
    background: str | None = None
    gender: str | None = None
    honor_mode: bool | None = None
    session_kind: str = SESSION_KIND_GAME
    remember_me: bool = False


class LifecycleAdvanceRequest(BaseModel):
    input: str = ""


class LifecycleMessage(BaseModel):
    message_id: str
    text: str


class SessionLifecycle(BaseModel):
    state: str
    step: int | None = None


class AdminGrantData(BaseModel):
    roles: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class SessionData(BaseModel):
    token: str
    player_id: str
    room_id: int
    expires_at: str
    expires_in_seconds: int
    first_login: bool = False
    resumed: bool = False
    replaced_sessions: int = 0
    player_flags: int = 0
    honor_mode: bool = True
    effective_honor_mode: bool = True
    account_userid: str | None = None
    session_kind: str = SESSION_KIND_GAME
    admin_grants: AdminGrantData = Field(default_factory=AdminGrantData)
    lifecycle: SessionLifecycle | None = None
    lifecycle_messages: list[LifecycleMessage] = Field(default_factory=list)


class SessionResponse(BaseModel):
    status: str
    session: SessionData


class LogoutResponse(BaseModel):
    status: str


class AdminElfTriggerRequest(BaseModel):
    player_id: str
    room_id: int


class AdminDropItemRequest(BaseModel):
    object_ref: int | str

    model_config = ConfigDict(extra="forbid")


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


def _admin_grant_payload(grant: AdminGrant | None = None) -> dict[str, list[str]]:
    return {
        "roles": sorted(grant.roles) if grant else [],
        "flags": sorted(grant.flags) if grant else [],
    }


class PlayerAdminUpdate(BaseModel):
    altnam: str | None = None
    attnam: str | None = None
    flags: list[str] | None = None
    honor_mode: bool | None = None
    level: int | None = None
    gamloc: int | None = None
    pgploc: int | None = None
    gold: int | None = None
    spts: int | None = None
    hitpts: int | None = None
    charms: list[int] | None = None
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
    grant_all_spells: bool = False

    model_config = ConfigDict(extra="forbid")


class PlayerAdminReplacement(models.PlayerModel):
    effective_honor_mode: bool | None = None


def _cors_origins_from_env() -> list[str]:
    configured = os.getenv("KYRGAME_CORS_ORIGINS")
    if not configured:
        return ["*"]
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _honor_mode_policy(app: FastAPI) -> HonorModePolicy:
    return getattr(app.state, "honor_mode_policy", HonorModePolicy())


def _effective_honor_mode(app: FastAPI, player: object) -> bool:
    return _honor_mode_policy(app).effective_honor_mode(
        player, modern_features.FOUNTAIN_IMMEDIATE_SP_RESTORE
    )


def _player_admin_payload(app: FastAPI, player: models.PlayerModel) -> dict:
    return {
        **player.model_dump(),
        "effective_honor_mode": _effective_honor_mode(app, player),
    }


def _http_rate_limit_max_client_keys() -> int:
    configured = os.getenv(HTTP_RATE_LIMIT_MAX_CLIENT_KEYS_ENV)
    if not configured:
        return HTTP_RATE_LIMIT_MAX_CLIENT_KEYS
    try:
        parsed = int(configured)
    except ValueError:
        return HTTP_RATE_LIMIT_MAX_CLIENT_KEYS
    return max(1, parsed)


def _client_rate_limit_key(request: Request) -> str:
    client_host = request.client.host if request.client else "unknown"
    if not _truthy_env(TRUST_PROXY_HEADERS_ENV):
        return client_host

    cf_connecting_ip = request.headers.get("cf-connecting-ip")
    if cf_connecting_ip:
        client_ip = cf_connecting_ip.strip()
        if client_ip:
            return client_ip

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first_hop = forwarded_for.split(",", 1)[0].strip()
        if first_hop:
            return first_hop

    for header_name in ("x-real-ip",):
        value = request.headers.get(header_name)
        if value:
            client_ip = value.strip()
            if client_ip:
                return client_ip

    return client_host


def _http_rate_limit_entry_seen_at(entry: object) -> float:
    if isinstance(entry, tuple) and len(entry) == 2:
        return float(entry[1])
    return time.monotonic()


def _prune_http_rate_limiters(
    limiters: dict[str, tuple[RateLimiter, float] | RateLimiter],
    *,
    now: float,
    window_seconds: float,
    max_client_keys: int,
    incoming_client_key: str,
) -> None:
    stale_before = now - window_seconds
    for client_key, entry in list(limiters.items()):
        if _http_rate_limit_entry_seen_at(entry) < stale_before:
            del limiters[client_key]

    while incoming_client_key not in limiters and len(limiters) >= max_client_keys:
        oldest_key = min(limiters, key=lambda key: _http_rate_limit_entry_seen_at(limiters[key]))
        del limiters[oldest_key]


def _enforce_http_rate_limit(
    request: Request,
    *,
    state_attr: str,
    max_events: int,
    window_seconds: float,
    detail: str,
) -> None:
    limiters = getattr(request.app.state, state_attr, None)
    if limiters is None:
        limiters = {}
        setattr(request.app.state, state_attr, limiters)

    now = time.monotonic()
    client_key = _client_rate_limit_key(request)
    _prune_http_rate_limiters(
        limiters,
        now=now,
        window_seconds=window_seconds,
        max_client_keys=_http_rate_limit_max_client_keys(),
        incoming_client_key=client_key,
    )
    entry = limiters.get(client_key)
    if entry is None:
        limiter = RateLimiter(max_events=max_events, window_seconds=window_seconds)
    elif isinstance(entry, tuple):
        limiter = entry[0]
    else:
        limiter = entry
    limiters[client_key] = (limiter, now)

    if not limiter.allow(now=now):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)


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


def _load_account_admin_grants() -> dict[str, AdminGrant]:
    path_value = os.getenv("KYRGAME_ADMIN_ALLOWLIST_PATH")
    if not path_value:
        return {}

    path = Path(path_value)
    if not path.exists():
        logger.warning("Admin allowlist file does not exist: %s", path)
        return {}

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        logger.warning("Admin allowlist file is not valid YAML: %s", path)
        return {}
    admins = data.get("admins", {}) if isinstance(data, dict) else {}
    grants: dict[str, AdminGrant] = {}
    if not isinstance(admins, dict):
        return grants

    for userid, settings in admins.items():
        if not isinstance(settings, dict):
            continue
        roles = _admin_grant_string_set(settings.get("roles", []))
        flags = _admin_grant_string_set(settings.get("flags", []))
        grants[accounts.normalize_userid(str(userid))] = AdminGrant(roles=roles, flags=flags)
    return grants


def _admin_grant_string_set(value: object) -> set[str]:
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, (list, tuple, set)):
        candidates = value
    else:
        return set()
    return {item.strip() for item in candidates if isinstance(item, str) and item.strip()}


def _account_grant_for_token(app: FastAPI, token: str) -> tuple[AdminGrant | None, bool]:
    session_factory = getattr(app.state, "session_factory", None)
    if session_factory is None:
        return None, False

    with session_factory() as db:
        session_record = repositories.PlayerSessionRepository(db).get_by_token(token)
        if session_record is None or session_record.account_id is None:
            return None, session_record is not None
        if session_record.session_kind != SESSION_KIND_ADMIN:
            return None, True
        account = db.get(models.Account, session_record.account_id)
        if account is None:
            return None, True
        grants: dict[str, AdminGrant] = getattr(app.state, "account_admin_grants", {})
        return grants.get(account.userid_norm), True


def require_admin(
    request: Request,
    roles: set[AdminRole] | None = None,
    flags: set[AdminFlag] | None = None,
):
    token = _extract_bearer_token(request)
    grants: dict[str, AdminGrant] = request.app.state.admin_grants
    grant = grants.get(token)
    if grant is None:
        grant, valid_account_token = _account_grant_for_token(request.app, token)
        if grant is None:
            if valid_account_token:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Insufficient admin role",
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized admin token",
            )

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
        grant, valid_account_token = _account_grant_for_token(app, token)
        if grant is None:
            if valid_account_token:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Insufficient admin role",
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized admin token",
            )

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
    return player_model_from_record(record)


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
    spells: list[models.SpellModel],
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
    if updates.honor_mode is not None:
        data["honor_mode"] = updates.honor_mode

    if updates.gamloc is not None:
        data["gamloc"] = updates.gamloc
    if updates.pgploc is not None:
        data["pgploc"] = updates.pgploc

    level = updates.level if updates.level is not None else data["level"]
    if updates.grant_all_spells:
        # Legacy: kyraedit level edits clamp to 25 and reset HP/SP to level maxima
        # (KYRSYSP.C EDT002 @ 129-146). Admin grant-all uses the same test-friendly ceiling.
        level = constants.MAX_PLAYER_LEVEL
    data["level"] = level
    if updates.level is not None or updates.grant_all_spells:
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

    if updates.grant_all_spells:
        # Legacy: level editing in kyraedit gives full HP/SP for the new level
        # (KYRSYSP.C EDT002 @ 145-146).
        data["hitpts"] = max_hitpoints
        data["spts"] = max_spellpoints

    if updates.gold is not None:
        data["gold"] = updates.gold
    if updates.cap_gold is not None:
        data["gold"] = min(data["gold"], updates.cap_gold)
    data["gold"] = max(0, data["gold"])

    if updates.charms is not None:
        if len(updates.charms) != constants.NCHARM:
            raise HTTPException(status_code=422, detail="charms must contain six entries")
        if any(charm < 0 for charm in updates.charms):
            raise HTTPException(status_code=422, detail="charms must be zero or greater")
        data["charms"] = [int(charm) for charm in updates.charms]

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

    if updates.grant_all_spells:
        offspls = 0
        defspls = 0
        othspls = 0
        for spell in spells:
            if spell.sbkref == constants.OFFENS:
                offspls |= spell.bitdef
            elif spell.sbkref == constants.DEFENS:
                defspls |= spell.bitdef
            else:
                othspls |= spell.bitdef
        data["offspls"] = offspls
        data["defspls"] = defspls
        data["othspls"] = othspls

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
    _sync_active_player_model(app, player, original_alias=original_alias)


def _copy_player_model_fields(target: models.PlayerModel, source: models.PlayerModel) -> None:
    for field, value in source.model_dump().items():
        object.__setattr__(target, field, value)


def _sync_active_player_model(
    app: FastAPI, player: models.PlayerModel, *, original_alias: str | None = None
) -> None:
    lookup = original_alias or player.plyrid
    aliases = {lookup, player.plyrid}
    synced: list[models.PlayerModel] = []

    session_connections = getattr(app.state, "session_connections", {})
    game_socket_players = getattr(app.state, "game_socket_players", {})
    for token, active_player in _active_player_sessions(app).items():
        if active_player.plyrid in aliases:
            _copy_player_model_fields(active_player, player)
            synced.append(active_player)
            active_socket = session_connections.get(token)
            if active_socket is not None:
                game_socket_players[active_socket] = player.plyrid

    active_players = getattr(app.state, "active_players", None)
    if active_players is not None:
        candidates: list[models.PlayerModel] = []
        if lookup in active_players:
            candidates.append(active_players.pop(lookup))
        current = active_players.get(player.plyrid)
        if current is not None and all(current is not candidate for candidate in candidates):
            candidates.append(current)

        for active_player in candidates:
            _copy_player_model_fields(active_player, player)
            if all(active_player is not synced_player for synced_player in synced):
                synced.append(active_player)

        if synced:
            active_players[player.plyrid] = synced[0]

    room_scripts = getattr(app.state, "room_scripts", None)
    room_players = getattr(room_scripts, "players", None)
    if room_players is not None:
        existing = room_players.get(lookup) or room_players.get(player.plyrid)
        if existing is not None:
            replacement = synced[0] if synced else existing
            _copy_player_model_fields(replacement, player)
            if lookup != player.plyrid:
                room_players.pop(lookup, None)
            room_players[player.plyrid] = replacement


def _remove_player_from_cache(app: FastAPI, alias: str):
    cache: list[models.PlayerModel] = app.state.fixture_cache["players"]
    app.state.fixture_cache["players"] = [player for player in cache if player.plyrid != alias]
    app.state.fixture_cache["summary"]["players"] = len(app.state.fixture_cache["players"])


def _active_player_sessions(app: FastAPI) -> dict[str, models.PlayerModel]:
    sessions = getattr(app.state, "active_player_sessions", None)
    if sessions is None:
        sessions = {}
        app.state.active_player_sessions = sessions
    return sessions


def _active_player_connected_at(app: FastAPI) -> dict[str, datetime]:
    connected_at = getattr(app.state, "active_player_connected_at", None)
    if connected_at is None:
        connected_at = {}
        app.state.active_player_connected_at = connected_at
    return connected_at


def _register_active_player_session(
    app: FastAPI,
    session_token: str,
    player: models.PlayerModel,
    *,
    connected_at: datetime | None = None,
) -> None:
    _active_player_sessions(app)[session_token] = player
    _active_player_connected_at(app)[session_token] = connected_at or datetime.now(timezone.utc)
    app.state.active_players[player.plyrid] = player


def _remove_active_player_session(
    app: FastAPI, session_token: str, player_id: str | None = None
) -> None:
    sessions = _active_player_sessions(app)
    _active_player_connected_at(app).pop(session_token, None)
    removed = sessions.pop(session_token, None)
    player_key = player_id or getattr(removed, "plyrid", None)
    if not player_key:
        return

    replacement = next(
        (
            player
            for player in sessions.values()
            if getattr(player, "plyrid", None) == player_key
        ),
        None,
    )
    if replacement is not None:
        app.state.active_players[player_key] = replacement
    else:
        app.state.active_players.pop(player_key, None)


def _active_player_in_room(
    app: FastAPI, player_id: str, room_id: int
) -> models.PlayerModel | None:
    for player in _active_player_sessions(app).values():
        if player.plyrid == player_id and player.gamloc == room_id:
            return player
    active_player = getattr(app.state, "active_players", {}).get(player_id)
    if active_player is not None and active_player.gamloc == room_id:
        return active_player
    return None


def _ensure_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _spellbook_count(
    player: models.PlayerModel, spells_catalog: list[models.SpellModel]
) -> int:
    return len(spellbook.list_spellbook_spells(player, spells_catalog))


def _wizard_symbol_for_player(player: models.PlayerModel) -> str:
    return (
        WIZARD_SYMBOL_FEMALE
        if int(player.flags) & int(constants.PlayerFlag.FEMALE)
        else WIZARD_SYMBOL_MALE
    )


def _public_player_summary(
    player: models.PlayerModel,
    *,
    spells_catalog: list[models.SpellModel],
    active: bool,
    last_seen: datetime | None,
    connected_at: datetime | None = None,
    now: datetime | None = None,
) -> dict:
    normalized_last_seen = _ensure_aware_utc(last_seen)
    normalized_connected_at = _ensure_aware_utc(connected_at)
    reference_now = now or datetime.now(timezone.utc)
    connection_duration_seconds = (
        max(0, int((reference_now - normalized_connected_at).total_seconds()))
        if normalized_connected_at is not None
        else None
    )
    display_name = player.plyrid.strip() or player.altnam.strip()
    return {
        "player_id": player.plyrid,
        "display_name": display_name,
        "level": player.level,
        "rank_title": legacy_title_for_level(player.level),
        "wizard_symbol": _wizard_symbol_for_player(player),
        "spellbook_count": _spellbook_count(player, spells_catalog),
        "active": active,
        "last_seen": normalized_last_seen.isoformat() if normalized_last_seen else None,
        "connected_at": normalized_connected_at.isoformat()
        if normalized_connected_at
        else None,
        "connection_duration_seconds": connection_duration_seconds,
    }


def _latest_session_seen_by_player_id(
    sessions: list[models.PlayerSession],
) -> dict[int, datetime]:
    latest: dict[int, datetime] = {}
    for session in sessions:
        last_seen = _ensure_aware_utc(session.last_seen)
        if last_seen is None:
            continue
        current = latest.get(session.player_id)
        if current is None or last_seen > current:
            latest[session.player_id] = last_seen
    return latest


def _spellbook_count_sql_expression(
    spells_catalog: list[models.SpellModel],
):
    terms = []
    for catalog_spell in spells_catalog:
        if catalog_spell.sbkref == constants.OFFENS:
            ownership_field = models.Player.offspls
        elif catalog_spell.sbkref == constants.DEFENS:
            ownership_field = models.Player.defspls
        else:
            ownership_field = models.Player.othspls
        terms.append(
            case(
                (ownership_field.op("&")(int(catalog_spell.bitdef)) != 0, 1),
                else_=0,
            )
        )
    return sum(terms, literal(0))


def _public_admin_account_player_ids(
    db: OrmSession,
    app: FastAPI,
    candidate_player_ids: set[int] | None = None,
) -> set[int]:
    admin_userids = {
        userid_norm
        for userid_norm, grant in getattr(app.state, "account_admin_grants", {}).items()
        if grant.roles or grant.flags
    }
    if not admin_userids:
        return set()
    if candidate_player_ids is not None and not candidate_player_ids:
        return set()

    conditions = [models.Account.userid_norm.in_(admin_userids)]
    if candidate_player_ids is not None:
        conditions.append(models.Account.player_id.in_(candidate_player_ids))

    return {
        int(player_id)
        for player_id in db.scalars(select(models.Account.player_id).where(*conditions))
        if player_id is not None
    }


def _session_player_ids_by_token(
    db: OrmSession, session_tokens: set[str]
) -> dict[str, int]:
    if not session_tokens:
        return {}
    return {
        session_token: int(player_id)
        for session_token, player_id in db.execute(
            select(models.PlayerSession.session_token, models.PlayerSession.player_id).where(
                models.PlayerSession.session_token.in_(session_tokens),
                models.PlayerSession.session_kind == SESSION_KIND_GAME,
            )
        )
    }


def _public_runtime_sessions(
    db: OrmSession,
    app: FastAPI,
    hidden_admin_player_ids: set[int],
) -> dict[str, models.PlayerModel]:
    runtime_sessions = _active_player_sessions(app)
    hidden_admin_session_tokens = {
        session_token
        for session_token, player_id in _session_player_ids_by_token(
            db, set(runtime_sessions)
        ).items()
        if player_id in hidden_admin_player_ids
    }
    return {
        session_token: player
        for session_token, player in runtime_sessions.items()
        if session_token not in hidden_admin_session_tokens
    }


def _public_leaderboard_player_statement(
    spells_catalog: list[models.SpellModel],
    exclude_player_ids: set[int] | None = None,
):
    spellbook_count_expr = _spellbook_count_sql_expression(spells_catalog).label(
        "public_spellbook_count"
    )
    statement = select(models.Player, spellbook_count_expr)
    if exclude_player_ids:
        statement = statement.where(~models.Player.id.in_(exclude_player_ids))

    return statement.order_by(
        models.Player.level.desc(),
        spellbook_count_expr.desc(),
        func.lower(models.Player.plyrid).asc(),
        models.Player.plyrid.asc(),
    ).limit(PUBLIC_LEADERBOARD_LIMIT)


def _latest_session_seen_for_player_ids(
    db: OrmSession, player_ids: set[int]
) -> dict[int, datetime]:
    if not player_ids:
        return {}

    rows = db.execute(
        select(models.PlayerSession.player_id, func.max(models.PlayerSession.last_seen))
        .where(
            models.PlayerSession.player_id.in_(player_ids),
            models.PlayerSession.session_kind == SESSION_KIND_GAME,
            models.PlayerSession.hidden_from_activity.is_(False),
        )
        .group_by(models.PlayerSession.player_id)
    )
    return {
        int(player_id): seen
        for player_id, last_seen in rows
        if (seen := _ensure_aware_utc(last_seen)) is not None
    }


def _recent_session_seen_rows(
    db: OrmSession,
    *,
    since: datetime,
    limit: int,
    exclude_player_ids: set[int] | None = None,
) -> list[tuple[int, datetime]]:
    latest_seen = func.max(models.PlayerSession.last_seen)
    conditions = [
        models.PlayerSession.last_seen >= since,
        models.PlayerSession.session_kind == SESSION_KIND_GAME,
        models.PlayerSession.hidden_from_activity.is_(False),
    ]
    if exclude_player_ids:
        conditions.append(~models.PlayerSession.player_id.in_(exclude_player_ids))
    rows = db.execute(
        select(models.PlayerSession.player_id, latest_seen)
        .where(*conditions)
        .group_by(models.PlayerSession.player_id)
        .order_by(latest_seen.desc(), models.PlayerSession.player_id.asc())
        .limit(limit)
    )
    return [
        (int(player_id), seen)
        for player_id, last_seen in rows
        if (seen := _ensure_aware_utc(last_seen)) is not None
    ]


def _player_records_by_id(
    db: OrmSession, player_ids: set[int]
) -> dict[int, models.Player]:
    if not player_ids:
        return {}
    return {
        int(record.id): record
        for record in db.scalars(select(models.Player).where(models.Player.id.in_(player_ids))).all()
        if record.id is not None
    }


async def _disconnect_sessions(app: FastAPI, tokens: list[str]):
    connections = app.state.session_connections
    for token in tokens:
        _remove_active_player_session(app, token)
        socket = connections.pop(token, None)
        if socket is not None:
            getattr(app.state, "game_socket_players", {}).pop(socket, None)
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


def _admin_room_summary(provider: FixtureProvider, room_id: int | None):
    if room_id is None:
        return None
    location = provider.location_index.get(room_id)
    if location is None:
        return {"id": room_id, "brief": None, "object_landing": None}
    return {
        "id": location.id,
        "brief": location.brfdes,
        "object_landing": location.objlds,
    }


def _admin_object_article(obj: models.GameObjectModel) -> str:
    article = "An" if "NEEDAN" in obj.flags or obj.name[:1].lower() in "aeiou" else "A"
    return f"{article} {obj.name}"


def _admin_drop_announcement(
    location: models.LocationModel, obj: models.GameObjectModel
) -> dict[str, object]:
    # Modeled after ashtre() spawning a shard with ASHM01 before pgmlobj().
    # Source: legacy/KYRROUS.C:707-727; message catalog ASHM01.
    return {
        "scope": "room",
        "event": "room_message",
        "type": "room_message",
        "message_id": None,
        "text": f"***\r\n{_admin_object_article(obj)} suddenly appears {location.objlds}!",
        "source": "admin_drop_item",
        "modeled_after_message_id": "ASHM01",
        "object_id": obj.id,
        "object_name": obj.name,
        "location": location.id,
    }


def _admin_room_objects_payload(
    location: models.LocationModel,
    objects_by_id: dict[int, models.GameObjectModel],
) -> dict[str, object]:
    return {
        "room_id": location.id,
        "room": {
            "id": location.id,
            "name": location.brfdes,
            "object_landing": location.objlds,
        },
        "room_objects": commands.room_object_entries(location, objects_by_id),
    }


def _admin_delete_announcement(
    location: models.LocationModel,
    object_id: int,
    objects_by_id: dict[int, models.GameObjectModel],
) -> dict[str, object]:
    obj = objects_by_id.get(object_id)
    object_name = obj.name if obj else f"object {object_id}"
    # Modeled after spl042 mower removing ground objects with inline prf()+sndloc().
    # Source: legacy/KYRSPEL.C:889-904.
    return {
        "scope": "room",
        "event": "room_message",
        "type": "room_message",
        "message_id": None,
        "text": f"***\rThe {object_name} {location.brfdes} vanishes!\r",
        "source": "admin_delete_item",
        "modeled_after_spell": "mower",
        "object_id": object_id,
        "object_name": object_name,
        "location": location.id,
    }


def _find_room_containing_object(provider: FixtureProvider, object_id: int) -> int | None:
    for location in sorted(provider.location_index.values(), key=lambda loc: loc.id):
        if object_id in location.objects:
            return location.id
    return None


def _ticks_until_next_routine(
    sequence: Sequence[str], routine_index: int, target_name: str
) -> int | None:
    if not sequence:
        return None
    start = routine_index % len(sequence)
    for offset in range(len(sequence)):
        if sequence[(start + offset) % len(sequence)] == target_name:
            return offset + 1
    return None


def _successful_gem_spawns_until_random(gem_counter: int) -> int:
    # Legacy gemakr() randomizes only when gemctr is already 10 at the start
    # of a successful placement. Source: legacy/KYRANIM.C:435-443.
    normalized_counter = max(0, min(gem_counter, 10))
    return max(1, 11 - normalized_counter)


def _admin_mob_snapshot(provider: FixtureProvider):
    animation_system: AnimationTickSystem | None = getattr(
        provider.scope.app.state, "animation_tick_system", None
    )
    if animation_system is None:
        raise HTTPException(status_code=503, detail="Animation system is not initialized")

    state = animation_system.state
    tick_scheduler = getattr(provider.scope.app.state, "tick_scheduler", None)
    tick_seconds = float(getattr(tick_scheduler, "tick_seconds", 1.0))
    routine_interval_seconds = 15.0 * tick_seconds
    routine_sequence = AnimationTickSystem.routine_sequence()
    full_cycle_interval_seconds = routine_interval_seconds * len(routine_sequence)
    brownie_interval_seconds = full_cycle_interval_seconds
    next_gem_attempt_ticks = _ticks_until_next_routine(
        routine_sequence, state.routine_index, "gemakr"
    )
    next_gem_attempt_seconds = (
        None
        if next_gem_attempt_ticks is None
        else routine_interval_seconds * next_gem_attempt_ticks
    )
    successful_spawns_until_random = _successful_gem_spawns_until_random(state.gem_counter)
    brownie_path = BrownieRoutine.path()
    next_brownie_room_id = BrownieRoutine.path_room(state.brownie_path_index)

    dryad_object_room_id = _find_room_containing_object(provider, 45)
    dryad_state_room_id = state.dryad_location
    dryad_room_id = (
        dryad_object_room_id if dryad_object_room_id is not None else dryad_state_room_id
    )
    # Normalize the primary dryad room value so downstream snapshot fields use
    # the fallback-backed room id even when the object lookup is temporarily out
    # of sync with animation state.
    dryad_object_room_id = dryad_room_id
    dragon_room_id = _find_room_containing_object(provider, 52)
    dragon_state_room_id = state.zar_location
    dragon_display_room_id = (
        dragon_room_id if dragon_room_id is not None else dragon_state_room_id
    )

    # Legacy mob state comes from KYRANIM.C globals and routines:
    # dloc/dryads lines 67,326-348; bpath/bpidx/bloc/browns lines 69-80,393-426;
    # zloc/zstat/zattck/chkzar/zarapp lines 81-84,154-173,452-459.
    return {
        "animation": {
            "routine_index": state.routine_index,
            "next_routine": animation_system.next_routine_name(),
            "routine_sequence": list(routine_sequence),
            "tick_seconds": tick_seconds,
            "animation_tick_interval_seconds": routine_interval_seconds,
            "brownie_routine_interval_seconds": brownie_interval_seconds,
            "brownie_full_path_interval_seconds": brownie_interval_seconds * len(brownie_path),
            "gem_spawn_interval_seconds": full_cycle_interval_seconds,
            "next_gem_spawn_attempt_seconds": next_gem_attempt_seconds,
            "gem_counter": state.gem_counter,
            "successful_spawns_until_random_gem": successful_spawns_until_random,
            "next_successful_gem_is_random": state.gem_counter == 10,
            "last_gem_attempt_room_id": state.gem_last_attempt_room_id,
            "last_gem_attempt_status": state.gem_last_attempt_status,
            "last_gem_attempt_object_count": state.gem_last_attempt_object_count,
            "last_gem_spawn_room_id": state.gem_last_spawn_room_id,
            "last_gem_spawn_object_id": state.gem_last_spawn_object_id,
            "last_gem_spawn_object_name": state.gem_last_spawn_object_name,
            "legacy_source": "legacy/KYRANIM.C:116-133",
        },
        "mobs": [
            {
                "id": "dryad",
                "name": "Dryad",
                "kind": "persistent_room_object",
                "status": "present" if dryad_object_room_id is not None else "unknown",
                "object_id": 45,
                "room_id": dryad_object_room_id,
                "state_room_id": state.dryad_location,
                "object_room_id": dryad_object_room_id,
                "room": _admin_room_summary(provider, dryad_object_room_id),
                "legacy_source": "legacy/KYRANIM.C:326-348",
            },
            {
                "id": "brownie",
                "name": "Brownie",
                "kind": "path_encounter",
                "status": "last_checked",
                "room_id": state.brownie_location,
                "room": _admin_room_summary(provider, state.brownie_location),
                "path_index": state.brownie_path_index % len(brownie_path),
                "path_length": len(brownie_path),
                "next_room_id": next_brownie_room_id,
                "next_room": _admin_room_summary(provider, next_brownie_room_id),
                "routine_interval_seconds": brownie_interval_seconds,
                "full_path_interval_seconds": brownie_interval_seconds * len(brownie_path),
                "legacy_source": "legacy/KYRANIM.C:69-80,393-426",
            },
            {
                "id": "elf",
                "name": "Elf",
                "kind": "transient_encounter",
                "status": "last_seen" if state.elf_last_room is not None else "between_encounters",
                "room_id": state.elf_last_room,
                "room": _admin_room_summary(provider, state.elf_last_room),
                "next_outcome": "gold" if state.elf_reward_next else "hint",
                "hint_index": state.elf_hint_index,
                "legacy_source": "legacy/KYRANIM.C:352-389",
            },
            {
                "id": "gem_spawner",
                "name": "Gem spawner",
                "kind": "world_spawn_routine",
                "status": "next_tick" if next_gem_attempt_ticks == 1 else "waiting",
                "room_id": state.gem_last_spawn_room_id,
                "room": _admin_room_summary(provider, state.gem_last_spawn_room_id),
                "gem_counter": state.gem_counter,
                "next_attempt_seconds": next_gem_attempt_seconds,
                "routine_interval_seconds": full_cycle_interval_seconds,
                "successful_spawns_until_random_gem": successful_spawns_until_random,
                "next_successful_gem_is_random": state.gem_counter == 10,
                "last_attempt_room_id": state.gem_last_attempt_room_id,
                "last_attempt_room": _admin_room_summary(
                    provider, state.gem_last_attempt_room_id
                ),
                "last_attempt_status": state.gem_last_attempt_status,
                "last_attempt_object_count": state.gem_last_attempt_object_count,
                "last_spawn_room_id": state.gem_last_spawn_room_id,
                "last_spawn_room": _admin_room_summary(provider, state.gem_last_spawn_room_id),
                "last_spawn_object_id": state.gem_last_spawn_object_id,
                "last_spawn_object_name": state.gem_last_spawn_object_name,
                "legacy_source": "legacy/KYRANIM.C:429-449",
            },
            {
                "id": "dragon",
                "name": "Zar",
                "kind": "persistent_room_object",
                "status": "present" if dragon_room_id is not None else "state_only",
                "object_id": 52,
                "room_id": dragon_display_room_id,
                "state_room_id": dragon_state_room_id,
                "object_room_id": dragon_room_id,
                "room": _admin_room_summary(provider, dragon_display_room_id),
                "counter": state.zar_counter,
                "attack_index": state.zar_attack_index % 4,
                "next_attack": ZarDragonRoutine.attack_name(state.zar_attack_index),
                "home_room_id": 302,
                "legacy_source": "legacy/KYRANIM.C:155-263,453-459",
            },
        ],
    }


async def _dispatch_animation_events(app: FastAPI, events) -> None:
    dispatcher = getattr(app.state, "dispatch_animation_event", None)
    if dispatcher is None:
        raise HTTPException(status_code=503, detail="Animation dispatcher is not initialized")

    for event in events:
        maybe_awaitable = dispatcher(event)
        if asyncio.iscoroutine(maybe_awaitable):
            await maybe_awaitable


def _elf_trigger_outcome(events) -> str:
    for event in events:
        target_message_id = event.payload.get("target_message_id")
        if target_message_id == "EMSG01":
            return "gold"
        if isinstance(target_message_id, str) and target_message_id.startswith("EHINT"):
            return "hint"
    return "no_active_player"


def _persist_first_login_player(
    db: OrmSession,
    player_id: str,
    template: models.PlayerModel,
    *,
    female: bool = False,
    honor_mode: bool = True,
) -> models.Player:
    player_model = template.model_copy(deep=True)
    initialize_player_for_first_login(
        player_model,
        player_id=player_id,
        uidnam=player_id[: constants.UIDSIZ],
        birthstone_picker=lambda low, high: low + secrets.randbelow(high - low),
        female=female,
        room_id=0,
    )
    player_model.honor_mode = honor_mode
    player = models.Player(**player_model.model_dump())
    db.add(player)
    db.flush([player])
    return player


def _find_player_record(db: OrmSession, player_id: str) -> models.Player | None:
    record = db.scalar(select(models.Player).where(models.Player.plyrid == player_id))
    if record is not None:
        return record

    record = _find_player_record_casefold(db, player_id)
    if record is not None:
        return record

    uid_alias = player_id[: constants.UIDSIZ]
    record = db.scalar(select(models.Player).where(models.Player.uidnam == uid_alias))
    if record is not None:
        return record

    canonical_id = player_id[: constants.ALSSIZ]
    if canonical_id != player_id:
        return db.scalar(select(models.Player).where(models.Player.plyrid == canonical_id))
    return None


def _find_player_record_casefold(db: OrmSession, player_id: str) -> models.Player | None:
    return db.scalar(
        select(models.Player).where(func.lower(models.Player.plyrid) == player_id.lower())
    )


def _is_female_creation_choice(*values: str | None) -> bool:
    return any((value or "").strip().lower() in {"lady", "sorceress"} for value in values)


def _canonical_first_login_player_id(raw_player_id: str) -> str:
    trimmed = raw_player_id.strip()
    if not PLAYER_ID_PATTERN.fullmatch(trimmed):
        raise ValueError("bad_player_id")
    return trimmed.lower().capitalize()


def _validated_compat_first_login_player_id(raw_player_id: str) -> str:
    trimmed = raw_player_id.strip()
    if not PLAYER_ID_PATTERN.fullmatch(trimmed):
        raise ValueError("bad_player_id")
    return trimmed


def _legacy_message_entry(
    messages: models.MessageBundleModel, message_id: str, *args: object
) -> dict[str, str]:
    text = messages.messages.get(message_id, "")
    if args:
        try:
            text = text % args
        except TypeError:
            pass
    return {"message_id": message_id, "text": text}


def _legacy_auth_error(
    request: Request,
    *,
    status_code: int,
    message_ids: list[str],
) -> HTTPException:
    messages = request.app.state.fixture_cache["messages"]
    return HTTPException(
        status_code=status_code,
        detail={
            "message_ids": message_ids,
            "messages": [_legacy_message_entry(messages, message_id) for message_id in message_ids],
        },
    )


def _ensure_first_login_player_id_available(
    db: OrmSession, request: Request, player_id: str
) -> None:
    if player_id.lower() in RESERVED_PLAYER_IDS or _find_player_record_casefold(db, player_id):
        raise _legacy_auth_error(
            request,
            status_code=status.HTTP_409_CONFLICT,
            message_ids=["NTGOOD", "B4PLA2"],
        )


def _first_login_lifecycle_messages(
    messages: models.MessageBundleModel, player_id: str
) -> list[dict[str, str]]:
    return [
        _legacy_message_entry(messages, "GOODPD", player_id),
    ]


def _current_first_login_lifecycle_messages(
    messages: models.MessageBundleModel,
    player_id: str,
    lifecycle_state: str | None,
    lifecycle_step: int | None,
) -> list[dict[str, str]]:
    if lifecycle_state != FIRST_LOGIN_INTRO_STATE:
        return []
    if lifecycle_step == 2:
        return _first_login_lifecycle_messages(messages, player_id)
    message_id = FIRST_LOGIN_INTRO_MESSAGES.get((lifecycle_step or 2) - 1)
    if message_id:
        return [_intro_lifecycle_message(messages, message_id)]
    return []


def _lifecycle_payload(session_record: models.PlayerSession) -> dict[str, object] | None:
    if not session_record.lifecycle_state:
        return None
    return {
        "state": session_record.lifecycle_state,
        "step": session_record.lifecycle_step,
    }


def _intro_lifecycle_message(
    messages: models.MessageBundleModel, message_id: str
) -> dict[str, str]:
    if message_id == "INTROD":
        return _legacy_message_entry(messages, message_id, GAME_VERSION)
    return _legacy_message_entry(messages, message_id)


def _active_player_flags(app: FastAPI) -> dict[str, int]:
    flags: dict[str, int] = {}
    for player in getattr(app.state, "active_players", {}).values():
        flags[player.plyrid] = int(player.flags)
    for player in _active_player_sessions(app).values():
        flags[player.plyrid] = int(player.flags)
    return flags


def _env_int(name: str, *, default: int, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        logger.warning("Ignoring invalid integer for %s: %r", name, raw)
        return default
    if parsed < minimum:
        logger.warning("Ignoring out-of-range integer for %s: %r", name, raw)
        return default
    return parsed


def _env_float(name: str, *, default: float, minimum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = float(raw)
    except ValueError:
        logger.warning("Ignoring invalid float for %s: %r", name, raw)
        return default
    if parsed < minimum:
        logger.warning("Ignoring out-of-range float for %s: %r", name, raw)
        return default
    return parsed


def _websocket_command_rate_limiter() -> RateLimiter:
    return RateLimiter(
        max_events=_env_int(
            WS_COMMAND_RATE_LIMIT_MAX_EVENTS_ENV,
            default=DEFAULT_WS_COMMAND_RATE_LIMIT_MAX_EVENTS,
            minimum=1,
        ),
        window_seconds=_env_float(
            WS_COMMAND_RATE_LIMIT_WINDOW_SECONDS_ENV,
            default=DEFAULT_WS_COMMAND_RATE_LIMIT_WINDOW_SECONDS,
            minimum=0.001,
        ),
    )


def _normalize_session_kind(value: str | None) -> str:
    session_kind = (value or SESSION_KIND_GAME).strip().lower()
    if session_kind not in VALID_SESSION_KINDS:
        raise HTTPException(status_code=422, detail="Unsupported session kind")
    return session_kind


def _session_payload(
    session_record: models.PlayerSession,
    player: models.Player,
    room_id: int,
    *,
    first_login: bool = False,
    resumed: bool = False,
    replaced_sessions: int = 0,
    lifecycle_messages: list[dict[str, str]] | None = None,
    account: models.Account | None = None,
    admin_grant: AdminGrant | None = None,
    honor_mode_policy: HonorModePolicy | None = None,
):
    expires_at = _as_utc(session_record.expires_at)
    now = datetime.now(timezone.utc)
    policy = honor_mode_policy or HonorModePolicy()
    return {
        "token": session_record.session_token,
        "player_id": player.plyrid,
        "room_id": room_id,
        "expires_at": expires_at.isoformat(),
        "expires_in_seconds": max(0, int((expires_at - now).total_seconds())),
        "first_login": first_login,
        "resumed": resumed,
        "replaced_sessions": replaced_sessions,
        "player_flags": int(player.flags),
        "honor_mode": bool(player.honor_mode),
        "effective_honor_mode": policy.effective_honor_mode(
            player, modern_features.FOUNTAIN_IMMEDIATE_SP_RESTORE
        ),
        "account_userid": account.userid if account is not None else None,
        "session_kind": session_record.session_kind,
        "admin_grants": _admin_grant_payload(admin_grant),
        "lifecycle": _lifecycle_payload(session_record),
        "lifecycle_messages": lifecycle_messages or [],
    }


def _pending_first_login_session(
    sessions: list[models.PlayerSession],
) -> models.PlayerSession | None:
    return next(
        (
            active_session
            for active_session in sessions
            if active_session.lifecycle_state in FIRST_LOGIN_PENDING_STATES
        ),
        None,
    )


def _entry_room_for_player(player: models.Player) -> int:
    if player.gamloc >= 0:
        return player.gamloc
    if player.pgploc >= 0:
        return player.pgploc
    return 0


def _set_player_entry_location(player: models.Player, room_id: int) -> None:
    # Legacy remvgp() stores the previous room in pgploc before gamloc=-1, and
    # login re-enters through entrgp(). See legacy/KYRUTIL.C:225-245 and
    # legacy/KYRANDIA.C:204-209.
    player.gamloc = room_id
    player.pgploc = room_id


async def _issue_player_session(
    *,
    request: Request,
    db: OrmSession,
    player: models.Player,
    account: models.Account | None = None,
    session_kind: str = SESSION_KIND_GAME,
    room_id: int | None = None,
    lifecycle_state: str | None = None,
    lifecycle_step: int | None = None,
    lifecycle_messages: list[dict[str, str]] | None = None,
    first_login: bool = False,
    resumed: bool = False,
    status_code: int = status.HTTP_201_CREATED,
    remember_me: bool = False,
) -> JSONResponse:
    repo = repositories.PlayerSessionRepository(db)
    target_room = _entry_room_for_player(player) if room_id is None else room_id
    if session_kind == SESSION_KIND_GAME and (
        room_id is not None
        or player.gamloc != target_room
        or player.pgploc != target_room
    ):
        _set_player_entry_location(player, target_room)

    replaced_tokens: list[str] = []
    if not hasattr(request.app.state, "session_replacement_lock"):
        request.app.state.session_replacement_lock = asyncio.Lock()

    async with request.app.state.session_replacement_lock:
        active_sessions = repo.list_active(player.id, session_kind=session_kind)
        if session_kind == SESSION_KIND_GAME and lifecycle_state is None:
            pending_lifecycle = _pending_first_login_session(active_sessions)
            if pending_lifecycle is None:
                pending_lifecycle = _pending_first_login_session(repo.list_active(player.id))
            if pending_lifecycle is not None:
                lifecycle_state = pending_lifecycle.lifecycle_state
                lifecycle_step = pending_lifecycle.lifecycle_step
                target_room = pending_lifecycle.room_id
                _set_player_entry_location(player, target_room)
                lifecycle_messages = _current_first_login_lifecycle_messages(
                    request.app.state.fixture_cache["messages"],
                    player.plyrid,
                    lifecycle_state,
                    lifecycle_step,
                )
                if pending_lifecycle.session_kind != SESSION_KIND_GAME:
                    pending_lifecycle.lifecycle_state = None
                    pending_lifecycle.lifecycle_step = None

        replaced_tokens = repo.deactivate_all(player.id, session_kind=session_kind)
        token = secrets.token_urlsafe(24)
        hidden_from_activity = session_kind != SESSION_KIND_GAME
        expiration_hours = (
            REMEMBERED_SESSION_EXPIRATION_HOURS
            if session_kind == SESSION_KIND_GAME and remember_me
            else repositories.DEFAULT_SESSION_EXPIRATION_HOURS
        )
        session_record = repo.create_session(
            player_id=player.id,
            account_id=account.id if account is not None else None,
            session_token=token,
            room_id=target_room,
            expiration_hours=expiration_hours,
            lifecycle_state=lifecycle_state,
            lifecycle_step=lifecycle_step,
            session_kind=session_kind,
            hidden_from_activity=hidden_from_activity,
        )
        db.commit()

    await _disconnect_sessions(request.app, replaced_tokens)

    if (
        session_kind == SESSION_KIND_GAME
        and not hidden_from_activity
        and session_record.lifecycle_state not in FIRST_LOGIN_PENDING_STATES
    ):
        await request.app.state.presence.set_location(player.plyrid, target_room, token)

    admin_grant = None
    if account is not None and session_kind == SESSION_KIND_ADMIN:
        admin_grant = getattr(request.app.state, "account_admin_grants", {}).get(
            account.userid_norm
        )

    body = {
        "status": "recovered" if resumed else "created",
        "session": _session_payload(
            session_record,
            player,
            target_room,
            first_login=first_login,
            resumed=resumed,
            replaced_sessions=len(replaced_tokens),
            lifecycle_messages=lifecycle_messages,
            account=account,
            admin_grant=admin_grant,
            honor_mode_policy=_honor_mode_policy(request.app),
        ),
    }
    return JSONResponse(content=body, status_code=status_code)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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


@auth_router.post("/register", response_model=SessionResponse)
async def register_account(
    payload: AccountAuthRequest,
    request: Request,
    db: Annotated[OrmSession, Depends(get_db_session)],
):
    _enforce_http_rate_limit(
        request,
        state_attr="session_rate_limiters",
        max_events=SESSION_RATE_LIMIT_MAX_EVENTS,
        window_seconds=SESSION_RATE_LIMIT_WINDOW_SECONDS,
        detail="Too many session creation attempts. Please try again later.",
    )
    if not payload.password:
        raise HTTPException(status_code=422, detail="Password is required")

    session_kind = _normalize_session_kind(payload.session_kind)
    try:
        canonical_userid = _canonical_first_login_player_id(payload.userid)
    except ValueError:
        raise _legacy_auth_error(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            message_ids=["BADPID", "B4PLA2"],
        )

    account_repo = repositories.AccountRepository(db)
    userid_norm = accounts.normalize_userid(canonical_userid)
    if account_repo.get_by_userid_norm(userid_norm) is not None:
        raise HTTPException(status_code=409, detail="User ID already has an account")

    if not hasattr(request.app.state, "player_claim_lock"):
        request.app.state.player_claim_lock = asyncio.Lock()

    async with request.app.state.player_claim_lock:
        player = _find_player_record(db, canonical_userid)
        first_login = False
        lifecycle_messages: list[dict[str, str]] = []
        lifecycle_state: str | None = None
        lifecycle_step: int | None = None

        if player is None:
            _ensure_first_login_player_id_available(db, request, canonical_userid)
            player = _persist_first_login_player(
                db,
                canonical_userid,
                request.app.state.fixture_cache["player_template"],
                female=_is_female_creation_choice(payload.background, payload.gender),
                honor_mode=_honor_mode_policy(request.app).stored_creation_value(
                    payload.honor_mode
                ),
            )
            first_login = True
            lifecycle_messages = _first_login_lifecycle_messages(
                request.app.state.fixture_cache["messages"], player.plyrid
            )
            lifecycle_state = FIRST_LOGIN_INTRO_STATE
            lifecycle_step = 2
        else:
            existing_owner = db.scalar(
                select(models.Account).where(models.Account.player_id == player.id)
            )
            if existing_owner is not None:
                raise HTTPException(status_code=409, detail="Player ID already has an account")

        account = account_repo.create_account(
            userid=player.plyrid,
            userid_norm=accounts.normalize_userid(player.plyrid),
            password_hash=accounts.hash_password(payload.password),
            player_id=player.id,
        )
        db.flush([account])

    return await _issue_player_session(
        request=request,
        db=db,
        player=player,
        account=account,
        session_kind=session_kind,
        lifecycle_state=lifecycle_state,
        lifecycle_step=lifecycle_step,
        lifecycle_messages=lifecycle_messages,
        first_login=first_login,
        remember_me=payload.remember_me,
    )


@auth_router.post("/login", response_model=SessionResponse)
async def login_account(
    payload: AccountAuthRequest,
    request: Request,
    db: Annotated[OrmSession, Depends(get_db_session)],
):
    _enforce_http_rate_limit(
        request,
        state_attr="session_rate_limiters",
        max_events=SESSION_RATE_LIMIT_MAX_EVENTS,
        window_seconds=SESSION_RATE_LIMIT_WINDOW_SECONDS,
        detail="Too many session creation attempts. Please try again later.",
    )
    session_kind = _normalize_session_kind(payload.session_kind)
    account = repositories.AccountRepository(db).get_by_userid_norm(
        accounts.normalize_userid(payload.userid)
    )
    if account is None or account.disabled:
        raise HTTPException(status_code=401, detail="Invalid userid or password")

    verification = accounts.verify_password(payload.password, account.password_hash)
    if not verification.valid:
        raise HTTPException(status_code=401, detail="Invalid userid or password")
    if verification.updated_hash:
        account.password_hash = verification.updated_hash

    player = db.get(models.Player, account.player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Bound player not found")

    return await _issue_player_session(
        request=request,
        db=db,
        player=player,
        account=account,
        session_kind=session_kind,
        room_id=payload.room_id,
        remember_me=payload.remember_me,
    )


@auth_router.post("/session", response_model=SessionResponse)
async def start_session(
    payload: SessionRequest,
    request: Request,
    db: Annotated[OrmSession, Depends(get_db_session)],
):
    _enforce_http_rate_limit(
        request,
        state_attr="session_rate_limiters",
        max_events=SESSION_RATE_LIMIT_MAX_EVENTS,
        window_seconds=SESSION_RATE_LIMIT_WINDOW_SECONDS,
        detail="Too many session creation attempts. Please try again later.",
    )

    template = request.app.state.fixture_cache["player_template"]
    repo = repositories.PlayerSessionRepository(db)
    if not hasattr(request.app.state, 'player_claim_lock'):
        request.app.state.player_claim_lock = asyncio.Lock()

    lifecycle_messages: list[dict[str, str]] = []
    lifecycle_state: str | None = None
    lifecycle_step: int | None = None
    player_claim_lock = request.app.state.player_claim_lock
    player_claim_lock_acquired = False

    try:
        if payload.create_player:
            await player_claim_lock.acquire()
            player_claim_lock_acquired = True
            try:
                canonical_player_id = _canonical_first_login_player_id(payload.player_id)
            except ValueError:
                raise _legacy_auth_error(
                    request,
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    message_ids=["BADPID", "B4PLA2"],
                )
            _ensure_first_login_player_id_available(db, request, canonical_player_id)
            player = _persist_first_login_player(
                db,
                canonical_player_id,
                template,
                female=_is_female_creation_choice(payload.background, payload.gender),
                honor_mode=_honor_mode_policy(request.app).stored_creation_value(
                    payload.honor_mode
                ),
            )
            first_login = True
            lifecycle_messages = _first_login_lifecycle_messages(
                request.app.state.fixture_cache["messages"], player.plyrid
            )
            lifecycle_state = FIRST_LOGIN_INTRO_STATE
            lifecycle_step = 2
        else:
            player = _find_player_record(db, payload.player_id)
            first_login = False
            if player is None:
                try:
                    _validated_compat_first_login_player_id(payload.player_id)
                except ValueError:
                    raise _legacy_auth_error(
                        request,
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        message_ids=["BADPID", "B4PLA2"],
                    )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Player-ID not found. Create Character to claim it.",
                )
            elif payload.room_id is not None:
                _set_player_entry_location(player, payload.room_id)

        room_id = _entry_room_for_player(player)

        replaced_tokens: list[str] = []
        session_record: models.PlayerSession | None = None
        session_account: models.Account | None = None
        resumed = False
        status_code = status.HTTP_201_CREATED

        if payload.resume_token:
            existing = repo.get_by_token(payload.resume_token)
            if not existing or existing.player_id != player.id:
                raise HTTPException(status_code=404, detail="Session not found or expired")
            if existing.account_id is not None:
                session_account = db.get(models.Account, existing.account_id)
            repo.mark_seen(payload.resume_token)
            db.commit()
            if player_claim_lock_acquired:
                player_claim_lock.release()
                player_claim_lock_acquired = False
            room_id = existing.room_id
            token = existing.session_token
            session_record = existing
            lifecycle_messages = _current_first_login_lifecycle_messages(
                request.app.state.fixture_cache["messages"],
                player.plyrid,
                existing.lifecycle_state,
                existing.lifecycle_step,
            )
            resumed = True
            status_code = status.HTTP_200_OK
        else:
            # One active game session is allowed per player. A fresh login replaces
            # any existing session for that same player, while other player accounts
            # remain unaffected.
            if not hasattr(request.app.state, 'session_replacement_lock'):
                request.app.state.session_replacement_lock = asyncio.Lock()

            async with request.app.state.session_replacement_lock:
                active_sessions = repo.list_active(player.id, session_kind=SESSION_KIND_GAME)
                pending_lifecycle = next(
                    (
                        active_session
                        for active_session in active_sessions
                        if active_session.lifecycle_state in FIRST_LOGIN_PENDING_STATES
                    ),
                    None,
                )
                if pending_lifecycle is not None and lifecycle_state is None:
                    lifecycle_state = pending_lifecycle.lifecycle_state
                    lifecycle_step = pending_lifecycle.lifecycle_step
                    room_id = pending_lifecycle.room_id
                    _set_player_entry_location(player, room_id)
                    lifecycle_messages = _current_first_login_lifecycle_messages(
                        request.app.state.fixture_cache["messages"],
                        player.plyrid,
                        lifecycle_state,
                        lifecycle_step,
                    )
                replaced_tokens = repo.deactivate_all(player.id, session_kind=SESSION_KIND_GAME)
                token = secrets.token_urlsafe(24)
                _set_player_entry_location(player, room_id)
                session_record = repo.create_session(
                    player_id=player.id,
                    session_token=token,
                    room_id=room_id,
                    lifecycle_state=lifecycle_state,
                    lifecycle_step=lifecycle_step,
                )
                db.commit()
            if player_claim_lock_acquired:
                player_claim_lock.release()
                player_claim_lock_acquired = False
    except Exception:
        if player_claim_lock_acquired:
            player_claim_lock.release()
        raise

    if session_record is None:
        raise HTTPException(status_code=500, detail="Session creation failed")

    if not payload.resume_token:
        # Commit happened inside the lock, now clean up old connections
        await _disconnect_sessions(request.app, replaced_tokens)

    if session_record.lifecycle_state not in FIRST_LOGIN_PENDING_STATES:
        await request.app.state.presence.set_location(player.plyrid, room_id, token)

    body = {
        "status": "recovered" if resumed else "created",
        "session": _session_payload(
            session_record,
            player,
            room_id,
            first_login=first_login,
            resumed=resumed,
            replaced_sessions=len(replaced_tokens),
            lifecycle_messages=lifecycle_messages,
            account=session_account,
            honor_mode_policy=_honor_mode_policy(request.app),
        ),
    }
    return JSONResponse(content=body, status_code=status_code)


@auth_router.post("/session/lifecycle/advance", response_model=SessionResponse)
async def advance_session_lifecycle(
    payload: LifecycleAdvanceRequest,
    request: Request,
    db: Annotated[OrmSession, Depends(get_db_session)],
    session_context: Annotated[
        tuple[models.PlayerSession, models.Player], Depends(require_active_session)
    ],
):
    session_record, player = session_context
    messages = request.app.state.fixture_cache["messages"]
    lifecycle_messages: list[dict[str, str]] = []

    if session_record.lifecycle_state == FIRST_LOGIN_INTRO_STATE:
        step = session_record.lifecycle_step or 2
        message_id = FIRST_LOGIN_INTRO_MESSAGES.get(step)
        if message_id:
            lifecycle_messages = [_intro_lifecycle_message(messages, message_id)]
            session_record.lifecycle_step = step + 1
        elif step == FIRST_LOGIN_ENTRY_STEP:
            # Legacy kyrand() case 6 follows the final INTROD prompt and calls
            # entrgp(0, ..., APPEARFLASH). See legacy/KYRANDIA.C:276-298.
            session_record.lifecycle_state = FIRST_LOGIN_ENTRY_STATE
            session_record.lifecycle_step = FIRST_LOGIN_ENTRY_STEP
        else:
            session_record.lifecycle_state = None
            session_record.lifecycle_step = None
    elif session_record.lifecycle_state != FIRST_LOGIN_ENTRY_STATE:
        raise HTTPException(status_code=409, detail="No active session lifecycle")

    repositories.PlayerSessionRepository(db).mark_seen(session_record.session_token)
    db.commit()

    return {
        "status": "advanced",
        "session": _session_payload(
            session_record,
            player,
            session_record.room_id,
            first_login=True,
            lifecycle_messages=lifecycle_messages,
            honor_mode_policy=_honor_mode_policy(request.app),
        ),
    }


@auth_router.get("/session", response_model=SessionResponse)
async def validate_session(
    request: Request,
    session_context: Annotated[tuple[models.PlayerSession, models.Player], Depends(require_active_session)]
):
    session_record, player = session_context
    return {
        "status": "active",
        "session": _session_payload(
            session_record,
            player,
            session_record.room_id,
            first_login=False,
            honor_mode_policy=_honor_mode_policy(request.app),
        ),
    }


@auth_router.post("/logout", response_model=LogoutResponse)
async def logout(
    session_context: Annotated[tuple[models.PlayerSession, models.Player], Depends(require_active_session)],
    db: Annotated[OrmSession, Depends(get_db_session)],
    request: Request,
):
    session_record, player = session_context
    repo = repositories.PlayerSessionRepository(db)
    repo.deactivate(session_record.session_token)
    db.commit()
    
    connections = request.app.state.session_connections
    active_socket = connections.pop(session_record.session_token, None)
    if active_socket is not None:
        getattr(request.app.state, "game_socket_players", {}).pop(active_socket, None)
    
    # Always clean up presence, even if socket operations fail
    try:
        if active_socket is not None and active_socket.application_state == WebSocketState.CONNECTED:
            await request.app.state.gateway.unregister(session_record.room_id, active_socket)
            await active_socket.close(code=status.WS_1000_NORMAL_CLOSURE)
    finally:
        _remove_active_player_session(request.app, session_record.session_token, player.plyrid)
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


public_router = APIRouter(prefix="/public", tags=["public"])


@public_router.get("/runtime-mode")
async def public_runtime_mode(request: Request):
    return _honor_mode_policy(request.app).runtime_payload()


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


@admin_router.get("/mobs")
async def admin_list_mobs(
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    admin: Annotated[AdminGrant, Depends(require_player_or_content_admin)],
):
    return _admin_mob_snapshot(provider)


@admin_router.post("/mobs/elf/trigger")
async def admin_trigger_elf(
    payload: AdminElfTriggerRequest,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    admin: Annotated[AdminGrant, Depends(require_player_or_content_admin)],
):
    app = provider.scope.app
    active_player = _active_player_in_room(app, payload.player_id, payload.room_id)
    if active_player is None:
        return {
            "status": "no_active_player",
            "room_id": payload.room_id,
            "player_id": payload.player_id,
            "outcome": "no_active_player",
            "snapshot": _admin_mob_snapshot(provider),
        }

    elf_routine = getattr(app.state, "animation_elf_routine", None)
    animation_system: AnimationTickSystem | None = getattr(app.state, "animation_tick_system", None)
    if elf_routine is None or animation_system is None:
        raise HTTPException(status_code=503, detail="Animation system is not initialized")

    events = list(elf_routine.trigger_room(animation_system.state, payload.room_id))
    # Admin-only test hook for KYRANIM.C elves(): force the random eloc to the
    # current room while preserving the legacy hint/gold branch and messages.
    animation_system.persist_state()
    await _dispatch_animation_events(app, events)
    outcome = _elf_trigger_outcome(events)
    telemetry_sink = getattr(app.state, "telemetry_sink", None)
    if telemetry_sink is not None:
        try:
            await telemetry_sink.record_system(
                event_type="animation.admin_trigger",
                payload={
                    "trigger_source": "admin",
                    "routine_name": "elves",
                    "room_id": payload.room_id,
                    "player_id": payload.player_id,
                    "outcome": outcome,
                    "event_count": len(events),
                },
            )
        except Exception:
            pass
    return {
        "status": "triggered" if events else "no_active_player",
        "room_id": payload.room_id,
        "player_id": payload.player_id,
        "outcome": outcome,
        "snapshot": _admin_mob_snapshot(provider),
    }


@admin_router.post("/rooms/{room_id}/objects/drop")
async def admin_drop_item_in_room(
    room_id: int,
    payload: AdminDropItemRequest,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    db: Annotated[OrmSession, Depends(get_db_session)],
    admin: Annotated[AdminGrant, Depends(require_player_or_content_admin)],
):
    location = provider.location_index.get(room_id)
    record = db.get(models.Location, room_id)
    if location is None or record is None:
        raise HTTPException(status_code=404, detail="Location not found")

    objects_by_id, objects_by_name = _object_catalog_indexes(provider.cache["objects"])
    object_id = _resolve_object_reference(
        payload.object_ref,
        objects_by_id,
        objects_by_name,
        field_name="object_ref",
    )
    obj = objects_by_id[object_id]

    room_objects = list(record.objects)
    if len(room_objects) >= constants.MXLOBS:
        raise HTTPException(status_code=409, detail="Room is full")

    updated_objects = [*room_objects, object_id]
    location_repo = repositories.LocationRepository(db)
    location_repo.update_objects(room_id, updated_objects)
    db.commit()

    updated_location = location.model_copy(
        update={"objects": updated_objects, "nlobjs": len(updated_objects)}
    )
    provider.scope.app.state.location_index[room_id] = updated_location
    _replace_cached_model(provider.cache["locations"], updated_location)

    announcement = _admin_drop_announcement(updated_location, obj)
    room_objects_event = commands._room_objects_event(
        updated_location,
        objects_by_id,
        None,
        None,
        scope="room",
        include_sender=True,
    )

    await _broadcast_game_json(
        provider.scope.app,
        provider.gateway,
        room_id,
        {
            "type": "room_broadcast",
            "room": room_id,
            "payload": announcement,
        },
    )
    await _broadcast_game_json(
        provider.scope.app,
        provider.gateway,
        room_id,
        {
            "type": "room_broadcast",
            "room": room_id,
            "payload": room_objects_event,
        },
    )

    telemetry_sink = getattr(provider.scope.app.state, "telemetry_sink", None)
    if telemetry_sink is not None:
        try:
            await telemetry_sink.record_system(
                event_type="admin.drop_item",
                payload={
                    "room_id": room_id,
                    "object_id": object_id,
                    "object_name": obj.name,
                    "status": "dropped",
                },
            )
        except Exception:
            pass

    return {
        "status": "dropped",
        "room_id": room_id,
        "object": {"id": obj.id, "name": obj.name},
        "room_objects": commands.room_object_entries(updated_location, objects_by_id),
        "announcement": {
            "message_id": None,
            "modeled_after_message_id": "ASHM01",
            "text": announcement["text"],
        },
    }


@admin_router.get("/rooms/{room_id}/objects")
async def admin_get_room_objects(
    room_id: int,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    db: Annotated[OrmSession, Depends(get_db_session)],
    admin: Annotated[AdminGrant, Depends(require_player_or_content_admin)],
):
    location = provider.location_index.get(room_id)
    record = db.get(models.Location, room_id)
    if location is None or record is None:
        raise HTTPException(status_code=404, detail="Location not found")

    objects_by_id, _objects_by_name = _object_catalog_indexes(provider.cache["objects"])
    room_objects = list(record.objects)
    live_location = location.model_copy(
        update={"objects": room_objects, "nlobjs": len(room_objects)}
    )
    return _admin_room_objects_payload(live_location, objects_by_id)


@admin_router.delete("/rooms/{room_id}/objects/{slot_index}")
async def admin_delete_room_object(
    room_id: int,
    slot_index: int,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    db: Annotated[OrmSession, Depends(get_db_session)],
    admin: Annotated[AdminGrant, Depends(require_player_or_content_admin)],
    expected_object_id: int,
):
    location = provider.location_index.get(room_id)
    record = db.get(models.Location, room_id)
    if location is None or record is None:
        raise HTTPException(status_code=404, detail="Location not found")

    room_objects = list(record.objects)
    if slot_index < 0 or slot_index >= len(room_objects):
        raise HTTPException(status_code=404, detail="Room object slot not found")

    object_id = room_objects[slot_index]
    if object_id != expected_object_id:
        raise HTTPException(status_code=409, detail="Room object slot changed")

    updated_objects = [
        *room_objects[:slot_index],
        *room_objects[slot_index + 1 :],
    ]
    location_repo = repositories.LocationRepository(db)
    location_repo.update_objects(room_id, updated_objects)
    db.commit()

    updated_location = location.model_copy(
        update={"objects": updated_objects, "nlobjs": len(updated_objects)}
    )
    provider.scope.app.state.location_index[room_id] = updated_location
    _replace_cached_model(provider.cache["locations"], updated_location)

    objects_by_id, _objects_by_name = _object_catalog_indexes(provider.cache["objects"])
    announcement = _admin_delete_announcement(updated_location, object_id, objects_by_id)
    room_objects_event = commands._room_objects_event(
        updated_location,
        objects_by_id,
        None,
        None,
        scope="room",
        include_sender=True,
    )

    await _broadcast_game_json(
        provider.scope.app,
        provider.gateway,
        room_id,
        {
            "type": "room_broadcast",
            "room": room_id,
            "payload": announcement,
        },
    )
    await _broadcast_game_json(
        provider.scope.app,
        provider.gateway,
        room_id,
        {
            "type": "room_broadcast",
            "room": room_id,
            "payload": room_objects_event,
        },
    )

    obj = objects_by_id.get(object_id)
    object_name = obj.name if obj else f"object {object_id}"
    return {
        "status": "deleted",
        "room_id": room_id,
        "slot_index": slot_index,
        "object": {"id": object_id, "name": object_name},
        "room_objects": commands.room_object_entries(updated_location, objects_by_id),
        "announcement": {
            "message_id": None,
            "modeled_after_spell": "mower",
            "text": announcement["text"],
        },
    }


@admin_router.get("/players")
async def admin_list_players(
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    admin: Annotated[AdminGrant, Depends(require_player_admin)],
):
    return {
        "players": [
            _player_admin_payload(provider.scope.app, player)
            for player in provider.players
        ]
    }


@admin_router.get("/players/{player_id}")
async def admin_get_player(
    player_id: str,
    request: Request,
    db: Annotated[OrmSession, Depends(get_db_session)],
    admin: Annotated[AdminGrant, Depends(require_player_admin)],
):
    record = _find_player_record(db, player_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Player not found")
    model = _player_model_from_record(record)
    return {"player": _player_admin_payload(request.app, model)}


@admin_router.post("/players", status_code=status.HTTP_201_CREATED)
async def admin_create_player(
    player: models.PlayerModel,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    db: Annotated[OrmSession, Depends(get_db_session)],
    admin: Annotated[AdminGrant, Depends(require_player_admin)],
):
    existing = _find_player_record(db, player.plyrid)
    if existing:
        raise HTTPException(status_code=409, detail="Player alias already exists")

    db.add(models.Player(**player.model_dump()))
    db.commit()
    _set_player_in_cache(provider.scope.app, player)
    return {"status": "created", "player": _player_admin_payload(provider.scope.app, player)}


@admin_router.put("/players/{player_id}")
async def admin_update_player(
    player_id: str,
    player: PlayerAdminReplacement,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    db: Annotated[OrmSession, Depends(get_db_session)],
    admin: Annotated[AdminGrant, Depends(require_player_admin)],
):
    record = _find_player_record(db, player_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Player not found")
    original_player_id = record.plyrid

    if player.plyrid != original_player_id and AdminFlag.ALLOW_RENAME.value not in admin.flags:
        raise HTTPException(status_code=403, detail="Rename not permitted for this admin token")

    if player.plyrid != original_player_id:
        conflict = db.scalar(select(models.Player).where(models.Player.plyrid == player.plyrid))
        if conflict and conflict.id != record.id:
            raise HTTPException(status_code=409, detail="Player alias already exists")

    player_data = player.model_dump(exclude={"effective_honor_mode"})
    for field, value in player_data.items():
        setattr(record, field, value)

    db.commit()
    updated = _player_model_from_record(record)
    _set_player_in_cache(
        provider.scope.app,
        updated,
        original_alias=original_player_id if player.plyrid != original_player_id else None,
    )
    if updated.plyrid != original_player_id:
        for token, active_player in _active_player_sessions(provider.scope.app).items():
            if active_player.plyrid == updated.plyrid:
                await provider.presence.set_location(
                    updated.plyrid,
                    active_player.gamloc,
                    token,
                )
    return {"status": "updated", "player": _player_admin_payload(provider.scope.app, updated)}


@admin_router.patch("/players/{player_id}")
async def admin_patch_player(
    player_id: str,
    updates: PlayerAdminUpdate,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    db: Annotated[OrmSession, Depends(get_db_session)],
    admin: Annotated[AdminGrant, Depends(require_player_admin)],
):
    record = _find_player_record(db, player_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Player not found")

    current = _player_model_from_record(record)
    updated = _apply_player_admin_update(
        current,
        updates,
        objects=provider.cache["objects"],
        spells=provider.cache["spells"],
    )

    for field, value in updated.model_dump().items():
        setattr(record, field, value)

    db.commit()
    _set_player_in_cache(provider.scope.app, updated)
    return {"status": "updated", "player": _player_admin_payload(provider.scope.app, updated)}


@admin_router.delete("/players/{player_id}")
async def admin_delete_player(
    player_id: str,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    db: Annotated[OrmSession, Depends(get_db_session)],
    admin: Annotated[AdminGrant, Depends(require_player_admin)],
):
    if AdminFlag.ALLOW_DELETE.value not in admin.flags:
        raise HTTPException(status_code=403, detail="Delete not permitted for this admin token")

    record = _find_player_record(db, player_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Player not found")
    canonical_player_id = record.plyrid

    session_repo = repositories.PlayerSessionRepository(db)
    tokens = session_repo.deactivate_all(record.id)

    db.delete(record)
    db.commit()

    await _disconnect_sessions(provider.scope.app, tokens)
    _remove_player_from_cache(provider.scope.app, canonical_player_id)
    return {"status": "deleted", "player_id": canonical_player_id}


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


@public_router.get("/player-id/{player_id}")
async def public_player_id_lookup(
    player_id: str,
    request: Request,
    db: Annotated[OrmSession, Depends(get_db_session)],
):
    _enforce_http_rate_limit(
        request,
        state_attr="public_player_id_lookup_rate_limiters",
        max_events=PUBLIC_PLAYER_ID_LOOKUP_RATE_LIMIT_MAX_EVENTS,
        window_seconds=PUBLIC_PLAYER_ID_LOOKUP_RATE_LIMIT_WINDOW_SECONDS,
        detail="Too many Player-ID checks. Please slow down.",
    )

    trimmed = player_id.strip()
    valid = bool(PLAYER_ID_PATTERN.fullmatch(trimmed))
    reserved = trimmed.lower() in RESERVED_PLAYER_IDS if trimmed else False
    existing = _find_player_record(db, trimmed) if valid else None
    canonical_player_id = _canonical_first_login_player_id(trimmed) if valid else trimmed
    exists = existing is not None
    available = valid and not reserved and not exists
    account_bound = (
        db.scalar(
            select(models.Account.id).where(models.Account.player_id == existing.id)
        )
        is not None
        if existing is not None
        else None
    )
    if not valid:
        status_value = "invalid"
    elif reserved:
        status_value = "reserved"
    elif exists:
        status_value = "existing"
    else:
        status_value = "available"

    return {
        "player_id": existing.plyrid if existing else canonical_player_id,
        "canonical_player_id": existing.plyrid if existing else canonical_player_id,
        "valid": valid,
        "exists": exists,
        "available": available,
        "reserved": reserved,
        "account_bound": account_bound,
        "status": status_value,
    }


@public_router.get("/player-activity")
async def public_player_activity(
    request: Request,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    db: Annotated[OrmSession, Depends(get_db_session)],
):
    now = datetime.now(timezone.utc)
    spells_catalog = provider.cache["spells"]
    runtime_connected_at = _active_player_connected_at(request.app)
    hidden_admin_player_ids = _public_admin_account_player_ids(db, request.app)
    runtime_sessions = _public_runtime_sessions(
        db, request.app, hidden_admin_player_ids
    )
    active_aliases = {player.plyrid for player in runtime_sessions.values()}
    active_records = (
        list(
            db.scalars(
                select(models.Player).where(models.Player.plyrid.in_(active_aliases))
            ).all()
        )
        if active_aliases
        else []
    )
    hidden_admin_aliases = {
        record.plyrid
        for record in active_records
        if record.id is not None and int(record.id) in hidden_admin_player_ids
    }
    public_active_records = [
        record
        for record in active_records
        if record.id is None or int(record.id) not in hidden_admin_player_ids
    ]
    players_by_alias = {
        record.plyrid: _player_model_from_record(record)
        for record in public_active_records
        if record.id is not None
    }
    record_id_by_alias = {
        record.plyrid: int(record.id)
        for record in public_active_records
        if record.id is not None
    }
    active_record_ids = set(record_id_by_alias.values())
    latest_seen = _latest_session_seen_for_player_ids(db, active_record_ids)

    active_summaries: list[dict] = []
    for session_token, active_player in runtime_sessions.items():
        if active_player.plyrid in hidden_admin_aliases:
            continue
        canonical_player = players_by_alias.get(active_player.plyrid, active_player)
        record_id = record_id_by_alias.get(canonical_player.plyrid)
        active_summaries.append(
            _public_player_summary(
                canonical_player,
                spells_catalog=spells_catalog,
                active=True,
                last_seen=latest_seen.get(record_id) if record_id is not None else now,
                connected_at=runtime_connected_at.get(session_token, now),
                now=now,
            )
        )

    active_summaries.sort(
        key=lambda player: (
            player["connection_duration_seconds"]
            if player["connection_duration_seconds"] is not None
            else 2**31,
            str(player["player_id"]).lower(),
        )
    )
    active_summaries = active_summaries[:PUBLIC_ACTIVE_PLAYER_LIMIT]

    recent_cutoff = now - RECENT_PUBLIC_PLAYER_WINDOW
    recent_rows = _recent_session_seen_rows(
        db,
        since=recent_cutoff,
        limit=PUBLIC_RECENT_PLAYER_SCAN_LIMIT,
        exclude_player_ids=active_record_ids | hidden_admin_player_ids,
    )
    recent_records = _player_records_by_id(db, {player_id for player_id, _ in recent_rows})
    recent_entries = []
    for player_id, last_seen in recent_rows:
        record = recent_records.get(player_id)
        if record is None:
            continue
        player = _player_model_from_record(record)
        if player.plyrid in active_aliases:
            continue
        recent_entries.append((player, last_seen))
    recent_entries.sort(key=lambda entry: entry[0].plyrid.lower())
    recent_entries.sort(key=lambda entry: entry[1], reverse=True)
    recent_summaries = [
        _public_player_summary(
            player,
            spells_catalog=spells_catalog,
            active=False,
            last_seen=last_seen,
            now=now,
        )
        for player, last_seen in recent_entries[:RECENT_PUBLIC_PLAYER_LIMIT]
    ]

    return {"active": active_summaries, "recent": recent_summaries}


@public_router.get("/leaderboard")
async def public_leaderboard(
    request: Request,
    provider: Annotated[FixtureProvider, Depends(get_request_provider)],
    db: Annotated[OrmSession, Depends(get_db_session)],
):
    now = datetime.now(timezone.utc)
    spells_catalog = provider.cache["spells"]
    hidden_admin_player_ids = _public_admin_account_player_ids(db, request.app)
    player_records = [
        record
        for record, _spellbook_count in db.execute(
            _public_leaderboard_player_statement(
                spells_catalog,
                exclude_player_ids=hidden_admin_player_ids,
            )
        ).all()
    ]
    latest_seen = _latest_session_seen_for_player_ids(
        db, {int(record.id) for record in player_records if record.id is not None}
    )
    runtime_connected_at = _active_player_connected_at(request.app)
    runtime_connected_by_alias = {
        player.plyrid: runtime_connected_at.get(session_token, now)
        for session_token, player in _public_runtime_sessions(
            db, request.app, hidden_admin_player_ids
        ).items()
    }

    entries = []
    for record in player_records:
        player = _player_model_from_record(record)
        connected_at = runtime_connected_by_alias.get(player.plyrid)
        active = connected_at is not None
        summary = _public_player_summary(
            player,
            spells_catalog=spells_catalog,
            active=active,
            last_seen=latest_seen.get(record.id),
            connected_at=connected_at if active else None,
            now=now,
        )
        entries.append(summary)

    return {"players": entries}


def _format_room_occupants(occupants: list[str], messages: models.MessageBundleModel | None):
    """Format the occupant list shown when entering a room.

    Mirrors ``locogps`` from the legacy engine, which lists other visible players
    in the room using the KUTM11/KUTM12 strings.【F:legacy/KYRUTIL.C†L271-L314】
    """

    return commands._format_room_occupants(occupants, messages)


async def _room_occupants_event(
    presence: PresenceService,
    player_id: str,
    room_id: int,
    messages: models.MessageBundleModel | None,
    player_flags_by_id: dict[str, int] | None = None,
):
    occupants = await presence.players_in_room(room_id)
    player_key = player_id.strip().casefold()
    others = commands._dedupe_room_occupants(
        sorted(
            occupant
            for occupant in occupants
            if str(occupant or "").strip().casefold() != player_key
        )
    )
    text, message_id = _format_room_occupants(others, messages)
    if not others or not text:
        return None

    return {
        "scope": "player",
        "event": "room_occupants",
        "type": "room_occupants",
        "location": room_id,
        "occupants": others,
        "occupant_details": [
            {"player_id": occupant, "flags": int((player_flags_by_id or {}).get(occupant, 0))}
            for occupant in others
        ],
        "text": text,
        "message_id": message_id,
    }


async def _publish_scry_event(app: FastAPI, player_id: str, event: dict) -> None:
    subscribers: dict[str, set[WebSocket]] = getattr(app.state, "scry_subscribers", {})
    sockets = set(subscribers.get(player_id, set()))
    stale: set[WebSocket] = set()
    for socket in sockets:
        if socket.application_state != WebSocketState.CONNECTED:
            stale.add(socket)
            continue
        try:
            await socket.send_json(_scry_event_payload(player_id, event))
        except Exception:
            stale.add(socket)
    if stale and player_id in subscribers:
        subscribers[player_id].difference_update(stale)


def _scry_event_payload(player_id: str, event: dict) -> dict:
    return {"type": "scry_event", "player_id": player_id, "event": event}


def _game_socket_player_id(app: FastAPI, socket: WebSocket) -> str | None:
    return getattr(app.state, "game_socket_players", {}).get(socket)


async def _publish_scry_output(app: FastAPI, player_id: str | None, message: dict) -> None:
    if not player_id:
        return
    await _publish_scry_event(
        app,
        player_id,
        {"event_type": "output", "payload": message},
    )


async def _send_game_socket_json(
    app: FastAPI,
    socket: WebSocket,
    message: dict,
    *,
    player_id: str | None = None,
) -> None:
    await socket.send_json(message)
    await _publish_scry_output(app, player_id or _game_socket_player_id(app, socket), message)


async def _broadcast_game_json(
    app: FastAPI,
    gateway: RoomGateway,
    room_id: int,
    message: dict,
    *,
    sender: WebSocket | None = None,
    exclude: set[WebSocket] | None = None,
) -> None:
    recipients = await gateway.broadcast(room_id, message, sender=sender, exclude=exclude)
    for recipient in recipients:
        await _publish_scry_output(app, _game_socket_player_id(app, recipient), message)


def _active_scry_target(app: FastAPI, target_player_id: str) -> models.PlayerModel | None:
    target_key = target_player_id.strip().casefold()
    if not target_key:
        return None
    for player in _active_player_sessions(app).values():
        if player.plyrid.casefold() == target_key:
            return player
    for player in getattr(app.state, "active_players", {}).values():
        if player.plyrid.casefold() == target_key:
            return player
    return None


async def _initial_scry_output_messages(
    provider: "FixtureProvider", target_player: models.PlayerModel
) -> list[dict]:
    room_id = target_player.gamloc
    state = commands.GameState(
        player=target_player,
        locations=provider.location_index,
        objects={obj.id: obj for obj in provider.cache["objects"]},
        messages=provider.message_bundles.get("en-US"),
        content_mappings=provider.content_mappings,
        presence=provider.presence,
    )
    messages: list[dict] = [{"type": "room_welcome", "room": room_id}]
    location = state.locations.get(room_id)
    if location is not None:
        description_id, long_description = commands._location_description(state, location)
        messages.extend(
            [
                {
                    "type": "command_response",
                    "room": room_id,
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
                },
                {
                    "type": "command_response",
                    "room": room_id,
                    "payload": {
                        "scope": "player",
                        "event": "location_description",
                        "type": "location_description",
                        "location": location.id,
                        "message_id": description_id,
                        "text": long_description or location.brfdes,
                        "objects": commands.room_object_entries(
                            location, state.objects or {}
                        ),
                    },
                },
                {
                    "type": "command_response",
                    "room": room_id,
                    "payload": commands._room_objects_event(
                        location, state.objects or {}, None, description_id
                    ),
                },
            ]
        )
    occupants_event = await _room_occupants_event(
        provider.presence,
        target_player.plyrid,
        room_id,
        state.messages,
        _active_player_flags(provider.scope.app),
    )
    if occupants_event:
        messages.append(
            {
                "type": "command_response",
                "room": room_id,
                "payload": occupants_event,
            }
        )
    return messages


def _entrance_room_message(
    player_id: str,
    room_id: int,
    player_flags: int | None = None,
    entrance_text: str = "appeared in a cloud of mists",
) -> dict:
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
        "text": f"*** {player_id} has just {entrance_text}!",
        "player_flags": player_flags,
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
    app.state.account_admin_grants = _load_account_admin_grants()
    app.state.telemetry_sink = TelemetryEventSink.from_env()
    app.state.scry_subscribers = {}
    app.state.game_socket_players = {}
    app.state.scry_publish_output = _publish_scry_output

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
    app.include_router(public_router)
    app.include_router(admin_router)
    app.include_router(players_router)

    gateway: RoomGateway | None = None
    app.state.session_connections = {}
    app.state.active_players = {}
    app.state.active_player_sessions = {}
    app.state.active_player_connected_at = {}

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
        await _broadcast_game_json(
            provider.scope.app,
            provider.gateway,
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
                        record = _find_player_record(db, target_id)
                        if record:
                            payload = _player_model_from_record(record)
                        else:
                            uid_alias = target_id[: constants.UIDSIZ]
                            canonical_id = target_id[: constants.ALSSIZ]
                            cached = next(
                                (
                                    p
                                    for p in provider.players
                                    if p.plyrid == target_id
                                    or p.uidnam == uid_alias
                                    or p.plyrid == canonical_id
                                ),
                                None,
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
            await _broadcast_game_json(
                provider.scope.app,
                provider.gateway,
                current_room,
                {
                    "type": "room_broadcast",
                    "room": current_room,
                    "payload": {
                        "event": "player_enter",
                        "player": player_id,
                        "player_flags": int(player.flags),
                    },
                },
            )
            await _broadcast_game_json(
                provider.scope.app,
                provider.gateway,
                current_room,
                {
                    "type": "room_broadcast",
                    "room": current_room,
                    "payload": _entrance_room_message(
                        player_id, current_room, int(player.flags)
                    ),
                },
            )

            occupant_event = await _room_occupants_event(
                provider.presence,
                player_id,
                current_room,
                provider.message_bundles.get("en-US"),
                _active_player_flags(provider.scope.app),
            )
            if occupant_event:
                # Legacy entrgp() sends locogps() to the entering player before the room
                # arrival broadcast (legacy/KYRUTIL.C:253-257).
                player_socket = provider.scope.app.state.session_connections.get(session_token)
                if player_socket and player_socket.application_state == WebSocketState.CONNECTED:
                    await _send_game_socket_json(
                        provider.scope.app,
                        player_socket,
                        {
                            "type": "command_response",
                            "room": current_room,
                            "payload": occupant_event,
                        }
                    )

            async with provider.scope.app.state.kyraedit_lock:
                provider.scope.app.state.kyraedit_session = None

            if websocket.application_state == WebSocketState.CONNECTED:
                await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)

    @app.websocket("/ws/admin/scry/{target_player_id}")
    async def scry_socket(
        websocket: WebSocket,
        target_player_id: str,
        provider: Annotated[FixtureProvider, Depends(get_websocket_provider)],
    ):
        admin_token = websocket.query_params.get("token") or websocket.query_params.get(
            "admin_token"
        )
        try:
            _validate_admin_token(provider.scope.app, admin_token, roles={AdminRole.PLAYER})
        except HTTPException as exc:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=exc.detail)
            return

        target_player = _active_scry_target(provider.scope.app, target_player_id)
        if target_player is None:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="SCRY target is not active",
            )
            return
        canonical_target_id = target_player.plyrid
        display_name = target_player.altnam.strip() or canonical_target_id

        await websocket.accept()
        subscribers: dict[str, set[WebSocket]] = provider.scope.app.state.scry_subscribers
        sockets = subscribers.setdefault(canonical_target_id, set())
        sockets.add(websocket)
        await websocket.send_json(
            {
                "type": "scry_started",
                "player_id": canonical_target_id,
                "display_name": display_name,
                "room": target_player.gamloc,
            }
        )
        for message in await _initial_scry_output_messages(provider, target_player):
            await websocket.send_json(
                _scry_event_payload(
                    canonical_target_id,
                    {"event_type": "output", "payload": message},
                )
            )
        try:
            while True:
                incoming = await websocket.receive_json()
                if incoming.get("type") in {"stop", "close"}:
                    break
                await websocket.send_json(
                    {"type": "scry_read_only", "detail": "SCRY observers cannot send commands"}
                )
        except WebSocketDisconnect:
            pass
        finally:
            sockets.discard(websocket)
            if not sockets:
                subscribers.pop(canonical_target_id, None)
            if (
                websocket.application_state == WebSocketState.CONNECTED
                and websocket.client_state == WebSocketState.CONNECTED
            ):
                await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)

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
        replaced_tokens: list[str] = []
        first_login_entry_pending = False
        try:
            session_repo = repositories.PlayerSessionRepository(db_session)
            session_record = session_repo.get_by_token(session_token)
            if not session_record:
                # Invalid or expired token - reject connection during handshake
                await websocket.send_denial_response(
                    Response(status_code=status.HTTP_401_UNAUTHORIZED, content="Invalid or expired token")
                )
                return

            if (
                session_record.session_kind != SESSION_KIND_GAME
                or session_record.hidden_from_activity
            ):
                await websocket.send_denial_response(
                    Response(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content="Session cannot enter game rooms",
                    )
                )
                return

            if session_record.lifecycle_state == FIRST_LOGIN_INTRO_STATE:
                await websocket.send_denial_response(
                    Response(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content="First-login intro is not complete",
                    )
                )
                return
            first_login_entry_pending = (
                session_record.lifecycle_state == FIRST_LOGIN_ENTRY_STATE
            )

            player = db_session.get(models.Player, session_record.player_id)
            if not player:
                # Player not found - reject connection during handshake
                await websocket.send_denial_response(
                    Response(status_code=status.HTTP_404_NOT_FOUND, content="Player not found")
                )
                return

            session_repo.mark_seen(session_token)
            for active_session in session_repo.list_active(player.id, session_kind=SESSION_KIND_GAME):
                if active_session.session_token == session_token:
                    continue
                replaced_tokens.append(active_session.session_token)
                session_repo.deactivate(active_session.session_token)
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

        if replaced_tokens:
            await _disconnect_sessions(provider.scope.app, replaced_tokens)

        # All validation passed - now accept the WebSocket connection
        await websocket.accept()
        connected_at = datetime.now(timezone.utc)

        session_connections = provider.scope.app.state.session_connections
        existing_socket = session_connections.get(session_token)
        if existing_socket is not None and existing_socket.application_state == WebSocketState.CONNECTED:
            await gateway.unregister(current_room, existing_socket)
            getattr(provider.scope.app.state, "game_socket_players", {}).pop(existing_socket, None)
            await existing_socket.close(
                code=status.WS_1013_TRY_AGAIN_LATER,
                reason="Game session replaced by another connection",
            )
        session_connections[session_token] = websocket
        provider.scope.app.state.game_socket_players[websocket] = player_id

        def current_player_id() -> str:
            return player_state.plyrid

        async def send_player_json(message: dict) -> None:
            active_player_id = current_player_id()
            await _send_game_socket_json(
                provider.scope.app,
                websocket,
                message,
                player_id=active_player_id,
            )
            await provider.scope.app.state.telemetry_sink.record(
                userid=active_player_id,
                event_type="output",
                payload=message,
            )

        async def record_player_input(command_text: str) -> None:
            payload = {"command": command_text}
            active_player_id = current_player_id()
            await provider.scope.app.state.telemetry_sink.record(
                userid=active_player_id,
                event_type="input",
                payload=payload,
            )
            await _publish_scry_event(
                provider.scope.app,
                active_player_id,
                {"event_type": "input", "payload": payload},
            )

        limiter = _websocket_command_rate_limiter()

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

        def lookup_active_player(player_alias: str) -> models.PlayerModel | None:
            alias = player_alias.lower()
            # Legacy fgamgp() scans only active in-memory players by true plyrid
            # (legacy/KYRUTIL.C:486-494), so DB-only player records must stay
            # invisible to remote-target spells.
            for player in active_players.values():
                if player.plyrid.lower() == alias:
                    return player
            for player in _active_player_sessions(provider.scope.app).values():
                if player.plyrid.lower() == alias:
                    return player
            return None

        state = commands.GameState(
            player=player_state,
            locations=provider.location_index,
            objects={obj.id: obj for obj in provider.cache["objects"]},
            messages=provider.message_bundles.get("en-US"),
            content_mappings=provider.content_mappings,
            db_session=persistent_session,
            presence=provider.presence,
            player_lookup=lookup_player,
            global_player_lookup=lookup_active_player,
            zar_controller=getattr(provider.scope.app.state, "animation_zar_routine", None),
            zar_state=getattr(
                getattr(provider.scope.app.state, "animation_tick_system", None),
                "state",
                None,
            ),
            honor_mode_policy=_honor_mode_policy(provider.scope.app),
        )

        _register_active_player_session(
            provider.scope.app,
            session_token,
            player_state,
            connected_at=connected_at,
        )
        await provider.presence.set_location(player_id, current_room, session_token)
        await gateway.register(current_room, websocket)

        # Immediately send the player their current room description to mirror move command behavior.
        location = state.locations.get(current_room)
        if location is not None:
            description_id, long_description = commands._location_description(state, location)
            await send_player_json(
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
            await send_player_json(
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
                        "objects": commands.room_object_entries(
                            location, state.objects or {}
                        ),
                    },
                }
            )
        occupants_event = await _room_occupants_event(
            provider.presence,
            player_id,
            current_room,
            state.messages,
            _active_player_flags(provider.scope.app),
        )
        if location is not None:
            await send_player_json(
                {
                    "type": "command_response",
                    "room": current_room,
                    "payload": commands._room_objects_event(
                        location, state.objects or {}, None, description_id
                    ),
                }
            )
        if occupants_event:
            await send_player_json(
                {
                    "type": "command_response",
                    "room": current_room,
                    "payload": occupants_event,
                }
            )

        await _broadcast_game_json(
            provider.scope.app,
            gateway,
            current_room,
            {
                "type": "room_broadcast",
                "room": current_room,
                "payload": {
                    "event": "player_enter",
                    "player": player_id,
                    "player_flags": int(player_state.flags),
                },
            },
            sender=websocket,
        )
        await _broadcast_game_json(
            provider.scope.app,
            gateway,
            current_room,
            {
                "type": "room_broadcast",
                "room": current_room,
                "payload": _entrance_room_message(
                    player_id,
                    current_room,
                    int(player_state.flags),
                    "appeared in a flash"
                    if first_login_entry_pending
                    else "appeared in a cloud of mists",
                ),
            },
            sender=websocket,
        )

        if first_login_entry_pending:
            with provider.scope.app.state.session_factory() as db:
                repo = repositories.PlayerSessionRepository(db)
                repo.set_lifecycle(session_token, None, None)
                repo.mark_seen(session_token)
                db.commit()

        async def _sync_current_room_from_state() -> None:
            nonlocal current_room
            target_room = state.player.gamloc
            if target_room < 0 or target_room not in state.locations:
                return
            active_player_id = current_player_id()
            if target_room == current_room:
                await provider.presence.set_location(
                    active_player_id, target_room, session_token
                )
                return
            await gateway.register(target_room, websocket, announce=False)
            await provider.presence.set_location(
                active_player_id, target_room, session_token
            )
            with provider.scope.app.state.session_factory() as db:
                repo = repositories.PlayerSessionRepository(db)
                repo.set_room(session_token, target_room)
                repo.mark_seen(session_token)
                db.commit()
            current_room = target_room

        session_exit_started = False

        async def _deactivate_current_session() -> None:
            nonlocal session_exit_started
            if session_exit_started:
                return
            session_exit_started = True
            with provider.scope.app.state.session_factory() as db:
                repo = repositories.PlayerSessionRepository(db)
                repo.deactivate(session_token)
                db.commit()
            await provider.presence.remove(session_token)
            await gateway.unregister(current_room, websocket)
            if session_connections.get(session_token) is websocket:
                session_connections.pop(session_token, None)
            _remove_active_player_session(
                provider.scope.app, session_token, current_player_id()
            )
            if websocket.application_state == WebSocketState.CONNECTED:
                await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)

        async def _send_level_up_cue(previous_level: int, location: int) -> None:
            if state.player.level <= previous_level:
                return
            await send_player_json(
                {
                    "type": "command_response",
                    "room": location,
                    "payload": {
                        "scope": "player",
                        "event": "player_level_up",
                        "type": "player_level_up",
                        "player": current_player_id(),
                        "previous_level": previous_level,
                        "level": state.player.level,
                        "location": location,
                    },
                }
            )

        try:
            while True:
                payload = await websocket.receive_json()
                meta = payload.get("meta") or None
                if not limiter.allow():
                    await send_player_json(
                        {"type": "rate_limited", "detail": "Too many commands, slow down."}
                    )
                    continue

                if payload.get("type") != "command":
                    await send_player_json({"type": "noop", "room": current_room})
                    continue

                await _sync_current_room_from_state()
                command_text = payload.get("command", "")
                await record_player_input(str(command_text))
                command_room = current_room
                previous_level = state.player.level
                args = payload.get("args", {}) or {}
                raw_tokens = command_text.strip().split()
                raw_verb = raw_tokens[0].lower() if raw_tokens else ""
                raw_args = raw_tokens[1:]
                tokens = raw_tokens
                if raw_verb and raw_verb not in commands.CommandVocabulary.chat_aliases:
                    tokens = commands.normalize_tokens(raw_tokens)
                verb = raw_verb or (tokens[0].lower() if tokens else "")
                arg_list = raw_args
                normalized_verb = tokens[0].lower() if tokens else ""
                normalized_args = tokens[1:]
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

                fatigue_bypassed = False
                if raw_tokens:
                    fatigue_bypass_requested = bool(
                        meta and meta.get(commands.FATIGUE_BYPASS_META_KEY)
                    )
                    if parsed is not None and parsed.verb == "x":
                        # Legacy kyra() handles `x` before the command-table fatigue path.
                        # See legacy/KYRANDIA.C:192-196.
                        parsed.args[commands.FATIGUE_CHECKED_ARG] = True
                        fatigue_bypassed = True
                    elif (
                        fatigue_bypass_requested
                        and parsed is not None
                        and commands.can_bypass_command_fatigue(parsed.verb, parsed.args)
                    ):
                        # UI satellite panels may request fatigue-free refreshes for
                        # the small read-only allowlist in commands.can_bypass_command_fatigue().
                        # Bypassed commands go straight to the dispatcher so a room routine
                        # cannot mutate state under a status-card refresh flag.
                        parsed.args[commands.FATIGUE_BYPASS_ARG] = True
                        fatigue_bypassed = True
                    else:
                        fatigue_result = commands.apply_command_fatigue_gate(
                            state,
                            getattr(parsed, "command_id", None) if parsed else None,
                        )
                        if fatigue_result is not None:
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
                                    "verb": getattr(parsed, "verb", verb) if parsed else verb,
                                },
                            }
                            if meta:
                                ack_payload["meta"] = meta
                            await send_player_json(ack_payload)
                            for event in fatigue_result.events:
                                envelope = {
                                    "type": "command_response",
                                    "room": current_room,
                                    "payload": event,
                                }
                                if meta:
                                    envelope["meta"] = meta
                                await send_player_json(envelope)
                            continue
                        if parsed is not None:
                            parsed.args[commands.FATIGUE_CHECKED_ARG] = True

                if raw_tokens and provider.room_scripts and not fatigue_bypassed:
                    # Legacy kyra() runs the room routine before the command table.
                    # See legacy/KYRCMDS.C:1251-1257.
                    handled = await provider.room_scripts.handle_command(
                        current_player_id(),
                        current_room,
                        command=verb,
                        args=arg_list,
                        player=state.player,
                    )
                    if (
                        not handled
                        and tokens != raw_tokens
                        and provider.room_scripts.allows_normalized_retry(current_room)
                    ):
                        # Generic parser cleanup can help older YAML rooms, while strict
                        # rooms opt out to preserve raw margv/GAMUTILS macro boundaries.
                        # See legacy/GAMUTILS.C:55-106.
                        handled = await provider.room_scripts.handle_command(
                            current_player_id(),
                            current_room,
                            command=normalized_verb,
                            args=normalized_args,
                            player=state.player,
                        )
                        if handled:
                            verb = normalized_verb
                            arg_list = normalized_args
                    if handled:
                        death_plan = getattr(
                            provider.room_scripts, "last_death_recovery_plan", None
                        )
                        try:
                            if death_plan is not None and getattr(
                                provider.room_scripts,
                                "defer_modern_death_recovery",
                                False,
                            ):
                                # modern_death_recovery: commit the recovered
                                # player and spill-room objects before live
                                # mutation or broadcasts. See docs/MODERN_FEATURES.md.
                                commands._persist_death_recovery_plan(
                                    state, state.player, death_plan
                                )
                                apply_death_recovery_plan(
                                    state.player, state.locations, death_plan
                                )
                                provider.room_scripts.sync_deferred_modern_death_recovery(
                                    death_plan
                                )
                                provider.room_scripts.last_death_recovery_plan = None
                            else:
                                commands._persist_player_state(state, state.player)
                        except Exception:
                            if death_plan is not None:
                                provider.room_scripts.get_and_clear_pending_events()
                                provider.room_scripts.last_death_recovery_plan = None
                            raise
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
                        await send_player_json(ack_payload)
                        await _send_level_up_cue(previous_level, command_room)
                        
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
                                event_room_value = event.get("room_id")
                                event_room = (
                                    current_room if event_room_value is None else int(event_room_value)
                                )
                                envelope = {"type": "room_broadcast", "room": event_room, "payload": event}
                                if meta:
                                    envelope["meta"] = meta
                                excluded_player = event.get("exclude_player")
                                excluded_players = set(event.get("exclude_players") or [])
                                if excluded_player:
                                    excluded_players.add(excluded_player)
                                excluded_sockets = set()
                                for excluded_player_id in excluded_players:
                                    for token in await provider.presence.sessions_for_player(
                                        excluded_player_id
                                    ):
                                        target_socket = session_connections.get(token)
                                        if target_socket:
                                            excluded_sockets.add(target_socket)
                                sender_socket = None if event.get("include_sender") else websocket
                                await _broadcast_game_json(
                                    provider.scope.app,
                                    gateway,
                                    event_room,
                                    envelope,
                                    sender=sender_socket,
                                    exclude=excluded_sockets,
                                )
                            elif scope == "global":
                                envelope = {"type": "system_broadcast", "payload": event}
                                if meta:
                                    envelope["meta"] = meta
                                for target_socket in list(session_connections.values()):
                                    if target_socket.application_state != WebSocketState.CONNECTED:
                                        continue
                                    await _send_game_socket_json(
                                        provider.scope.app,
                                        target_socket,
                                        envelope,
                                    )
                            elif scope == "target":
                                target_id = event.get("player")
                                if not target_id:
                                    continue
                                if event.get("death_reset"):
                                    sync_active_player_state_from_db(
                                        provider.scope.app, target_id
                                    )
                                # Legacy msgutl2 actor messages render to usrnum before room fan-out
                                # (legacy/KYRSPEL.C:389-396; room calls such as legacy/KYRROUS.C:847).
                                # The web port mirrors that actor view across every active player session,
                                # while silent command metadata keeps actor effects in the suppressible stream.
                                silent = bool(meta and meta.get("silent"))
                                envelope_type = "command_response"
                                if target_id == current_player_id() and not silent:
                                    envelope_type = "room_broadcast"
                                envelope_room = event.get("room_id", current_room)
                                envelope = {"type": envelope_type, "room": envelope_room, "payload": event}
                                if meta:
                                    envelope["meta"] = meta
                                for token in await provider.presence.sessions_for_player(target_id):
                                    target_socket = session_connections.get(token)
                                    if not target_socket:
                                        continue
                                    if target_socket.application_state != WebSocketState.CONNECTED:
                                        continue
                                    await _send_game_socket_json(
                                        provider.scope.app,
                                        target_socket,
                                        envelope,
                                        player_id=target_id,
                                    )
                            else:
                                envelope = {"type": "command_response", "room": current_room, "payload": event}
                                if meta:
                                    envelope["meta"] = meta
                                await send_player_json(envelope)

                        if transfer_event:
                            target_room = int(transfer_event.get("target_room", current_room))
                            leave_text = transfer_event.get("leave_text")
                            arrive_text = transfer_event.get("arrive_text")
                            legacy_transfer_format = bool(
                                transfer_event.get("legacy_transfer_format")
                            )
                            if legacy_transfer_format:
                                # Legacy remvgp()/entrgp() wrap room-facing movement text.
                                # Source: legacy/KYRUTIL.C:225-257.
                                if leave_text:
                                    leave_text = (
                                        f"*** {state.player.altnam} has just {leave_text}!"
                                    )
                                if arrive_text:
                                    arrive_text = (
                                        f"*** {state.player.altnam} has just {arrive_text}!"
                                    )
                            death_reset = bool(transfer_event.get("death_reset"))
                            transfer_metadata = {
                                key: transfer_event[key]
                                for key in (
                                    "modern_death_recovery",
                                    "old_level",
                                    "new_level",
                                    "filtered_items",
                                    "vanished_items",
                                    "dropped_rooms",
                                    "refresh_location",
                                    "recipient_scope",
                                )
                                if key in transfer_event
                            }
                            # YAML hitoth() death resets mirror initgp()+entrgp(), so
                            # every active session for the player must relocate and refresh.
                            # Source: legacy/KYRSPEL.C:303-321, legacy/KYRANDIA.C:325-356,
                            # and legacy/KYRUTIL.C:236-260.
                            if leave_text:
                                await _broadcast_game_json(
                                    provider.scope.app,
                                    gateway,
                                    current_room,
                                    {
                                        "type": "room_broadcast",
                                        "room": current_room,
                                        "payload": {
                                            "scope": "room",
                                            "event": "room_message",
                                            "type": "room_message",
                                            "player": current_player_id(),
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
                                location = state.locations.get(target_room)

                                async def _send_transfer_refresh(
                                    target_socket: WebSocket,
                                ) -> None:
                                    if location is None:
                                        return
                                    description_id, long_description = commands._location_description(
                                        state, location
                                    )
                                    refresh_events = [
                                        {
                                            "scope": "player",
                                            "event": "location_update",
                                            "type": "location_update",
                                            "location": location.id,
                                            "description": location.brfdes,
                                            "description_id": description_id,
                                            "long_description": long_description,
                                            "message_id": description_id,
                                            **({"death_reset": True} if death_reset else {}),
                                            **transfer_metadata,
                                        },
                                        {
                                            "scope": "player",
                                            "event": "location_description",
                                            "type": "location_description",
                                            "location": location.id,
                                            "message_id": description_id,
                                            "text": long_description or location.brfdes,
                                            **({"death_reset": True} if death_reset else {}),
                                            **transfer_metadata,
                                        },
                                    ]
                                    room_objects_event = commands._room_objects_event(
                                        location, state.objects or {}, None, description_id
                                    )
                                    if death_reset:
                                        room_objects_event["death_reset"] = True
                                    room_objects_event.update(transfer_metadata)
                                    refresh_events.append(room_objects_event)

                                    occupant_event = await _room_occupants_event(
                                        provider.presence,
                                        current_player_id(),
                                        target_room,
                                        state.messages,
                                        _active_player_flags(provider.scope.app),
                                    )
                                    if occupant_event:
                                        refresh_events.append(occupant_event)

                                    for refresh_event in refresh_events:
                                        envelope = {
                                            "type": "command_response",
                                            "room": target_room,
                                            "payload": refresh_event,
                                        }
                                        if meta:
                                            envelope["meta"] = meta
                                        await _send_game_socket_json(
                                            provider.scope.app,
                                            target_socket,
                                            envelope,
                                            player_id=current_player_id(),
                                        )

                                transfer_tokens = {session_token}
                                if death_reset:
                                    transfer_tokens.update(
                                        await provider.presence.sessions_for_player(
                                            current_player_id()
                                        )
                                    )

                                for target_token in transfer_tokens:
                                    target_socket = session_connections.get(target_token)
                                    if (
                                        target_socket is not None
                                        and target_socket.application_state
                                        == WebSocketState.CONNECTED
                                    ):
                                        await gateway.register(
                                            target_room, target_socket, announce=False
                                        )

                                    await provider.presence.set_location(
                                        current_player_id(), target_room, target_token
                                    )
                                    with provider.scope.app.state.session_factory() as db:
                                        repo = repositories.PlayerSessionRepository(db)
                                        repo.set_room(target_token, target_room)
                                        repo.mark_seen(target_token)
                                        db.commit()

                                    if target_token == session_token:
                                        current_room = target_room

                                    if (
                                        target_socket is not None
                                        and target_socket.application_state
                                        == WebSocketState.CONNECTED
                                    ):
                                        await _send_transfer_refresh(target_socket)

                                if death_reset:
                                    sync_active_player_state_from_db(
                                        provider.scope.app, current_player_id()
                                    )

                            if arrive_text:
                                await _broadcast_game_json(
                                    provider.scope.app,
                                    gateway,
                                    current_room,
                                    {
                                        "type": "room_broadcast",
                                        "room": current_room,
                                        "payload": {
                                            "scope": "room",
                                            "event": "room_message",
                                            "type": "room_message",
                                            "player": current_player_id(),
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
                    await send_player_json(
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
                    await send_player_json(
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

                session_exit_requested = any(
                    event.get("event") == "session_exit" for event in result.events
                )
                target_room = state.player.gamloc
                occupant_event = None
                if (
                    not session_exit_requested
                    and target_room != current_room
                    and target_room in state.locations
                ):
                    await gateway.register(target_room, websocket, announce=False)
                    await provider.presence.set_location(
                        current_player_id(), target_room, session_token
                    )
                    with provider.scope.app.state.session_factory() as db:
                        repo = repositories.PlayerSessionRepository(db)
                        repo.set_room(session_token, target_room)
                        repo.mark_seen(session_token)
                        db.commit()
                    current_room = target_room
                    occupant_event = await _room_occupants_event(
                        provider.presence,
                        current_player_id(),
                        current_room,
                        state.messages,
                        _active_player_flags(provider.scope.app),
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
                await send_player_json(ack_payload)
                await _send_level_up_cue(previous_level, command_room)

                for event in result.events:
                    scope = event.get("scope", "player")
                    if scope == "room":
                        event_room_value = event.get("room_id")
                        event_room = (
                            current_room if event_room_value is None else int(event_room_value)
                        )
                        envelope = {"type": "room_broadcast", "room": event_room, "payload": event}
                        if meta:
                            envelope["meta"] = meta
                        excluded_player = event.get("exclude_player")
                        excluded_players = set(event.get("exclude_players") or [])
                        if excluded_player:
                            excluded_players.add(excluded_player)
                        excluded_sockets = set()
                        for excluded_player_id in excluded_players:
                            for token in await provider.presence.sessions_for_player(
                                excluded_player_id
                            ):
                                target_socket = session_connections.get(token)
                                if target_socket:
                                    excluded_sockets.add(target_socket)
                        sender_socket = None if event.get("include_sender") else websocket
                        await _broadcast_game_json(
                            provider.scope.app,
                            gateway,
                            event_room,
                            envelope,
                            sender=sender_socket,
                            exclude=excluded_sockets,
                        )
                    elif scope == "global":
                        envelope = {"type": "system_broadcast", "payload": event}
                        if meta:
                            envelope["meta"] = meta
                        for target_socket in list(session_connections.values()):
                            if target_socket.application_state != WebSocketState.CONNECTED:
                                continue
                            await _send_game_socket_json(
                                provider.scope.app,
                                target_socket,
                                envelope,
                            )
                    elif scope == "nearby_room":
                        # Legacy sndnear(): broadcast to players in adjacent rooms.
                        # See legacy/KYRUTIL.C:193-208.
                        nearby_room_id = event.get("room_id")
                        if nearby_room_id is not None:
                            envelope = {"type": "room_broadcast", "room": nearby_room_id, "payload": event}
                            if meta:
                                envelope["meta"] = meta
                            excluded_player = event.get("exclude_player")
                            excluded_players = set(event.get("exclude_players") or [])
                            if excluded_player:
                                excluded_players.add(excluded_player)
                            excluded_sockets = set()
                            for excluded_player_id in excluded_players:
                                for token in await provider.presence.sessions_for_player(
                                    excluded_player_id
                                ):
                                    target_socket = session_connections.get(token)
                                    if target_socket:
                                        excluded_sockets.add(target_socket)
                            await _broadcast_game_json(
                                provider.scope.app,
                                gateway,
                                nearby_room_id,
                                envelope,
                                exclude=excluded_sockets or None,
                            )
                            if event.get("include_sender") and nearby_room_id != current_room:
                                await send_player_json(envelope)
                    elif scope == "target":
                        target_id = event.get("player")
                        if not target_id:
                            continue
                        if event.get("death_reset"):
                            sync_active_player_state_from_db(provider.scope.app, target_id)
                        envelope_room = event.get("room_id", current_room)
                        envelope = {"type": "command_response", "room": envelope_room, "payload": event}
                        if meta:
                            envelope["meta"] = meta
                        for token in await provider.presence.sessions_for_player(target_id):
                            target_socket = session_connections.get(token)
                            if not target_socket:
                                continue
                            if target_socket.application_state != WebSocketState.CONNECTED:
                                continue
                            location = event.get("location")
                            if event.get("type") == "location_update" and isinstance(location, int):
                                await gateway.register(location, target_socket, announce=False)
                                await provider.presence.set_location(target_id, location, token)
                                with provider.scope.app.state.session_factory() as db:
                                    repo = repositories.PlayerSessionRepository(db)
                                    repo.set_room(token, location)
                                    repo.mark_seen(token)
                                    db.commit()
                            await _send_game_socket_json(
                                provider.scope.app,
                                target_socket,
                                envelope,
                                player_id=target_id,
                            )
                            if event.get("type") == "location_update" and isinstance(location, int):
                                occupants_event = await _room_occupants_event(
                                    provider.presence,
                                    target_id,
                                    location,
                                    state.messages,
                                    _active_player_flags(provider.scope.app),
                                )
                                if occupants_event:
                                    occupants_envelope = {
                                        "type": "command_response",
                                        "room": location,
                                        "payload": occupants_event,
                                    }
                                    if meta:
                                        occupants_envelope["meta"] = meta
                                    await _send_game_socket_json(
                                        provider.scope.app,
                                        target_socket,
                                        occupants_envelope,
                                        player_id=target_id,
                                    )
                    elif scope == "control":
                        if event.get("event") == "session_exit":
                            session_exit_requested = True
                    else:
                        envelope = {"type": "command_response", "room": current_room, "payload": event}
                        if meta:
                            envelope["meta"] = meta
                        await send_player_json(envelope)
                if session_exit_requested:
                    await _deactivate_current_session()
                    break
        except WebSocketDisconnect:
            await provider.presence.remove(session_token)
            await gateway.unregister(current_room, websocket)
        finally:
            if session_connections.get(session_token) is websocket:
                _remove_active_player_session(
                    provider.scope.app, session_token, current_player_id()
                )
                session_connections.pop(session_token, None)
            getattr(provider.scope.app.state, "game_socket_players", {}).pop(websocket, None)
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
