"""Repository-root wrapper for the moving mob singleton audit CLI."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from kyrgame.scripts.audit_moving_mobs import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
