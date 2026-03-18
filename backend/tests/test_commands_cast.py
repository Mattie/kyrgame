import random

import pytest

from kyrgame import commands, constants, fixtures
from kyrgame.effects import EffectResult, SpellEffect


class FakePresence:
    async def players_in_room(self, room_id: int) -> set[str]:  # noqa: ARG002
        return set()


def _build_state(player):
    locations = {location.id: location for location in fixtures.load_locations()}
    objects = {obj.id: obj for obj in fixtures.load_objects()}
    messages = fixtures.load_messages()
    content_mappings = fixtures.load_content_mappings()
    return commands.GameState(
        player=player,
        locations=locations,
        objects=objects,
        messages=messages,
        content_mappings=content_mappings,
        presence=FakePresence(),
        player_lookup=lambda _player_id: None,
    )


def _build_player(**updates):
    player = fixtures.build_player()
    data = player.model_dump()
    data.update(updates)
    return player.model_copy(update=data)


class TrackingPresence:
    def __init__(self, occupants: set[str]):
        self._occupants = occupants

    async def players_in_room(self, room_id: int) -> set[str]:  # noqa: ARG002
        return self._occupants


@pytest.mark.anyio
async def test_cast_requires_spell_name():
    player = _build_player(flags=int(constants.PlayerFlag.LOADED))
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": ""}, state)

    assert [event["message_id"] for event in result.events] == ["OBJM07"]


@pytest.mark.anyio
async def test_cast_rejects_non_memorized_spells_with_broadcast():
    player = _build_player(flags=int(constants.PlayerFlag.LOADED), spells=[], nspells=0)
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "noouch"}, state)

    assert [event["message_id"] for event in result.events] == ["NOTMEM", "SPFAIL"]
    assert result.events[1]["exclude_player"] == state.player.plyrid


@pytest.mark.anyio
async def test_cast_enforces_level_gate_with_sndutl_emote():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=1,
        spts=20,
        spells=[0],
        nspells=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "abbracada"}, state)

    assert result.events[0]["message_id"] == "KSPM10"
    assert result.events[1]["text"] == f"*** {state.player.altnam} is mouthing off."


@pytest.mark.anyio
async def test_cast_enforces_spell_point_gate_with_sndutl_emote():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=10,
        spts=1,
        spells=[0],
        nspells=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "abbracada"}, state)

    assert result.events[0]["message_id"] == "KSPM10"
    assert result.events[1]["text"] == f"*** {state.player.altnam} is waving his arms."


@pytest.mark.anyio
async def test_cast_consumes_memorized_spell_and_triggers_effects(monkeypatch):
    class StubEffectEngine:
        last_call = None

        def __init__(self, spells, messages, clock=None, rng=None, objects=None, locations=None):  # noqa: D401, ARG002
            self.spells = {spell.id: spell for spell in spells}
            self.messages = messages
            self.effects = {}

        def cast_spell(self, player, spell_id, target, target_player=None, *, apply_cost=True):
            StubEffectEngine.last_call = {
                "spell_id": spell_id,
                "target": target,
                "target_player": target_player,
                "apply_cost": apply_cost,
            }
            return EffectResult(
                success=True,
                message_id="SPLTEST",
                text="cast ok",
                animation="sparkle",
                context={"target": target},
            )

    monkeypatch.setattr(commands, "SpellEffectEngine", StubEffectEngine)

    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=5,
        spts=4,
        spells=[42],
        nspells=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "noouch"}, state)

    assert state.player.spells == []
    assert state.player.nspells == 0
    assert state.player.spts == 3
    assert StubEffectEngine.last_call == {
        "spell_id": 42,
        "target": None,
        "target_player": None,
        "apply_cost": False,
    }
    assert result.events[0]["message_id"] == "SPLTEST"


@pytest.mark.anyio
async def test_cast_targeted_spell_resolves_player_and_calls_effect_engine(monkeypatch):
    class StubEffectEngine:
        last_call = None

        def __init__(self, spells, messages, clock=None, rng=None, objects=None, locations=None):  # noqa: D401, ARG002
            self.spells = {spell.id: spell for spell in spells}
            self.messages = messages
            saywhat = self.spells[50]
            self.effects = {
                50: SpellEffect(
                    spell=saywhat,
                    cost=saywhat.level,
                    cooldown=0.0,
                    requires_target=True,
                )
            }

        def cast_spell(self, player, spell_id, target, target_player=None, *, apply_cost=True):
            StubEffectEngine.last_call = {
                "spell_id": spell_id,
                "target": target,
                "target_player": target_player,
                "apply_cost": apply_cost,
            }
            return EffectResult(
                success=True,
                message_id="S51M03",
                text="cast ok",
                animation="sparkle",
                context={"target": target},
            )

    monkeypatch.setattr(commands, "SpellEffectEngine", StubEffectEngine)

    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=10,
        spts=15,
        spells=[50],
        nspells=1,
    )
    target = _build_player(
        plyrid="target",
        attnam="target",
        altnam="Target",
        gamloc=player.gamloc,
    )
    state = _build_state(player)
    state.presence = TrackingPresence({player.plyrid, target.plyrid})
    state.player_lookup = lambda pid: target if pid == target.plyrid else player

    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "saywhat target"}, state)

    assert StubEffectEngine.last_call == {
        "spell_id": 50,
        "target": "target",
        "target_player": target,
        "apply_cost": False,
    }
    assert result.events[0]["message_id"] == "S51M03"


