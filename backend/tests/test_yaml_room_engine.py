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
    assert room_engine.spells_by_name["zapher"].id in base_player.spells

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
