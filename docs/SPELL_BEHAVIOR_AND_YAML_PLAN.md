# Legacy Spell Behavior Summary and YAML Definition Proposal

## Legacy spell behaviors (all 67 entries)
The legacy `spells` table binds an invocation name to a handler routine and embeds a short effect note. The table below mirrors those notes to keep parity while porting:

| ID | Spell | Legacy note |
| --- | --- | --- |
| 0 | abbracada | other protection II (scry/teleport defense) |
| 1 | allbettoo | ultimate heal |
| 2 | blowitawa | destroy one item |
| 3 | blowoutma | destroy all items |
| 4 | bookworm | zap other's spell book |
| 5 | burnup | fireball I |
| 6 | cadabra | see invisibility I |
| 7 | cantcmeha | invisibility I |
| 8 | canthur | ultimate protection I |
| 9 | chillou | ice storm II |
| 10 | clutzopho | drop all items |
| 11 | cuseme | detect power (spell points) |
| 12 | dumdum | forget all spells |
| 13 | feeluck | teleport random |
| 14 | firstai | heal III |
| 15 | flyaway | transform into pegasus |
| 16 | fpandl | firebolt I |
| 17 | freezuu | ice ball II |
| 18 | frostie | cone of cold II |
| 19 | frozenu | ice ball I |
| 20 | frythes | firebolt III |
| 21 | gotcha | lightning bolt II |
| 22 | goto | teleport specific |
| 23 | gringri | transform into pseudo dragon |
| 24 | handsof | object protection I |
| 25 | heater | ice protection II |
| 26 | hehhehh | lightning storm |
| 27 | hocus | dispel magic |
| 28 | holyshe | lightning bolt III |
| 29 | hotflas | lightning ball |
| 30 | hotfoot | fireball II |
| 31 | hotkiss | firebolt II |
| 32 | hotseat | ice protection I |
| 33 | howru | detect health |
| 34 | hydrant | fire protection II |
| 35 | ibebad | ultimate protection II |
| 36 | icedtea | ice storm I |
| 37 | icutwo | see invisibility III |
| 38 | iseeyou | see invisibility II |
| 39 | koolit | cone of cold I |
| 40 | makemyd | object protection II |
| 41 | mower | destroy things on ground |
| 42 | noouch | heal I |
| 43 | nosey | read other's memorized spells |
| 44 | peekabo | invisibility II |
| 45 | peepint | scry someone |
| 46 | pickpoc | steal a player's item |
| 47 | pocus | magic missile |
| 48 | polarba | ice protection III |
| 49 | sapspel | sap spell points II |
| 50 | saywhat | forget one spell |
| 51 | screwem | fire storm |
| 52 | smokey | fire protection I |
| 53 | snowjob | cone of cold III |
| 54 | sunglass | lightning protection I |
| 55 | surgless | lightning protection III |
| 56 | takethat | sap spell points I |
| 57 | thedoc | heal II |
| 58 | tiltowait | earthquake |
| 59 | tinting | lightning protection II |
| 60 | toastem | fireball III |
| 61 | weewillo | transform into willowisp |
| 62 | whereami | location finder |
| 63 | whopper | fire protection III |
| 64 | whoub | detect true identity |
| 65 | zapher | lightning bolt I |
| 66 | zelastone | aerial servant |

> The table summarizes the legacy spell list at `legacy/KYRSPEL.C` lines 138-205.【F:legacy/KYRSPEL.C†L138-L205】

Additional runtime behaviors to preserve from the same file:
- Spell points regenerate up to `2 * level` every real-time tick, and active charms count down simultaneously. When a charm expires, the engine clears related flags (e.g., invisibility, pegasus, willowisp, pseudo-dragon) and restores the original name before broadcasting to the room.【F:legacy/KYRSPEL.C†L215-L259】

## YAML-based spell definition proposal
The room YAML experiment demonstrates how recurring behaviors can move into data while remaining expressive enough for conditionals, random rolls, and message wiring.【F:docs/YAML_ROOM_EXAMPLE.md†L3-L48】【F:docs/YAML_ROOM_EXAMPLE.md†L81-L182】 Spells share similar patterns—command parsing, level and cost gates, effect application, timers/charms, messaging, and occasional random targeting—so a parallel YAML layer looks feasible for faster onboarding of the remaining unported spell routines.

### Goals
- Mirror the legacy spell table (IDs, invocation strings, level gates, flags) in YAML to let designers add or tweak spells without Python code changes.
- Keep effect primitives reusable across offensive, defensive, utility, and transformation spells while delegating resource costs and cooldowns to the engine.
- Support timers/charms so transformations and protections expire using the existing tick handler semantics.

### Proposed schema sketch
```yaml
spells:
  - id: 5
    name: burnup
    invocation: burnup
    level_required: 6
    school: fire
    cost: { spell_points: 10, items: [] }
    target: { type: room_occupant, count: 1, allow_self: false }
    effects:
      - type: damage
        element: fire
        dice: { count: 10, sides: 6 }
        resist_flag: fire_protection
      - type: message
        to_caster: S06M00
        to_room: S06M01
    cooldown_sec: 12
    charm:
      apply_flag: none
      duration_ticks: 0
  - id: 24
    name: handsof
    invocation: handsof
    level_required: 3
    cost: { spell_points: 3 }
    target: { type: inventory_item }
    effects:
      - type: apply_buff
        buff_flag: object_protection
        duration_ticks: 8
      - type: message
        to_caster: S25M00
```

### Engine responsibilities
- **Parsing & validation:** Load YAML via `pydantic`/JSON Schema, enforcing unique IDs and matching invocation strings to prevent collision with existing commands.
- **Target resolution:** Map `target` configs to player lookup, ground item selection, or location teleport targets.
- **Effect primitives:** Provide reusable handlers for damage, heals, resource drains, item destruction, teleportation, transformations (flag + charm duration), detection/scry, and inventory shuffles. Each primitive emits configurable messages.
- **Timers:** Register charm durations with the tick loop so invisibility, transformations, and protections expire identically to the C logic.【F:legacy/KYRSPEL.C†L215-L259】
- **Testing hooks:** Reuse the room-YAML testing pattern (fixture-driven validations and golden-path simulations) to assert spell effects, gating, and expirations without bespoke unit tests per spell.

### Suggested rollout
1. Define a YAML schema covering cost/target/effect primitives and charm metadata, then load it alongside existing JSON fixtures.
2. Prototype a handful of spells from each category (damage, heal, protection, teleport, transformation) to validate coverage against the legacy table.【F:legacy/KYRSPEL.C†L138-L205】
3. Gradually migrate the remaining spell routines from the porting gap list to YAML-backed definitions, keeping parity tests that mirror the C behaviors and message IDs.