@pytest.mark.anyio
async def test_cast_target_missing_emits_phantom_failure():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        spells=[4],
        nspells=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "bookworm nobody"}, state)

    assert result.events[0]["message_id"] == "KSPM02"
    assert result.events[1]["scope"] == "room"


@pytest.mark.anyio
async def test_cast_target_object_emits_kspm_resist_messages():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        spells=[4],
        nspells=1,
    )
    state = _build_state(player)
    location = state.locations[state.player.gamloc]
    pearl_id = next(obj.id for obj in state.objects.values() if obj.name == "pearl")
    location = location.model_copy(update={"objects": [pearl_id], "nlobjs": 1})
    state.locations[location.id] = location

    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "bookworm pearl"}, state)

    assert [event["message_id"] for event in result.events] == ["KSPM00", "KSPM01"]


@pytest.mark.anyio
async def test_cast_bookworm_broadcast_excludes_target_player():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        spells=[4],
        nspells=1,
    )
    target = _build_player(
        plyrid="target",
        attnam="target",
        altnam="Target",
        gamloc=player.gamloc,
        offspls=1,
    )
    state = _build_state(player)
    state.presence = TrackingPresence({player.plyrid, target.plyrid})
    state.player_lookup = lambda pid: target if pid == target.plyrid else player

    moonstone_id = next(obj.id for obj in state.objects.values() if obj.name == "moonstone")
    player = player.model_copy(
        update={"gpobjs": [moonstone_id], "obvals": [0], "npobjs": 1}
    )
    state.player = player

    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "bookworm target"}, state)

    assert [event["message_id"] for event in result.events] == ["S05M03", "S05M04", "S05M05"]
    assert result.events[1]["player"] == target.plyrid
    assert result.events[2]["exclude_player"] == target.plyrid


@pytest.mark.anyio
async def test_cast_targeting_dragon_backfires_on_caster():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        spells=[4],
        nspells=1,
        hitpts=60,
    )
    state = _build_state(player)
    state.rng = random.Random(5)
    location = state.locations[state.player.gamloc]
    dragon_id = next(obj.id for obj in state.objects.values() if obj.name == "dragon")
    location = location.model_copy(update={"objects": [dragon_id], "nlobjs": 1})
    state.locations[location.id] = location

    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "bookworm dragon"}, state)

    expected_damage = random.Random(5).randint(20, 46)
    assert [event["message_id"] for event in result.events[:2]] == ["ZMSG08", "ZMSG09"]
    assert state.player.hitpts == 60 - expected_damage


@pytest.mark.anyio
async def test_cast_area_damage_spells_apply_damage_and_protection():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=10,
        spts=25,
        spells=[5],
        nspells=1,
    )
    target = _build_player(
        plyrid="target",
        attnam="target",
        altnam="Target",
        gamloc=player.gamloc,
        hitpts=30,
        level=5,
    )
    protected = _build_player(
        plyrid="shielded",
        attnam="shielded",
        altnam="Shielded",
        gamloc=player.gamloc,
        hitpts=30,
        level=5,
    )
    protected.charms[constants.FIRPRO] = 1
    state = _build_state(player)
    state.presence = TrackingPresence({player.plyrid, target.plyrid, protected.plyrid})
    state.player_lookup = lambda pid: {
        player.plyrid: player,
        target.plyrid: target,
        protected.plyrid: protected,
    }.get(pid)

    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "burnup"}, state)

    message_ids = {event["message_id"] for event in result.events}
    assert "S06M00" in message_ids
    assert "S06M01" in message_ids
    assert "S06M02" in message_ids
    assert "S06M03" in message_ids
    assert "S06M04" in message_ids
    assert target.hitpts == 20
    assert protected.hitpts == 30


@pytest.mark.anyio
async def test_cast_goto_moves_caster_with_standard_room_transition_events():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        gamloc=0,
        spells=[22],
        nspells=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "goto 1"}, state)

    assert state.player.gamloc == 1
    assert state.player.pgploc == 0
    assert result.events[0]["message_id"] == "S23M02"
    assert any(
        event.get("event") == "player_enter"
        and event.get("from") == 0
        and event.get("to") == 1
        for event in result.events
    )
    assert any(
        event.get("event") == "location_update" and event.get("location") == 1
        for event in result.events
    )


@pytest.mark.anyio
async def test_cast_whoub_reveals_target_true_identity():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        spells=[64],
        nspells=1,
    )
    target = _build_player(
        plyrid="truth",
        attnam="Mirror Mask",
        altnam="A Willowisp",
        gamloc=player.gamloc,
        flags=int(constants.PlayerFlag.WILLOW),
    )
    target.charms[constants.CharmSlot.ALTERNATE_NAME] = 6
    state = _build_state(player)
    state.presence = TrackingPresence({player.plyrid, target.plyrid})
    state.player_lookup = lambda pid: target if pid == target.plyrid else player

    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "whoub Mirror Mask"}, state)

    assert [event["message_id"] for event in result.events] == ["S65M00", "S65M01", "S65M02"]
    assert "truth" in result.events[0]["text"]
    assert result.events[1]["player"] == target.plyrid
    assert result.events[2]["exclude_player"] == target.plyrid


