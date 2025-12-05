import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from kyrgame import fixtures


def build_offline_bundle(output_path: Path, fixture_root: Path | None = None) -> Path:
    """Package fixture content for offline-capable clients."""

    bundles = fixtures.load_message_bundles(fixture_root)
    default_bundle = bundles[fixtures.DEFAULT_LOCALE]

    payload = {
        "version": f"{default_bundle.version}-offline",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "locales": sorted(bundles.keys()),
        "messages": default_bundle.model_dump(),
        "commands": [cmd.model_dump() for cmd in fixtures.load_commands(fixture_root)],
        "objects": [obj.model_dump() for obj in fixtures.load_objects(fixture_root)],
        "spells": [spell.model_dump() for spell in fixtures.load_spells(fixture_root)],
        "locations": [loc.model_dump() for loc in fixtures.load_locations(fixture_root)],
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Package fixtures into an offline bundle")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("legacy/Dist/offline-content.json"),
        help="Where to write the offline bundle",
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=None,
        help="Optional alternate fixture root",
    )
    args = parser.parse_args()

    build_offline_bundle(args.output, args.fixtures)


if __name__ == "__main__":
    main()
