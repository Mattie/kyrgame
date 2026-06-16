# Porting Plan: Kyrandia to JS Frontend + Python Backend

## Goals
- Deliver a modern multiplayer web experience with a JS front-end and Python back-end while preserving gameplay behaviors documented in the legacy C code.
- Keep the C data structures as authoritative schemas when designing persistence and APIs to ensure compatibility with assets and rules.
- Build the new stack so it can run locally via Docker/WSL2 with repeatable tests and fixtures.
- Keep the original MajorBBS sources organized in `legacy/` so they remain easy to reference as we extract content and parity requirements.

## Porting Guardrails
- For message parity, validate the C call site and the `.MSG` catalog together. Legacy routines may use inline `prf(...)` or `CHAR_BUFFER` text, and target/caster/room broadcasts may use different message IDs.
- For multiplayer fan-out, preserve the legacy recipient split (`outprf`, `sndoth`, `sndbt2`, `sndloc`) in WebSocket delivery and test each recipient surface when messages differ.
- For animation cadence, keep `animat()` aligned to the 15-tick scheduler and six-routine rotation (`dryads`, `elves`, `gemakr`, `gemakr`, `zarapp`, `browns`) unless a PR explicitly changes pacing.

## Porting Checklist

- [x] Captured legacy constants (sizes, limits, flags) from `legacy/KYRANDIA.H` in `backend/kyrgame/constants.py` to anchor model validation.
- [x] Defined initial Pydantic + SQLAlchemy models for spells, objects, locations, and a partial player record mirroring the legacy structs.
- [x] Generated JSON fixtures for commands, locations, objects, spells, and localized message bundles with validation tests.
- [x] Added loader utilities to seed a database session from fixtures and a script to package offline content (`backend/kyrgame/scripts/package_content.py`).
- [x] Stood up a FastAPI skeleton with fixture-backed HTTP endpoints, a room WebSocket gateway, simple presence tracking, rate limiting, and a stub room script engine (e.g., the willow routine).
- [x] Expand player modeling to cover the full legacy state (timers, spell slots, inventories, gems) with validation and serialization parity to `gmplyr`.
- [x] Validated gmplyr player field ranges (charm timers, gem/stump indices, macro cap, spell IDs) across models + fixtures.
- [x] Persist player sessions and runtime state in a real database (PostgreSQL) with migrations, replacing the current in-memory SQLite bootstrap.
- [x] Added runtime bootstrap seeding guards (`KYRGAME_RESET_ON_BOOT`, `KYRGAME_SEED_IF_EMPTY`) so fixture reloads only run for explicit resets or empty databases.
- [x] Documented startup seeding controls (`KYRGAME_RESET_ON_BOOT`, `KYRGAME_SEED_IF_EMPTY`) in runtime/admin docs and `.env` example with demo/prod-safe defaults.
- [x] Flesh out the command dispatcher to mirror `KYRCMDS.C` (movement, speech variants, inventory, combat, system commands) with authoritative state changes and permission checks. *(Updated give-recipient messaging to include the legacy `gmsgutl` actor prefix before `GIVERU10` text so UI renders the giver identity.)*
- [x] Persist both giver and recipient state for `give` gold/item transfers so DB-backed sessions cannot duplicate resources after reconnect.
- [x] Port look/examine/see (looker) command handling with tests to mirror legacy room/object/player inspection.
- [x] Align looker player descriptions with FEMALE flag (FDES vs MDES) for parity with `KYRANDIA.C`/`KYRSYSP.C`.
- [x] Ensure WebSocket sessions hydrate player identity fields (altnam/attnam) from persisted records for looker messaging.
- [x] Match LOOK player targeting and level-driven appearance updates to legacy `findgp`/`glvutl`/`kyraedit` behavior.
- [x] Enforced `findgp`-style invisibility gating (`ckinvs`) for targeted player verbs (`whisper`/`give`/`wink`/player-targeted `get`) so invisible occupants cannot be resolved without see-invisibility parity.
- [x] Restored `aimer()` gating so `aim`/`point` rejects non-`AIMABL` inventory objects with `OBJM04`, matching legacy `KYROBJR.C` weapon checks.
- [x] Added structured room spoiler metadata (legacy routines + YAML scripts) and a spoiler command for runtime parity guidance.
- [x] Recreate world/object/spell services that reflect `KYRLOCS.C`, `KYROBJS.C`, `KYRSPEL.C`, and `KYRANIM.C`, including timers, room routines, and object/spell effects. *(Completed explicit gap tracking in `docs/PORTING_PLAN_world_object_spell_gaps.md`, including remaining runtime spell handlers, Zar death relocation/refresh behavior, and browser-visible legacy fan-out for remote target effects.)*
- [x] Port remaining room routines (rooms 288/291/293/295/302) via YAML scripts in `backend/fixtures/room_scripts/` unless YAML is insufficient; reuse established patterns and include legacy source line comments as required.
- [x] Added `AnimationTickSystem` with coordinator-owned routine index rotation, timed one-shot flags (`sesame`/`chantd`/`rockpr`), Zar state (`zloc`/counter/attack index), and multiplayer-ready persistence hooks to mirror `KYRANIM.C` animation cadence semantics.
- [x] Ported `gemakr()` parity into animation services with legacy `genrdn()` exclusive forest-room targeting (`44..167`) and random-gem selection (`0..11`), `<4` room-object capacity gating, deterministic/random gem cadence (`garnet` default with every 11th successful spawn randomized), persisted gem cadence plus last attempt/spawn state, system telemetry for spawn attempts/skips, admin tracker status with last spawn room/object details, and room broadcast payload updates for multiplayer clients (including `room_objects` event/type envelope parity plus `location` + object `{id}` entries for navigator refresh handling).
- [x] Ported `dryads()`, `elves()`, and `browns()` into animation services with dryad movement/capacity handling, elf hint/gold alternation, brownie gold/inventory theft, persisted player/room mutations, room-broadcast payloads, and navigator rendering for legacy hidden NPC presence lines (`KUTM05`/`KUTM06`).
- [x] Added an admin-only mob tracker endpoint and navigator panel exposing current legacy animation state (`dloc`, brownie `bloc`/`bpidx`, elf last sighting, and Zar room/counter/next attack/object presence) for live parity debugging.
- [x] Added an admin-only Elf trigger in the mob tracker so testers can force the legacy `elves()` hint/gold encounter in the current room without waiting for random animation selection.
- [x] Added shared client-side inline rendering for legacy creature names so console text, room object labels, HUD summaries, and the admin mob tracker visually call out Zar/dragon, dryad, elf, and brownie without changing backend message catalogs or event payloads.
- [x] Added shared client-side inline rendering for legacy transformation forms and readable object variants so Unseen Force, pegasus, psuedo dragon, willowisp, parchment, and tome receive stable emoji/color treatment without changing backend message catalogs or event payloads.
- [x] Filtered account-admin players out of public active/recent player activity and leaderboard payloads by default while leaving game sessions playable.
- [x] Bridged animation one-shot flags from room runtime state into scheduled animation broadcasts so legacy fade/reset messages (e.g., WALM05) trigger and clear like `KYRANIM.C` globals.
- [x] Added a WebSocket solo level journey test and checklist covering level-up commands from level 1 through 25, with quest-item acquisition commands for dagger, charm, tiara, wand, kyragem, and devotion tokens plus controlled setup for birthstones, stump gem sequencing, spouse state, the `KYRKEY` module entitlement model, and the truth-maze random branch. [Tracker: `docs/solo_level_journey_checklist.md`]
- [x] Added a direct player level-up WebSocket cue for frontend ambient-audio reactions, with Python room routine and YAML room-script coverage proving level increases emit `player_level_up` metadata without changing legacy room text.
- [x] Implement authentication/session lifecycle matching `kyloin`/`kyrand` semantics (login, reconnection, concurrent session handling) with tests.
- [x] Build admin/editing endpoints that port `KYRSYSP.C` behaviors (player editor, content maintenance) with authorization. *(Admin panel now includes a grant-all-spells admin toggle that also sets max level and max spell points for spell-testing workflows.)*
- [x] Repaired read-only admin SCRY monitoring with account-admin authorization, case-insensitive active target lookup, initial room snapshots, main-console rendering, observed input lines, and playable admin console sessions that use separate admin and game tokens.
- [x] Added an admin-only item drop tool that places catalog objects into live room state, persists the room object list, and broadcasts an ASHM01-modeled appearance line plus `room_objects` refresh so connected players see the item without reconnecting. The panel now also reads live room object slots, shows hidden/mob objects for admin inspection, and can remove a selected slot with mower-modeled vanish messaging from `legacy/KYRSPEL.C`.
- [x] Preserve non-editable player flags when applying admin editor updates to mirror `KYRSYSP.C` flag handling.
- [x] Ensure LOOKER4 room broadcasts exclude the target player, mirroring legacy `sndbt2` behavior.
- [x] Updated msgutl2 room scripts (rooms 34/35/36/182) to broadcast to other occupants only, matching legacy exclusion behavior.
- [x] Infer YAML message scope from `message_id`/`broadcast_message_id` to reduce duplication in room scripts.
- [x] Centralized direct-and-others room messaging in `kyrgame.messaging` and applied it to Python + YAML room handlers so actor-excluding broadcasts stay consistent.
- [x] Preserved `msgutl2`-style actor-visible room-script effects across all active WebSocket sessions for the player, covering multi-session fan-out for self-target YAML events while honoring silent command metadata.
- [x] Persist YAML room script player mutations (levels, flags, inventory, gold, location) to the database for session continuity.
- [x] Persist ordinary movement and room object pickup/drop player mutations so fresh sessions restore location and inventory outside special room/script paths.
- [x] Captured spell bitflags from `legacy/KYRSPLS.H` in `backend/kyrgame/constants.py` for reuse in room routines.
- [x] Centralized spellbook ownership/memorization invariants in `backend/kyrgame/spellbook.py` and routed room-script spell grants/purchases through the shared service (ownership bits in `offspls/defspls/othspls`, memorized IDs in `spells`).
- [x] Updated YAML `grant_spell` actions to default to spellbook-bit grants only, with optional `memorize: true` for explicit scripted pre-memorization exceptions (legacy parity with separate grant/memorize flow).
- [x] Ported full spellbook rendering for `look spellbook`/`read spellbook` to legacy `seesbk` semantics (ordered bitfield scan, 3-column `SBOOK2` rows, `SBOOK3` empty state, and `SBOOK4` footer with title/player substitution).

