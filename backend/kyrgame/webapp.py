import secrets
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from starlette.websockets import WebSocketState

from . import commands, constants, models, repositories
from .gateway import RoomGateway
from .presence import PresenceService
from .rate_limit import RateLimiter
from .runtime import bootstrap_app, shutdown_app


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
            raise HTTPException(status_code=404, detail="Session not found")
        repo.mark_seen(payload.resume_token)
        room_id = existing.room_id
        token = existing.session_token
        resumed = True
        status_code = status.HTTP_200_OK
    else:
        if not payload.allow_multiple:
            replaced_tokens = repo.deactivate_all(player.id)
        token = secrets.token_urlsafe(24)
        repo.create_session(player_id=player.id, session_token=token, room_id=room_id)

    db.commit()

    session_connections = request.app.state.session_connections
    for old_token in replaced_tokens:
        old_socket = session_connections.pop(old_token, None)
        previous_room = request.app.state.presence.session_rooms.get(old_token)
        if previous_room is not None and old_socket is not None:
            await request.app.state.gateway.unregister(previous_room, old_socket)
        if old_socket is not None and old_socket.application_state == WebSocketState.CONNECTED:
            await old_socket.close(code=status.WS_1011_INTERNAL_ERROR)
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
    if active_socket is not None and active_socket.application_state == WebSocketState.CONNECTED:
        await request.app.state.gateway.unregister(session_record.room_id, active_socket)
        await active_socket.close(code=status.WS_1000_NORMAL_CLOSURE)
    await request.app.state.presence.remove(session_record.session_token)
    return LogoutResponse(status="logged_out")


commands_router = APIRouter(tags=["commands"])


@commands_router.get("/commands")
async def list_commands(provider: Annotated[FixtureProvider, Depends(get_request_provider)]):
    return [command.model_dump() for command in provider.cache["commands"]]


world_router = APIRouter(prefix="/world", tags=["world"])


@world_router.get("/locations")
async def list_locations(provider: Annotated[FixtureProvider, Depends(get_request_provider)]):
    return [location.model_dump() for location in provider.cache["locations"]]


objects_router = APIRouter(tags=["objects"])


@objects_router.get("/objects")
async def list_objects(provider: Annotated[FixtureProvider, Depends(get_request_provider)]):
    return [game_object.model_dump() for game_object in provider.cache["objects"]]


spells_router = APIRouter(tags=["spells"])


@spells_router.get("/spells")
async def list_spells(provider: Annotated[FixtureProvider, Depends(get_request_provider)]):
    return [spell.model_dump() for spell in provider.cache["spells"]]


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
async def fixture_summary(provider: Annotated[FixtureProvider, Depends(get_request_provider)]):
    return provider.cache["summary"]


@admin_router.post("/reload-scripts")
async def reload_room_scripts(provider: Annotated[FixtureProvider, Depends(get_request_provider)]):
    scripts = provider.room_scripts
    scripts.reload_scripts()
    return {"status": "ok", "reloads": scripts.reloads}


@players_router.get("/example")
async def example_player(provider: Annotated[FixtureProvider, Depends(get_request_provider)]):
    return provider.cache["player_template"].model_dump()


@players_router.post("/echo")
async def echo_player(player: models.PlayerModel):
    return {"player": player.model_dump()}


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await bootstrap_app(app)
        yield
        await shutdown_app(app)

    app = FastAPI(title="Kyrgame API", lifespan=lifespan)

    app.include_router(auth_router)
    app.include_router(commands_router)
    app.include_router(world_router)
    app.include_router(objects_router)
    app.include_router(spells_router)
    app.include_router(i18n_router)
    app.include_router(admin_router)
    app.include_router(players_router)

    gateway: RoomGateway | None = None
    app.state.session_connections = {}

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
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        db_session = provider.scope.app.state.session_factory()
        try:
            session_repo = repositories.PlayerSessionRepository(db_session)
            session_record = session_repo.get_by_token(session_token)
            if not session_record:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

            player = db_session.get(models.Player, session_record.player_id)
            if not player:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

            session_repo.mark_seen(session_token)
            db_session.commit()
            player_id = player.plyrid
            current_room = session_record.room_id
        finally:
            db_session.close()

        session_connections = provider.scope.app.state.session_connections
        existing_socket = session_connections.get(session_token)
        if existing_socket is not None and existing_socket.application_state == WebSocketState.CONNECTED:
            await gateway.unregister(current_room, existing_socket)
            await existing_socket.close(code=status.WS_1013_TRY_AGAIN_LATER)
        session_connections[session_token] = websocket

        limiter = RateLimiter(max_events=2, window_seconds=0.5)

        player_state = provider.cache["player_template"].model_copy(deep=True)
        player_state.plyrid = player_id
        player_state.gamloc = current_room
        player_state.pgploc = current_room
        state = commands.GameState(
            player=player_state,
            locations=provider.location_index,
            objects={obj.id: obj for obj in provider.cache["objects"]},
        )

        await provider.presence.set_location(player_id, current_room, session_token)
        await gateway.register(current_room, websocket)

        await gateway.broadcast(
            current_room,
            {
                "type": "room_broadcast",
                "room": current_room,
                "payload": {"event": "player_enter", "player": player_id},
            },
            sender=websocket,
        )

        try:
            while True:
                payload = await websocket.receive_json()
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
                    result = await provider.command_dispatcher.dispatch_parsed(parsed, state)
                except commands.CommandError as exc:  # type: ignore[attr-defined]
                    await websocket.send_json(
                        {
                            "type": "command_error",
                            "room": current_room,
                            "payload": {
                                "command_id": getattr(parsed, "command_id", None)
                                if "parsed" in locals()
                                else None,
                                "message_id": getattr(exc, "message_id", None),
                                "detail": str(exc),
                            },
                        }
                    )
                    continue

                target_room = state.player.gamloc
                if target_room != current_room:
                    await gateway.register(target_room, websocket, announce=False)
                    await provider.presence.set_location(player_id, target_room, session_token)
                    with provider.scope.app.state.session_factory() as db:
                        repo = repositories.PlayerSessionRepository(db)
                        repo.set_room(session_token, target_room)
                        repo.mark_seen(session_token)
                        db.commit()
                    current_room = target_room

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
                await websocket.send_json(ack_payload)

                for event in result.events:
                    scope = event.get("scope", "player")
                    if scope == "room":
                        await gateway.broadcast(
                            current_room,
                            {"type": "room_broadcast", "room": current_room, "payload": event},
                            sender=websocket,
                        )
                    else:
                        await websocket.send_json(
                            {"type": "command_response", "room": current_room, "payload": event}
                        )
        except WebSocketDisconnect:
            await provider.presence.remove(session_token)
            await gateway.unregister(current_room, websocket)
            if session_connections.get(session_token) is websocket:
                session_connections.pop(session_token, None)
        finally:
            if session_connections.get(session_token) is websocket:
                session_connections.pop(session_token, None)

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
