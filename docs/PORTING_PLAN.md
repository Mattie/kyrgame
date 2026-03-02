# Porting Plan: Kyrandia to JS Frontend + Python Backend

## Goals
- Deliver a modern multiplayer web experience with a JS front-end and Python back-end while preserving gameplay behaviors documented in the legacy C code.
- Keep the C data structures as authoritative schemas when designing persistence and APIs to ensure compatibility with assets and rules.
- Build the new stack so it can run locally via Docker/WSL2 with repeatable tests and fixtures.
- Keep the original MajorBBS sources organized in `legacy/` so they remain easy to reference as we extract content and parity requirements.

## Porting Checklist

- [x] Captured legacy constants (sizes, limits, flags) from `legacy/KYRANDIA.H` in `backend/kyrgame/constants.py` to anchor model validation.
- [x] Defined initial Pydantic + SQLAlchemy models for spells, objects, locations, and a partial player record mirroring the legacy structs.
- [x] Generated JSON fixtures for commands, locations, objects, spells, and localized message bundles with validation tests.
- [x] Added loader utilities to seed a database session from fixtures and a script to package offline content (`backend/kyrgame/scripts/package_content.py`).
- [x] Stood up a FastAPI skeleton with fixture-backed HTTP endpoints, a room WebSocket gateway, simple presence tracking, rate limiting, and a stub room script engine (e.g., the willow routine).
- [x] Expand player modeling to cover the full legacy state (timers, spell slots, inventories, gems) with validation and serialization parity to `gmplyr`.
- [x] Validated gmplyr player field ranges (charm timers, gem/stump indices, macro cap, spell IDs) across models + fixtures.
- [x] Persist player sessions and runtime state in a real database (PostgreSQL) with migrations, replacing the current in-memory SQLite bootstrap.
- [x] Flesh out the command dispatcher to mirror `KYRCMDS.C` (movement, speech variants, inventory, combat, system commands) with authoritative state changes and permission checks. *(Updated give-recipient messaging to include the legacy `gmsgutl` actor prefix before `GIVERU10` text so UI renders the giver identity.)*
- [x] Persist both giver and recipient state for `give` gold/item transfers so DB-backed sessions cannot duplicate resources after reconnect.
- [x] Port look/examine/see (looker) command handling with tests to mirror legacy room/object/player inspection.
- [x] Align looker player descriptions with FEMALE flag (FDES vs MDES) for parity with `KYRANDIA.C`/`KYRSYSP.C`.
- [x] Ensure WebSocket sessions hydrate player identity fields (altnam/attnam) from persisted records for looker messaging.
- [x] Match LOOK player targeting and level-driven appearance updates to legacy `findgp`/`glvutl`/`kyraedit` behavior.
- [x] Added structured room spoiler metadata (legacy routines + YAML scripts) and a spoiler command for runtime parity guidance.
- [ ] Recreate world/object/spell services that reflect `KYRLOCS.C`, `KYROBJS.C`, `KYRSPEL.C`, and `KYRANIM.C`, including timers, room routines, and object/spell effects. *(In progress: added temple/fountain/spring/heart-and-soul/waterfall/Tashanna/reflection-pool/pantheon/portal/waller/slot-machine/misty-ruins/sandman/tulips/singer/forgtr/oflove/believ/philos/truthy/bodyma/mindma room routines plus object/spell effect engines with cooldowns, transformations, costs, and sap spell points support for sapspel/takethat. Track remaining gaps with the checkboxes in `docs/PORTING_PLAN_world_object_spell_gaps.md`—mark entries complete there as they’re implemented and only check off this line item once that appendix is fully completed.)*
- [x] Port remaining room routines (rooms 288/291/293/295/302) via YAML scripts in `backend/fixtures/room_scripts/` unless YAML is insufficient; reuse established patterns and include legacy source line comments as required.
- [x] Added `AnimationTickSystem` with coordinator-owned routine index rotation, timed one-shot flags (`sesame`/`chantd`/`rockpr`), and multiplayer-ready persistence hooks to mirror `KYRANIM.C` animation cadence semantics.
- [x] Bridged animation one-shot flags from room runtime state into scheduled animation broadcasts so legacy fade/reset messages (e.g., WALM05) trigger and clear like `KYRANIM.C` globals.
- [x] Implement authentication/session lifecycle matching `kyloin`/`kyrand` semantics (login, reconnection, concurrent session handling) with tests.
- [x] Build admin/editing endpoints that port `KYRSYSP.C` behaviors (player editor, content maintenance) with authorization. *(Admin panel now includes a grant-all-spells toggle for testing spellbook ownership updates.)*
- [x] Preserve non-editable player flags when applying admin editor updates to mirror `KYRSYSP.C` flag handling.
- [x] Ensure LOOKER4 room broadcasts exclude the target player, mirroring legacy `sndbt2` behavior.
- [x] Updated msgutl2 room scripts (rooms 34/35/36/182) to broadcast to other occupants only, matching legacy exclusion behavior.
- [x] Infer YAML message scope from `message_id`/`broadcast_message_id` to reduce duplication in room scripts.
- [x] Centralized direct-and-others room messaging in `kyrgame.messaging` and applied it to Python + YAML room handlers so actor-excluding broadcasts stay consistent.
- [x] Persist YAML room script player mutations (levels, flags, inventory, gold, location) to the database for session continuity.
- [x] Captured spell bitflags from `legacy/KYRSPLS.H` in `backend/kyrgame/constants.py` for reuse in room routines.
- [x] Centralized spellbook ownership/memorization invariants in `backend/kyrgame/spellbook.py` and routed room-script spell grants/purchases through the shared service (ownership bits in `offspls/defspls/othspls`, memorized IDs in `spells`).
- [x] Updated YAML `grant_spell` actions to default to spellbook-bit grants only, with optional `memorize: true` for explicit scripted pre-memorization exceptions (legacy parity with separate grant/memorize flow).
- [x] Ported full spellbook rendering for `look spellbook`/`read spellbook` to legacy `seesbk` semantics (ordered bitfield scan, 3-column `SBOOK2` rows, `SBOOK3` empty state, and `SBOOK4` footer with title/player substitution).