- [x] Added a tick-based scheduler service to mirror MajorBBS `rtkick` intervals for spell/animation timers (`KYRSPEL.C`/`KYRANIM.C`).

- [x] Wired `bootstrap_app`/`shutdown_app` to own `TickScheduler` lifecycle (env-driven `KYRGAME_TICK_SECONDS`, timer registration, and cleanup before scheduler shutdown).
- [x] Added `RuntimeTickCoordinator` to centralize recurring timer registration (spell/animation now, future timers later) and lifecycle hooks in `bootstrap_app`/`shutdown_app`.
- [x] Aligned animation scheduler startup with `KYRANIM.C` first-delay parity (`rtkick(30)` then recurring `rtkick(15)`), persisted animation globals in DB-backed `runtime_state`, and added system telemetry audit events for animation ticks, brownie steps, and admin animation triggers.
- [x] Ported `splrtk` into a stateless `SpellTickSystem` with scheduler registration, macro reset, +2 spell-point regen cap, and ALTNAM expiry/reversion side effects (`backend/kyrgame/spells/tick_system.py`).
- [x] Persisted JSON-backed charm timer decrements from `SpellTickSystem` so ALTNAM transformations such as `weewillo` expire across database-backed ticks.
- [x] Routed live spell-tick expiry fan-out through WebSockets and synced ticked active sessions so transformation timers cannot leave stale `altnam`/`attnam` state in MudConsole clients.

