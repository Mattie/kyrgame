import pytest

from kyrgame import commands, fixtures, models


class FakeClock:
    def __init__(self, start: float = 100.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float):
        self.now += seconds


@pytest.fixture
def base_state():
    locations = {location.id: location for location in fixtures.load_locations()}
    objects = {obj.id: obj for obj in fixtures.load_objects()}
    player = fixtures.build_player()
    return commands.GameState(player=player, locations=locations, objects=objects)


def test_registry_exposes_command_metadata():
    registry = commands.build_default_registry()

    move_entry = registry["move"]
    chat_entry = registry["chat"]

    assert move_entry.metadata.required_level >= 1
    assert chat_entry.metadata.required_level == 0
    assert move_entry.metadata.cooldown_seconds == 0
    assert chat_entry.metadata.cooldown_seconds > 0


@pytest.mark.parametrize(
    "verb,args,expected_location,expected_event_type",
    [
        ("move", {"direction": "north"}, 1, "player_moved"),
        ("chat", {"text": "hello"}, 0, "chat"),
        ("inventory", {}, 0, "inventory"),
    ],
)
@pytest.mark.anyio
async def test_command_handlers_apply_state_and_emit_events(base_state, verb, args, expected_location, expected_event_type):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry, clock=FakeClock())

    result = await dispatcher.dispatch(verb, args, base_state)

    assert base_state.player.gamloc == expected_location
    assert any(event["type"] == expected_event_type for event in result.events)
    assert result.state.player is base_state.player


@pytest.mark.anyio
async def test_move_tracks_previous_location(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry, clock=FakeClock())

    base_state.player.pgploc = 99

    await dispatcher.dispatch("move", {"direction": "north"}, base_state)

    assert base_state.player.pgploc == 0
    assert base_state.player.gamloc == 1


@pytest.mark.anyio
async def test_insufficient_level_blocks_execution(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    base_state.player.level = 0

    with pytest.raises(commands.LevelRequirementError):
        await dispatcher.dispatch("move", {"direction": "north"}, base_state)


@pytest.mark.anyio
async def test_blocked_exit_prevents_move(base_state):
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    base_state.player.gamloc = 7

    with pytest.raises(commands.BlockedExitError):
        await dispatcher.dispatch("move", {"direction": "east"}, base_state)


@pytest.mark.anyio
async def test_cooldown_prevents_spam(base_state):
    clock = FakeClock()
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry, clock=clock)

    await dispatcher.dispatch("chat", {"text": "hello"}, base_state)

    with pytest.raises(commands.CooldownActiveError):
        await dispatcher.dispatch("chat", {"text": "hello again"}, base_state)

    clock.advance(registry["chat"].metadata.cooldown_seconds + 0.1)
    result = await dispatcher.dispatch("chat", {"text": "hello later"}, base_state)

    assert any(
        event["type"] == "chat" and event["text"] == "hello later" for event in result.events
    )
