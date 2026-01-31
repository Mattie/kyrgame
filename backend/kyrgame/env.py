from __future__ import annotations

import os
from pathlib import Path


def _default_env_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".env"


def load_env_file(path: Path | None = None) -> bool:
    env_path = Path(path) if path else _default_env_path()
    if not env_path.exists():
        return False

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()

        if "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'").strip()

        if not key or key in os.environ:
            continue

        os.environ[key] = value

    return True