- [x] Documented runtime tick-scheduler usage (`KYRGAME_TICK_SECONDS`, registration helpers, shutdown cleanup) in backend architecture/development docs for future timer ports.

- [x] Ported `learn`/`memorize` command handling to legacy `memori`/`memutl` parity (`KSPM09` ownership failures, `GAISPL`/`LOSSPL` MAXSPL messaging, `MEMSPL` room broadcast excluding caster, and persisted memorized slots).
- [x] Ported `spells` command handling to legacy `shwsutl` parity (exact memorized-list grammar, spell point + level/title status text in a single response event, and structured memorized spell metadata payloads for UI cards).
- [x] Added shared legacy rank-title handling plus public `/public/player-activity` and `/public/leaderboard` endpoints for landing-page activity, recent players, and level/spellbook leaderboard sorting.
- [x] Optimized public leaderboard ranking so the database applies the level/spellbook/player-id ordering before payload slicing, and kept out-of-game public display names on canonical Player-IDs during transformations.
- [x] Ported `cast`/`chant` command handling to legacy `caster` gating (missing spell, memorized checks, level/spell-point gates, and spell-point consumption) with broadcast parity.
- [x] Aligned targeted spell casting (bookworm/dumdum/howru/saywhat) with `chkstf` target resolution and `sndbt2`-style broadcasts.
- [x] Restored `mower` spell sender-inclusive room-facing vanish broadcasts for each destroyed `PICKUP` ground object while preserving caster `YOUCASTSPELL` and room-object refresh parity with `spl042`.
- [x] Added spellbook forgetting helpers plus effect-engine integration for `dumdum`/`saywhat` (IDs 12/50) to keep memorized spell loss centralized.
- [x] Verified `saywhat` (spl051) OBJPRO/empty-spellbook failures and msgutl3-style broadcasts with targeted cast coverage in tests.
- [x] Verified spell lookup boundaries: `cast`/`memorize` spell names remain exact-name paths (`splchk`/`fsbspl`), current-room spell targets use legacy `findgp` attention-name prefixes plus room/inventory object prefixes via `chkstf`, room 9 `buyspl` preserves its reversed `sameto(stocked_spell_name, input)` match boundary, and `peepint` is the legacy remote-room viewing path by exact global player id.
- [x] Prioritized room routine handling ahead of command registry dispatch to mirror `kyra()` flow in `KYRCMDS.C`.
- [x] Restored temple room-first handling for the exact `TEMPLE` phrase (`glory be to tashanna`) after legacy-style article stripping, so it reaches the level-3 gate before command dispatch; added legacy command-table alias audit coverage.
- [x] Ported village temple `marry`/`wed` parity with legacy `findgp`-style target lookup, `MARRYD` spouse persistence, and actor/target/bystander `MARRY0`-`MARRY8` fan-out.
- [x] Aligned GET command room broadcasts (GETLOC5/GETLOC7) and player-target exclusion with legacy `getloc()` sndoth/sndbt2 behavior.
- [x] Audited room broadcast recipient splits against legacy `msgutl2`/`sndoth`/`sndbt2`/`sndloc`, aligning Python room routines, YAML room scripts, command room events, and frontend filtering for actor-excluding, target-excluding, and sender-inclusive cases.
- [x] Restored legacy `remvgp` departure fan-out for ordinary movement and in-game `x`, including source-room walk-out/sparkling-light messages, direct `EXIKYR`, session/presence deactivation, persisted exit state, and `pgploc` re-entry after `gamloc=-1`.
- [x] Deduped trimmed room occupant presence identifiers so room `look`/entry text cannot list the same player twice with trailing-space variants.
- [x] Prevented the React console from rendering room occupants twice when explicit `room_occupants` events overlap with local room snapshot state, and centralized legacy KUTM11/KUTM12 suffix formatting across command, WebSocket, and runtime refresh paths.
- [x] Extended pickup command synonyms (get/grab/take/snatch/steal/pilfer/pickpocket) in the parser/registry to mirror legacy getter aliases.
- [x] Matched MajorBBS `sameto` prefix lookup for generic current-room/player/object targets: `get`/`grab` resolves visible player `attnam` prefixes before room objects, `look` checks room objects before inventory objects before visible players, and matching keeps legacy first-hit/no-ambiguity behavior.
- [x] Preserved transformed-player look targeting through legacy `attnam` lookup, including transformed self-look via names like `willowisp`.
- [x] Preserved duplicate room-object slots during legacy prefix pickup: `get`/`grab` removes only the matched `lcobjs` slot, matching `fgmlobj` + `tgmlobj(objno)` behavior.
- [x] Corrected upper-level `chklvl()` room parity so legacy `KYRKEY` maps to active module entitlement while the Pantheon golden key remains physical object 14 for explicit `key` routines; restored KYRA5-KYRA9 fallback replies for room-declined commands such as bare `jump`.
- [x] Audited and tightened upper-level journey room command boundaries against legacy macro behavior (`gi_bagthe`, `bagprep`, `bagwrd`, `rstrin`/`sameas`, and `hitoth`) so strict rooms no longer inherit generic normalized retry shortcuts.
- [x] Fixed room 32 bubbling spring rose pickup parity so full inventories emit `GROSE3`/`GROSE4` and successful pickups grant object 40 before `GROSE1`/`GROSE2`, matching `rosutl()` (`legacy/KYRROUS.C:742-753`).
- [x] Restored room 38 magic fountain offering parity so `drop`/`throw`/`toss <item> in fountain` consumes inventory, blessed pinecones spawn scroll object 35 in the live world every third offering, shards grant object 16 every sixth offering, and `FOUNTI` sets `BLESSD`, matching `magicf()` (`legacy/KYRROUS.C:759-819`).
- [x] Restored room 185 smooth-walled alcove key/crevice verb parity so `waller()` uses legacy `drpwrds` (`drop`/`insert`/`put`/`stick`/`thrust`) after `bagprep()` strips prepositions, matching `legacy/KYRROUS.C:109-115` and `legacy/KYRROUS.C:939-960`.
- [x] Preserved room 185 `waller()` offered-object gating so only `key` succeeds at the crevice; wrong offerings still emit `WALM01`/`WALM02`.
- [x] Added player-targeted GET parsing and getgp-style theft handling (including room/target broadcasts).
- [x] Normalize non-chat command tokenization to strip articles/prepositions per `GAMUTILS.C` (`gi_bagthe`/`bagprep`).
- [x] Preserve full whisper payloads for `whisper <target> <message...>` parsing so `whispr` receives complete `margv[2]` text (including quoted multi-word content).
- [x] Audited legacy MajorBBS `pfnlvl` profanity-filter branches and kept them separate from character level, restoring normal level-3 `say`/`whisper`/`yell` behavior.
- [x] Preserve CRLF line breaks from the legacy `.MSG` files in the message bundle fixtures for accurate display formatting.
- [x] Cataloged spell/object routines and drafted an effect engine design for parity tracking (`docs/spell_object_effect_engine_design.md`).
- [x] Surface session expiration metadata in `/auth/session` responses (repository already tracks `expires_at`); add contract tests and client handling. *(Response contract now includes `expires_at`/`expires_in_seconds`, `backend/tests/test_api_contract_gaps.py` covers create/validate/resume, and the navigator displays expiry plus a fresh-token reconnect action.)* [Tracker: `docs/legacy_command_porting.md`]
- [x] Attached live room-object snapshots to `location_description` payloads and rendered console object lines from that snapshot, preventing stale item text after pickups, drops, reconnects, and room entry refreshes.
- [x] Synced YAML room-object mutations back into the live room-object store with sender-inclusive refresh events, covering room 26 shard spawning and live setter persistence.
- [x] Added 30-day player remember-me sessions for account login/register, direct `/play` token resume, remembered-token cleanup on rejection, and a player logout action in the active-player popover.

