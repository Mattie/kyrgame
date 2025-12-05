# Kyrandia Code Organization (v7.2)

This document summarizes how the original C code is organized so it can be reimplemented with a modern JavaScript front-end and Python back-end. The notes highlight the major data structures, the responsibilities of each source file, and the external assets the BBS module expects.

## Core data structures

The shared header [`KYRANDIA.H`](../legacy/KYRANDIA.H) lives under `legacy/` and defines the size limits, bit flags, and all global structures used throughout the game:

- Spellbook content is described by the `spell` struct, which stores the invocation text, handler function pointer, message references, and level gating, with a fixed array of 67 spells (`NGSPLS`).
- Players use the `gmplyr` struct, capturing their BBS user identity, in-game alias, inventory slots (`MXPOBS`), current location, flags, currency, memorized spells (`MAXSPL`), and birthstone configuration. An array of these records is allocated per connection slot at runtime. The constants above it document limits such as maximum objects or charm timers.
- The world is a grid of `gamloc` entries with brief descriptions, object slots, and directional exits, sized for `NGLOCS` rooms. Each location can also have an optional routine hook defined through `glcrou` to implement special behaviors.
- Objects (`gamobj`) and command definitions (`cmdwrd`) tie user-visible strings to behavior pointers, which will map cleanly to future event handlers or controller methods.

These structures are the primary inputs for any port: translating them into database schemas or server-side models will let the new stack preserve game logic while replacing the BBS-specific runtime.

## Module-level responsibilities

Each C file targets a distinct subsystem, with clear boundaries that can be mirrored in a service-oriented Python back-end and modular JS client:

- `legacy/KYRANDIA.C` is the entry point, wiring the module into the MajorBBS runtime. It opens message catalogs (`ELWKYR.MDF`, `elwkyrl.mcv`, `elwkyrs.mcv`, `elwkyrm.mcv`), loads the player data file (`elwkyr.dat`), initializes dynamic arrays for players and locations, and seeds subsystems like utilities, dynamic locations, spells, and animation. When porting, this initialization flow maps to bootstrapping configuration, loading content from storage, and attaching middleware.
- `legacy/KYRCMDS.C` houses the command table and the handlers that parse player input (movement, communication verbs, inventory operations). It is the main dispatch layer for translating free-form text into game actions, which can be reimagined as routed API calls or chat/command events from the front-end.
- `legacy/KYRLOCS.C` enumerates the rooms and associates each with a long description and an optional location routine, effectively functioning as the world layout and trigger registry. These routines can become scripted server-side events responding to player presence.
- `legacy/KYROBJS.C` defines the catalog of game objects and their behavior callbacks. It is the source of item metadata (names, flags, message references) and should be mirrored by an item schema plus per-item server logic in the port.
- `legacy/KYRSPEL.C` implements spell utilities, timers, and handlers, tying spellbook entries to effects like protections, attacks, or movement. This can inform a dedicated combat/spell service layer in the new back-end.
- `legacy/KYRANIM.C` runs timed creature animations and encounter logic. Its timer-driven model aligns with scheduled tasks or background workers in a modern stack.
- `legacy/KYRUTIL.C` supplies general multiplayer utilities (common helpers for messaging, targeting, RNG, etc.), which can be distilled into shared helper modules for the port.
- `legacy/KYRALOC.C` contains dynamic allocation routines for room state (e.g., object placement arrays). When porting, this logic should be represented by persistent state management (database rows or in-memory caches) instead of BBS-specific dynamic files.
- `legacy/KYRPROT.C` focuses on loading and saving data structures, which will translate to serialization/deserialization against your chosen datastore or API payloads.
- `legacy/KYRSYSP.C` implements the sysop (administrator) editor for player records, foreshadowing the admin interfaces or management endpoints you may want in the new system.

## Content and assets

The `legacy/Dist/` folder mirrors the packaged release and identifies runtime content dependencies. The README there notes three message files (`ELWKYRM.MSG`, `ELWKYRL.MSG`, `ELWKYRS.MSG`) that customize gameplay text, location descriptions, and sysop editor strings, and it points to solution strings and configurable options inside `ELWKYRM`. These message catalogs will need to be extracted and delivered through the new client/server text pipeline.

The core executable also expects supporting data files for players and locations (`elwkyr.dat`, `elwkyr.lcs`), spelled out in the main initializer, which can be mapped to database tables or JSON fixtures in the port. Understanding how these files are read and updated will guide migration of persistence to the Python service.

## Applying this layout to the JS/Python stack

- Treat the structs in `KYRANDIA.H` as canonical schemas. Define equivalent models (ORM classes or Pydantic schemas) for players, locations, objects, spells, and commands, keeping field semantics and size limits in mind for validation.
- Mirror the module boundaries when designing services: a command dispatcher (user input router), world/location service (movement, exits, triggers), object service (item metadata and effects), spell/combat service, and background task scheduler for recurring events.
- Replace message catalogs with a content layer that can source localized strings to the JS client; the message IDs referenced across the C files should become keys in your new content store.
- Convert file-based persistence (`elwkyr.dat`, `elwkyr.lcs`) into a database-backed layer, ensuring that session-scoped runtime data (like timed effects) is modeled separately from durable character progression.

Use this map as a starting point when carving the C logic into API endpoints, socket events, and front-end UI flows; aligning the modern modules with the legacy responsibilities will help preserve behavior while decoupling from the BBS runtime.
