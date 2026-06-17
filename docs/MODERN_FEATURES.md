# Modern Feature Registry

Modern features are gameplay changes that belong outside strict legacy parity. A player with `honor_mode=true` receives the legacy-only path. A player with `honor_mode=false` can receive the modern path, unless the server starts with `KYRGAME_FORCE_HONOR_MODE=1`.

Every modern feature must have:

- A stable id in `backend/kyrgame/modern_features.py`.
- A human-readable entry in this file.
- Tests covering both the honor-mode path and the modern path.
- A legacy behavior note with source references when the feature changes ported gameplay.

## Active Features

### Fountain immediate spell-point restore

- **Feature id:** `fountain_immediate_sp_restore`
- **Scope:** room 38, Fountain of Eternal Magic
- **Honor behavior:** drinking from the fountain uses the legacy `DRINK0`/`DRINK1` water response and does not restore spell points outside the recurring spell tick.
- **Modern behavior:** non-honor players recover up to 2 spell points immediately when drinking or swallowing fountain water. If spell points are restored, the drinker sees `...The fresh water is very delicious and refreshing! Your mind feels clearer.`
- **Legacy refs:** `legacy/KYRROUS.C:759-819`, `legacy/KYRROUS.C:1429`, `legacy/Dist/ELWKYRM.MSG:1575`
- **Tests:** `backend/tests/test_room_scripts.py`

## Adding A Feature

1. Add a `ModernFeature` entry in `backend/kyrgame/modern_features.py`.
2. Gate gameplay through `HonorModePolicy.modern_feature_enabled(...)`.
3. Add tests for stored honor mode, forced honor mode, and the modern path.
4. Add the feature to this document before enabling it.
