#!/usr/bin/env sh
set -e

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export PYTHONPATH="${PYTHONPATH:-}:${SCRIPT_DIR}"

python -m kyrgame.scripts.seed_db

exec "$@"