### Complete Playable Game Parity (Completed Gameplay Lane)

- [x] Completed remaining `KYRCMDS.C` command handler parity for `kissr1`, `kissr2`, `thinkr`, `flyrou`, `shover`, and the `smparr` simple-emote table. Coverage now includes direct, target, room, nearby-room, movement, inventory/object, and failure branches with legacy message IDs and source comments. [Tracker: `docs/legacy_command_porting.md`]
- [x] Added command-registry parity coverage proving every legacy command and simple emote resolves to an implemented handler or a named tracker entry, with gameplay verbs kept out of the silent generic-stub path. [Tracker: `docs/legacy_command_porting.md`]
- [x] Verified browser-visible rendering for the gameplay command surface: help, aim/point, brief/unbrief, check/count/gold/hits, drink/swallow, give/hand/pass/toss, pray, rub, yell/shout/scream/shriek, whisper, wink, kiss/shove, fly, think, simple emotes, and documented alias paths represented in the Playwright flow. [Tracker: `docs/legacy_command_porting.md`]
- [x] Added multiplayer client integration tests that exercise direct, target, room, nearby-room, actor-excluding, and target-excluding WebSocket fan-out using seeded fixtures and real browser rendering. Follow-up coverage now includes PR 178 review fixes for shove destination entrant updates and give-overflow room object fan-out. [Tracker: `docs/legacy_command_porting.md`]
- [x] Promoted item/effect checklist coverage into automated backend and targeted Playwright scenarios for consumables, readables, weapon/aim flows, scenery restrictions, dragonstaff/Zar behavior, gemstone inline rendering, and backend/component creature rendering. [Tracker: `docs/ITEM_EFFECT_MANUAL_TESTING_CHECKLIST.md`]
- [x] Extended solo-level and late-game regression coverage to include reconnect/state persistence after late-game level-ups, physical-key independence for `chklvl()` rooms, and spellbook state checks. [Tracker: `docs/solo_level_journey_checklist.md`]

