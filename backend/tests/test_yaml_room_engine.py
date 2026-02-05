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


def test_philos_wonder_levels_with_key(room_engine, base_player):
    key_id = room_engine.objects_by_name["key"].id
    player = base_player.model_copy(
        update={
            "level": 22,
            "gpobjs": [key_id],
            "obvals": [0],
            "npobjs": 1,
        }
    )

    result = room_engine.handle(
        player=player,
        room_id=264,
        command="wonder",
        args=[],
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
        rng=StubRandom([0.25]),
    )
    level_engine = yaml_rooms.YamlRoomEngine(
        definitions=fixtures.load_room_scripts(),
        messages=messages,
        objects=objects,
        spells=spells,
        locations=locations,
        rng=StubRandom([0.75]),
    )

    key_id = damage_engine.objects_by_name["key"].id
    base = fixtures.build_player()
    player = base.model_copy(
        update={
            "level": 17,
            "hitpts": 20,
            "gpobjs": [key_id],
            "obvals": [0],
            "npobjs": 1,
        }
    )

    result_damage = damage_engine.handle(
        player=player,
        room_id=280,
        command="seek",
        args=["truth"],
    )

    assert result_damage.handled is True
    assert player.hitpts == 0
    assert player.level == 17
    assert messages.messages["TRUM01"] in [
        evt["text"] for evt in result_damage.events if evt["scope"] == "direct"
    ]

    player = player.model_copy(update={"hitpts": 20})
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


def test_bodyma_requires_object_charm_and_handles_full_inventory(room_engine):
    bracelet_id = room_engine.objects_by_name["broach"].id
    key_id = room_engine.objects_by_name["key"].id
    player = fixtures.build_player().model_copy(
        update={
            "level": 12,
            "charms": [0, 0, 0, 0, 1, 0],
            "gpobjs": [key_id, 0, 1, 2, 3, 4],
            "obvals": [0, 0, 0, 0, 0, 0],
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
    assert bracelet_id in player.gpobjs
    assert player.npobjs == 6
    assert room_engine.messages.messages["BODM03"] in [
        evt["text"] for evt in result.events if evt["scope"] == "direct"
    ]


def test_mindma_grants_pendant(room_engine, base_player):
    key_id = room_engine.objects_by_name["key"].id
    player = base_player.model_copy(
        update={
            "level": 13,
            "gpobjs": [key_id],
            "obvals": [0],
            "npobjs": 1,
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


@pytest.mark.parametrize(
    ("room_id", "command", "args", "target_level", "success_message"),
    [
        (252, "sing", [], 19, "LEVL19"),
        (253, "forget", [], 20, "LEVL20"),
        (255, "offer", ["love"], 22, "LEVL22"),
        (255, "offer", ["my", "love"], 22, "LEVL22"),
        (257, "believe", ["magic"], 21, "LEVL21"),
    ],
)
def test_bard_trials_level_up_with_key(
    room_engine, base_player, room_id, command, args, target_level, success_message
):
    key_id = room_engine.objects_by_name["key"].id
    player = base_player.model_copy(
        update={"level": target_level - 1, "gpobjs": [key_id], "obvals": [0], "npobjs": 1}
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


def test_bard_trial_requires_key_at_target_level(room_engine, base_player):
    player = base_player.model_copy(update={"level": 18, "gpobjs": [], "obvals": [], "npobjs": 0})

    result = room_engine.handle(
        player=player,
        room_id=252,
        command="sing",
        args=[],
    )

    assert result.handled is True
    assert player.level == 18
    direct_texts = [evt["text"] for evt in result.events if evt["scope"] == "direct"]
    broadcast_texts = [
        evt["text"] for evt in result.events if evt["scope"] == "broadcast"
    ]
    assert room_engine.messages.messages["NPAY00"] in direct_texts
    assert room_engine.messages.messages["NPAY01"] % player.altnam in broadcast_texts


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


def test_believe_in_magic_is_not_required(room_engine, base_player):
    player = base_player.model_copy(update={"level": 20})

    result = room_engine.handle(
        player=player,
        room_id=257,
        command="believe",
        args=["in", "magic"],
    )

    assert result.handled is False
