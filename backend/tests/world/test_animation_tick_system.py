import pytest

from kyrgame import fixtures
from kyrgame.world.animation_tick_system import (
    AnimationTickEvent,
    AnimationTickSystem,
    BrownieRoutine,
    DryadWanderRoutine,
    ElfEncounterRoutine,
    GemSpawnRoutine,
    InMemoryAnimationTickPersistence,
    ZarDragonRoutine,
)


def test_animation_tick_rotates_routines_in_legacy_order():
    seen: list[str] = []

    system = AnimationTickSystem(
        persistence=InMemoryAnimationTickPersistence(),
        routine_handlers={
            "dryads": lambda state: seen.append("dryads"),
            "elves": lambda state: seen.append("elves"),
            "gemakr": lambda state: seen.append("gemakr"),
            "zarapp": lambda state: seen.append("zarapp"),
            "browns": lambda state: seen.append("browns"),
        },
        mob_updater=lambda state: None,
    )

    for _ in range(8):
        system.tick()

    assert seen == [
        "dryads",
        "elves",
        "gemakr",
        "gemakr",
        "zarapp",
        "browns",
        "dryads",
        "elves",
    ]


def test_animation_tick_clears_global_timed_flags_after_dispatching_events():
    persistence = InMemoryAnimationTickPersistence()
    system = AnimationTickSystem(persistence=persistence)

    system.set_timed_flag("sesame")
    system.set_timed_flag("chantd")
    system.set_timed_flag("rockpr")

    result = system.tick()

    assert result.timed_events == [
        AnimationTickEvent(flag="sesame", room_id=185, message_id="WALM05"),
        AnimationTickEvent(flag="chantd", room_id=7, message_text="***\rThe altar stops glowing.\r"),
        AnimationTickEvent(flag="rockpr", room_id=27, message_text="***\rThe mists settle down.\r"),
    ]
    assert system.state.timed_flags["sesame"] == 0
    assert system.state.timed_flags["chantd"] == 0
    assert system.state.timed_flags["rockpr"] == 0


def test_animation_tick_updates_mobs_every_tick_and_persists_state():
    calls: list[int] = []
    persistence = InMemoryAnimationTickPersistence()

    def _mob_update(state):
        calls.append(state.zar_counter)
        state.zar_counter += 1

    system = AnimationTickSystem(
        persistence=persistence,
        mob_updater=_mob_update,
    )

    system.tick()
    system.tick()

    assert calls == [0, 1]

    reloaded = AnimationTickSystem(
        persistence=persistence,
        mob_updater=lambda state: None,
    )
    assert reloaded.state.zar_counter == 2
    assert reloaded.state.routine_index == 2


def test_animation_tick_uses_initial_state_from_persistence_for_multiplayer_bootstrap():
    persistence = InMemoryAnimationTickPersistence()
    persistence.save(
        {
            "routine_index": 4,
            "zar_counter": 11,
            "zar_location": 250,
            "zar_attack_index": 3,
            "timed_flags": {"sesame": 1},
        }
    )

    system = AnimationTickSystem(persistence=persistence)

    assert system.state.routine_index == 4
    assert system.state.zar_counter == 11
    assert system.state.zar_location == 250
    assert system.state.zar_attack_index == 3
    assert system.state.timed_flags["sesame"] == 1