### Legacy Gameplay Support Gaps

- [x] Shared `hitoth()` death handling for all spell/self/area damage paths, including reset, room fan-out, active-session relocation, and DB persistence. *(Extended coverage to the room-script `damage` action and readable scroll damage, including ruby cache, flaming thicket, and scroll RNG parity.)*
- [x] Legacy `macros` fatigue gate from `kyrand()` case 7: increment per accepted command, emit `TIRED` on the 20th command before tick reset, with an allowlisted read-only UI refresh bypass for satellite status panels.
- [x] First-login player-ID lifecycle parity: 3-9 letters, duplicate rejection, `Sysop` plus visible entity-name reservation (`Zar`, `dragon`, `dryad`, `elf`, `brownie`), `GETALS`/`BADPID`/`NTGOOD`/`GOODPD`, ENTER-gated `INTROA`/`INTROB`/`INTROC`/`INTROD` paging, delayed room entry, initgp-style player initialization, `APPEARFLASH` first-entry broadcast, and wizard player-name UI styling.
- [x] Corrected first-login/death-reset birthstone generation to match legacy `genrdn(0,12)` exclusive-upper-bound semantics, preventing object 12 (`elixir`) from being assigned as a birthstone.
- [x] Corrected additional room-routine parity gaps in the village temple, slot machine, and demon gate: room 7 now honors legacy `putwrds` (`lay`/`place`/`put`) for tiara/charm offerings, room 186 uses `genrdn(1,11)`/`genrdn(0,12)` odds and gem-only prizes, and room 218 emits legacy `remvgp`/`entrgp` player-name fan-out on both sides of the transfer.
- [x] Preserved silver altar birthstone and brown-gem stump progress on wrong or premature offerings while still consuming valid offered inventory objects, matching `silver()`/`stumpr()` reset boundaries in `legacy/KYRROUS.C`.
- [x] Preserved the original `INTROD` version and designed/programmed-by credit block while appending the modernized porting credit block for first-login intro paging.
- [x] Frontend first-login intro rendering through the existing console/session UI, including blank ENTER advancement, typed-input consumption during intro, WASD command gating, and room description suppression until lifecycle completion.
- [x] Simulated MajorBBS-style screen-length paging for long first-login lifecycle output with `C` continue, `N` nonstop, and `Q` quit controls.
- [x] In-game `x` exit parity: emit `EXIKYR`, broadcast sparkling-light departure, deactivate session/presence, persist player state, and re-enter fresh sessions from `pgploc` when `gamloc` is negative.
- [x] Aligned village temple `chantd` with the hardcoded room state used by `temple()`, so animation ticks clear the exact offering window and altar glow text renders through `room_message` instead of the raw event label.
- [ ] Frontend rendering for remaining exit lifecycle messages through the existing console/session UI.

