import json
from pathlib import Path
from typing import List

from . import constants, models

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
DEFAULT_LOCALE = "en-US"


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


def load_commands(path: Path | None = None) -> List[models.CommandModel]:
    fixture_path = (path or FIXTURE_ROOT) / "commands.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [models.CommandModel(**item) for item in data]


def load_message_bundle(
    locale: str = DEFAULT_LOCALE, version: str | None = None, path: Path | None = None
) -> models.MessageBundleModel:
    base = (path or FIXTURE_ROOT) / "messages"
    suffix = version or "legacy"
    fixture_path = base / f"{locale}.{suffix}.json"
    if not fixture_path.exists():
        available = list(bundle.name for bundle in base.glob("*.json"))
        raise FileNotFoundError(f"No message bundle for {locale} ({suffix}); found {available}")
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return models.MessageBundleModel(**data)


def load_message_bundles(path: Path | None = None) -> dict[str, models.MessageBundleModel]:
    bundle_dir = (path or FIXTURE_ROOT) / "messages"
    bundles: dict[str, models.MessageBundleModel] = {}
    for bundle_path in bundle_dir.glob("*.json"):
        data = json.loads(bundle_path.read_text(encoding="utf-8"))
        bundle = models.MessageBundleModel(**data)
        bundles[bundle.locale] = bundle
    if not bundles:
        raise FileNotFoundError(f"No message bundles found under {bundle_dir}")
    return bundles


def load_messages(path: Path | None = None) -> models.MessageBundleModel:
    return load_message_bundle(path=path)


def fixture_summary(path: Path | None = None) -> dict:
    """Return counts useful for tests and seed scripts."""
    location_models = load_locations(path)
    object_models = load_objects(path)
    spell_models = load_spells(path)
    command_models = load_commands(path)
    message_bundles = load_message_bundles(path)
    default_bundle = message_bundles[DEFAULT_LOCALE]
    return {
        "locations": len(location_models),
        "objects": len(object_models),
        "spells": len(spell_models),
        "commands": len(command_models),
        "messages": len(default_bundle.messages),
        "locales": sorted(message_bundles.keys()),
    }
