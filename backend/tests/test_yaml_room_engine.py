import re

import pytest

from kyrgame import constants, fixtures, yaml_rooms


class StubRandom:
    def __init__(self, values):
        self.values = list(values)

    def randrange(self, start, stop):  # pragma: no cover - simple test helper
        if not self.values:
            raise ValueError("No random values left")
        return self.values.pop(0)

    def random(self):  # pragma: no cover - simple test helper
        if not self.values:
            raise ValueError("No random values left")
        return self.values.pop(0)


def _walk_action_types(value):
    if isinstance(value, dict):
        action_type = value.get("type")
        if action_type is not None:
            yield action_type
        for nested in value.values():
            yield from _walk_action_types(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_action_types(item)


def _walk_actions(value):
    if isinstance(value, dict):
        if "type" in value:
            yield value
        for nested in value.values():
            yield from _walk_actions(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_actions(item)


@pytest.fixture
def room_engine():
    messages = fixtures.load_messages()
    objects = fixtures.load_objects()
    spells = fixtures.load_spells()
    definitions = fixtures.load_room_scripts()
    locations = fixtures.load_locations()
    return yaml_rooms.YamlRoomEngine(
        definitions=definitions,
        messages=messages,
        objects=objects,
        spells=spells,
        locations=locations,
    )


@pytest.fixture
def base_player():
    player = fixtures.build_player()
    trimmed = player.model_copy(
        update={
            "gpobjs": [0],
            "obvals": [10],
            "npobjs": 1,
            "gold": 0,
            "hitpts": 8,
            "level": max(player.level, 3),
        }
    )
    return trimmed


def test_room_scripts_fixture_is_split_into_files():
    fixture_dir = fixtures.FIXTURE_ROOT / "room_scripts"
    assert fixture_dir.is_dir()

    room_files = sorted(fixture_dir.glob("*.yaml"))
    assert len(room_files) >= 6
    assert all(re.fullmatch(r"room_\d{4}\.yaml", path.name) for path in room_files)
    assert {8, 9, 10, 12, 14, 16}.issubset(
        {int(path.stem.split("_")[-1]) for path in room_files}
    )


def test_room_script_actions_use_readable_known_types():
    definitions = fixtures.load_room_scripts()
    action_types = set(_walk_action_types(definitions))

    assert "hitoth" not in action_types
    assert "damage" in action_types
    assert action_types <= {
        "add_gold",
        "add_room_object",
        "branch_by_item",
        "conditional",
        "damage",
        "grant_object",
        "grant_spell",
        "heal",
        "increment_room_state",
        "level_gate",
        "level_up",
        "message",
        "nonlethal_damage",
        "purchase_spell",
        "random_chance",
        "random_choice",
        "random_range",
        "remove_inventory_index",
        "remove_item",
        "set_player_flag",
        "transfer_player",
    }


def test_yaml_room_engine_rejects_unknown_action_types():
    engine = yaml_rooms.YamlRoomEngine(
        definitions={
            "rooms": [
                {
                    "id": 999,
                    "triggers": [
                        {
                            "verbs": ["touch"],
                            "actions": [{"type": "typo_damage", "amount": 1}],
                        }
                    ],
                }
            ]
        },
        messages=fixtures.load_messages(),
        objects=fixtures.load_objects(),
        spells=fixtures.load_spells(),
        locations=fixtures.load_locations(),
    )

    with pytest.raises(ValueError, match="Unknown YAML room action type"):
        engine.handle(
            player=fixtures.build_player(),
            room_id=999,
            command="touch",
            args=[],
        )


def test_damage_action_resets_only_when_damage_kills():
    messages = fixtures.load_messages()
    objects = fixtures.load_objects()
    spells = fixtures.load_spells()
    locations = fixtures.load_locations()
    definitions = {
        "rooms": [
            {
                "id": 998,
                "triggers": [
                    {
                        "verbs": ["sting"],
                        "actions": [{"type": "damage", "amount": 8}],
                    }
                ],
            }
        ]
    }
    engine = yaml_rooms.YamlRoomEngine(
        definitions=definitions,
        messages=messages,
        objects=objects,
        spells=spells,
        locations=locations,
        rng=StubRandom([0, 1, 2, 3]),
    )

    survivor = fixtures.build_player().model_copy(
        update={"hitpts": 9, "gamloc": 998, "pgploc": 998}
    )
    survived = engine.handle(survivor, 998, "sting", [])

    assert survived.handled is True
    assert survivor.hitpts == 1
    assert survivor.gamloc == 998
    assert not any(evt.get("death_reset") for evt in survived.events)

    killed = fixtures.build_player().model_copy(
        update={"hitpts": 8, "gamloc": 998, "pgploc": 998}
    )
    died = engine.handle(killed, 998, "sting", [])

    assert died.handled is True
    assert killed.level == 1
    assert killed.hitpts == 4
    assert killed.gamloc == 0
    assert killed.pgploc == 0
    assert messages.messages["DIEMSG"] in [
        evt["text"] for evt in died.events if evt["scope"] == "direct"
    ]
    assert any(
        evt.get("event") == "room_transfer" and evt.get("death_reset") is True
        for evt in died.events
    )


def test_damage_action_uses_modern_death_recovery_for_non_honor_player():
    messages = fixtures.load_messages()
    messages.messages["KILLED"] = "bad killed template %s %s"
    objects = fixtures.load_objects()
    spells = fixtures.load_spells()
    locations = {location.id: location for location in fixtures.load_locations()}
    locations[302] = locations[302].model_copy(update={"objects": [], "nlobjs": 0})
    definitions = {
        "rooms": [
            {
                "id": 302,
                "triggers": [
                    {
                        "verbs": ["sting"],
                        "actions": [{"type": "damage", "amount": 8}],
                    }
                ],
            }
        ]
    }
    engine = yaml_rooms.YamlRoomEngine(
        definitions=definitions,
        messages=messages,
        objects=objects,
        spells=spells,
        locations=locations.values(),
        rng=StubRandom([]),
    )
    player = fixtures.build_player().model_copy(
        update={
            "hitpts": 8,
            "level": 10,
            "gamloc": 302,
            "pgploc": 302,
            "gold": 55,
            "gpobjs": [
                constants.SOULSTONE_OBJECT_ID,
                constants.KYRAGEM_OBJECT_ID,
                0,
            ],
            "obvals": [1, 2, 3],
            "npobjs": 3,
            "spells": [66],
            "nspells": 1,
            "offspls": 11,
            "defspls": 22,
            "othspls": 33,
            "charms": [1] * constants.NCHARM,
            "macros": 0,
            "flags": int(
                constants.PlayerFlag.LOADED
                | constants.PlayerFlag.GOTKYG
                | constants.PlayerFlag.INVISF
                | constants.PlayerFlag.PEGASU
                | constants.PlayerFlag.WILLOW
                | constants.PlayerFlag.PDRAGN
            ),
            "honor_mode": False,
        }
    )

    died = engine.handle(player, 302, "sting", [])

    assert died.handled is True
    assert player.gamloc == constants.WILLOW_ROOM_ID
    assert player.pgploc == constants.WILLOW_ROOM_ID
    assert player.level == 9
    assert player.hitpts == 36
    assert player.spts == 18
    assert player.gold == 0
    assert player.gpobjs == []
    assert player.spells == []
    assert player.nspells == 0
    assert (player.offspls, player.defspls, player.othspls) == (11, 22, 33)
    assert player.charms == [0] * constants.NCHARM
    assert player.macros == constants.MODERN_DEATH_EXHAUSTION_MACROS
    assert player.flags == int(constants.PlayerFlag.LOADED)
    assert engine.get_room_objects(302) == [0]
    assert any(
        evt.get("scope") == "direct"
        and evt.get("message_id") == "DIEMSG"
        and evt.get("modern_death_recovery") is True
        and evt.get("filtered_items")
        == [constants.SOULSTONE_OBJECT_ID, constants.KYRAGEM_OBJECT_ID]
        for evt in died.events
    )
    assert any(
        evt.get("scope") == "broadcast"
        and evt.get("event") == "room_objects"
        and evt.get("room_id") == 302
        and evt.get("modern_death_recovery") is True
        for evt in died.events
    )
    assert any(
        evt.get("scope") == "broadcast"
        and evt.get("message_id") == "DROPIT3"
        and evt.get("object_id") == 0
        and "dropped its" in evt.get("text", "")
        for evt in died.events
    )
    killed_event = next(
        evt for evt in died.events if evt.get("message_id") == "KILLED"
    )
    assert killed_event.get("text") == "bad killed template %s %s"
    drop_index = next(
        index
        for index, evt in enumerate(died.events)
        if evt.get("scope") == "broadcast"
        and evt.get("message_id") == "DROPIT3"
        and evt.get("object_id") == 0
    )
    death_index = next(
        index
        for index, evt in enumerate(died.events)
        if evt.get("scope") == "direct" and evt.get("message_id") == "DIEMSG"
    )
    killed_index = next(
        index
        for index, evt in enumerate(died.events)
        if evt.get("message_id") == "KILLED"
    )
    assert drop_index < death_index
    assert drop_index < killed_index


def test_nonlethal_damage_action_clamps_without_death_reset():
    engine = yaml_rooms.YamlRoomEngine(
        definitions={
            "rooms": [
                {
                    "id": 997,
                    "triggers": [
                        {
                            "verbs": ["scrape"],
                            "actions": [{"type": "nonlethal_damage", "amount": 8}],
                        }
                    ],
                }
            ]
        },
        messages=fixtures.load_messages(),
        objects=fixtures.load_objects(),
        spells=fixtures.load_spells(),
        locations=fixtures.load_locations(),
        rng=StubRandom([0, 1, 2, 3]),
    )

    player = fixtures.build_player().model_copy(
        update={"hitpts": 3, "gamloc": 997, "pgploc": 997}
    )
    result = engine.handle(player, 997, "scrape", [])

    assert result.handled is True
    assert player.hitpts == 0
    assert player.gamloc == 997
    assert player.pgploc == 997
    assert not any(evt.get("death_reset") for evt in result.events)


def test_truthy_random_chance_names_reward_as_success_and_damage_as_failure():
    definitions = fixtures.load_room_scripts()
    truthy = next(room for room in definitions["rooms"] if room["id"] == 280)

    chance_actions = [
        action for action in _walk_actions(truthy) if action.get("type") == "random_chance"
    ]
    choices = [
        action for action in _walk_actions(truthy) if action.get("type") == "random_choice"
    ]

    assert choices == []
    assert len(chance_actions) == 1
    chance = chance_actions[0]
    assert chance["probability"] == 0.5
    assert chance["on_success"] == [
        {
            "type": "message",
            "message_id": "TRUM02",
            "broadcast_message_id": "TRUM03",
            "broadcast_format": ["player_altnam"],
        },
        {"type": "level_up"},
    ]
    assert chance["on_failure"] == [
        {"type": "message", "message_id": "TRUM01"},
        {"type": "damage", "amount": 100},
    ]


def test_yaml_room_engine_inferrs_message_scope_from_ids():
    messages = fixtures.load_messages()
    objects = fixtures.load_objects()
    spells = fixtures.load_spells()
    locations = fixtures.load_locations()
    player = fixtures.build_player()
    player.altnam = "Echo"

    definitions = {
        "rooms": [
            {
                "id": 999,
                "name": "msgutl2_demo",
                "triggers": [
                    {
                        "verbs": ["wave"],
                        "actions": [
                            {
                                "type": "message",
                                "message_id": "DRINK0",
                                "broadcast_message_id": "DRINK1",
                                "broadcast_format": ["player_altnam"],
                            }
                        ],
                    }
                ],
            }
        ]
    }

    engine = yaml_rooms.YamlRoomEngine(
        definitions=definitions,
        messages=messages,
        objects=objects,
        spells=spells,
        locations=locations,
    )

    result = engine.handle(player=player, room_id=999, command="wave", args=[])

    direct_events = [evt for evt in result.events if evt["scope"] == "direct"]
    broadcast_events = [evt for evt in result.events if evt["scope"] == "broadcast"]

    assert engine.messages.messages["DRINK0"] in [evt["text"] for evt in direct_events]
    assert engine.messages.messages["DRINK1"] % player.altnam in [
        evt["text"] for evt in broadcast_events
    ]
    assert broadcast_events[0].get("exclude_player") == player.plyrid


def test_arg_strip_allows_optional_words():
    messages = fixtures.load_messages()
    objects = fixtures.load_objects()
    spells = fixtures.load_spells()
    locations = fixtures.load_locations()
    player = fixtures.build_player()

    definitions = {
        "rooms": [
            {
                "id": 998,
                "name": "strip_demo",
                "triggers": [
                    {
                        "verbs": ["offer"],
                        "arg_strip": ["my"],
                        "arg_matches": [
                            {"index": 0, "value": "love"},
                        ],
                        "actions": [
                            {
                                "type": "message",
                                "message_id": "OFFER0",
                                "broadcast_message_id": "OFFER1",
                                "broadcast_format": ["player_altnam"],
                            }
                        ],
                    }
                ],
            }
        ]
    }

    engine = yaml_rooms.YamlRoomEngine(
        definitions=definitions,
        messages=messages,
        objects=objects,
        spells=spells,
        locations=locations,
    )

    result = engine.handle(
        player=player,
        room_id=998,
        command="offer",
        args=["my", "love"],
    )

    assert result.handled is True


@pytest.mark.parametrize("room_id", [255, 257, 280, 282, 285, 288, 291, 293, 302])
def test_strict_upper_rooms_disable_generic_normalized_retry(room_engine, room_id):
    assert room_engine.allows_normalized_retry(room_id) is False


def test_getgol_converts_gems_and_rejects_unknown(room_engine, base_player):
    base_player.gold = 10

    result = room_engine.handle(
        player=base_player,
        room_id=8,
        command="give",
        args=["ruby"],
    )

    assert result.handled is True
    assert base_player.gold == 32  # +22 from ruby
    assert base_player.npobjs == 0

    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    broadcast_texts = [evt["text"] for evt in result.events if evt["scope"] == "broadcast"]

    assert room_engine.messages.messages["TRDM00"] % 22 in direct_texts
    assert any(text.endswith("22 pieces of gold.") for text in broadcast_texts)

    missing = room_engine.handle(
        player=base_player,
        room_id=8,
        command="trade",
        args=["emerald"],
    )
    assert missing.handled is True

    direct_missing = [evt["text"] for evt in missing.events if evt["scope"] == "direct"]
    assert room_engine.messages.messages["TRDM05"] in direct_missing


def test_getgol_kyragem_grants_soulstone(room_engine, base_player):
    base_player.gpobjs.append(29)
    base_player.obvals.append(0)
    base_player.npobjs = 2

    result = room_engine.handle(
        player=base_player,
        room_id=8,
        command="sell",
        args=["kyragem"],
    )

    assert 29 not in base_player.gpobjs
    assert 28 in base_player.gpobjs

    texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    assert room_engine.messages.messages["TRDM02"] in texts


def test_buyspl_respects_prices_and_sets_spell_bits(room_engine, base_player):
    base_player = base_player.model_copy(
        update={
            "gold": 200,
            "offspls": 0,
            "defspls": 0,
            "othspls": 0,
            "spells": [],
            "nspells": 0,
        }
    )

    purchase = room_engine.handle(
        player=base_player,
        room_id=9,
        command="buy",
        args=["zapher"],
    )

    assert base_player.gold == 150
    assert base_player.offspls & room_engine.spells_by_name["zapher"].bitdef
    assert base_player.spells == []
    assert base_player.nspells == 0
    direct_texts = [evt["text"] for evt in purchase.events if evt["scope"] == "direct"]
    assert room_engine.messages.messages["BUYM02"] in direct_texts

    base_player.gold = 200
    base_player.offspls = 0

    partial_purchase = room_engine.handle(
        player=base_player,
        room_id=9,
        command="buy",
        args=["za"],
    )

    assert base_player.gold == 200
    assert not base_player.offspls
    partial_direct_texts = [
        evt["text"] for evt in partial_purchase.events if evt["scope"] == "direct"
    ]
    assert room_engine.messages.messages["BUYM04"] in partial_direct_texts

    base_player.gold = 10
    base_player.offspls = 0

    poor = room_engine.handle(
        player=base_player,
        room_id=9,
        command="purchase",
        args=["thedoc"],
    )

    assert base_player.gold == 10
    assert not base_player.defspls
    reject_texts = [evt["text"] for evt in poor.events if evt["scope"] == "direct"]
    assert room_engine.messages.messages["BUYM00"] in reject_texts


@pytest.mark.parametrize(
    ("command", "args"),
    [
        ("wonder", []),
        ("consider", ["life"]),
    ],
)
def test_philos_aliases_level_without_physical_key(
    room_engine, base_player, command, args
):
    player = base_player.model_copy(
        update={
            "level": 22,
            "gpobjs": [],
            "obvals": [],
            "npobjs": 0,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=264,
        command=command,
        args=args,
    )

    assert result.handled is True
    assert player.level == 23

    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    broadcast_texts = [evt["text"] for evt in result.events if evt["scope"] == "broadcast"]

    assert room_engine.messages.messages["LEVL23"] in direct_texts
    assert room_engine.messages.messages["LVL9M1"] % player.altnam in broadcast_texts


def test_truthy_seeking_truth_can_hurt_or_level():
    messages = fixtures.load_messages()
    objects = fixtures.load_objects()
    spells = fixtures.load_spells()
    locations = fixtures.load_locations()

    damage_engine = yaml_rooms.YamlRoomEngine(
        definitions=fixtures.load_room_scripts(),
        messages=messages,
        objects=objects,
        spells=spells,
        locations=locations,
        rng=StubRandom([0.75, 0, 1, 2, 3]),
    )
    level_engine = yaml_rooms.YamlRoomEngine(
        definitions=fixtures.load_room_scripts(),
        messages=messages,
        objects=objects,
        spells=spells,
        locations=locations,
        rng=StubRandom([0.25]),
    )

    base = fixtures.build_player()
    player = base.model_copy(
        update={
            "level": 17,
            "hitpts": 20,
            "gpobjs": [],
            "obvals": [],
            "npobjs": 0,
        }
    )

    result_damage = damage_engine.handle(
        player=player,
        room_id=280,
        command="seek",
        args=["truth"],
    )

    assert result_damage.handled is True
    assert player.hitpts == 4
    assert player.level == 1
    assert player.gamloc == 0
    direct_texts = [
        evt["text"] for evt in result_damage.events if evt["scope"] == "direct"
    ]
    broadcast_texts = [
        evt["text"] for evt in result_damage.events if evt["scope"] == "broadcast"
    ]
    assert messages.messages["TRUM01"] in direct_texts
    assert messages.messages["DIEMSG"] in direct_texts
    assert messages.messages["KILLED"] % "Hero Alt" in broadcast_texts
    assert any(evt.get("event") == "room_transfer" for evt in result_damage.events)

    player = base.model_copy(
        update={
            "level": 17,
            "hitpts": 20,
            "gpobjs": [],
            "obvals": [],
            "npobjs": 0,
        }
    )
    result_level = level_engine.handle(
        player=player,
        room_id=280,
        command="seek",
        args=["truth"],
    )

    assert result_level.handled is True
    assert player.level == 18
    assert messages.messages["TRUM02"] in [
        evt["text"] for evt in result_level.events if evt["scope"] == "direct"
    ]


@pytest.mark.parametrize(
    "args",
    [
        ["truth"],
        ["the", "truth"],
        ["a", "truth"],
        ["an", "truth"],
    ],
)
def test_truthy_uses_gi_bagthe_article_filter(room_engine, base_player, args):
    player = base_player.model_copy(update={"level": 17, "hitpts": 40})
    room_engine.rng = StubRandom([0.25])

    result = room_engine.handle(
        player=player,
        room_id=280,
        command="seek",
        args=args,
    )

    assert result.handled is True
    assert player.level == 18


@pytest.mark.parametrize("args", [["to", "truth"], ["in", "truth"], ["the", "a", "truth"]])
def test_truthy_rejects_non_legacy_filtered_forms(room_engine, base_player, args):
    player = base_player.model_copy(update={"level": 17})

    result = room_engine.handle(
        player=player,
        room_id=280,
        command="seek",
        args=args,
    )

    assert result.handled is False
    assert player.level == 17


def test_bodyma_requires_object_charm_and_handles_full_inventory(room_engine):
    broach_id = room_engine.objects_by_name["broach"].id
    player = fixtures.build_player().model_copy(
        update={
            "level": 12,
            "charms": [0, 0, 0, 0, 1, 0],
            "gpobjs": [0, 1, 2, 3, 4, 5],
            "obvals": [10, 11, 12, 13, 14, 15],
            "npobjs": 6,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=282,
        command="jump",
        args=["chasm"],
    )

    assert result.handled is True
    assert player.level == 13
    assert player.gpobjs == [5, 1, 2, 3, 4, broach_id]
    assert player.obvals == [15, 11, 12, 13, 14, 0]
    assert player.npobjs == 6
    assert room_engine.messages.messages["BODM03"] in [
        evt["text"] for evt in result.events if evt["scope"] == "direct"
    ]


def test_bodyma_levels_with_object_protection_without_physical_key(room_engine):
    broach_id = room_engine.objects_by_name["broach"].id
    player = fixtures.build_player().model_copy(
        update={
            "level": 12,
            "charms": [0, 0, 0, 0, 6, 0],
            "gpobjs": [],
            "obvals": [],
            "npobjs": 0,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=282,
        command="jump",
        args=["chasm"],
    )

    assert result.handled is True
    assert player.level == 13
    assert player.gpobjs == [broach_id]
    assert room_engine.messages.messages["BODM01"] in [
        evt["text"] for evt in result.events if evt["scope"] == "direct"
    ]


@pytest.mark.parametrize(
    "args",
    [
        ["chasm"],
        ["the", "chasm"],
        ["a", "chasm"],
        ["an", "chasm"],
        ["across", "chasm"],
        ["across", "the", "chasm"],
    ],
)
def test_bodyma_uses_legacy_article_and_across_filters(room_engine, args):
    player = fixtures.build_player().model_copy(
        update={
            "level": 12,
            "charms": [0, 0, 0, 0, 1, 0],
            "gpobjs": [],
            "obvals": [],
            "npobjs": 0,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=282,
        command="jump",
        args=args,
    )

    assert result.handled is True
    assert player.level == 13


@pytest.mark.parametrize(
    "args",
    [["over", "chasm"], ["into", "chasm"], ["to", "chasm"], ["the", "a", "chasm"]],
)
def test_bodyma_rejects_non_legacy_filtered_forms(room_engine, args):
    player = fixtures.build_player().model_copy(
        update={
            "level": 12,
            "charms": [0, 0, 0, 0, 1, 0],
            "gpobjs": [],
            "obvals": [],
            "npobjs": 0,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=282,
        command="jump",
        args=args,
    )

    assert result.handled is False
    assert player.level == 12


def test_bodyma_unprotected_jump_uses_damage_death_reset(room_engine):
    player = fixtures.build_player().model_copy(
        update={
            "level": 12,
            "hitpts": 48,
            "gamloc": 282,
            "pgploc": 282,
            "charms": [0, 0, 0, 0, 0, 0],
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=282,
        command="jump",
        args=["chasm"],
    )

    assert result.handled is True
    assert player.level == 1
    assert player.gamloc == 0
    assert player.hitpts == 4
    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    assert room_engine.messages.messages["BODM04"] in direct_texts
    assert room_engine.messages.messages["DIEMSG"] in direct_texts


def test_mindma_grants_pendant(room_engine, base_player):
    player = base_player.model_copy(
        update={
            "level": 13,
            "gpobjs": [],
            "obvals": [],
            "npobjs": 0,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=285,
        command="answer",
        args=["time"],
    )

    assert result.handled is True
    assert player.level == 14
    assert room_engine.objects_by_name["pendant"].id in player.gpobjs
    assert room_engine.messages.messages["MINM01"] in [
        evt["text"] for evt in result.events if evt["scope"] == "direct"
    ]


def test_mindma_rejects_article_form(room_engine, base_player):
    player = base_player.model_copy(update={"level": 13})

    result = room_engine.handle(
        player=player,
        room_id=285,
        command="answer",
        args=["the", "time"],
    )

    assert result.handled is False
    assert player.level == 13


def test_mindma_full_inventory_uses_legacy_slot_replacement(room_engine, base_player):
    pendant_id = room_engine.objects_by_name["pendant"].id
    player = base_player.model_copy(
        update={
            "level": 13,
            "gpobjs": [0, 1, 2, 3, 4, 5],
            "obvals": [0] * 6,
            "npobjs": 6,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=285,
        command="answer",
        args=["time"],
    )

    assert result.handled is True
    assert player.level == 14
    assert player.gpobjs == [5, 1, 2, 3, 4, pendant_id]
    assert room_engine.messages.messages["MINM03"] in [
        evt["text"] for evt in result.events if evt["scope"] == "direct"
    ]


def test_vhealr_offers_rose_healing(room_engine, base_player):
    base_player.gpobjs.append(40)
    base_player.obvals.append(0)
    base_player.npobjs = 2
    base_player.hitpts = 5
    base_player.level = 3

    heal = room_engine.handle(
        player=base_player,
        room_id=10,
        command="offer",
        args=["rose"],
    )

    assert base_player.hitpts == 12  # capped at level*4
    assert 40 not in base_player.gpobjs

    heal_texts = [evt["text"] for evt in heal.events if evt["scope"] == "direct"]
    assert room_engine.messages.messages["TAKROS"] in heal_texts

    reject = room_engine.handle(
        player=base_player,
        room_id=10,
        command="offer",
        args=["ruby"],
    )
    reject_texts = [evt["text"] for evt in reject.events if evt["scope"] == "direct"]
    assert room_engine.messages.messages["NOGOOD"] in reject_texts


def test_gquest_can_find_gold_and_handles_water_and_rose(base_player):
    messages = fixtures.load_messages()
    objects = fixtures.load_objects()
    spells = fixtures.load_spells()
    definitions = fixtures.load_room_scripts()
    locations = fixtures.load_locations()
    engine = yaml_rooms.YamlRoomEngine(
        definitions=definitions,
        messages=messages,
        objects=objects,
        spells=spells,
        locations=locations,
        rng=StubRandom([5]),
    )

    base_player.gold = 0

    search = engine.handle(
        player=base_player,
        room_id=12,
        command="dig",
        args=["brook"],
    )

    assert base_player.gold == 5
    direct_texts = [evt["text"] for evt in search.events if evt["scope"] == "direct"]
    assert engine.messages.messages["FNDGOL"] % 5 in direct_texts

    drink = engine.handle(
        player=base_player,
        room_id=12,
        command="drink",
        args=["water"],
    )
    drink_texts = [evt["text"] for evt in drink.events if evt["scope"] == "direct"]
    assert engine.messages.messages["DRINK0"] in drink_texts

    rose = engine.handle(
        player=base_player,
        room_id=12,
        command="get",
        args=["rose"],
    )
    assert 40 in base_player.gpobjs
    rose_texts = [evt["text"] for evt in rose.events if evt["scope"] == "direct"]
    assert engine.messages.messages["GROSE1"] in rose_texts


def test_gpcone_random_pinecone_requires_inventory_space(base_player):
    messages = fixtures.load_messages()
    objects = fixtures.load_objects()
    spells = fixtures.load_spells()
    definitions = fixtures.load_room_scripts()
    locations = fixtures.load_locations()
    engine = yaml_rooms.YamlRoomEngine(
        definitions=definitions,
        messages=messages,
        objects=objects,
        spells=spells,
        locations=locations,
        rng=StubRandom([0.1]),
    )

    base_player = base_player.model_copy(
        update={
            "npobjs": constants.MXPOBS - 1,
            "gpobjs": list(range(constants.MXPOBS - 1)),
            "obvals": [0] * (constants.MXPOBS - 1),
        }
    )

    success = engine.handle(
        player=base_player,
        room_id=14,
        command="get",
        args=["pinecone"],
    )

    assert 32 in base_player.gpobjs
    success_texts = [evt["text"] for evt in success.events if evt["scope"] == "direct"]
    assert engine.messages.messages["PINEC0"] in success_texts

    engine_fail = yaml_rooms.YamlRoomEngine(
        definitions=definitions,
        messages=messages,
        objects=objects,
        spells=spells,
        locations=locations,
        rng=StubRandom([0.9]),
    )
    base_player = base_player.model_copy(
        update={
            "npobjs": constants.MXPOBS,
            "gpobjs": list(range(constants.MXPOBS)),
            "obvals": [0] * constants.MXPOBS,
        }
    )

    failure = engine_fail.handle(
        player=base_player,
        room_id=14,
        command="take",
        args=["pinecone"],
    )
    fail_texts = [evt["text"] for evt in failure.events if evt["scope"] == "direct"]
    assert engine_fail.messages.messages["PINEC2"] in fail_texts


def test_arg_at_trigger_matches_second_argument(base_player):
    messages = fixtures.load_messages()
    objects = fixtures.load_objects()
    spells = fixtures.load_spells()
    locations = fixtures.load_locations()
    definitions = {
        "rooms": [
            {
                "id": 999,
                "triggers": [
                    {
                        "verbs": ["drop"],
                        "arg_at": {"index": 1, "value": "pool"},
                        "actions": [
                            {"type": "message", "scope": "direct", "text": "matched"}
                        ],
                    }
                ],
            }
        ]
    }
    engine = yaml_rooms.YamlRoomEngine(
        definitions=definitions,
        messages=messages,
        objects=objects,
        spells=spells,
        locations=locations,
    )

    miss = engine.handle(
        player=base_player, room_id=999, command="drop", args=["dagger"]
    )
    assert miss.handled is False

    hit = engine.handle(
        player=base_player, room_id=999, command="drop", args=["dagger", "pool"]
    )
    assert hit.handled is True
    assert any(event["text"] == "matched" for event in hit.events)


def test_fearno_levels_player_when_phrase_matched(base_player):
    messages = fixtures.load_messages()
    objects = fixtures.load_objects()
    spells = fixtures.load_spells()
    definitions = fixtures.load_room_scripts()
    locations = fixtures.load_locations()

    engine = yaml_rooms.YamlRoomEngine(
        definitions=definitions,
        messages=messages,
        objects=objects,
        spells=spells,
        locations=locations,
    )

    base_player.level = 4
    base_player.hitpts = 16
    base_player.spts = 8
    base_player.nmpdes = 1

    success = engine.handle(
        player=base_player,
        room_id=16,
        command="fear",
        args=["no", "evil"],
    )

    assert base_player.level == 5
    assert base_player.hitpts == 20
    assert base_player.spts == 10
    assert base_player.nmpdes == 2

    success_texts = [evt["text"] for evt in success.events if evt["scope"] == "direct"]
    assert engine.messages.messages["FEAR01"] in success_texts

    base_player.level = 6
    already = engine.handle(
        player=base_player,
        room_id=16,
        command="fear",
        args=["no", "evil"],
    )
    high_texts = [evt["text"] for evt in already.events if evt["scope"] == "direct"]
    assert engine.messages.messages["LVLM00"] in high_texts


def test_requires_item_trigger_skips_when_missing(base_player):
    messages = fixtures.load_messages()
    objects = fixtures.load_objects()
    spells = fixtures.load_spells()
    locations = fixtures.load_locations()

    garnet_id = next(obj.id for obj in objects if obj.name == "garnet")

    definitions = {
        "rooms": [
            {
                "id": 999,
                "name": "requires_item_demo",
                "triggers": [
                    {
                        "verbs": ["drop"],
                        "arg_matches": [{"index": 0, "value": "garnet"}],
                        "requires_item": "garnet",
                        "actions": [
                            {"type": "message", "scope": "direct", "text": "matched"}
                        ],
                    }
                ],
            }
        ]
    }

    engine = yaml_rooms.YamlRoomEngine(
        definitions=definitions,
        messages=messages,
        objects=objects,
        spells=spells,
        locations=locations,
    )

    miss = engine.handle(
        player=base_player, room_id=999, command="drop", args=["garnet"]
    )
    assert miss.handled is False

    base_player.gpobjs.append(garnet_id)
    base_player.obvals.append(0)
    base_player.npobjs = len(base_player.gpobjs)
    hit = engine.handle(player=base_player, room_id=999, command="drop", args=["garnet"])
    assert hit.handled is True
    assert any(event["text"] == "matched" for event in hit.events)


def _panthe_phrase_args():
    return [
        "legends",
        "of",
        "the",
        "time",
        "and",
        "space",
        "are",
        "true",
        "forever",
        "and",
        "never",
        "die",
    ]


def test_panthe_grants_key_when_phrase_matches(room_engine, base_player):
    player = base_player.model_copy(update={"gpobjs": [], "obvals": [], "npobjs": 0})

    result = room_engine.handle(
        player=player,
        room_id=183,
        command="say",
        args=_panthe_phrase_args(),
    )

    assert result.handled is True
    key_id = room_engine.objects_by_name["key"].id
    assert key_id in player.gpobjs

    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    broadcast_texts = [
        evt["text"] for evt in result.events if evt["scope"] == "broadcast"
    ]
    assert room_engine.messages.messages["PANM00"] in direct_texts
    assert room_engine.messages.messages["PANM01"] % player.altnam in broadcast_texts


def test_panthe_rejects_phrase_when_inventory_full(room_engine, base_player):
    player = base_player.model_copy(
        update={
            "gpobjs": [0] * constants.MXPOBS,
            "obvals": [0] * constants.MXPOBS,
            "npobjs": constants.MXPOBS,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=183,
        command="say",
        args=_panthe_phrase_args(),
    )

    assert result.handled is True
    assert player.npobjs == constants.MXPOBS
    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    assert room_engine.messages.messages["PANM02"] in direct_texts


def test_portal_enters_and_broadcasts_random_vision(base_player):
    messages = fixtures.load_messages()
    objects = fixtures.load_objects()
    spells = fixtures.load_spells()
    locations = fixtures.load_locations()
    definitions = fixtures.load_room_scripts()
    engine = yaml_rooms.YamlRoomEngine(
        definitions=definitions,
        messages=messages,
        objects=objects,
        spells=spells,
        locations=locations,
        rng=StubRandom([4]),
    )
    player = base_player.model_copy(update={"altnam": "Echo", "flags": 0})

    result = engine.handle(
        player=player,
        room_id=184,
        command="enter",
        args=["portal"],
    )

    assert result.handled is True
    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    assert messages.messages["PORTAL"] in direct_texts
    assert messages.messages["PORTAL4"] in direct_texts
    assert messages.messages["ENDPOR"] in direct_texts

    broadcast_texts = [
        evt["text"] for evt in result.events if evt["scope"] == "broadcast"
    ]
    assert messages.messages["OEPORT"] % (player.altnam, "he") in broadcast_texts


def test_grant_spell_memorize_flag_controls_pre_memorization(base_player):
    messages = fixtures.load_messages()
    objects = fixtures.load_objects()
    spells = fixtures.load_spells()
    locations = fixtures.load_locations()
    player = base_player.model_copy(update={"offspls": 0, "spells": [], "nspells": 0})

    definitions = {
        "rooms": [
            {
                "id": 997,
                "name": "grant_spell_memorize_demo",
                "triggers": [
                    {
                        "verbs": ["touch"],
                        "actions": [
                            {"type": "grant_spell", "spell": "clutzopho", "book": "offensive"},
                            {"type": "message", "scope": "direct", "text": "book:%s", "format": ["granted_spell_name"]},
                        ],
                    },
                    {
                        "verbs": ["chant"],
                        "actions": [
                            {
                                "type": "grant_spell",
                                "spell": "frostie",
                                "book": "offensive",
                                "memorize": True,
                            },
                            {"type": "message", "scope": "direct", "text": "book:%s", "format": ["granted_spell_name"]},
                        ],
                    },
                ],
            }
        ]
    }

    engine = yaml_rooms.YamlRoomEngine(
        definitions=definitions,
        messages=messages,
        objects=objects,
        spells=spells,
        locations=locations,
    )

    no_memorize = engine.handle(player=player, room_id=997, command="touch", args=[])
    assert no_memorize.handled is True
    assert player.nspells == 0
    assert player.spells == []
    assert player.offspls & engine.spells_by_name["clutzopho"].bitdef
    assert any(evt.get("text") == "book:clutzopho" for evt in no_memorize.events)

    memorize = engine.handle(player=player, room_id=997, command="chant", args=[])
    assert memorize.handled is True
    assert player.spells[-1] == engine.spells_by_name["frostie"].id
    assert player.nspells == 1
    assert any(evt.get("text") == "book:frostie" for evt in memorize.events)


def test_waller_chant_sets_sesame_flag(room_engine, base_player):
    result = room_engine.handle(
        player=base_player,
        room_id=185,
        command="chant",
        args=[],
    )

    assert result.handled is True
    state = room_engine.get_room_state(185)
    assert state.get("sesame") >= 1

    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    broadcast_texts = [
        evt["text"] for evt in result.events if evt["scope"] == "broadcast"
    ]
    assert room_engine.messages.messages["WALM03"] in direct_texts
    assert room_engine.messages.messages["WALM04"] in broadcast_texts


def test_waller_transfer_requires_sesame_and_key(room_engine, base_player):
    key_id = room_engine.objects_by_name["key"].id
    player = base_player.model_copy(update={"gpobjs": [key_id], "obvals": [0], "npobjs": 1})
    room_engine.get_room_state(185)["sesame"] = 1

    success = room_engine.handle(
        player=player,
        room_id=185,
        command="drop",
        args=["key", "crevice"],
    )

    assert success.handled is True
    assert key_id not in player.gpobjs
    transfer_events = [evt for evt in success.events if evt.get("event") == "room_transfer"]
    assert transfer_events
    assert transfer_events[0]["target_room"] == 186
    assert transfer_events[0]["legacy_transfer_format"] is True

    direct_texts = [evt["text"] for evt in success.events if evt["scope"] == "direct"]
    assert room_engine.messages.messages["WALM00"] in direct_texts

    room_engine.get_room_state(185)["sesame"] = 0
    player = base_player.model_copy(update={"gpobjs": [key_id], "obvals": [0], "npobjs": 1})

    failure = room_engine.handle(
        player=player,
        room_id=185,
        command="drop",
        args=["key", "crevice"],
    )

    direct_texts = [evt["text"] for evt in failure.events if evt["scope"] == "direct"]
    assert room_engine.messages.messages["WALM01"] in direct_texts


@pytest.mark.parametrize("command", ["drop", "insert", "put", "stick", "thrust"])
def test_waller_key_crevice_accepts_legacy_drpwrds(room_engine, base_player, command):
    key_id = room_engine.objects_by_name["key"].id
    player = base_player.model_copy(update={"gpobjs": [key_id], "obvals": [0], "npobjs": 1})
    room_engine.get_room_state(185)["sesame"] = 1

    result = room_engine.handle(
        player=player,
        room_id=185,
        command=command,
        args=["key", "crevice"],
    )

    assert result.handled is True
    assert player.gamloc == 186
    assert key_id not in player.gpobjs
    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    assert room_engine.messages.messages["WALM00"] in direct_texts


def test_waller_chant_arms_put_key_crevice(room_engine, base_player):
    key_id = room_engine.objects_by_name["key"].id
    player = base_player.model_copy(update={"gpobjs": [key_id], "obvals": [0], "npobjs": 1})

    sesame = room_engine.handle(
        player=player,
        room_id=185,
        command="chant",
        args=[],
    )

    assert sesame.handled is True

    result = room_engine.handle(
        player=player,
        room_id=185,
        command="put",
        args=["key", "crevice"],
    )

    assert result.handled is True
    assert player.gamloc == 186
    assert key_id not in player.gpobjs
    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    assert room_engine.messages.messages["WALM00"] in direct_texts


def test_waller_put_key_crevice_requires_sesame(room_engine, base_player):
    key_id = room_engine.objects_by_name["key"].id
    player = base_player.model_copy(update={"gpobjs": [key_id], "obvals": [0], "npobjs": 1})

    result = room_engine.handle(
        player=player,
        room_id=185,
        command="put",
        args=["key", "crevice"],
    )

    assert result.handled is True
    assert player.gamloc == 0
    assert key_id in player.gpobjs
    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    assert room_engine.messages.messages["WALM01"] in direct_texts


def test_waller_wrong_object_crevice_fails_even_when_carrying_key(room_engine, base_player):
    key_id = room_engine.objects_by_name["key"].id
    player = base_player.model_copy(update={"gpobjs": [key_id], "obvals": [0], "npobjs": 1})
    room_engine.get_room_state(185)["sesame"] = 1

    result = room_engine.handle(
        player=player,
        room_id=185,
        command="put",
        args=["sword", "crevice"],
    )

    assert result.handled is True
    assert player.gamloc == 0
    assert key_id in player.gpobjs
    assert not [evt for evt in result.events if evt.get("event") == "room_transfer"]
    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    assert room_engine.messages.messages["WALM01"] in direct_texts
    assert room_engine.messages.messages["WALM00"] not in direct_texts


def test_waller_say_opensesame_arms_insert_key_crevice(room_engine, base_player):
    key_id = room_engine.objects_by_name["key"].id
    player = base_player.model_copy(update={"gpobjs": [key_id], "obvals": [0], "npobjs": 1})

    sesame = room_engine.handle(
        player=player,
        room_id=185,
        command="say",
        args=["opensesame"],
    )

    assert sesame.handled is True

    result = room_engine.handle(
        player=player,
        room_id=185,
        command="insert",
        args=["key", "crevice"],
    )

    assert result.handled is True
    assert player.gamloc == 186
    assert key_id not in player.gpobjs
    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    assert room_engine.messages.messages["WALM00"] in direct_texts


def test_waller_throw_key_crevice_is_not_a_legacy_drpwrd(room_engine, base_player):
    key_id = room_engine.objects_by_name["key"].id
    player = base_player.model_copy(update={"gpobjs": [key_id], "obvals": [0], "npobjs": 1})
    room_engine.get_room_state(185)["sesame"] = 1

    result = room_engine.handle(
        player=player,
        room_id=185,
        command="throw",
        args=["key", "crevice"],
    )

    assert result.handled is False
    assert player.gamloc == 0
    assert key_id in player.gpobjs
    assert result.events == []


@pytest.mark.parametrize(
    ("room_id", "command", "args", "target_level", "success_message"),
    [
        (252, "sing", [], 19, "LEVL19"),
        (252, "hum", [], 19, "LEVL19"),
        (252, "whistle", ["to", "seer"], 19, "LEVL19"),
        (253, "forget", [], 20, "LEVL20"),
        (253, "forget", ["everything"], 20, "LEVL20"),
        (255, "offer", ["love"], 22, "LEVL22"),
        (255, "offer", ["my", "love"], 22, "LEVL22"),
        (255, "offer", ["my", "love", "forever"], 22, "LEVL22"),
        (255, "offer", ["true", "love"], 22, "LEVL22"),
        (255, "offer", ["the", "love"], 22, "LEVL22"),
        (257, "believe", ["in", "magic"], 21, "LEVL21"),
    ],
)
def test_bard_trials_level_up_without_physical_key(
    room_engine, base_player, room_id, command, args, target_level, success_message
):
    player = base_player.model_copy(
        update={"level": target_level - 1, "gpobjs": [], "obvals": [], "npobjs": 0}
    )

    result = room_engine.handle(
        player=player,
        room_id=room_id,
        command=command,
        args=args,
    )

    assert result.handled is True
    assert player.level == target_level
    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    broadcast_texts = [
        evt["text"] for evt in result.events if evt["scope"] == "broadcast"
    ]
    assert room_engine.messages.messages[success_message] in direct_texts
    assert room_engine.messages.messages["LVL9M1"] % player.altnam in broadcast_texts


def test_bard_trial_does_not_require_physical_key_at_target_level(room_engine, base_player):
    player = base_player.model_copy(update={"level": 18, "gpobjs": [], "obvals": [], "npobjs": 0})

    result = room_engine.handle(
        player=player,
        room_id=252,
        command="sing",
        args=[],
    )

    assert result.handled is True
    assert player.level == 19
    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    broadcast_texts = [
        evt["text"] for evt in result.events if evt["scope"] == "broadcast"
    ]
    assert room_engine.messages.messages["LEVL19"] in direct_texts
    assert room_engine.messages.messages["LVL9M1"] % player.altnam in broadcast_texts


def test_bard_trial_ignores_key_when_level_is_too_low(room_engine, base_player):
    player = base_player.model_copy(update={"level": 10, "gpobjs": [], "obvals": [], "npobjs": 0})

    result = room_engine.handle(
        player=player,
        room_id=252,
        command="sing",
        args=[],
    )

    assert result.handled is True
    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    broadcast_texts = [
        evt["text"] for evt in result.events if evt["scope"] == "broadcast"
    ]
    assert room_engine.messages.messages["LVLM02"] in direct_texts
    assert room_engine.messages.messages["LVLM03"] % player.altnam in broadcast_texts


def test_forgtr_requires_forget_as_first_token(room_engine, base_player):
    player = base_player.model_copy(update={"level": 19})

    result = room_engine.handle(
        player=player,
        room_id=253,
        command="please",
        args=["forget"],
    )

    assert result.handled is False
    assert player.level == 19


@pytest.mark.parametrize(
    "args",
    [
        ["magic"],
        ["the", "magic"],
        ["to", "magic"],
    ],
)
def test_believ_requires_raw_believe_in_magic(room_engine, base_player, args):
    player = base_player.model_copy(update={"level": 20})

    result = room_engine.handle(
        player=player,
        room_id=257,
        command="believe",
        args=args,
    )

    assert result.handled is False
    assert player.level == 20


@pytest.mark.parametrize(
    "args",
    [
        ["my", "true", "love"],
        ["my", "my", "love"],
    ],
)
def test_oflove_checks_only_first_two_words_after_offer(room_engine, base_player, args):
    player = base_player.model_copy(update={"level": 21})

    result = room_engine.handle(
        player=player,
        room_id=255,
        command="offer",
        args=args,
    )

    assert result.handled is False
    assert player.level == 21


def test_heartm_requires_matching_spouse(room_engine, base_player):
    player = base_player.model_copy(
        update={
            "spouse": "Juliet",
            "level": 14,
            "gpobjs": [],
            "obvals": [],
            "npobjs": 0,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=288,
        command="offer",
        args=["heart", "Romeo"],
    )

    assert result.handled is False


@pytest.mark.parametrize(
    "args",
    [
        ["heart", "Juliet"],
        ["heart", "to", "Juliet"],
    ],
)
def test_heartm_accepts_bagprep_spouse_forms(room_engine, base_player, args):
    player = base_player.model_copy(
        update={
            "spouse": "Juliet",
            "level": 14,
            "gpobjs": [],
            "obvals": [],
            "npobjs": 0,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=288,
        command="offer",
        args=args,
    )

    assert result.handled is True
    assert player.level == 15


@pytest.mark.parametrize(
    "args",
    [
        ["the", "heart", "Juliet"],
        ["heart", "to", "the", "Juliet"],
        ["heart", "Juliet", "please"],
    ],
)
def test_heartm_rejects_non_legacy_article_and_trailing_forms(
    room_engine, base_player, args
):
    player = base_player.model_copy(
        update={
            "spouse": "Juliet",
            "level": 14,
            "gpobjs": [],
            "obvals": [],
            "npobjs": 0,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=288,
        command="offer",
        args=args,
    )

    assert result.handled is False
    assert player.level == 14


def test_heartm_grants_locket_and_levels_up(room_engine, base_player):
    player = base_player.model_copy(
        update={
            "spouse": "Juliet",
            "level": 14,
            "gpobjs": [0, 1, 2, 3, 4, 5],
            "obvals": [0] * 6,
            "npobjs": 6,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=288,
        command="offer",
        args=["heart", "Juliet"],
    )

    assert result.handled is True
    assert player.level == 15
    assert player.gpobjs == [5, 1, 2, 3, 4, 15]

    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    broadcast_texts = [evt["text"] for evt in result.events if evt["scope"] == "broadcast"]
    assert room_engine.messages.messages["HEAR01"] in direct_texts
    assert room_engine.messages.messages["HEAR03"] in direct_texts
    assert room_engine.messages.messages["HEAR02"] % player.altnam in broadcast_texts


def test_soulma_grants_ring_and_levels_up(room_engine, base_player):
    player = base_player.model_copy(
        update={
            "level": 15,
            "gpobjs": [],
            "obvals": [],
            "npobjs": 0,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=291,
        command="ignore",
        args=["time"],
    )

    assert result.handled is True
    assert player.level == 16
    assert 39 in player.gpobjs

    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    broadcast_texts = [evt["text"] for evt in result.events if evt["scope"] == "broadcast"]
    assert room_engine.messages.messages["SOUL01"] in direct_texts
    assert room_engine.messages.messages["SOUL02"] % player.altnam in broadcast_texts


def test_soulma_rejects_article_form(room_engine, base_player):
    player = base_player.model_copy(update={"level": 15})

    result = room_engine.handle(
        player=player,
        room_id=291,
        command="ignore",
        args=["the", "time"],
    )

    assert result.handled is False
    assert player.level == 15


def test_soulma_full_inventory_uses_legacy_slot_replacement(room_engine, base_player):
    player = base_player.model_copy(
        update={
            "level": 15,
            "gpobjs": [0, 1, 2, 3, 4, 5],
            "obvals": [0] * 6,
            "npobjs": 6,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=291,
        command="ignore",
        args=["time"],
    )

    assert result.handled is True
    assert player.level == 16
    assert player.gpobjs == [5, 1, 2, 3, 4, 39]
    assert room_engine.messages.messages["SOUL03"] in [
        evt["text"] for evt in result.events if evt["scope"] == "direct"
    ]


def test_fanbel_belief_levels_up(room_engine, base_player):
    player = base_player.model_copy(
        update={
            "level": 23,
            "gpobjs": [],
            "obvals": [],
            "npobjs": 0,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=293,
        command="believe",
        args=["in", "fantasy"],
    )

    assert result.handled is True
    assert player.level == 24

    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    broadcast_texts = [evt["text"] for evt in result.events if evt["scope"] == "broadcast"]
    assert room_engine.messages.messages["LEVL24"] in direct_texts
    assert room_engine.messages.messages["LVL9M1"] % player.altnam in broadcast_texts


@pytest.mark.parametrize(
    "args",
    [
        ["fantasy"],
        ["the", "fantasy"],
        ["in", "fantasy", "please"],
    ],
)
def test_fanbel_requires_exact_belinf_phrase(room_engine, base_player, args):
    player = base_player.model_copy(
        update={
            "level": 23,
            "gpobjs": [],
            "obvals": [],
            "npobjs": 0,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=293,
        command="believe",
        args=args,
    )

    assert result.handled is False
    assert player.level == 23


def test_devote_requires_four_tokens(room_engine, base_player):
    player = base_player.model_copy(
        update={
            "level": 16,
            "gpobjs": [],
            "obvals": [],
            "npobjs": 0,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=295,
        command="devote",
        args=[],
    )

    assert result.handled is True
    assert player.level == 16

    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    broadcast_texts = [evt["text"] for evt in result.events if evt["scope"] == "broadcast"]
    assert room_engine.messages.messages["DEVM03"] in direct_texts
    assert room_engine.messages.messages["DEVM04"] % player.altnam in broadcast_texts


def test_devote_consumes_tokens_and_levels_up(room_engine, base_player):
    player = base_player.model_copy(
        update={
            "level": 16,
            "gpobjs": [23, 17, 15, 39],
            "obvals": [0] * 4,
            "npobjs": 4,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=295,
        command="devote",
        args=[],
    )

    assert result.handled is True
    assert player.level == 17
    assert not {23, 17, 15, 39}.intersection(player.gpobjs)

    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    broadcast_texts = [evt["text"] for evt in result.events if evt["scope"] == "broadcast"]
    assert room_engine.messages.messages["DEVM01"] in direct_texts
    assert room_engine.messages.messages["DEVM02"] % player.altnam in broadcast_texts


def test_devote_requires_jewelry_but_not_physical_golden_key(room_engine, base_player):
    physical_key_id = room_engine.objects_by_name["key"].id
    player = base_player.model_copy(
        update={
            "level": 16,
            "gpobjs": [23, 17, 15, 39],
            "obvals": [0] * 4,
            "npobjs": 4,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=295,
        command="devote",
        args=[],
    )

    assert result.handled is True
    assert player.level == 17
    assert physical_key_id not in player.gpobjs


def test_devote_ignores_trailing_words_but_rejects_devotion(room_engine, base_player):
    player = base_player.model_copy(
        update={
            "level": 16,
            "gpobjs": [23, 17, 15, 39],
            "obvals": [0] * 4,
            "npobjs": 4,
        }
    )

    success = room_engine.handle(
        player=player,
        room_id=295,
        command="devote",
        args=["myself"],
    )

    assert success.handled is True
    assert player.level == 17

    player = base_player.model_copy(
        update={
            "level": 16,
            "gpobjs": [23, 17, 15, 39],
            "obvals": [0] * 4,
            "npobjs": 4,
        }
    )
    rejected = room_engine.handle(
        player=player,
        room_id=295,
        command="devotion",
        args=[],
    )

    assert rejected.handled is False
    assert player.level == 16


def test_wingam_riddle_levels_up(room_engine, base_player):
    player = base_player.model_copy(
        update={
            "level": 24,
            "gpobjs": [],
            "obvals": [],
            "npobjs": 0,
        }
    )

    riddle = room_engine.messages.messages["RIDDLE"]
    result = room_engine.handle(
        player=player,
        room_id=302,
        command="answer",
        args=riddle.split(" "),
    )

    assert result.handled is True
    assert player.level == 25

    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    broadcast_events = [evt for evt in result.events if evt["scope"] == "broadcast"]
    broadcast_texts = [evt["text"] for evt in broadcast_events]
    global_texts = [evt["text"] for evt in result.events if evt["scope"] == "global"]
    assert room_engine.messages.messages["YOUWIN"] in direct_texts
    assert room_engine.messages.messages["SHEWON"] % player.altnam in broadcast_texts
    assert all(evt.get("exclude_player") == player.plyrid for evt in broadcast_events)
    assert global_texts == []


def test_thicket_walk_keeps_ouch_private_and_broadcasts_burning_to_others(
    room_engine, base_player
):
    result = room_engine.handle(
        player=base_player,
        room_id=19,
        command="walk",
        args=["thicket"],
    )

    assert result.handled is True

    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    broadcast_events = [evt for evt in result.events if evt["scope"] == "broadcast"]
    broadcast_texts = [evt["text"] for evt in broadcast_events]

    assert "...Ouch!" in direct_texts
    assert "...Ouch!" not in broadcast_texts
    assert any("burning in the flaming thicket" in text for text in broadcast_texts)
    assert all(evt.get("exclude_player") == base_player.plyrid for evt in broadcast_events)


def test_wingam_riddle_falls_through_when_zar_is_away(room_engine, base_player):
    player = base_player.model_copy(update={"level": 24, "gpobjs": [], "obvals": [], "npobjs": 0})
    room_engine.get_room_state(302)["zar_location"] = 250

    riddle = room_engine.messages.messages["RIDDLE"]
    result = room_engine.handle(
        player=player,
        room_id=302,
        command="answer",
        args=riddle.split(" "),
    )

    assert result.handled is False
    assert player.level == 24
    assert result.events == []


def test_wingam_allows_case_but_requires_catalog_punctuation(room_engine, base_player):
    player = base_player.model_copy(update={"level": 24, "gpobjs": [], "obvals": [], "npobjs": 0})

    result = room_engine.handle(
        player=player,
        room_id=302,
        command="answer",
        args=[
            "Cast",
            "the",
            "spells",
            "and",
            "cross",
            "the",
            "seas,",
            "heart,",
            "soul,",
            "mind,",
            "and",
            "body",
            "are",
            "the",
            "keys",
        ],
    )

    assert result.handled is True
    assert player.level == 25

    player = base_player.model_copy(update={"level": 24, "gpobjs": [], "obvals": [], "npobjs": 0})
    missing_commas = room_engine.handle(
        player=player,
        room_id=302,
        command="answer",
        args=[
            "cast",
            "the",
            "spells",
            "and",
            "cross",
            "the",
            "seas",
            "heart",
            "soul",
            "mind",
            "and",
            "body",
            "are",
            "the",
            "keys",
        ],
    )

    assert missing_commas.handled is False
    assert player.level == 24

    player = base_player.model_copy(update={"level": 24, "gpobjs": [], "obvals": [], "npobjs": 0})
    trailing_period = room_engine.handle(
        player=player,
        room_id=302,
        command="answer",
        args=[
            "cast",
            "the",
            "spells",
            "and",
            "cross",
            "the",
            "seas,",
            "heart,",
            "soul,",
            "mind,",
            "and",
            "body",
            "are",
            "the",
            "keys.",
        ],
    )

    assert trailing_period.handled is False
    assert player.level == 24