### Release/Ops Cleanup (Final Porting Lane)

- [ ] Provide Docker Compose, Makefile targets, CI wiring, and package-content automation after gameplay parity is complete. *(In progress: added `backend/Dockerfile` with uvicorn startup, runtime env defaults, and default `/data` directory creation for SQLite deployments; added root `compose.yaml`, `.env.docker.example`, `.dockerignore`, Makefile targets, a Cloudflare tunnel profile using the frontend network namespace plus Vite proxying for backend paths, service restart policies for alpha testing, `docs/ALPHA_TESTING_RUNBOOK.md`, and file-contract tests for the dev stack. Remaining: CI wiring, package-content CI job, and full compose-up smoke.)* Acceptance criteria: `docker compose up` brings up API + DB + seed path, `make up/test/seed/package-content` are documented and runnable in CI, and CI executes backend pytest + packaging smoke checks.

## Remaining Implementation Task Plan

1. **Legacy gameplay support gaps**
   - Next meaty gameplay target: focused frontend pass for remaining exit message surfaces now that the backend `x` path has landed.
2. **Documentation and tracker closure**
   - Keep `docs/PORTING_PLAN.md`, `docs/legacy_command_porting.md`, `docs/PORTING_PLAN_world_object_spell_gaps.md`, and `docs/solo_level_journey_checklist.md` aligned after each gameplay PR.
   - For every ported gameplay routine, include legacy source references and verify both C call sites and message catalog IDs.

