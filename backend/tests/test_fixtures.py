import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from kyrgame import constants
from kyrgame import loader
from kyrgame import models
from kyrgame.database import create_session, get_engine, init_db_schema

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def load_json(name: str):
    with open(FIXTURE_DIR / name, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_yaml(name: str):
    with open(FIXTURE_DIR / name, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_location_fixture_constraints():
    raw_locations = load_json("locations.json")
    parsed_locations = [models.LocationModel(**item) for item in raw_locations]

    assert parsed_locations, "locations fixture should not be empty"
    assert len(parsed_locations) == constants.NGLOCS
    for loc in parsed_locations:
        assert len(loc.brfdes) <= constants.BRFDES_LEN
        assert len(loc.objlds) <= constants.OBJLDS_LEN
        assert len(loc.objects) <= constants.MXLOBS
        assert loc.nlobjs == len(loc.objects)
        assert loc.gi_north is not None
        assert loc.gi_south is not None
        assert loc.gi_east is not None
        assert loc.gi_west is not None

    with pytest.raises(ValidationError):
        models.LocationModel(
            id=999,
            brfdes="X" * (constants.BRFDES_LEN + 1),
            objlds="short text",
            objects=[],
            gi_north=0,
            gi_south=0,
            gi_east=0,
            gi_west=0,
        )


def test_object_and_spell_fixtures_enforce_limits():
    raw_objects = load_json("objects.json")
    parsed_objects = [models.GameObjectModel(**item) for item in raw_objects]
    assert parsed_objects, "objects fixture should not be empty"
    assert len(parsed_objects) == constants.NGOBJS
    for obj in parsed_objects:
        assert obj.id <= constants.NGOBJS

    raw_spells = load_json("spells.json")
    parsed_spells = [models.SpellModel(**item) for item in raw_spells]
    assert parsed_spells, "spells fixture should not be empty"
    assert len(parsed_spells) == constants.NGSPLS
    for spell in parsed_spells:
        assert len(spell.name) <= constants.SPELL_NAME_LEN
        assert spell.level >= 0

    with pytest.raises(ValidationError):
        models.SpellModel(id=1, name="X" * (constants.SPELL_NAME_LEN + 1), sbkref=0, bitdef=0, level=0, splrou="r")


def test_command_fixture_constraints():
    raw_commands = load_json("commands.json")
    parsed_commands = [models.CommandModel(**item) for item in raw_commands]
    assert parsed_commands
    for idx, cmd in enumerate(parsed_commands):
        assert cmd.id == idx
        assert len(cmd.command) <= 32


def test_messages_fixture_shape():
    catalog = load_yaml("messages.yaml")
    parsed = models.MessageCatalogModel(**catalog)
    assert "FOREST" in parsed.messages
    assert len(parsed.messages) > 100


def test_loader_populates_database(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'kyrgame.db'}")
    init_db_schema(engine)
    session = create_session(engine)

    loader.load_all_from_fixtures(session, FIXTURE_DIR)

    assert session.query(models.Location).count() == len(load_json("locations.json"))
    assert session.query(models.GameObject).count() == len(load_json("objects.json"))
    assert session.query(models.Command).count() == len(load_json("commands.json"))
    assert session.query(models.Spell).count() == len(load_json("spells.json"))
    assert session.query(models.Message).count() == len(load_yaml("messages.yaml")['messages'])
