import json
from pathlib import Path
from typing import Iterable, List

import yaml

from . import constants, models

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"


def load_locations(path: Path | None = None) -> List[models.LocationModel]:
    fixture_path = (path or FIXTURE_ROOT) / "locations.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [models.LocationModel(**item) for item in data]


def load_objects(path: Path | None = None) -> List[models.GameObjectModel]:
    fixture_path = (path or FIXTURE_ROOT) / "objects.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [models.GameObjectModel(**item) for item in data]


def load_spells(path: Path | None = None) -> List[models.SpellModel]:
    fixture_path = (path or FIXTURE_ROOT) / "spells.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [models.SpellModel(**item) for item in data]


def load_messages(path: Path | None = None) -> models.MessageCatalogModel:
    fixture_path = (path or FIXTURE_ROOT) / "messages.yaml"
    data = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
    return models.MessageCatalogModel(**data)


def fixture_summary(path: Path | None = None) -> dict:
    """Return counts useful for tests and seed scripts."""
    location_models = load_locations(path)
    object_models = load_objects(path)
    spell_models = load_spells(path)
    message_catalog = load_messages(path)
    return {
        "locations": len(location_models),
        "objects": len(object_models),
        "spells": len(spell_models),
        "messages": len(message_catalog.messages),
    }