def test_gemakr_uses_legacy_cadence_capacity_and_random_gem_every_11th_spawn():
    room_objects = {50: [], 51: []}
    room_rolls = iter([50] * 11)
    gem_rolls = iter([9])

    routine = GemSpawnRoutine(
        room_picker=lambda low, high: next(room_rolls),
        gem_picker=lambda low, high: next(gem_rolls),
        room_objects_getter=lambda room_id: room_objects.get(room_id, []),
        room_objects_setter=lambda room_id, objects: room_objects.__setitem__(room_id, list(objects)),
        gem_name_lookup=lambda gem_id: {2: "garnet", 9: "onyx"}[gem_id],
        message_formatter=lambda gem_name: f"spawned {gem_name}",
    )

    state = AnimationTickSystem(persistence=InMemoryAnimationTickPersistence()).state
    events: list[AnimationTickEvent] = []
    for _ in range(11):
        room_objects[50] = []
        events.extend(routine(state))

    assert [event.payload["spawned_object_id"] for event in events] == [2] * 10 + [9]
    assert state.gem_counter == 0
    assert events[0].payload["location"] == 50
    assert events[0].payload["objects"] == [{"id": 2}]

    room_objects[51] = [0, 1, 2, 3]
    blocked_event = GemSpawnRoutine(
        room_picker=lambda low, high: 51,
        gem_picker=lambda low, high: 5,
        room_objects_getter=lambda room_id: room_objects.get(room_id, []),
        room_objects_setter=lambda room_id, objects: room_objects.__setitem__(room_id, list(objects)),
        gem_name_lookup=lambda gem_id: "ignored",
        message_formatter=lambda gem_name: gem_name,
    )(state)
    assert blocked_event == []
    assert room_objects[51] == [0, 1, 2, 3]


def _message_formatter(message_id: str, *args):
    messages = fixtures.load_messages().messages
    template = messages[message_id]
    return template % args if args else template


def _build_player(**updates):
    player = fixtures.build_player()
    data = player.model_dump()
    data.update(updates)
    return player.model_copy(update=data)


