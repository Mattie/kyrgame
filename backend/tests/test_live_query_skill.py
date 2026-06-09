from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_QUERY_SCRIPT = (
    REPO_ROOT
    / "local-docker"
    / "skills"
    / "live-query"
    / "scripts"
    / "Find-LiveGem.ps1"
)


@pytest.mark.skipif(
    not LIVE_QUERY_SCRIPT.exists(),
    reason="local-docker live-query skill script is intentionally local-only",
)
def test_live_query_skill_defaults_to_world_room_scan_and_neutral_labels():
    text = LIVE_QUERY_SCRIPT.read_text(encoding="utf-8")

    assert "[int]$ForestMin = 0," in text
    assert "[int]$ForestMax = 171" in text
    assert '"Nearest live rooms:"' in text
    assert '"No $gemKey found in rooms $ForestMin..$ForestMax."' in text
