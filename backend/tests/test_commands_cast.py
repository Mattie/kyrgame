import random

import pytest
from sqlalchemy import select

from kyrgame import commands, constants, fixtures, models
from kyrgame.database import create_session, get_engine, init_db_schema
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


class RoomPresence:
    def __init__(self, occupants_by_room: dict[int, set[str]]):
        self._occupants_by_room = occupants_by_room

    async def players_in_room(self, room_id: int) -> set[str]:
        return set(self._occupants_by_room.get(room_id, set()))


class OrderedPresence:
    def __init__(self, occupants: list[str]):
        self._occupants = occupants

    async def players_in_room(self, room_id: int):  # noqa: ARG002
        return list(self._occupants)


class FixedRng:
    def __init__(self, *, randrange_values=(), randint_values=()):
        self._randrange_values = list(randrange_values)
        self._randint_values = list(randint_values)

    def randrange(self, low: int, high: int) -> int:  # noqa: ARG002
        if self._randrange_values:
            return self._randrange_values.pop(0)
        return low

    def randint(self, low: int, high: int) -> int:  # noqa: ARG002
        if self._randint_values:
            return self._randint_values.pop(0)
        return low


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
async def test_cast_targeting_dragon_death_resets_caster_and_refreshes_room():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED | constants.PlayerFlag.FEMALE),
        altnam="Some psuedo dragon",
        attnam="psuedo dragon",
        level=25,
        spts=25,
        spells=[4],
        nspells=1,
        hitpts=1,
        gamloc=7,
        pgploc=7,
        gold=44,
        gpobjs=[0],
        obvals=[10],
        npobjs=1,
        stones=[9, 8, 7, 6],
    )
    state = _build_state(player)
    state.rng = FixedRng(randint_values=[20], randrange_values=[2, 3, 4, 5])
    location = state.locations[state.player.gamloc]
    dragon_id = next(obj.id for obj in state.objects.values() if obj.name == "dragon")
    location = location.model_copy(update={"objects": [dragon_id], "nlobjs": 1})
    state.locations[location.id] = location

    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "bookworm dragon"}, state)

    assert [event["message_id"] for event in result.events[:4]] == [
        "ZMSG08",
        "ZMSG09",
        "DIEMSG",
        "KILLED",
    ]
    assert state.player.gamloc == 0
    assert state.player.pgploc == 0
    assert state.player.altnam == state.player.plyrid
    assert state.player.attnam == state.player.plyrid
    assert state.player.flags == int(constants.PlayerFlag.LOADED | constants.PlayerFlag.FEMALE)
    assert state.player.level == 1
    assert state.player.hitpts == 4
    assert state.player.spts == 2
    assert state.player.gold == 0
    assert state.player.gpobjs == []
    assert state.player.spells == []
    assert state.player.stones == [2, 3, 4, 5]
    assert any(
        event.get("scope") == "target"
        and event.get("player") == state.player.plyrid
        and event.get("event") == "location_update"
        and event.get("location") == 0
        for event in result.events
    )
    assert any(
        event.get("scope") == "nearby_room"
        and event.get("room_id") == 0
        and "appeared in a holy light" in (event.get("text") or "")
        for event in result.events
    )


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
async def test_cast_area_damage_death_resets_each_dead_target_and_preserves_guards():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=10,
        spts=25,
        spells=[5],
        nspells=1,
        gamloc=7,
    )
    target_one = _build_player(
        plyrid="target1",
        attnam="Target One",
        altnam="Target One",
        gamloc=7,
        hitpts=6,
        level=5,
        gold=20,
        gpobjs=[0],
        obvals=[10],
        npobjs=1,
    )
    target_two = _build_player(
        plyrid="target2",
        attnam="Target Two",
        altnam="Target Two",
        gamloc=7,
        hitpts=10,
        level=5,
        spells=[1],
        nspells=1,
    )
    protected = _build_player(
        plyrid="shielded",
        attnam="Shielded",
        altnam="Shielded",
        gamloc=7,
        hitpts=6,
        level=5,
    )
    protected.charms[constants.FIRPRO] = 1
    mercy = _build_player(
        plyrid="mercy",
        attnam="Mercy",
        altnam="Mercy",
        gamloc=7,
        hitpts=6,
        level=1,
    )
    state = _build_state(player)
    state.rng = FixedRng(randrange_values=[2, 2, 2, 2, 3, 3, 3, 3])
    state.presence = OrderedPresence(
        [player.plyrid, target_one.plyrid, target_two.plyrid, protected.plyrid, mercy.plyrid]
    )
    players = {
        player.plyrid: player,
        target_one.plyrid: target_one,
        target_two.plyrid: target_two,
        protected.plyrid: protected,
        mercy.plyrid: mercy,
    }
    state.player_lookup = players.get

    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "burnup"}, state)

    assert target_one.gamloc == 0
    assert target_one.level == 1
    assert target_one.hitpts == 4
    assert target_one.gold == 0
    assert target_one.gpobjs == []
    assert target_one.stones == [2, 2, 2, 2]
    assert target_two.gamloc == 0
    assert target_two.level == 1
    assert target_two.hitpts == 4
    assert target_two.spells == []
    assert target_two.stones == [3, 3, 3, 3]
    assert protected.gamloc == 7
    assert protected.hitpts == 6
    assert mercy.gamloc == 7
    assert mercy.hitpts == 6

    death_events = [
        event
        for event in result.events
        if event.get("scope") == "target" and event.get("message_id") == "DIEMSG"
    ]
    killed_events = [
        event
        for event in result.events
        if event.get("message_id") == "KILLED" and event.get("room_id") == 7
    ]
    arrivals = [
        event
        for event in result.events
        if event.get("room_id") == 0
        and "appeared in a holy light" in (event.get("text") or "")
    ]
    assert {event["player"] for event in death_events} == {"target1", "target2"}
    assert {event["exclude_player"] for event in killed_events} == {"target1", "target2"}
    assert {event["exclude_player"] for event in arrivals} == {"target1", "target2"}


