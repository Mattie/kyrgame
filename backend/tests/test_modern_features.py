from pathlib import Path

from kyrgame import modern_features


def test_registered_modern_features_have_documentation_entries():
    docs = (
        Path(__file__).resolve().parents[2] / "docs" / "MODERN_FEATURES.md"
    ).read_text(encoding="utf-8")

    for feature in modern_features.MODERN_FEATURES:
        assert feature.id in docs
        assert feature.title in docs


def test_registered_modern_features_have_stable_unique_ids():
    ids = [feature.id for feature in modern_features.MODERN_FEATURES]

    assert ids == sorted(set(ids))
    assert "fountain_immediate_sp_restore" in ids