- [x] Added a tick-based scheduler service to mirror MajorBBS `rtkick` intervals for spell/animation timers (`KYRSPEL.C`/`KYRANIM.C`).

- [x] Wired `bootstrap_app`/`shutdown_app` to own `TickScheduler` lifecycle (env-driven `KYRGAME_TICK_SECONDS`, timer registration, and cleanup before scheduler shutdown).
- [x] Added `RuntimeTickCoordinator` to centralize recurring timer registration (spell/animation now, future timers later) and lifecycle hooks in `bootstrap_app`/`shutdown_app`.
- [x] Ported `splrtk` into a stateless `SpellTickSystem` with scheduler registration, macro reset, +2 spell-point regen cap, and ALTNAM expiry/reversion side effects (`backend/kyrgame/spells/tick_system.py`).

- [x] Documented runtime tick-scheduler usage (`KYRGAME_TICK_SECONDS`, registration helpers, shutdown cleanup) in backend architecture/development docs for future timer ports.

- [x] Ported `learn`/`memorize` command handling to legacy `memori`/`memutl` parity (`KSPM09` ownership failures, `GAISPL`/`LOSSPL` MAXSPL messaging, `MEMSPL` room broadcast excluding caster, and persisted memorized slots).
- [x] Ported `spells` command handling to legacy `shwsutl` parity (exact memorized-list grammar, spell point + level/title status text in a single response event, and structured memorized spell metadata payloads for UI cards).
- [x] Ported `cast`/`chant` command handling to legacy `caster` gating (missing spell, memorized checks, level/spell-point gates, and spell-point consumption) with broadcast parity.
- [x] Aligned targeted spell casting (bookworm/dumdum/howru/saywhat) with `chkstf` target resolution and `sndbt2`-style broadcasts.
- [x] Added spellbook forgetting helpers plus effect-engine integration for `dumdum`/`saywhat` (IDs 12/50) to keep memorized spell loss centralized.
- [x] Verified `saywhat` (spl051) OBJPRO/empty-spellbook failures and msgutl3-style broadcasts with targeted cast coverage in tests.
- [x] Prioritized room routine handling ahead of command registry dispatch to mirror `kyra()` flow in `KYRCMDS.C`.
- [x] Aligned GET command room broadcasts (GETLOC5/GETLOC7) and player-target exclusion with legacy `getloc()` sndoth/sndbt2 behavior.
- [x] Extended pickup command synonyms (get/grab/take/snatch/steal/pilfer/pickpocket) in the parser/registry to mirror legacy getter aliases.
- [x] Added player-targeted GET parsing and getgp-style theft handling (including room/target broadcasts).
- [x] Normalize non-chat command tokenization to strip articles/prepositions per `GAMUTILS.C` (`gi_bagthe`/`bagprep`).
- [x] Preserve full whisper payloads for `whisper <target> <message...>` parsing so `whispr` receives complete `margv[2]` text (including quoted multi-word content).
- [x] Preserve CRLF line breaks from the legacy `.MSG` files in the message bundle fixtures for accurate display formatting.
- [x] Cataloged spell/object routines and drafted an effect engine design for parity tracking (`docs/spell_object_effect_engine_design.md`).
- [ ] Provide Docker Compose, Makefile targets, and CI wiring to exercise API, WebSocket, and packaging flows in WSL2-friendly environments. *(Acceptance criteria: `docker compose up` brings up API + DB + seed path, `make up/test/seed/package-content` are documented and runnable in CI, and CI executes backend pytest + packaging smoke checks.)* [Tracker: command + client integration parity in `docs/legacy_command_porting.md`; world/object/spell parity dependencies in `docs/PORTING_PLAN_world_object_spell_gaps.md`]
- [ ] Add integration/e2e tests that couple the JS client, WebSocket transport, and backend services against seeded fixtures. *(Acceptance criteria: an automated suite launches frontend + backend together, validates `/auth/session` -> WS join -> command/broadcast rendering loop, and runs in CI.)* [Tracker: `docs/legacy_command_porting.md`]
- [ ] Surface session expiration metadata in `/auth/session` responses (repository already tracks `expires_at`); add contract tests and client handling. *(Acceptance criteria: response contract includes expiry metadata, `backend/tests/test_app_contracts.py` asserts presence/shape, and the navigator handles expiry/reconnect states.)* [Tracker: `docs/legacy_command_porting.md`]