@pytest.mark.anyio
async def test_cast_area_self_death_stops_later_old_room_damage():
    rose_id = next(obj.id for obj in fixtures.load_objects() if obj.name == "rose")
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        spells=[58],
        nspells=1,
        gamloc=7,
        pgploc=7,
        hitpts=1,
        gpobjs=[rose_id],
        obvals=[0],
        npobjs=1,
    )
    target = _build_player(
        plyrid="target",
        attnam="Target",
        altnam="Target",
        gamloc=7,
        pgploc=7,
        level=25,
        hitpts=60,
    )
    state = _build_state(player)
    state.rng = FixedRng(randrange_values=[2, 3, 4, 5])
    state.presence = OrderedPresence([target.plyrid, player.plyrid])
    players = {player.plyrid: player, target.plyrid: target}
    state.player_lookup = players.get

    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "tiltowait"}, state)

    self_hit_room_message = next(
        event
        for event in result.events
        if event.get("message_id") == "S59M05"
        and event.get("exclude_player") == player.plyrid
    )
    assert state.player.gamloc == 0
    assert target.gamloc == 7
    assert target.hitpts == 60
    assert self_hit_room_message["scope"] == "nearby_room"
    assert self_hit_room_message["room_id"] == 7
    room_object_locations = [
        event.get("location")
        for event in result.events
        if event.get("event") == "room_objects"
    ]
    assert room_object_locations == [0]
    assert not any(
        event.get("message_id") in {"S59M04", "S59M05"}
        and event.get("player") == target.plyrid
        for event in result.events
    )


