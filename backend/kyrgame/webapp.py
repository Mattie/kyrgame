from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from .gateway import RoomGateway
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
    def room_scripts(self):
        return self.scope.app.state.room_scripts


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
    app.include_router(admin_router)

    gateway: RoomGateway | None = None

    @app.websocket("/ws/rooms/{room_id}")
    async def room_socket(websocket: WebSocket, room_id: int, provider: Annotated[FixtureProvider, Depends(get_websocket_provider)]):
        nonlocal gateway
        if gateway is None:
            gateway = provider.gateway
        await gateway.register(room_id, websocket)
        try:
            while True:
                payload = await websocket.receive_json()
                if payload.get("type") == "command":
                    await websocket.send_json({"type": "command_response", "room": room_id, "echo": payload})
                    await gateway.broadcast(
                        room_id,
                        {"type": "room_broadcast", "room": room_id, "payload": payload},
                        sender=websocket,
                    )
                else:
                    await websocket.send_json({"type": "noop", "room": room_id})
        except WebSocketDisconnect:
            await gateway.unregister(room_id, websocket)

    return app