## Remaining Implementation Task Plan

1. **Complete player/domain modeling**
   - Translate every `gmplyr` field (timers, charms, macros, marital status, gem layout, memorized spells) into validated Pydantic/ORM models.
   - Normalize bitflag handling (player/object/spell flags) into enums/helpers and add fixtures or factories that respect the legacy limits.
   - Extend loader and fixture validation tests to catch parity gaps versus `KYRANDIA.H` constants.
2. **Persistence + migrations**
   - Introduce PostgreSQL-backed storage with SQLAlchemy session configuration for pooled connections and Alembic migrations that mirror the domain models.
   - Replace the in-memory bootstrap in `runtime.py` with environment-driven configuration (database URL, migration runner) and seed paths that can run in Docker/CI.
   - Add repository/service layers that separate persistence (player inventory, spell timers, room occupants) from request handling.
3. **Command dispatcher parity**
   - Expand `commands.py` to cover the full verb set from `KYRCMDS.C` (movement variants, speech, trading, object interactions, spell casting, system commands) and encode level/flag/condition checks.
   - Wire dispatcher results into the WebSocket gateway so server-side state updates drive broadcasts (movement, chat, combat outcomes) and error semantics mirror legacy text.
   - Create fixture-driven tests that assert behavior against known message IDs and location/object relationships.
   - Added long-form room entry descriptions and initial inventory pickup/drop handling aligned to `getter`/`dropit` in `KYRCMDS.C`.
4. **World, object, and spell services**
   - Port room routine behaviors from `KYRLOCS.C`/`KYRROUS.C` into `RoomScriptEngine`, preserving timers and entry/exit triggers; cover with scheduler-driven tests. (Progress: added YAML-driven routines for rooms 8, 9, 10, 12, 14, and 16.)
   - Ported the remaining room routines (rooms 288/291/293/295/302) via YAML scripts in `backend/fixtures/room_scripts/`, reusing established patterns and adding legacy source file + line comments for reviewer parity checks.
   - Model object effects and spell routines from `KYROBJS.C`/`KYRSPEL.C`/`KYRANIM.C`, including cooldowns, resource costs, and targeting rules, with unit + integration coverage.
   - Use `backend/kyrgame/timing/TickScheduler` to register recurring spell/effect/mob timers (e.g., `register_spell_tick`, `register_animation_tick`, or `register_recurring_timer`) and wire them into runtime services as those handlers are ported.
   - Captured Tashanna's heart-and-soul ritual (room 101) and the willowisp/pegasus transformation spells; flesh out remaining spellbook and room routines with legacy gating (inventory limits, level costs) and persistence hooks.
   - Expose APIs for content lookups (descriptions, auxiliary text) that reference the legacy message catalogs.