@pytest.mark.anyio
async def test_cast_goto_emits_room_broadcast_message_payload_for_occupants():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        gamloc=0,
        spells=[22],
        nspells=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "goto 1"}, state)

    room_messages = [event for event in result.events if event.get("message_id") == "S23M03"]
    assert room_messages
    assert room_messages[0]["scope"] == "nearby_room"
    assert room_messages[0]["room_id"] == 0


@pytest.mark.anyio
async def test_cast_goto_emits_remvgp_vanished_departure_emote_to_origin_room():
    """On successful goto, a 'vanished in a red cloud' emote must be sent to the
    origin room, mirroring remvgp(gmpptr, "vanished in a red cloud") from legacy.

    Parity: legacy/KYRSPEL.C:712.
    """
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        gamloc=0,
        spells=[22],
        nspells=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "goto 1"}, state)

    vanished_events = [
        e for e in result.events
        if e.get("scope") == "nearby_room"
        and e.get("room_id") == 0
        and e.get("text") == f"*** {player.altnam} has just vanished in a red cloud!"
    ]
    assert vanished_events, "Expected a 'vanished in a red cloud' departure emote to origin room"
    assert vanished_events[0].get("exclude_player") == player.plyrid


@pytest.mark.anyio
async def test_cast_goto_invalid_target_uses_legacy_failure_messages():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        spells=[22],
        nspells=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "goto 999"}, state)

    assert state.player.gamloc == player.gamloc
    assert [event["message_id"] for event in result.events] == ["S23M00", "S23M01"]


@pytest.mark.anyio
async def test_cast_goto_non_numeric_target_uses_atoi_zero_teleports_to_room_0():
    """Legacy spl023() uses atoi() for parsing: pure-alpha input (no numeric prefix)
    yields 0, which is a valid room, so the caster is teleported to room 0.

    Parity: legacy/KYRSPEL.C:701 — atoi("abc") == 0, 0 <= 218, goto succeeds.
    """
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        gamloc=1,
        spells=[22],
        nspells=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "goto abc"}, state)

    # atoi("abc") == 0 → teleport to room 0 succeeds
    assert state.player.gamloc == 0
    assert result.events[0]["message_id"] == "S23M02"


@pytest.mark.anyio
async def test_cast_goto_numeric_prefix_target_uses_atoi_prefix_room():
    """Legacy atoi parsing: a numeric-prefix string like '12foo' is parsed as 12.

    Parity: legacy/KYRSPEL.C:701 — atoi("12foo") == 12, teleport to room 12.
    """
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        gamloc=0,
        spells=[22],
        nspells=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "goto 12foo"}, state)

    assert state.player.gamloc == 12
    assert result.events[0]["message_id"] == "S23M02"


@pytest.mark.anyio
async def test_cast_goto_no_room_arg_emits_objm07_and_sndutl_room_broadcast():
    """Legacy spl023(): margc==2 (no room arg) → OBJM07 to caster + sndutl room emote.

    Parity: legacy/KYRSPEL.C:696-699.
    """
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        spells=[22],
        nspells=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "goto"}, state)

    # Caster location must not change.
    assert state.player.gamloc == player.gamloc

    # Caster receives OBJM07; room receives sndutl broadcast (no message_id).
    message_ids = [event["message_id"] for event in result.events]
    assert message_ids[0] == "OBJM07"
    assert message_ids[1] is None

    # Room event must be scoped to "room" and exclude the caster.
    room_event = result.events[1]
    assert room_event["scope"] == "room"
    assert room_event.get("exclude_player") == player.plyrid
    assert "failing at spellcasting" in room_event["text"]


@pytest.mark.anyio
async def test_cast_goto_transition_events_keep_cast_command_message_id():
    """Teleport transition metadata should stay tied to the cast command.

    Legacy spl023() emits S23M03 only for the departure broadcast in the origin
    room; destination movement/update events remain part of the cast command flow.
    """
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        gamloc=0,
        spells=[22],
        nspells=1,
    )
    state = _build_state(player)
    vocabulary = commands.CommandVocabulary(fixtures.load_commands(), fixtures.load_messages())
    registry = commands.build_default_registry(vocabulary)
    dispatcher = commands.CommandDispatcher(registry)

    parsed = vocabulary.parse_text("cast goto 1")
    result = await dispatcher.dispatch_parsed(parsed, state)

    location_update = next(
        event for event in result.events if event.get("event") == "location_update"
    )
    player_enter = next(event for event in result.events if event.get("event") == "player_enter")
    departure = next(event for event in result.events if event.get("message_id") == "S23M03")

    assert location_update["message_id"] == "CMD003"
    assert player_enter["message_id"] == "CMD003"
    assert departure["message_id"] == "S23M03"