@pytest.mark.anyio
async def test_cast_direct_damage_death_resets_target_refreshes_room_and_persists(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'kyrgame.db'}")
    init_db_schema(engine)
    with create_session(engine) as session:
        player = _build_player(
            flags=int(constants.PlayerFlag.LOADED),
            plyrid="caster",
            attnam="Caster",
            altnam="Caster",
            level=25,
            spts=25,
            spells=[47],
            nspells=1,
            gamloc=7,
            pgploc=7,
        )
        target = _build_player(
            uidnam="target-uid",
            plyrid="target",
            attnam="target",
            altnam="Target Mask",
            gamloc=7,
            pgploc=7,
            hitpts=2,
            level=5,
            flags=int(
                constants.PlayerFlag.LOADED
                | constants.PlayerFlag.FEMALE
                | constants.PlayerFlag.MARRYD
            ),
            gold=55,
            gpobjs=[0, 1],
            obvals=[10, 20],
            npobjs=2,
            spells=[1, 23],
            nspells=2,
            charms=[
                1 if index != constants.OBJPRO else 0
                for index in range(constants.NCHARM)
            ],
            gemidx=3,
            stones=[9, 8, 7, 6],
            macros=19,
            stumpi=8,
            spouse="beloved",
        )
        state = _build_state(player)
        state.rng = FixedRng(randrange_values=[2, 3, 4, 5])
        state.presence = TrackingPresence({player.plyrid, target.plyrid})
        state.player_lookup = lambda pid: {player.plyrid: player, target.plyrid: target}.get(pid)
        state.db_session = session
        session.add(models.Player(**player.model_dump()))
        session.add(models.Player(**target.model_dump()))
        session.commit()

        registry = commands.build_default_registry()
        dispatcher = commands.CommandDispatcher(registry)

        result = await dispatcher.dispatch("cast", {"raw": "pocus target"}, state)

        assert any(
            event.get("scope") == "target"
            and event.get("player") == target.plyrid
            and event.get("message_id") == "DIEMSG"
            for event in result.events
        )
        assert any(
            event.get("scope") == "nearby_room"
            and event.get("room_id") == 7
            and event.get("message_id") == "KILLED"
            and event.get("exclude_player") == target.plyrid
            for event in result.events
        )
        assert any(
            event.get("scope") == "target"
            and event.get("event") == "location_update"
            and event.get("player") == target.plyrid
            and event.get("location") == 0
            for event in result.events
        )
        assert any(
            event.get("scope") == "target"
            and event.get("event") == "location_description"
            and event.get("player") == target.plyrid
            and event.get("location") == 0
            and event.get("message_id") == "KRD000"
            for event in result.events
        )
        assert any(
            event.get("scope") == "target"
            and event.get("event") == "room_objects"
            and event.get("player") == target.plyrid
            and event.get("location") == 0
            for event in result.events
        )
        assert any(
            event.get("scope") == "nearby_room"
            and event.get("room_id") == 0
            and event.get("exclude_player") == target.plyrid
            and "appeared in a holy light" in (event.get("text") or "")
            for event in result.events
        )

        assert target.uidnam == "target-uid"
        assert target.plyrid == "target"
        assert target.altnam == "target"
        assert target.attnam == "target"
        assert target.gamloc == 0
        assert target.pgploc == 0
        assert target.flags == int(constants.PlayerFlag.LOADED | constants.PlayerFlag.FEMALE)
        assert target.level == 1
        assert target.hitpts == 4
        assert target.spts == 2
        assert target.gold == 0
        assert target.gpobjs == []
        assert target.spells == []
        assert target.charms == [0] * constants.NCHARM
        assert target.stones == [2, 3, 4, 5]

        record = session.scalar(select(models.Player).where(models.Player.plyrid == "target"))
        assert record is not None
        assert record.altnam == "target"
        assert record.attnam == "target"
        assert record.gamloc == 0
        assert record.pgploc == 0
        assert record.level == 1
        assert record.hitpts == 4
        assert record.spts == 2
        assert record.gold == 0
        assert record.gpobjs == []
        assert record.spells == []
        assert record.charms == [0] * constants.NCHARM
        assert record.stones == [2, 3, 4, 5]


@pytest.mark.anyio
async def test_cast_target_death_refresh_uses_reset_target_brief_flag():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED | constants.PlayerFlag.BRFSTF),
        plyrid="caster",
        attnam="Caster",
        altnam="Caster",
        level=25,
        spts=25,
        spells=[47],
        nspells=1,
        gamloc=7,
        pgploc=7,
    )
    target = _build_player(
        plyrid="target",
        attnam="target",
        altnam="Target",
        gamloc=7,
        pgploc=7,
        hitpts=2,
        level=5,
        flags=int(constants.PlayerFlag.LOADED),
    )
    state = _build_state(player)
    state.rng = FixedRng(randrange_values=[2, 3, 4, 5])
    state.presence = TrackingPresence({player.plyrid, target.plyrid})
    state.player_lookup = lambda pid: {player.plyrid: player, target.plyrid: target}.get(pid)

    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "pocus target"}, state)

    description_event = next(
        event
        for event in result.events
        if event.get("scope") == "target"
        and event.get("event") == "location_description"
        and event.get("player") == target.plyrid
    )
    assert description_event["message_id"] == "KRD000"
    assert description_event["text"] == state.messages.messages["KRD000"]