5. **Auth/session lifecycle**
   - Implement login/session establishment matching `kyloin` expectations (logo display, first-time character creation), session tokens, and reconnection handling.
   - Track active sessions in persistence + presence service, enforcing single-session or multi-session policies from the original module.
   - Add tests for session recovery, concurrent logins, and logout flows.
6. **Admin/editor tooling**
   - Add secured HTTP endpoints (and CLI scripts if needed) for player management, content edits, and message bundle updates reflecting `KYRSYSP.C` behaviors.
   - Cover authorization policies and validation with tests and update documentation for operator workflows.
   - [x] Extend admin player editor to adjust inventory slots, gem/stump progression, and birthstones with catalog validation to mirror kyraedit flows.
7. **Ops, packaging, and CI**
   - Deliver Docker Compose with API, Postgres, and seed jobs; create Makefile targets for `make up`, `make test`, `make seed`, and `make package-content`.
   - Configure CI (lint, type check, unit/integration tests) and artifact generation for offline bundles.
   - Document local development steps in `backend/DEVELOPMENT.md` or README updates.
8. **Integration + client alignment**
   - Build end-to-end tests that drive the FastAPI/WebSocket stack with multiple simulated players and assert broadcast rules.
   - Define the contract for the JS client (event schema, error payloads) and ensure fixtures + APIs expose the localized message catalog needed for UI parity.

## Architectural Direction
- **Data contracts:** Mirror the structs in `legacy/KYRANDIA.H` as ORM/Pydantic models (player, location, objects, spells, commands) to maintain limits and flags when validating client input and persisting state.
- **Service boundaries:** Align services with legacy modules: command dispatcher (from `KYRCMDS.C`), world/location service (from `KYRLOCS.C`), object catalog/effects (from `KYROBJS.C`), spell/combat engine (from `KYRSPEL.C`), timers/animations (from `KYRANIM.C`), and admin tooling (from `KYRSYSP.C`).
- **Content pipeline:** Extract message catalogs and location/object tables into JSON fixtures so the backend can deliver localized text to the client and seed databases.
- **Transport:** Use WebSockets for real-time room broadcasts and HTTP for setup/admin flows, with server-side authorization enforcing level/flag checks.

## Environment & Tooling Baseline
- **Backend:** Python 3.11+, FastAPI (or similar) for HTTP + WebSocket endpoints, SQLAlchemy for persistence, Alembic for migrations, pytest for TDD, and pydantic models for validation.
- **Frontend:** TypeScript + React (or Svelte) with state synced via WebSockets; Vite for dev/build; Vitest/Cypress for TDD.
- **Runtime:** Docker-compose for API, DB (PostgreSQL), and front-end assets, runnable under WSL2. Include a `Makefile` to wrap common tasks (`make test`, `make up`, `make seed`).

## Phase 1: Domain Modeling & Fixtures (TDD)
1. **Schema extraction:** Convert `legacy/KYRANDIA.H` structs into Python domain models and matching DB schemas (players, locations, objects, spells, commands). Use unit tests to assert field constraints (e.g., max slots, flag masks).
2. **Fixture generation:** Serialize content from `KYRLOCS.C`, `KYROBJS.C`, and spell tables into JSON fixtures. Add tests to validate fixture completeness (counts match `NGLOCS`, `NGOBJS`, `NGSPLS`) and referential integrity.
3. **Content loader:** Implement a loader that seeds the database from fixtures; test idempotency and error handling for missing fields.
4. **Docker baseline:** Add docker-compose with API + Postgres; include a healthcheck and smoke test (`pytest -m smoke`) to confirm the stack starts and schemas migrate in WSL2.

