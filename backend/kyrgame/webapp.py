from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from .gateway import RoomGateway
from .presence import PresenceService
from .rate_limit import RateLimiter
from .runtime import bootstrap_app, shutdown_app


class SessionRequest(BaseModel):
    player_id: str


class SessionResponse(BaseModel):
    status: str
    session: dict


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


def get_request_provider(request: Request) -> FixtureProvider:
    return FixtureProvider(request)


def get_websocket_provider(websocket: WebSocket) -> FixtureProvider:
    return FixtureProvider(websocket)


auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post("/session", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def start_session(payload: SessionRequest):
    return {"status": "ok", "session": {"player_id": payload.player_id, "message": "Session established"}}


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


@admin_router.get("/fixtures")
async def fixture_summary(provider: Annotated[FixtureProvider, Depends(get_request_provider)]):
    return provider.cache["summary"]


@admin_router.post("/reload-scripts")
async def reload_room_scripts(provider: Annotated[FixtureProvider, Depends(get_request_provider)]):
    scripts = provider.room_scripts
    scripts.reload_scripts()
    return {"status": "ok", "reloads": scripts.reloads}


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

    gateway: RoomGateway | None = None

    @app.websocket("/ws/rooms/{room_id}")
    async def room_socket(
        websocket: WebSocket,
        room_id: int,
        provider: Annotated[FixtureProvider, Depends(get_websocket_provider)],
    ):
        nonlocal gateway
        if gateway is None:
            gateway = provider.gateway

        player_id = websocket.query_params.get("player_id")
        if not player_id:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        locations = provider.location_index
        limiter = RateLimiter(max_events=2, window_seconds=0.5)
        current_room = room_id

        await provider.presence.set_location(player_id, current_room)
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

                command = payload.get("command")
                args = payload.get("args", {}) or {}

                if command == "move":
                    direction = args.get("direction")
                    try:
                        target_room = _resolve_room_from_direction(current_room, direction, locations)
                    except ValueError as exc:
                        await websocket.send_json(
                            {"type": "command_error", "room": current_room, "detail": str(exc)}
                        )
                        continue

                    if target_room != current_room:
                        await gateway.register(target_room, websocket, announce=False)
                        await provider.presence.set_location(player_id, target_room)
                        current_room = target_room

                        await gateway.broadcast(
                            current_room,
                            {
                                "type": "room_broadcast",
                                "room": current_room,
                                "payload": {"event": "player_enter", "player": player_id},
                            },
                            sender=websocket,
                        )

                    await websocket.send_json(
                        {"type": "command_response", "room": current_room, "payload": payload}
                    )
                elif command == "chat":
                    await websocket.send_json(
                        {"type": "command_response", "room": current_room, "payload": payload}
                    )
                    await gateway.broadcast(
                        current_room,
                        {
                            "type": "room_broadcast",
                            "room": current_room,
                            "payload": {"event": "chat", "player": player_id, "args": args},
                        },
                        sender=websocket,
                    )
                else:
                    await websocket.send_json({"type": "command_response", "room": current_room, "payload": payload})
        except WebSocketDisconnect:
            await provider.presence.remove(player_id)
            await gateway.unregister(current_room, websocket)

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
