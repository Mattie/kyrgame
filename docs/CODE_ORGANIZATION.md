# Code Organization for Kyrandia

This document summarizes how the legacy MajorBBS/Worldgroup Kyrandia module is laid out so it can be ported to a modern JavaScript front-end with a Python backend. Use it as a map of the current code when planning API boundaries, data models, and gameplay flows.

## Top-Level Structure
- **Core entry point:** `KYRANDIA.C` registers the module with the BBS host, opens message/data files, initializes global arrays, and wires the main input handler (`kyrand`). It also defines global pointers for players, locations, and message files, plus the module descriptor used by the hosting system. 【F:KYRANDIA.C†L51-L164】
- **Shared definitions:** `KYRANDIA.H` declares the primary gameplay structs (players, locations, spells), constants for limits (max spells, objects, charms), and helper function prototypes used across the codebase. These definitions are the best starting point for mapping data models to new services. 【F:KYRANDIA.H†L111-L170】
- **Utility helpers:** `KYRUTIL.C` provides low-level helpers for pronoun handling, visibility checks, and broadcasting room text to other players, all of which assume a multiplayer synchronous environment. These routines hint at the message patterns that need to be re-created over websockets/HTTP. 【F:KYRUTIL.C†L5-L80】
- **Command processing:** `KYRCMDS.C` contains the command table and dispatcher that interpret user text (movement, chat, actions). Porting will require replacing this interpreter with front-end input parsing and backend command routing. 【F:KYRCMDS.C†L5-L35】
- **Game content tables:**
  - `KYROBJS.C` defines the object catalog (names, properties) used throughout gameplay. 【F:KYROBJS.C†L5-L35】
  - `KYRSPEL.C` (not shown here) mirrors this pattern for spells/prayers. 
  - `KYRLOCS.C` maps world locations to long descriptions and per-room handlers via the `lcrous` array. 【F:KYRLOCS.C†L5-L29】
- **Other behavior modules:** Files like `KYRANIM.C`, `KYRPROT.C`, `KYRROUS.C`, and `KYROBJR.C` encapsulate specialized logic (animation sequences, protections, room routines, object reactions). They plug into the shared data structures from `KYRANDIA.H`.

## Data Model Highlights
- **Players (`struct gmplyr`):** Tracks identity, alias, carried objects, stats (level, hit points, spell points), charm timers, memorized spells, location, and financial state. This struct can be translated directly into backend models and session state. 【F:KYRANDIA.H†L120-L148】
- **Locations (`struct gamloc`):** Each room stores a brief description, objects present, and directional links. The `lcrous` table pairs location IDs with handler routines for scripted behavior. 【F:KYRANDIA.H†L153-L170】
- **Spells (`struct spell`):** Spell definitions bind an invocation string to a handler function pointer, required level, and bitflag categorization; these can become backend actions with permission checks. 【F:KYRANDIA.H†L111-L118】

## Runtime Flow (Legacy)
1. **Initialization:** `init__elwkyr` opens message catalogs/data files (`elwkyrl/rs/mmcv`, `elwkyr.dat`), allocates player and location arrays, seeds utilities/animations, and registers the module with the host. This sequence identifies which assets/configuration must be available when bootstrapping the new services. 【F:KYRANDIA.C†L138-L164】
2. **Logon & state load:** `kyloin` runs on user login to show the logo and ensure a data block exists for the player; in the port, this corresponds to authenticating a user and loading/saving their character record. 【F:KYRANDIA.C†L166-L176】
3. **Command loop:** `kyrand` (main input handler) processes user input, routes to command handlers (`KYRCMDS.C`), and updates game state. A modern backend would expose these as REST/websocket endpoints, while the front-end would render responses and room broadcasts. (Handler implementation resides throughout `KYRCMDS.C`.)
4. **Room/animation hooks:** Location-specific logic is invoked via the `lcrous` table, while animations and timed effects are dispatched from modules like `KYRANIM.C`. These hooks will need event-driven equivalents in the new architecture.

## Porting Considerations
- **State persistence:** Player state is currently stored with `dfaOpen` and binary blocks (`elwkyr.dat`). Replace with database-backed persistence and design DTOs that mirror `struct gmplyr` while remaining transport-friendly. 【F:KYRANDIA.C†L151-L159】【F:KYRANDIA.H†L120-L148】
- **Messaging:** The code assumes synchronous terminal-style output (`outprf`, `prfmsg`, room broadcasts). Model these as server-to-client events; `sndoth`/`sndutl` patterns illustrate when to fan out messages to co-located players. 【F:KYRUTIL.C†L63-L80】
- **Content files:** Message catalogs (`*.mcv`), location data (`elwkyr.lcs`), and object/spell tables are static C arrays. For the port, consider serializing them to JSON/fixtures consumed by the Python backend so the JS client can request descriptions dynamically. 【F:KYRANDIA.C†L57-L63】【F:KYRLOCS.C†L5-L29】【F:KYROBJS.C†L5-L35】
- **Access control & levels:** Spell casting and command availability depend on player level and bitflags (see `struct spell` and `struct gmplyr` fields). Preserve these checks server-side to keep authoritative gameplay logic. 【F:KYRANDIA.H†L111-L142】
- **Networking model:** Movement and interactions hinge on shared location state (`gmlocs`, `gmparr`) and broadcasting. Translate these shared arrays into backend-managed rooms and sessions, emitting events to subscribed clients to mirror the legacy multiplayer feel. 【F:KYRANDIA.C†L84-L105】【F:KYRANDIA.H†L153-L170】