## Phase 2: Backend Gameplay Services (TDD)
1. **Command dispatcher service:** Model `KYRCMDS.C` behavior as typed commands (move, chat, inventory). TDD: start with command parsing tests, then handler behavior tests that mutate in-memory world state.
2. **World service:** Implement room navigation using exits from location fixtures, with tests covering movement, invalid exits, and room entry triggers (mirroring `lcrous`).
3. **Object service:** Port item metadata and behaviors; unit tests for pickup/drop rules, stack limits, and special interactions.
4. **Spell/combat service:** Recreate spell flag gating and timers (from `KYRSPEL.C`/`KYRANIM.C`), with tests for level requirements, cooldowns, and concurrent effects.
5. **Persistence layer:** Implement player load/save and session state caching, replacing `elwkyr.dat` semantics. TDD with repository tests and transactional rollbacks.
6. **Admin endpoints:** Provide secured CRUD for player records and content, reflecting `KYRSYSP.C`. Tests cover authorization and validation.

## Phase 3: Realtime Transport & Messaging (TDD)
1. **WebSocket gateway:** Add room-level channels that broadcast events (movement, chat, spell effects) following patterns in `KYRUTIL.C`/`KYRANDIA.C`. Integration tests simulate multiple clients and assert fan-out/broadcast rules.
2. **Message catalog delivery:** API for fetching message strings keyed by legacy IDs, seeded from catalogs. Tests ensure correct localization and fallback behavior.
3. **Session lifecycle:** Implement login/logout hooks mirroring `kyloin` flow, issuing auth tokens and loading character state. Tests cover reconnection and concurrent logins.

## Phase 4: Frontend Client (TDD)
1. **Command UI:** Build a command input bar with autocomplete for verbs/targets; unit tests for parser logic and integration tests for round-tripping commands over WebSockets.
2. **Room view:** Render location descriptions, exits, and occupants from server events. Snapshot tests ensure text rendering fidelity to fixtures; integration tests assert updates on movement broadcasts.
3. **Inventory/spellbook panels:** Display objects and spells with actions gated by level/flags. Tests enforce UI state rules and disabled states.
4. **Combat/effects HUD:** Show timers and status effects synced from server events; tests validate timer updates and expiration handling.

## Phase 5: Ops & DX
1. **CI pipeline:** Add lint/format/test stages for both stacks (ruff/pytest; eslint/prettier/vitest). Configure Docker build cache layers and WSL2-friendly volume mounts.
2. **Dev ergonomics:** Provide `make dev` to start hot-reload back-end and front-end with seeded data; document setup in README.
3. **Observability:** Add structured logging and basic metrics (request counts, WS connections); tests verify logging format and sampling.

## Cross-Cutting TDD Strategy
- Start each subsystem with failing unit tests derived from legacy behaviors (counts, flags, level gates) before implementation.
- Favor fixture-driven tests that compare modern outputs to legacy message IDs/structures so refactors stay grounded in original data.
- Include integration tests that spin up Docker services locally (via `make test-e2e`) to validate API/WebSocket flows in WSL2.

## Early Deliverables Checklist
- Docker Compose stack runs (`make up`) and seeds DB from fixtures.
- Core domain models with tests passing for constraints and fixture integrity.
- Command dispatcher and world navigation available via WebSocket API with integration tests for movement and chat.
- Basic React UI showing room description and handling command input in dev mode.

## Current Backend Capabilities (for UI planning)
- **Fixture delivery:** HTTP endpoints expose commands, locations, objects, spells, and localized message bundles seeded from JSON fixtures, with an admin summary route for quick sanity checks.
- **Session + auth stubs:** `/auth/session` issues bearer tokens, optionally targeting a starting room; admin roles/flags are represented via bearer tokens for tooling endpoints.
- **Room transport:** WebSocket gateway delivers welcome payloads, room broadcast events, and command responses; PresenceService tracks occupants per room and re-scopes subscriptions when players move.
- **Command dispatch bridge:** Parsed `chat` and `move` commands execute through the dispatcher, emit broadcast payloads, and enforce basic rate limiting for spam.
- **Repositories/migrations:** SQLAlchemy models and fixture-backed repositories exist alongside Alembic scaffolding, though persistence is still in-memory for tests.
- **Admin endpoints:** Provide secured CRUD for player records and content, reflecting `KYRSYSP.C` behaviors. Tests cover authorization and validation, and a PATCH flow clamps level-derived HP/SP, gold caps, and spouse updates for tooling parity. Admin tokens now come from environment configuration (auto-loaded from `backend/.env`, or override with `KYRGAME_ENV_FILE`; see `backend/.env.example` and `backend/ADMINISTRATION.md`).