## Architectural Direction
- **Data contracts:** Mirror the structs in `legacy/KYRANDIA.H` as ORM/Pydantic models (player, location, objects, spells, commands) to maintain limits and flags when validating client input and persisting state.
- **Service boundaries:** Align services with legacy modules: command dispatcher (from `KYRCMDS.C`), world/location service (from `KYRLOCS.C`), object catalog/effects (from `KYROBJS.C`), spell/combat engine (from `KYRSPEL.C`), timers/animations (from `KYRANIM.C`), and admin tooling (from `KYRSYSP.C`).
- **Content pipeline:** Extract message catalogs and location/object tables into JSON fixtures so the backend can deliver localized text to the client and seed databases.
- **Transport:** Use WebSockets for real-time room broadcasts and HTTP for setup/admin flows, with server-side authorization enforcing level/flag checks.

## Environment & Tooling Baseline
- **Backend:** Python 3.11+, FastAPI (or similar) for HTTP + WebSocket endpoints, SQLAlchemy for persistence, Alembic for migrations, pytest for TDD, and pydantic models for validation.
- **Frontend:** TypeScript + React (or Svelte) with state synced via WebSockets; Vite for dev/build; Vitest/Cypress for TDD.
- **Runtime:** Docker-compose for API, DB (PostgreSQL), and front-end assets, runnable under WSL2. Include a `Makefile` to wrap common tasks (`make test`, `make up`, `make seed`).

