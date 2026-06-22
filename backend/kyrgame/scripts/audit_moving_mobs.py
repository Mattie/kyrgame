from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from kyrgame import database
from kyrgame.moving_mobs import (
    audit_moving_mobs,
    cleanup_confirmation_token,
    cleanup_moving_mobs,
)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _print_audit_table(audit: dict[str, object]) -> None:
    rows = []
    for mob in audit["mobs"]:
        rows.append(
            [
                str(mob["id"]),
                str(mob["kind"]),
                str(mob.get("tracker_room_id")),
                str(mob.get("copy_count")),
                str(mob.get("singleton_status")),
                ",".join(str(room_id) for room_id in mob.get("object_rooms", [])),
            ]
        )
    headers = ["mob", "kind", "tracker", "copies", "status", "object_rooms"]
    widths = [
        max(len(row[index]) for row in [headers, *rows])
        for index in range(len(headers))
    ]
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def _session_from_args(args: argparse.Namespace):
    engine = database.get_engine(args.database_url)
    return database.create_session(engine)


def run_audit(args: argparse.Namespace) -> int:
    with _session_from_args(args) as session:
        audit = audit_moving_mobs(session)
    if args.format == "json":
        _print_json(audit)
    else:
        _print_audit_table(audit)
        print(f"\nconfirmation_token: {cleanup_confirmation_token(audit)}")
    return 0


def run_cleanup(args: argparse.Namespace) -> int:
    with _session_from_args(args) as session:
        try:
            result = cleanup_moving_mobs(
                session,
                dry_run=not args.apply,
                apply=args.apply,
                confirm=args.confirm,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if args.apply:
            session.commit()
    if args.format == "json":
        _print_json(result)
    else:
        _print_audit_table(result["audit"])
        print(f"\napplied: {result['applied']}")
        print(f"confirmation_token: {result['confirmation_token']}")
        if result["changes"]:
            print("changes:")
            for change in result["changes"]:
                print(
                    f"  {change['mob_id']} room {change['room_id']}: "
                    f"{change['before']} -> {change['after']}"
                )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit and repair Kyrgame moving mob singletons")
    parser.add_argument("--database-url", help="Database URL. Defaults to DATABASE_URL.")

    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Report moving mob singleton state")
    audit.add_argument("--format", choices=["table", "json"], default="table")
    audit.set_defaults(func=run_audit)

    cleanup = sub.add_parser("cleanup", help="Dry-run or apply moving mob singleton cleanup")
    cleanup.add_argument("--format", choices=["table", "json"], default="table")
    cleanup.add_argument("--dry-run", action="store_true", help="Preview cleanup without writing")
    cleanup.add_argument("--apply", action="store_true", help="Apply cleanup after confirmation")
    cleanup.add_argument("--confirm", help="Confirmation token emitted by audit or dry-run")
    cleanup.set_defaults(func=run_cleanup)

    args = parser.parse_args(argv)
    if args.command == "cleanup" and args.dry_run and args.apply:
        parser.error("cleanup accepts either --dry-run or --apply")
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - CLI shim
    raise SystemExit(main(sys.argv[1:]))