def test_dryad_routine_moves_dryad_and_evicts_full_destination_room():
    room_objects = {0: [45], 20: [0, 1, 2, 3, 4, 5]}

    routine = DryadWanderRoutine(
        room_picker=lambda low, high: 20,
        room_objects_getter=lambda room_id: room_objects.get(room_id, []),
        room_objects_setter=lambda room_id, objects: room_objects.__setitem__(room_id, list(objects)),
        object_name_lookup=lambda object_id: f"object {object_id}",
        location_phrase_lookup=lambda room_id: "nearby",
        message_formatter=_message_formatter,
    )
    state = AnimationTickSystem(persistence=InMemoryAnimationTickPersistence()).state

    events = routine(state)

    assert state.dryad_location == 20
    assert room_objects[0] == []
    assert room_objects[20] == [0, 1, 2, 3, 4, 45]
    assert [event.message_id for event in events if event.message_id] == [
        "DMSG00",
        "DMSG01",
        "DMSG02",
    ]
    evict_event = next(event for event in events if event.message_id == "DMSG01")
    assert "object 5" in evict_event.message_text
    assert events[-1].payload["objects"] == [{"id": 0}, {"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 45}]


def test_elf_routine_alternates_hints_and_gold_rewards():
    player = _build_player(plyrid="hero", altnam="Hero", gamloc=50, gold=5)
    persisted: list[int] = []
    room_rolls = iter([50, 50])
    gold_rolls = iter([7])

    routine = ElfEncounterRoutine(
        room_picker=lambda low, high: next(room_rolls),
        gold_picker=lambda low, high: next(gold_rolls),
        player_getter=lambda room_id: player if player.gamloc == room_id else None,
        player_persister=lambda updated: persisted.append(updated.gold),
        message_formatter=_message_formatter,
    )
    state = AnimationTickSystem(persistence=InMemoryAnimationTickPersistence()).state

    hint_events = routine(state)
    reward_events = routine(state)

    assert state.elf_hint_index == 1
    assert state.elf_reward_next == 0
    assert hint_events[1].message_id == "EMSG03"
    assert hint_events[1].payload["target_message_id"] == "EHINT0"
    assert reward_events[1].message_id == "EMSG02"
    assert reward_events[1].payload["target_message_id"] == "EMSG01"
    assert player.gold == 12
    assert persisted == [12]


def test_brownie_routine_follows_path_and_steals_gold_then_inventory():
    player = _build_player(
        plyrid="hero",
        altnam="Hero",
        gamloc=71,
        gold=9,
        gpobjs=[0, 1],
        obvals=[10, 20],
        npobjs=2,
    )
    persisted: list[tuple[int, list[int]]] = []

    routine = BrownieRoutine(
        player_getter=lambda room_id: player if player.gamloc == room_id else None,
        player_persister=lambda updated: persisted.append((updated.gold, list(updated.gpobjs))),
        message_formatter=_message_formatter,
        pronoun_lookup=lambda updated: "him",
    )
    state = AnimationTickSystem(persistence=InMemoryAnimationTickPersistence()).state

    gold_events = routine(state)
    state.brownie_path_index = 0
    inventory_events = routine(state)

    assert player.gold == 0
    assert player.gpobjs == []
    assert player.obvals == []
    assert player.npobjs == 0
    assert state.brownie_location == 71
    assert gold_events[1].message_id == "BMSG02"
    assert gold_events[1].payload["target_message_id"] == "BMSG01"
    assert inventory_events[1].message_id == "BMSG04"
    assert inventory_events[1].payload["target_message_id"] == "BMSG03"
    assert persisted == [(0, [0, 1]), (0, [])]


def _build_zar_routine(
    *,
    room_objects,
    players=None,
    room_rolls=None,
    chance_rolls=None,
    persisted=None,
    location_updates=None,
):
    room_roll_iter = iter(room_rolls or [])
    chance_roll_iter = iter(chance_rolls or [])
    persisted = persisted if persisted is not None else []
    location_updates = location_updates if location_updates is not None else []

    def _set_room(room_id, objects):
        room_objects[room_id] = list(objects)
        location_updates.append((room_id, list(objects)))

    return ZarDragonRoutine(
        room_picker=lambda low, high: next(room_roll_iter),
        chance_picker=lambda low, high: next(chance_roll_iter),
        room_objects_getter=lambda room_id: list(room_objects.get(room_id, [])),
        room_objects_setter=_set_room,
        players_getter=lambda room_id: [
            player for player in (players or []) if player.gamloc == room_id
        ],
        player_persister=lambda player: persisted.append(
            (player.plyrid, player.hitpts, player.gamloc)
        ),
        message_formatter=_message_formatter,
    )


def test_zar_placement_clears_room_adds_special_prop_and_preserves_dryad():
    room_objects = {7: [45, 0], 302: [52]}
    location_updates: list[tuple[int, list[int]]] = []
    routine = _build_zar_routine(
        room_objects=room_objects,
        location_updates=location_updates,
    )
    state = AnimationTickSystem(persistence=InMemoryAnimationTickPersistence()).state

    events = routine.place_zar(state, 7, "ZMSG11")

    assert state.zar_location == 7
    assert room_objects[7] == [52, 47, 45]
    assert events == [
        AnimationTickEvent(flag="pzinlc", room_id=7, message_id="ZMSG11"),
        AnimationTickEvent(
            flag="pzinlc",
            room_id=7,
            payload={
                "type": "room_objects",
                "event": "room_objects",
                "location": 7,
                "objects": [{"id": 52}, {"id": 47}, {"id": 45}],
            },
        ),
    ]
    assert location_updates[-1] == (7, [52, 47, 45])


def test_zar_chkzar_relocates_when_hungry_and_room_is_empty():
    room_objects = {250: [], 302: [52]}
    routine = _build_zar_routine(room_objects=room_objects, room_rolls=[250])
    state = AnimationTickSystem(persistence=InMemoryAnimationTickPersistence()).state
    state.zar_location = 302
    state.zar_counter = 5

    events = routine.chkzar(state)

    assert [event.message_id for event in events if event.message_id] == ["ZMSG00", "ZMSG01"]
    assert room_objects[302] == []
    assert room_objects[250] == [52]
    assert state.zar_location == 250
    assert state.zar_counter == 6


def test_zar_chkzar_returns_home_after_legacy_counter_limit():
    room_objects = {250: [52], 302: []}
    routine = _build_zar_routine(room_objects=room_objects)
    state = AnimationTickSystem(persistence=InMemoryAnimationTickPersistence()).state
    state.zar_location = 250
    state.zar_counter = 25

    events = routine.chkzar(state)

    assert [event.message_id for event in events if event.message_id] == ["ZMSG00", "ZMSG01"]
    assert room_objects[250] == []
    assert room_objects[302] == [52]
    assert state.zar_location == 302
    assert state.zar_counter == 1


def test_zarapp_broadcasts_sighting_to_random_legacy_room():
    routine = _build_zar_routine(room_objects={}, room_rolls=[87])
    state = AnimationTickSystem(persistence=InMemoryAnimationTickPersistence()).state

    assert routine.zarapp(state) == [
        AnimationTickEvent(flag="zarapp", room_id=87, message_id="ZARABO")
    ]


def test_zarfood_rotates_attacks_applies_protection_and_skips_level_25():
    bite = _build_player(plyrid="bite", altnam="Bite", gamloc=302, hitpts=100)
    breath = _build_player(plyrid="breath", altnam="Breath", gamloc=302, hitpts=100)
    breath.charms[1] = 1
    claw = _build_player(plyrid="claw", altnam="Claw", gamloc=302, hitpts=100)
    lightning = _build_player(plyrid="lightning", altnam="Lightning", gamloc=302, hitpts=100)
    lightning.charms[3] = 1
    archmage = _build_player(
        plyrid="archmage", altnam="Archmage", gamloc=302, level=25, hitpts=100
    )
    persisted: list[tuple[str, int, int]] = []
    routine = _build_zar_routine(
        room_objects={302: [52]},
        players=[bite, breath, claw, lightning, archmage],
        persisted=persisted,
    )
    state = AnimationTickSystem(persistence=InMemoryAnimationTickPersistence()).state
    state.zar_location = 302

    found_food, events = routine.zarfood(state)

    assert found_food is True
    assert events[0].message_id == "ZMSG02"
    assert [event.message_id for event in events if event.message_id == "ZMSG07"] == [
        "ZMSG07",
        "ZMSG07",
        "ZMSG07",
        "ZMSG07",
    ]
    target_events = [
        event for event in events if event.payload.get("target_only") is True
    ]
    assert [event.payload["target_message_id"] for event in target_events] == [
        "ZMSG03",
        "ZMSG04",
        "ZMSG05",
        "ZMSG06",
    ]
    assert (bite.hitpts, breath.hitpts, claw.hitpts, lightning.hitpts, archmage.hitpts) == (
        84,
        72,
        88,
        84,
        100,
    )
    assert state.zar_attack_index == 1
    assert persisted == [
        ("bite", 84, 302),
        ("breath", 72, 302),
        ("claw", 88, 302),
        ("lightning", 84, 302),
    ]


def test_zarfood_emits_existing_death_messages_when_attack_kills_player():
    player = _build_player(plyrid="target", altnam="Target", gamloc=302, hitpts=10)
    routine = _build_zar_routine(room_objects={302: [52]}, players=[player])
    state = AnimationTickSystem(persistence=InMemoryAnimationTickPersistence()).state
    state.zar_location = 302

    _, events = routine.zarfood(state)

    assert player.gamloc == 0
    assert player.pgploc == 0
    assert player.level == 1
    assert player.hitpts == 4
    assert any(
        event.payload.get("target_message_id") == "DIEMSG" for event in events
    )
    assert any(event.message_id == "KILLED" for event in events)
    assert any(
        event.payload.get("target_only") is True
        and event.payload.get("target_event") == "location_update"
        and event.payload.get("move_player_to") == 0
        for event in events
    )
    assert any(
        "appeared in a holy light" in (event.message_text or "")
        and event.payload.get("exclude_player") == "target"
        for event in events
    )