@pytest.mark.anyio
async def test_cast_clutzopho_persists_target_inventory_and_room_objects(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'kyrgame.db'}")
    init_db_schema(engine)
    with create_session(engine) as session:
        player = _build_player(
            flags=int(constants.PlayerFlag.LOADED),
            level=25,
            spts=25,
            gamloc=7,
            gpobjs=[],
            obvals=[],
            npobjs=0,
            spells=[10],
            nspells=1,
        )
        target = _build_player(
            plyrid="target",
            attnam="target",
            altnam="Target",
            gamloc=7,
            gpobjs=[0, 1],
            obvals=[10, 20],
            npobjs=2,
        )
        state = _build_state(player)
        location = state.locations[7].model_copy(update={"objects": [2], "nlobjs": 1})
        state.locations[7] = location
        state.presence = TrackingPresence({player.plyrid, target.plyrid})
        state.player_lookup = lambda pid: {player.plyrid: player, target.plyrid: target}.get(pid)
        state.db_session = session
        session.add(models.Player(**player.model_dump()))
        session.add(models.Player(**target.model_dump()))
        session.add(models.Location(**location.model_dump()))
        session.commit()

        registry = commands.build_default_registry()
        dispatcher = commands.CommandDispatcher(registry)

        result = await dispatcher.dispatch("cast", {"raw": "clutzopho target"}, state)

        target_record = session.scalar(select(models.Player).where(models.Player.plyrid == "target"))
        location_record = session.scalar(select(models.Location).where(models.Location.id == 7))
        room_events = [event for event in result.events if event.get("type") == "room_objects"]

        assert target_record is not None
        assert location_record is not None
        assert target_record.gpobjs == []
        assert target_record.npobjs == 0
        assert location_record.objects == [2, 1, 0]
        assert room_events
        assert [obj["id"] for obj in room_events[-1]["objects"]] == [2, 1, 0]


@pytest.mark.anyio
async def test_cast_mower_persists_ground_cleanup_and_room_objects(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'kyrgame.db'}")
    init_db_schema(engine)
    with create_session(engine) as session:
        player = _build_player(
            flags=int(constants.PlayerFlag.LOADED),
            level=25,
            spts=25,
            gamloc=7,
            gpobjs=[],
            obvals=[],
            npobjs=0,
            spells=[41],
            nspells=1,
        )
        state = _build_state(player)
        location = state.locations[7].model_copy(update={"objects": [0, 45], "nlobjs": 2})
        state.locations[7] = location
        state.db_session = session
        session.add(models.Player(**player.model_dump()))
        session.add(models.Location(**location.model_dump()))
        session.commit()

        registry = commands.build_default_registry()
        dispatcher = commands.CommandDispatcher(registry)

        result = await dispatcher.dispatch("cast", {"raw": "mower"}, state)

        location_record = session.scalar(select(models.Location).where(models.Location.id == 7))
        room_events = [event for event in result.events if event.get("type") == "room_objects"]

        assert location_record is not None
        assert location_record.objects == [45]
        assert room_events
        assert [obj["id"] for obj in room_events[-1]["objects"]] == [45]


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
async def test_cast_peepint_uses_legacy_global_player_lookup_for_target_notification():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        gamloc=7,
        spells=[45],
        nspells=1,
    )
    target = _build_player(
        plyrid="target",
        attnam="Target Mask",
        altnam="Target Mask",
        gamloc=12,
    )
    state = _build_state(player)
    state.presence = RoomPresence({7: {player.plyrid}, 12: {target.plyrid}})
    state.player_lookup = lambda pid: (
        player if pid == player.plyrid else target if pid == target.plyrid else None
    )
    state.global_player_lookup = lambda name: target if name == target.plyrid else None
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "peepint target"}, state)

    assert [event["message_id"] for event in result.events] == ["KSPM04", "KSPM06", "KSPM07"]
    assert state.messages.messages["KRD012"] in result.events[0]["text"]
    assert result.events[1]["scope"] == "target"
    assert result.events[1]["player"] == target.plyrid
    assert result.events[1]["room_id"] == target.gamloc
    assert result.events[2]["scope"] == "room"
    assert result.events[2]["exclude_player"] == player.plyrid


@pytest.mark.anyio
async def test_cast_peepint_without_target_uses_legacy_objm07_failure():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        gamloc=7,
        spells=[45],
        nspells=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "peepint"}, state)

    assert [event["message_id"] for event in result.events] == ["OBJM07", "KSPM07"]
    assert result.events[0]["scope"] == "player"
    assert result.events[1]["scope"] == "room"
    assert result.events[1]["exclude_player"] == player.plyrid


