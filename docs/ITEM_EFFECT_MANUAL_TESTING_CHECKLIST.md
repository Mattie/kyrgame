# Item Effect Manual Testing Checklist

This checklist is intended for admins/testers validating recently ported object behavior from legacy Kyrandia into the modern backend/frontend flow. It focuses on **player-visible behavior** and is designed to expand as additional object classes are ported.

## Scope covered in this revision

- Object effect mappings for IDs 0–53 where applicable to player commands.
- Action-gated item behavior for `drink`, `read`, `rub`, and `attack` flows.
- Consumable inventory mutation for drinkables/readables/dragonstaff.
- Room/context restrictions for non-portable scenery props.
- Dragonstaff bridge behavior pending full Zar animation/service wiring.

---

## Preconditions (one-time setup)

- [ ] Server and frontend are running.
- [ ] Tester can log in as a regular player and at least one admin/debug-capable account.
- [ ] Admin has a way to grant or spawn specific inventory items for the test player.
- [ ] Test player starts with an empty or known inventory baseline.
- [ ] Optional: keep a second player online for attack/target command validation.

---

## A. Gems / Curios / Jewelry message-only interactions

> Legacy intent: these items mostly provide descriptive text behavior rather than special scripted object routines.

- [ ] Grant one gem (example: `ruby`) and use the UI command path to interact with it (e.g., examine/use flow supported by frontend).
  - Expected: interaction succeeds and returns the item-appropriate descriptive text.
  - Expected: item is **not consumed** by this interaction.
- [ ] Repeat with one curios item (example: `staff`) and one jewelry/flower item (example: `ring` or `tulip`).
  - Expected: same message-oriented behavior; no forced target/context requirements.

---

## B. Drinkables (`elixir`, `potion`)

> Ported behavior: drinkables require the **drink** action and consume one inventory copy.

- [ ] Grant `elixir` and issue `drink elixir`.
  - Expected: drink success text is shown (`OBJM08` equivalent).
  - Expected: `elixir` count in inventory decreases by one.
- [ ] Grant `potion` and issue `drink potion`.
  - Expected: same drink success pattern.
  - Expected: `potion` copy is consumed.
- [ ] Negative path: attempt wrong action (example: `read elixir` or `rub potion`).
  - Expected: action is rejected with error/invalid-action style response.
  - Expected: item is **not** consumed on rejection.

---

## C. Readables (`scroll`, `codex`, `tome`, `parchment`)

> Ported behavior: readable items require **read** action and are consumed when used.

- [ ] Grant one `scroll` and issue `read scroll`.
  - Expected: readable interaction resolves successfully.
  - Expected: `scroll` is consumed from inventory.
- [ ] Repeat for `codex`, `tome`, and `parchment`.
  - Expected: all four follow the same read-and-consume pattern.
- [ ] Negative path: issue non-read action (example: `drink scroll`).
  - Expected: rejected; no inventory mutation.

---

## D. Combat items (`dagger`, `sword`)

> Ported behavior: attack-item usage requires attack semantics and a target.

- [ ] Grant `dagger` and issue attack without target (`attack dagger` where UI allows).
  - Expected: rejected due to missing target.
- [ ] Grant `sword` and issue attack without target.
  - Expected: rejected due to missing target.
- [ ] With second player online, issue target form (example pattern: `attack sword at <player>` based on UI command style).
  - Expected: action is accepted when target is valid/resolvable.

---

## E. Scenery/NPC props room/context restrictions (IDs 45–53)

> Ported behavior: these props are room-anchored and enforce context restrictions.

- [ ] Attempt interaction with one prop from the **wrong room**.
  - Expected: rejected because the object cannot be used outside its required room context.
- [ ] Move to the prop’s canonical room and repeat interaction.
  - Expected: interaction returns prop-specific response text instead of generic failure.

Suggested props/rooms to spot-check:
- `tree` in room 0
- `altar` (temple) in room 7
- `sign` in room 9
- `machine` in room 186

---

## F. Dragonstaff (`rub` flow + Zar bridge)

> Ported behavior: dragonstaff requires `rub`, consumes the item on use, and currently bridges to callback/pending flow until full Zar systems are integrated.

- [ ] Grant `dragonstaff`; issue `rub dragonstaff`.
  - Expected: rub flow succeeds with dragonstaff/Zar messaging.
  - Expected: dragonstaff inventory entry is consumed.
- [ ] If running with Zar callback wiring enabled in the environment:
  - Expected: callback-backed summon/response path is returned.
- [ ] If callback wiring is not enabled:
  - Expected: pending/placeholder bridge response appears (non-crashing graceful path).

---

## Regression notes / observations

- [ ] Record any message-ID mismatches between expected legacy text and UI output.
- [ ] Record any inventory desync (UI vs backend state) after item consumption.
- [ ] Record any command parsing mismatch (frontend command helper vs backend expected action).
- [ ] Create follow-up issues for gaps found.

---

## Template for future item-port additions

When adding new item parity coverage in future PRs, append a new section with:

- **Object IDs / names affected**
- **Legacy source reference** (file + function/line range)
- **Player command verbs required**
- **Positive-path checklist**
- **Negative-path checklist**
- **Multiplayer/context requirements**
- **Known limitations / pending subsystem integrations**
