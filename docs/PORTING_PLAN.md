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
- [x] Persist player sessions and runtime state in a real database (PostgreSQL) with migrations, replacing the current in-memory SQLite bootstrap.
- [x] Flesh out the command dispatcher to mirror `KYRCMDS.C` (movement, speech variants, inventory, combat, system commands) with authoritative state changes and permission checks.
- [ ] Recreate world/object/spell services that reflect `KYRLOCS.C`, `KYROBJS.C`, `KYRSPEL.C`, and `KYRANIM.C`, including timers, room routines, and object/spell effects.
- [ ] Implement authentication/session lifecycle matching `kyloin`/`kyrand` semantics (login, reconnection, concurrent session handling) with tests.
- [ ] Build admin/editing endpoints that port `KYRSYSP.C` behaviors (player editor, content maintenance) with authorization.
- [ ] Provide Docker Compose, Makefile targets, and CI wiring to exercise API, WebSocket, and packaging flows in WSL2-friendly environments.
- [ ] Add integration/e2e tests that couple the JS client, WebSocket transport, and backend services against seeded fixtures.

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
4. **World, object, and spell services**
   - Port room routine behaviors from `KYRLOCS.C`/`KYRROUS.C` into `RoomScriptEngine`, preserving timers and entry/exit triggers; cover with scheduler-driven tests.
   - Model object effects and spell routines from `KYROBJS.C`/`KYRSPEL.C`/`KYRANIM.C`, including cooldowns, resource costs, and targeting rules, with unit + integration coverage.
   - Expose APIs for content lookups (descriptions, auxiliary text) that reference the legacy message catalogs.
5. **Auth/session lifecycle**
   - Implement login/session establishment matching `kyloin` expectations (logo display, first-time character creation), session tokens, and reconnection handling.
   - Track active sessions in persistence + presence service, enforcing single-session or multi-session policies from the original module.
   - Add tests for session recovery, concurrent logins, and logout flows.
6. **Admin/editor tooling**
   - Add secured HTTP endpoints (and CLI scripts if needed) for player management, content edits, and message bundle updates reflecting `KYRSYSP.C` behaviors.
   - Cover authorization policies and validation with tests and update documentation for operator workflows.
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