## Next Steps: View-Only Developer Navigator UI
1. **Lock in client contracts**
   - _Last verified against code on 2026-03-01 (`backend/kyrgame/webapp.py`, `backend/tests/test_app_contracts.py`)._
   - [x] Document the minimal payloads the UI will consume: session creation shape, location listing (IDs, exits, descriptions), object catalog, and room broadcast envelope (`room_broadcast`, `command_response`). [Tracker: `docs/legacy_command_porting.md`]
   - [x] Add an `/auth/session` convenience option for specifying a starting room to simplify navigating fixtures without gameplay gates. [Tracker: `docs/legacy_command_porting.md`]
   - [ ] Capture token lifetime/refresh requirements (currently missing from HTTP responses even though the repository stores `expires_at`). *(Acceptance criteria: define token TTL + refresh policy in docs, return TTL metadata from `/auth/session`, and cover the contract in `backend/tests/test_app_contracts.py`.)* [Tracker: `docs/legacy_command_porting.md`]
2. **Bootstrap the front-end workspace**
   - _Last verified against code on 2026-03-01 (`backend/kyrgame/webapp.py`, `backend/tests/test_app_contracts.py`)._
   - [x] Scaffold a Vite + React + TypeScript app (or reuse existing tooling if added later) under `frontend/` with lint/test hooks aligned to repository standards. [Tracker: `docs/legacy_command_porting.md`]
   - [x] Wire shared configuration for API base URL and WebSocket endpoint (token injection to follow). [Tracker: `docs/legacy_command_porting.md`]
   - [x] Enable CORS defaults for the navigator dev origin (`localhost:5173`) with an environment override knob (`KYRGAME_CORS_ORIGINS`). [Tracker: `docs/legacy_command_porting.md`]
3. **Implement a "view-only" navigator flow**
   - _Last verified against code on 2026-03-01 (`backend/kyrgame/webapp.py`, `backend/tests/test_app_contracts.py`, and world parity tracker status in `docs/PORTING_PLAN_world_object_spell_gaps.md`)._
   - [ ] Simple session form that requests a token for a chosen player ID and optional room ID; persist token in memory for the session. [Tracker: `docs/legacy_command_porting.md`]
   - [ ] Fetch world data on load (`/world/locations`, `/objects`, `/commands`, `/i18n/<locale>/messages`) and cache in state for rendering labels/tooltips. [Tracker: `docs/legacy_command_porting.md`]
   - [ ] Connect to `/ws/rooms/{room_id}?token=...` and render the welcome payload plus ongoing `room_broadcast` events in an activity log. [Tracker: `docs/legacy_command_porting.md`]
   - [ ] Present a room panel showing description, exits, ground objects, and current occupants; add an exit list that dispatches `move` commands over WebSocket to change rooms. [Tracker: `docs/legacy_command_porting.md`]
4. **Developer ergonomics for exploration**
   - _Last verified against code on 2026-03-01 (`backend/kyrgame/webapp.py`, `backend/tests/test_app_contracts.py`)._
   - [ ] Add a lightweight world map/index view listing all locations with search/filter so developers can jump directly to a room via session reset. [Tracker: `docs/legacy_command_porting.md`]
   - [ ] Include debug toggles to show raw event JSON and command IDs to aid future parity work. [Tracker: `docs/legacy_command_porting.md`]
   - [ ] Provide graceful fallbacks when the WebSocket closes (e.g., token expired) and a reconnect button to resume the navigator session. *(Acceptance criteria: navigator displays explicit expired/closed state and supports user-triggered reconnect using a fresh valid token.)* [Tracker: `docs/legacy_command_porting.md`]
5. **Testing + docs**
   - _Last verified against code on 2026-03-01 (`backend/kyrgame/webapp.py`, `backend/tests/test_app_contracts.py`, and world parity tracker status in `docs/PORTING_PLAN_world_object_spell_gaps.md`)._
   - [ ] Add Vitest unit tests for parsing room data and rendering components; include a Cypress/Vitest integration that spins up the FastAPI test app and confirms room joins/moves render correctly. *(Acceptance criteria: unit tests cover room payload parsing + UI rendering branches, and integration coverage asserts end-to-end room join/move updates.)* [Tracker: command/client behavior in `docs/legacy_command_porting.md`; world/object/spell dependencies in `docs/PORTING_PLAN_world_object_spell_gaps.md`]
   - [ ] Update README/back-end docs with steps for launching the navigator UI alongside the API for local exploration. [Tracker: `docs/legacy_command_porting.md`]