@pytest.mark.anyio
async def test_cast_zelastone_uses_legacy_global_player_lookup_and_target_room_surfaces():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        gamloc=7,
        spells=[66],
        nspells=1,
    )
    target = _build_player(
        plyrid="target",
        attnam="Target Mask",
        altnam="Target Mask",
        gamloc=12,
        hitpts=40,
    )
    target.charms[constants.OBJPRO] = 1
    state = _build_state(player)
    state.presence = RoomPresence({7: {player.plyrid}, 12: {target.plyrid}})
    state.player_lookup = lambda pid: (
        player if pid == player.plyrid else target if pid == target.plyrid else None
    )
    state.global_player_lookup = lambda name: target if name == target.plyrid else None
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "zelastone target"}, state)

    assert [event["message_id"] for event in result.events] == [
        "S67M02",
        "S67M03",
        "S67M04",
        "S67M08",
        "S67M09",
    ]
    assert result.events[3]["scope"] == "target"
    assert result.events[3]["player"] == target.plyrid
    assert result.events[3]["room_id"] == target.gamloc
    assert result.events[2]["scope"] == "nearby_room"
    assert result.events[2]["room_id"] == target.gamloc
    assert result.events[4]["scope"] == "nearby_room"
    assert result.events[4]["exclude_player"] == target.plyrid
    assert result.events[1]["scope"] == "room"
    assert result.events[1]["exclude_player"] == player.plyrid


@pytest.mark.anyio
async def test_cast_zelastone_target_hit_death_resets_remote_target():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        gamloc=7,
        spells=[66],
        nspells=1,
    )
    target = _build_player(
        plyrid="target",
        attnam="Target Mask",
        altnam="Target Mask",
        gamloc=12,
        hitpts=30,
        level=5,
        gold=99,
        gpobjs=[0],
        obvals=[10],
        npobjs=1,
        stones=[9, 8, 7, 6],
    )
    state = _build_state(player)
    state.rng = FixedRng(randint_values=[50, 40], randrange_values=[2, 3, 4, 5])
    state.presence = RoomPresence({7: {player.plyrid}, 12: {target.plyrid}})
    state.player_lookup = lambda pid: (
        player if pid == player.plyrid else target if pid == target.plyrid else None
    )
    state.global_player_lookup = lambda name: target if name == target.plyrid else None
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "zelastone target"}, state)

    assert target.gamloc == 0
    assert target.level == 1
    assert target.hitpts == 4
    assert target.gold == 0
    assert target.gpobjs == []
    assert target.stones == [2, 3, 4, 5]
    assert any(
        event.get("scope") == "target"
        and event.get("player") == "target"
        and event.get("message_id") == "DIEMSG"
        for event in result.events
    )
    assert any(
        event.get("scope") == "nearby_room"
        and event.get("room_id") == 12
        and event.get("message_id") == "KILLED"
        and event.get("exclude_player") == "target"
        for event in result.events
    )
    assert any(
        event.get("scope") == "nearby_room"
        and event.get("room_id") == 0
        and event.get("exclude_player") == "target"
        and "appeared in a holy light" in (event.get("text") or "")
        for event in result.events
    )


@pytest.mark.anyio
async def test_cast_zelastone_missing_target_death_resets_caster():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED | constants.PlayerFlag.FEMALE),
        altnam="Caster Mask",
        attnam="Caster Mask",
        level=25,
        spts=25,
        gamloc=7,
        hitpts=20,
        spells=[66],
        nspells=1,
        stones=[9, 8, 7, 6],
    )
    state = _build_state(player)
    state.rng = FixedRng(randint_values=[20], randrange_values=[2, 3, 4, 5])
    state.global_player_lookup = lambda name: None
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "zelastone nobody"}, state)

    assert [event["message_id"] for event in result.events[:4]] == [
        "S67M00",
        "S67M01",
        "DIEMSG",
        "KILLED",
    ]
    assert state.player.gamloc == 0
    assert state.player.level == 1
    assert state.player.hitpts == 4
    assert state.player.flags == int(constants.PlayerFlag.LOADED | constants.PlayerFlag.FEMALE)
    assert state.player.stones == [2, 3, 4, 5]
    assert any(
        event.get("scope") == "target"
        and event.get("player") == state.player.plyrid
        and event.get("event") == "location_update"
        and event.get("location") == 0
        for event in result.events
    )


@pytest.mark.anyio
async def test_cast_zelastone_without_target_uses_legacy_mystery_failure():
    player = _build_player(
        flags=int(constants.PlayerFlag.LOADED),
        level=25,
        spts=25,
        gamloc=7,
        spells=[66],
        nspells=1,
    )
    state = _build_state(player)
    registry = commands.build_default_registry()
    dispatcher = commands.CommandDispatcher(registry)

    result = await dispatcher.dispatch("cast", {"raw": "zelastone"}, state)

    assert [event["message_id"] for event in result.events] == ["KSPM03", None]
    assert "failing at spellcasting" in result.events[1]["text"]
    assert result.events[1]["scope"] == "room"
    assert result.events[1]["exclude_player"] == player.plyrid


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
