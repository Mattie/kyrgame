# Item Effect Manual Testing Checklist

This checklist is intended for admins/testers validating recently ported object behavior from legacy Kyrandia into the modern backend/frontend flow. It focuses on **player-visible behavior** and is designed to expand as additional object classes are ported.

## Scope covered in this revision

- Object effect mappings for IDs 0–53 where applicable to player commands.
- Action-gated item behavior for `drink`, `read`, `rub`, and `aim/point` flows.
- Consumable inventory mutation for drinkables/readables/dragonstaff.
- Room/context restrictions for non-portable scenery props.
- Dragonstaff `zaritm` behavior with full Zar summon, relocation, and attack wiring.

## Automated coverage

- [x] Backend command/effect tests cover drinkable consumption, readable scroll/spellbook behavior, aim/point target validation, non-aimable inventory rejection, scenery/context restrictions, dragonstaff `rub`/Zar summon and attack branches, and inline event payload preservation.
- [x] Playwright covers browser-visible `drink elixir`, `swallow potion`, `aim dagger`, `point sword`, `rub emerald`, and gemstone inline rendering inside transfer messages; backend/component coverage protects creature/Zar rendering and event payload behavior until the later frontend pass broadens visual checks.
- [x] Package-content smoke verification regenerates `legacy/Dist/offline-content.json` from the current fixture set; timestamp-only artifact churn is left out of gameplay parity changes.

---

## Preconditions (one-time setup)

- [ ] Server and frontend are running.
- [ ] Tester can log in as a regular player and at least one admin/debug-capable account.
- [ ] Admin has a way to grant or spawn specific inventory items for the test player.
- [ ] Test player starts with an empty or known inventory baseline.
- [ ] Optional: keep a second player online for aim/point target-command validation.

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

> Ported behavior: legacy uses the `aim` / `point` verb family (not a dedicated `attack` command), and weapon-style object usage requires a target.

- [ ] Grant `dagger` and issue `point dagger` (or `aim dagger`) without a target.
  - Expected: rejected due to missing target (`OBJM05`-style response).
- [ ] Grant `sword` and issue `point sword` without a target.
  - Expected: rejected due to missing target.
- [ ] With second player online, issue target form (`point sword at <player>`).
  - Expected: action is accepted when target is valid/resolvable in-room.

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

## F. Dragonstaff (`rub` flow + Zar)

> Ported behavior: dragonstaff requires `rub`, consumes the item on use, and routes through Zar's legacy `zaritm` summon/attack flow.

- [ ] Grant `dragonstaff`; issue `rub dragonstaff`.
  - Expected: the room sees `*** <player> is rubbing <his/her/its> dragonstaff!`.
  - Expected: dragonstaff inventory entry is consumed immediately.
- [ ] With Zar in another room, issue `rub dragonstaff`.
  - Expected: the player receives `ZMSG13`, Zar's old room receives `ZMSG10`, the player's room receives `ZMSG11`, and the player receives `ZMSG14`.
  - Expected: Zar's old room loses object `52`; the player's room gains object `52` plus any legacy special prop for that room.
  - Expected: Zar may attack after the summon according to the legacy 50% chance.
- [ ] With Zar already in the player's room, issue `rub dragonstaff`.
  - Expected: the player receives `ZMSG12`, then `ZMSG14`.
  - Expected: Zar attacks active non-level-25 players in the room using the rotating bite/breath/claw/lightning sequence.
- [ ] Spot-check protections during Zar attacks.
  - Expected: fire protection reduces dragon breath damage and lightning protection reduces lightning damage.
- [ ] Confirm a level 25 player in Zar's room is skipped by Zar's attack pass.

## G. Creature inline display parity

> Frontend-only display behavior: creature names are decorated by the shared inline renderer, while backend message text and event payloads remain legacy/plain.

- [ ] Observe Zar/dragon text in the MUD console and admin mob tracker.
  - Expected: `dragon` and `Zar` render with 🐲 and red text.
- [ ] Observe dryad, elf, and brownie text in room/object lines or the admin mob tracker.
  - Expected: `dryad` renders with 🌱 and yellowgreen text, `elf` renders with 🧝 and green text, and `brownie` renders with 😈 and brown text.
- [ ] Verify token matching around dragon item names.
  - Expected: `dragon` and `dragon's` are styled, while `dragonstaff` remains plain.
- [ ] Confirm gemstone labels still render with their gemstone emoji/color treatment.

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