## Active Completion Phases (3HTDD)
1. **Goal: full command surface parity**
   - Goal tests prove each remaining handler family works through the command boundary with legacy message IDs and recipient splits.
   - Steer tests cover the next rule: target lookup, inventory/object lookup, transformation movement, shove movement, or simple-emote speak fallback.
   - Unit tests cover only parser/formatting details such as articles, prepositions, spouse/pronoun text, and amulet telepathy arguments.
2. **Goal: browser-visible multiplayer parity**
   - Goal tests drive at least two browser sessions through room, target, nearby, and actor-excluding output.
   - Steer tests prove the client renders each WebSocket envelope shape used by ported commands.
   - Unit tests stay at component/message-normalization boundaries when rendering defects are local.
3. **Goal: late-game confidence**
   - Goal tests prove solo level 1-25 remains intact and late-game reconnect restores level, room, inventory, and spellbook state.
   - Steer tests promote the manual item/effect scenarios into executable checks.
   - Unit tests protect effect helpers where broad examples would hide parsing or inventory edge cases.
4. **Goal: release workflow**
   - This phase stays last: Docker Compose, Makefile targets, CI, package-content smoke checks, and release-facing documentation.

## Cross-Cutting TDD Strategy
- Start each subsystem with failing unit tests derived from legacy behaviors (counts, flags, level gates) before implementation.
- Favor fixture-driven tests that compare modern outputs to legacy message IDs/structures so refactors stay grounded in original data.
- Keep Goal tests focused on player-visible outcomes, Steer tests focused on the next meaningful rule, and Unit tests focused on narrow parser/effect mechanics.

## Completion Deliverables Checklist
- Remaining command families have real parity handlers or deliberate tracker entries.
- Already-ported commands have browser-visible verification where the tracker requires it.
- Multiplayer fan-out is covered at backend and browser boundaries.
- Manual item/effect checks have automated coverage or recorded follow-up gaps.
- Release/Ops cleanup provides Docker Compose, Makefile targets, CI, and package-content smoke checks after gameplay parity closes.

## Current Backend Capabilities (for UI planning)
- **Fixture delivery:** HTTP endpoints expose commands, locations, objects, spells, and localized message bundles seeded from JSON fixtures, with an admin summary route for quick sanity checks.
- **Session + auth stubs:** `/auth/session` issues bearer tokens, optionally targeting a starting room; admin roles/flags are represented via bearer tokens for tooling endpoints.
- **Room transport:** WebSocket gateway delivers welcome payloads, room broadcast events, and command responses; PresenceService tracks occupants per room and re-scopes subscriptions when players move.
- **Command dispatch bridge:** Parsed `chat` and `move` commands execute through the dispatcher, emit broadcast payloads, and enforce basic rate limiting for spam.
- **Repositories/migrations:** SQLAlchemy models and fixture-backed repositories exist alongside Alembic scaffolding, though persistence is still in-memory for tests.
- **Admin endpoints:** Provide secured CRUD for player records and content, reflecting `KYRSYSP.C` behaviors. Tests cover authorization and validation, and a PATCH flow clamps level-derived HP/SP, gold caps, and spouse updates for tooling parity. Admin tokens now come from environment configuration (auto-loaded from `backend/.env`, or override with `KYRGAME_ENV_FILE`; see `backend/.env.example` and `backend/ADMINISTRATION.md`).

## Next Steps: Legacy Gameplay Support
1. **Frontend lifecycle surfaces**
   - Verify exit messages render cleanly through the existing console/session UI and cover any remaining disconnect prompts.
