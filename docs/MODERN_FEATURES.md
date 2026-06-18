# Modern Feature Registry

Modern features are gameplay changes that belong outside strict legacy parity. A player with `honor_mode=true` receives the legacy-only path. A player with `honor_mode=false` can receive the modern path, unless the server starts with `KYRGAME_FORCE_HONOR_MODE=1`.

This file is the canonical registry for modern behavior. Code should reference the stable feature id, and branch comments should name the id so modern behavior is easy to find, audit, or remove.

Every modern feature must have:

- A stable id in `backend/kyrgame/modern_features.py`.
- A human-readable entry in this file.
- Tests covering both the honor-mode path and the modern path.
- A legacy behavior note with source references when the feature changes ported gameplay.

## Taxonomy

- **Quality-of-life:** reduces friction while preserving most legacy risk and reward.
- **Recovery:** changes the aftermath of failure without changing the triggering danger.
- **Runtime policy:** controls how modern behavior is enabled, hidden, or overridden.

## Extraction Notes

- Modern feature gates should call `HonorModePolicy.modern_feature_enabled(player, feature_id)`.
- Shared modern behavior should live behind clearly named helpers or plans rather than being mixed into legacy helpers.
- Event payloads should include the feature id or a feature-specific boolean when clients need to distinguish modern behavior.
- Legacy paths should keep their source references and should remain usable when force-honor mode is enabled.

## Active Features

### Fountain immediate spell-point restore

- **Feature id:** `fountain_immediate_sp_restore`
- **Taxonomy:** quality-of-life
- **Scope:** room 38, Fountain of Eternal Magic
- **Honor behavior:** drinking from the fountain uses the legacy `DRINK0`/`DRINK1` water response and does not restore spell points outside the recurring spell tick.
- **Modern behavior:** non-honor players recover up to 2 spell points immediately when drinking or swallowing fountain water. If spell points are restored, the drinker sees `...The fresh water is very delicious and refreshing! Your mind feels clearer.`
- **Legacy refs:** `legacy/KYRROUS.C:759-819`, `legacy/KYRROUS.C:1429`, `legacy/Dist/ELWKYRM.MSG:1575`
- **Tests:** `backend/tests/test_room_scripts.py`

### Modern death recovery

- **Feature id:** `modern_death_recovery`
- **Taxonomy:** recovery
- **Scope:** command damage, YAML room-script `damage`, and Zar animation deaths.
- **Honor behavior:** honor-mode players and all players under `KYRGAME_FORCE_HONOR_MODE=1` keep the legacy `hitoth()`/`initgp()` full reset to level 1, empty inventory, empty spellbook ownership, rerolled birthstones, cleared progress, and room-0 holy-light arrival.
- **Modern behavior:** non-honor deaths use a shared `DeathRecoveryPlan` from `backend/kyrgame/player_lifecycle.py`.
- **Legacy refs:** `legacy/KYRSPEL.C:303-321`, `legacy/KYRANDIA.C:325-356`, `legacy/KYRSYSP.C:148`
- **Tests:** `backend/tests/test_player_lifecycle.py`, `backend/tests/test_commands_cast.py`, `backend/tests/test_yaml_room_engine.py`, `backend/tests/world/test_animation_tick_system.py`

Modern death state:

- The player returns to willow room `0` with `gamloc=0`, `pgploc=0`, `altnam=plyrid`, and `attnam=plyrid`.
- Level becomes `max(1, old_level - 1)`.
- `nmpdes` is recalculated from the new level, hit points become `4 * level`, and spell points become `2 * level`.
- Gold is lost, carried inventory is cleared, object values are lost, and `macros=19` starts the player exhausted.
- Memorized spells are forgotten with `spells=[]` and `nspells=0`.
- Spellbook ownership bits are preserved: `offspls`, `defspls`, and `othspls`.
- Identity and long-lived progress are preserved: `uidnam`, `plyrid`, `honor_mode`, `LOADED`, `FEMALE`, `BRFSTF`, `MARRYD`, `BLESSD`, `spouse`, `stones`, `gemidx`, and `stumpi`.
- Temporary effects are cleared: `charms`, `INVISF`, `PEGASU`, `WILLOW`, and `PDRAGN`.
- `GOTKYG` is cleared when the new level is below 9, matching `legacy/KYRSYSP.C:148`.
- `GOTKYG` is also cleared when death occurs in castle rooms `219..302` while carrying soulstone object `28` or kyragem object `29`.

Inventory placement:

- Soulstone `28` and kyragem `29` are filtered from castle deaths and do not drop.
- All other carried item ids are placed independently, including duplicates.
- Drops fill the death room first, then randomly shuffled adjacent rooms from north, south, east, and west exits.
- Remaining items are placed in random dark forest rooms `44..167`.
- If every eligible room is full, remaining items vanish and death recovery still completes.
- Ground objects store object ids only, so carried `obvals` are intentionally discarded.
- Rooms that receive drops get `room_objects` refresh events and `DROPIT3` drop messages.

Persistence and events:

- Command and live Zar paths stage the recovered player row and changed room-object rows in one database commit when a session is available.
- Success broadcasts are emitted after the recovery plan is applied and persisted.
- Events include `death_reset`, `modern_death_recovery`, `old_level`, `new_level`, `filtered_items`, `vanished_items`, `dropped_rooms`, `refresh_location`, and `recipient_scope`.
- Death messaging reuses `DIEMSG`, `KILLED`, holy-light arrival text, `room_objects`, and `DROPIT3`.

## Adding A Feature

1. Add a `ModernFeature` entry in `backend/kyrgame/modern_features.py`.
2. Gate gameplay through `HonorModePolicy.modern_feature_enabled(...)`.
3. Add tests for stored honor mode, forced honor mode, and the modern path.
4. Add the feature to this document before enabling it.
