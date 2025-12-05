"""Minimal CLI helpers for secured admin endpoints.

These helpers mirror the KYRSYSP.C editor workflows by letting operators
update player records and message bundles from the command line without
hand-crafting HTTP requests.
"""

import argparse
import json
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def push_player(args: argparse.Namespace) -> None:
    payload = _load_payload(Path(args.file))
    player_id = args.player_id or payload.get("plyrid")
    if not player_id:
        raise SystemExit("Player payload must include plyrid or --player-id")

    url = f"{args.base_url}/admin/players"
    method = httpx.post if args.create else httpx.put
    if not args.create:
        url = f"{url}/{player_id}"

    response = method(url, json=payload, headers=_headers(args.token))
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2))


def push_message_bundle(args: argparse.Namespace) -> None:
    payload = _load_payload(Path(args.file))
    url = f"{args.base_url}/admin/i18n/{args.locale}"
    response = httpx.put(url, json=payload, headers=_headers(args.token))
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Call Kyrandia admin endpoints")
    parser.add_argument("--token", required=True, help="Admin bearer token")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Base URL for the running Kyrgame API (default: http://localhost:8000)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    player = sub.add_parser("push-player", help="Create or replace a player record")
    player.add_argument("--file", required=True, help="Path to a PlayerModel JSON payload")
    player.add_argument("--player-id", help="Override player id when replacing")
    player.add_argument(
        "--create",
        action="store_true",
        help="Use POST instead of PUT to create a brand new record",
    )
    player.set_defaults(func=push_player)

    bundle = sub.add_parser("update-bundle", help="Replace a message bundle for a locale")
    bundle.add_argument("--file", required=True, help="Path to a MessageBundleModel JSON payload")
    bundle.add_argument("--locale", required=True, help="Locale identifier in the payload")
    bundle.set_defaults(func=push_message_bundle)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":  # pragma: no cover - CLI shim
    main()
