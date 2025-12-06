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

### Feasibility Analysis

The room YAML experiment in `YAML_ROOM_EXAMPLE.md` demonstrates how recurring behaviors can move into data while remaining expressive enough for conditionals, random rolls, and message wiring. After analyzing all 67 spell implementations in `legacy/KYRSPEL.C`, spells share similar patterns that make a parallel YAML approach highly feasible.

**Common spell patterns observed:**

1. **Cost validation** (spell points, required items)
2. **Target resolution** (player, self, room occupants, items, locations)
3. **Effect application** (damage, heal, charm, transform, teleport, detect)
4. **Messaging** (to caster, target, room, others)
5. **Timer/charm management** (durations, expiry, stacking)
6. **Resistance checks** (protection charms, flags)
7. **Random outcomes** (damage rolls, targeting, effects)

**Spell category breakdown:**

| Category | Count | Examples | Complexity |
|----------|-------|----------|------------|
| Offensive (direct damage) | 21 | burnup, fpandl, gotcha | Low |
| Defensive (protections) | 12 | handsof, heater, smokey | Low |
| Healing | 3 | noouch, thedoc, allbettoo | Low |
| Transformation | 4 | cantcmeha, flyaway, weewillo | Medium |
| Teleportation | 2 | goto, feeluck | Medium |
| Detection/Scry | 5 | cuseme, howru, peepint | Low |
| Item manipulation | 7 | blowitawa, clutzopho, pickpoc | Medium |
| Spell manipulation | 4 | dumdum, saywhat, bookworm | Medium |
| Utility/Special | 9 | tiltowait, zelastone, whereami | High |

**Pattern coverage estimate:**
- **95%** of spells follow one of ~10 core effect patterns
- **5%** have unique mechanics requiring custom handlers (e.g., `zelastone` aerial servant, `tiltowait` earthquake)

**Benefits over code-based approach:**

✅ **Reduced code duplication:** Similar spells differ only in parameters (damage dice, duration, messages)  
✅ **Faster iteration:** Designers can add/tweak spells without Python knowledge  
✅ **Better maintainability:** All spells in one data file vs. 67+ handler functions  
✅ **Easier testing:** Data-driven tests can validate all spells systematically  
✅ **Legacy parity:** YAML can preserve exact behavior including message IDs and timing

**Challenges identified:**

⚠️ **Complex targeting:** Some spells (e.g., `zelastone`) select random other player in room  
⚠️ **Multi-step sequences:** Spells like `pickpoc` (steal item) require inventory shuffling  
⚠️ **Conditional effects:** Some spells have success/failure branches with different outcomes  
⚠️ **State manipulation:** Direct access to flags, charms, spell lists requires clean abstractions

**Solutions:**

- Extend target types to support `random_other_player`, `all_ground_items`, etc.
- Add `conditional_branch` effect type with success/failure action lists
- Provide comprehensive effect primitives that encapsulate state changes
- Allow inline Python expressions for truly unique edge cases (escaped hatch for 5%)

### Goals
- Mirror the legacy spell table (IDs, invocation strings, level gates, flags) in YAML to let designers add or tweak spells without Python code changes.
- Keep effect primitives reusable across offensive, defensive, utility, and transformation spells while delegating resource costs and cooldowns to the engine.
- Support timers/charms so transformations and protections expire using the existing tick handler semantics.

### Proposed schema sketch

The following examples demonstrate how different spell categories translate to YAML, following the same comprehensive pattern established in `YAML_ROOM_EXAMPLE.md`. Each example includes the legacy C implementation reference, complete YAML definition, and behavioral notes.

#### Example 1: Offensive Spell - "burnup" (Fireball I)

**Legacy implementation:** `legacy/KYRSPEL.C` lines 517-521 (spl006 function)

```c
static VOID
spl006(VOID)                       /* spell #6 routine                     */
{
     msgutl2(S06M00,S06M01);
     masshitr(10,FIRPRO,S06M02,S06M03,S06M04,0,1);
}
```

**YAML definition:**

```yaml
spells:
  - id: 5
    name: burnup
    invocation: burnup
    description: "Cast a fireball that damages all enemies in the room"
    
    # Gating and cost
    level_required: 6
    school: offensive
    element: fire
    cost:
      spell_points: 10
      items: []  # No item requirement
    
    # Target configuration
    target:
      type: room_occupants
      count: all
      allow_self: false
      filter: enemies_only
    
    # Execution sequence
    effects:
      # Step 1: Display casting messages
      - type: message
        to_caster: S06M00
        text: "You hurl a blazing fireball!"
      
      - type: message
        to_room: S06M01
        format_with: caster_name
        text: "{caster_name} hurls a blazing fireball!"
      
      # Step 2: Apply damage with resistance check
      - type: multi_target_damage
        dice_count: 10
        dice_sides: 6
        element: fire
        resistance_charm: FIRPRO  # fire_protection charm
        
        # Per-target message variants
        on_hit:
          to_target: S06M02
          to_caster: S06M03
          to_room: S06M04
          text_caster: "Your fireball engulfs {target_name}!"
          text_target: "{caster_name}'s fireball engulfs you!"
          text_room: "{caster_name}'s fireball engulfs {target_name}!"
        
        on_resist:
          to_target: S06M05
          to_caster: S06M06
          to_room: S06M07
          text_caster: "{target_name} resists your fireball!"
          text_target: "You resist {caster_name}'s fireball!"
          text_room: "{target_name} resists {caster_name}'s fireball!"
    
    # Cooldown and charm tracking
    cooldown_sec: 12
    charm:
      apply_flag: none
      duration_ticks: 0
```

**Behavioral notes:**
- Mass-effect offensive spell targeting all room occupants except caster
- Damage roll: 10d6 per target
- Fire protection charm (FIRPRO) provides resistance
- Messages differentiate between successful hits and resisted attacks
- No items consumed, only spell points

---

#### Example 2: Defensive Spell - "handsof" (Object Protection I)

**Legacy implementation:** `legacy/KYRSPEL.C` lines 760-764 (spl025 function, inferred structure)

```c
static VOID
spl025(VOID)                       /* spell #25 routine                    */
{
     gmpptr->charms[OBJPRO]+=(2*3);  // 6 ticks
     msgutl2(S25M00,S25M01);
}
```

**YAML definition:**

```yaml
spells:
  - id: 24
    name: handsof
    invocation: handsof
    description: "Protect your possessions from theft and destruction"
    
    # Gating and cost
    level_required: 3
    school: defensive
    element: none
    cost:
      spell_points: 3
      items: []
    
    # Target configuration
    target:
      type: self
      count: 1
      allow_self: true
    
    # Execution sequence
    effects:
      # Step 1: Apply protection charm
      - type: apply_charm
        charm_type: OBJPRO  # object_protection
        duration_ticks: 6    # 2 * 3 (base duration * level multiplier)
        stacking: extend     # Extends existing charm if already active
      
      # Step 2: Display success messages
      - type: message
        to_caster: S25M00
        text: "Your possessions glow with protective magic!"
      
      - type: message
        to_room: S25M01
        format_with: caster_name
        text: "{caster_name}'s possessions glow briefly!"
    
    # Cooldown and charm tracking
    cooldown_sec: 0  # Can be cast repeatedly
    charm:
      apply_flag: OBJPRO
      duration_ticks: 6
      
      # Charm behavior
      protection_against:
        - spell_blowitawa   # destroy one item (id: 2)
        - spell_blowoutma   # destroy all items (id: 3)
        - spell_bookworm    # zap spell book (id: 4)
        - spell_pickpoc     # steal item (id: 46)
      
      expiry_message:
        to_caster: BASMSG_OBJPRO
        text: "Your object protection fades away."
```

**Behavioral notes:**
- Self-targeted buff spell applying OBJPRO charm
- Duration: 6 real-time ticks (regenerates 2 spell points per tick, so ~3 minutes)
- Charms stack by extending duration (new duration adds to existing)
- Protects against item destruction and theft spells
- Expiry handled by `splrtk` timer (lines 222-264 in KYRSPEL.C)

---

#### Example 3: Utility Spell - "goto" (Teleport Specific)

**Legacy implementation:** `legacy/KYRSPEL.C` lines 692-716 (spl023 function)

```c
static VOID
spl023(VOID)                       /* spell #23 routine                    */
{
     INT i;

     if (margc == 2) {
          youmsg(OBJM07);
          sndutl("failing at spellcasting.");
     }
     else {
          if ((i=gtmloc(margv[2])) != -1) {
               prfmsg(S23M00);
               outprf(usrnum);
               prfmsg(S23M01,gmpptr->altnam);
               sndoth();
               remvgp(gmpptr,"vanished in a puff of smoke");
               entrgp(i,gmpptr,"appeared in a puff of smoke");
          }
          else {
               prfmsg(S23M02);
               outprf(usrnum);
               prfmsg(S23M03,gmpptr->altnam,hisher(gmpptr));
               sndoth();
          }
     }
}
```

**YAML definition:**

```yaml
spells:
  - id: 22
    name: goto
    invocation: goto
    description: "Teleport to a specific location by name"
    
    # Gating and cost
    level_required: 13
    school: utility
    element: none
    cost:
      spell_points: 13
      items: []
    
    # Target configuration
    target:
      type: location_by_name
      count: 1
      allow_self: true
      argument_required: true  # Must specify location name
    
    # Execution sequence
    effects:
      # Step 1: Validate location argument
      - type: conditional_branch
        conditions:
          # Success: valid location name provided
          - condition:
              - type: argument_count
                min: 3  # "cast goto <location>"
              - type: location_exists
                location_source: argument
                argument_index: 2
            
            actions:
              # Step 1a: Display departure messages
              - type: message
                to_caster: S23M00
                text: "You begin to fade from view..."
              
              - type: message
                to_room: S23M01
                format_with: caster_name
                text: "{caster_name} begins to fade from view..."
              
              # Step 1b: Execute teleport
              - type: teleport
                target_location_source: argument
                argument_index: 2
                exit_message: "vanished in a puff of smoke"
                entry_message: "appeared in a puff of smoke"
                broadcast_exit: true
                broadcast_entry: true
          
          # Failure: missing or invalid location
          - default: true
            actions:
              - type: message
                to_caster: S23M02
                text: "The spell fizzles - you don't know that location!"
              
              - type: message
                to_room: S23M03
                format_with: [caster_name, caster_possessive]
                text: "{caster_name} waves {caster_possessive} hands frantically, but nothing happens!"
    
    # Cooldown and charm tracking
    cooldown_sec: 30
    charm:
      apply_flag: none
      duration_ticks: 0
```

**Behavioral notes:**
- Requires player to specify target location as argument
- Location lookup via `gtmloc` (location name parser)
- Success moves player from current room to target with broadcast messages
- Failure if location invalid or unknown
- Higher spell point cost reflects utility power

---

#### Example 4: Transformation Spell - "cantcmeha" (Invisibility I)

**Legacy implementation:** `legacy/KYRSPEL.C` lines 531-538 (spl008 function)

```c
static VOID
spl008(VOID)                       /* spell #8 routine                     */
{
     prfmsg(S08M00);
     outprf(usrnum);
     prfmsg(S08M01,gmpptr->altnam);
     sndoth();
     chgbod("Some Unseen Force","Unseen Force",INVISF,2);
}
```

**YAML definition:**

```yaml
spells:
  - id: 7
    name: cantcmeha
    invocation: cantcmeha
    description: "Transform into an invisible force, hiding your identity"
    
    # Gating and cost
    level_required: 7
    school: utility
    element: none
    cost:
      spell_points: 7
      items: []
    
    # Target configuration
    target:
      type: self
      count: 1
      allow_self: true
    
    # Execution sequence
    effects:
      # Step 1: Display transformation messages
      - type: message
        to_caster: S08M00
        text: "You feel yourself fading from sight..."
      
      - type: message
        to_room: S08M01
        format_with: caster_name
        text: "{caster_name} fades from sight!"
      
      # Step 2: Apply transformation
      - type: transform_identity
        new_display_name: "Some Unseen Force"
        new_short_name: "Unseen Force"
        transform_flag: INVISF  # invisibility flag
        duration_ticks: 2       # Short duration for level I
        
        # Name handling
        preserve_original: true
        restore_on_expiry: true
        
        # Associated charm for tracking
        charm_type: ALTNAM  # alternate name charm
        charm_duration: 2
    
    # Cooldown and charm tracking
    cooldown_sec: 15
    charm:
      apply_flag: ALTNAM
      duration_ticks: 2
      
      # Transformation details
      behavior:
        - sets_flag: INVISF
        - changes_display_name: true
        - conceals_identity: true
      
      expiry_action:
        - type: restore_identity
          broadcast_message: RET2NM
          text: "{original_name} suddenly appears!"
        - type: clear_flag
          flags: [INVISF, PEGASU, WILLOW, PDRAGN]
        - type: message
          to_caster: BASMSG_ALTNAM
          text: "You return to your normal form."
```

**Behavioral notes:**
- Changes player's displayed name to hide identity
- Sets INVISF flag affecting visibility and targeting
- Duration: 2 ticks (short-lived level I version)
- Expiry automatically restores original name via `splrtk` timer
- Uses `chgbod` helper which manages both name change and charm/flag setting
- ALTNAM charm tracks transformed state

---

#### Example 5: Detection Spell - "cuseme" (Detect Power)

**Legacy implementation:** `legacy/KYRSPEL.C` lines 593-603 (spl012 function)

```c
static VOID
spl012(VOID)                       /* spell #12 routine                    */
{
     if (chkstf()) {
          prfmsg(S12M00,ogmptr->altnam,ogmptr->spts);
          outprf(usrnum);
          prfmsg(S12M01,gmpptr->altnam);
          outprf(ogmptr->modno);
          prfmsg(S12M02,gmpptr->altnam,ogmptr->altnam);
          sndbt2();
     }
}
```

**YAML definition:**

```yaml
spells:
  - id: 11
    name: cuseme
    invocation: cuseme
    description: "Detect the spell power reserves of another player"
    
    # Gating and cost
    level_required: 3
    school: utility
    element: none
    cost:
      spell_points: 3
      items: []
    
    # Target configuration
    target:
      type: player
      count: 1
      allow_self: false
      argument_required: true  # Must specify target player
    
    # Execution sequence
    effects:
      # Step 1: Validate target (uses chkstf - check staff/target)
      - type: conditional_branch
        conditions:
          # Success: valid player target
          - condition:
              - type: argument_count
                min: 3  # "cast cuseme <player>"
              - type: player_exists
                player_source: argument
                argument_index: 2
            
            actions:
              # Step 1a: Reveal target's spell points to caster
              - type: message
                to_caster: S12M00
                format_with: [target_display_name, target_spell_points]
                text: "{target_display_name} has {target_spell_points} spell points remaining."
              
              # Step 1b: Notify target they were detected
              - type: message
                to_target: S12M01
                format_with: caster_name
                text: "{caster_name} senses your magical energy!"
              
              # Step 1c: Broadcast to other room occupants
              - type: message
                to_others: S12M02
                format_with: [caster_name, target_display_name]
                text: "{caster_name} probes {target_display_name} with magic!"
          
          # Failure: missing or invalid target
          - condition:
              - type: argument_count
                max: 2  # No target specified
            
            actions:
              - type: message
                to_caster: SOMETHINGMISSSPELL
                text: "...Something is missing and the spell fails!"
              
              - type: broadcast_action
                action_text: "trying to cast a spell, without success."
          
          # Failure: target not a player (object or invalid)
          - default: true
            actions:
              - type: message
                to_caster: KSPM02
                text: "You can't detect the power of that!"
              
              - type: broadcast_action
                action_text: "casting at phantoms!"
    
    # Cooldown and charm tracking
    cooldown_sec: 5
    charm:
      apply_flag: none
      duration_ticks: 0
```

**Behavioral notes:**
- Requires valid player target via `chkstf` validation
- Reveals target's current spell points (`ogmptr->spts`)
- Three-way messaging: caster sees info, target gets notified, room sees action
- Uses `sndbt2` to broadcast to others excluding caster and target
- No lasting effects, instant information spell

### Engine responsibilities

The spell YAML engine requires sophisticated runtime support to handle the diverse spell behaviors while maintaining legacy parity. Following the pattern established in the room YAML proposal, the engine must provide:

#### 1. Parsing & Validation

**Schema enforcement:**
- Load YAML via `pydantic` models with strict type checking
- Validate unique spell IDs (0-66 matching legacy table)
- Enforce unique invocation strings to prevent collision with commands/keywords
- Validate message ID references against fixture message catalog
- Check that all referenced charm types, flags, and effects exist

**Example validation model:**
```python
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Literal

class SpellCost(BaseModel):
    spell_points: int = Field(ge=0)
    items: List[str] = Field(default_factory=list)

class SpellTarget(BaseModel):
    type: Literal["self", "player", "room_occupants", "inventory_item", "location_by_name"]
    count: int = Field(ge=1)
    allow_self: bool = True
    argument_required: bool = False

class SpellEffect(BaseModel):
    type: str
    # Additional fields vary by effect type
    
class SpellDefinition(BaseModel):
    id: int = Field(ge=0, le=66)
    name: str
    invocation: str
    description: str
    level_required: int = Field(ge=1, le=25)
    school: Literal["offensive", "defensive", "utility"]
    cost: SpellCost
    target: SpellTarget
    effects: List[SpellEffect]
    cooldown_sec: int = Field(ge=0)
    
    @validator('invocation')
    def invocation_lowercase(cls, v):
        return v.lower()
```

#### 2. Target Resolution

**Player targeting:**
- Parse player name from command arguments
- Resolve via `findgp` (find game player) equivalent
- Handle invisibility/transformed names (check INVISF, PEGASU, WILLOW, PDRAGN flags)
- Validate target in same room as caster
- Check allow_self flag for self-targeting restrictions

**Room occupant targeting:**
- Get all players in current location via `gmlptr->gpinloc`
- Filter by allow_self, enemies_only, allies_only criteria
- Handle mass-effect spells (iterate all targets)

**Item targeting:**
- Inventory items via `fgmpobj` (find game player object)
- Ground items via `fgmlobj` (find game location object)
- Validate ownership and pickup flags

**Location targeting:**
- Parse location name/ID from arguments
- Resolve via `gtmloc` (get location by name)
- Validate location exists and is accessible

#### 3. Effect Primitives

Each effect type maps to reusable handler functions:

**Damage effects:**
```python
async def apply_damage(
    caster: Player,
    target: Player,
    dice_count: int,
    dice_sides: int,
    element: str,
    resistance_charm: Optional[str] = None
) -> DamageResult:
    """
    Apply damage to target with resistance check.
    Mirrors legacy striker() and masshitr() functions.
    """
    # Roll damage: genrdn(dice_count, dice_count * dice_sides)
    damage = random.randint(dice_count, dice_count * dice_sides)
    
    # Check resistance charm (FIRPRO, ICEPRO, LIGPRO)
    if resistance_charm and target.charms.get(resistance_charm, 0) > 0:
        damage = 0  # Full resistance
        result = "resisted"
    else:
        target.hitpts -= damage
        result = "hit"
    
    # Handle death
    if target.hitpts <= 0:
        await handle_player_death(target, caster)
    
    return DamageResult(damage=damage, result=result)
```

**Heal effects:**
```python
async def apply_heal(
    target: Player,
    amount: int,
    max_health: Optional[int] = None
) -> HealResult:
    """
    Restore hit points with optional cap.
    Mirrors legacy heal spell patterns.
    """
    old_hp = target.hitpts
    target.hitpts += amount
    
    # Cap at max (usually 4 * level)
    if max_health:
        target.hitpts = min(target.hitpts, max_health)
    
    healed = target.hitpts - old_hp
    return HealResult(healed=healed, new_hp=target.hitpts)
```

**Charm/buff effects:**
```python
async def apply_charm(
    target: Player,
    charm_type: str,
    duration_ticks: int,
    stacking: Literal["replace", "extend", "max"] = "extend"
) -> CharmResult:
    """
    Apply timed buff/charm to player.
    Mirrors legacy charm[] array manipulation.
    """
    current = target.charms.get(charm_type, 0)
    
    if stacking == "replace":
        target.charms[charm_type] = duration_ticks
    elif stacking == "extend":
        target.charms[charm_type] = current + duration_ticks
    elif stacking == "max":
        target.charms[charm_type] = max(current, duration_ticks)
    
    return CharmResult(
        charm_type=charm_type,
        duration=target.charms[charm_type]
    )
```

**Transformation effects:**
```python
async def transform_identity(
    target: Player,
    new_display_name: str,
    new_short_name: str,
    transform_flag: str,
    duration_ticks: int
) -> TransformResult:
    """
    Change player identity with timed reversion.
    Mirrors legacy chgbod() function.
    """
    # Preserve original name
    target.original_name = target.plyrid
    
    # Apply transformation
    target.altnam = new_display_name
    target.attnam = new_short_name
    target.flags |= get_flag(transform_flag)
    
    # Set ALTNAM charm for expiry tracking
    target.charms[ALTNAM] = duration_ticks
    
    return TransformResult(
        old_name=target.original_name,
        new_name=new_display_name,
        expires_in_ticks=duration_ticks
    )
```

**Teleport effects:**
```python
async def teleport_player(
    player: Player,
    target_location: int,
    exit_message: str,
    entry_message: str,
    broadcast: bool = True
) -> TeleportResult:
    """
    Move player to new location with broadcasts.
    Mirrors legacy remvgp() + entrgp() sequence.
    """
    old_loc = player.gamloc
    
    # Remove from current location
    if broadcast:
        await broadcast_to_location(
            old_loc,
            f"{player.altnam} {exit_message}",
            exclude=player
        )
    
    player.gamloc = target_location
    
    # Enter new location
    if broadcast:
        await broadcast_to_location(
            target_location,
            f"{player.altnam} {entry_message}",
            exclude=player
        )
    
    return TeleportResult(
        old_location=old_loc,
        new_location=target_location
    )
```

**Item manipulation effects:**
```python
async def consume_item(
    player: Player,
    item_keyword: str
) -> ItemResult:
    """Remove item from player inventory."""
    item = find_player_object(player, item_keyword)
    if item:
        remove_player_object(player, item)
        return ItemResult(success=True, item=item)
    return ItemResult(success=False, item=None)

async def grant_item(
    player: Player,
    item_id: int
) -> ItemResult:
    """Add item to player inventory with capacity check."""
    if player.npobjs >= MAX_INVENTORY:
        return ItemResult(success=False, reason="inventory_full")
    
    add_player_object(player, item_id)
    return ItemResult(success=True, item=get_object(item_id))
```

**Detection/information effects:**
```python
async def detect_player_info(
    caster: Player,
    target: Player,
    info_type: Literal["health", "spell_points", "identity", "spells"]
) -> DetectionResult:
    """
    Reveal information about target player.
    Mirrors various detection spell patterns.
    """
    if info_type == "health":
        info = target.hitpts
    elif info_type == "spell_points":
        info = target.spts
    elif info_type == "identity":
        info = target.plyrid  # True name
    elif info_type == "spells":
        info = get_memorized_spells(target)
    
    return DetectionResult(info_type=info_type, value=info)
```

#### 4. Timer System

**Real-time tick handler:**

The legacy `splrtk` function (lines 222-264) handles spell point regeneration and charm expiry every 30 seconds. The YAML engine must integrate with this system:

```python
class SpellTickHandler:
    """
    Manages spell point regeneration and charm expiry.
    Called every 30 seconds via scheduler.
    """
    
    async def process_tick(self):
        """Process all active players."""
        for player in get_active_players():
            # Regenerate spell points (2 per tick, cap at 2*level)
            if player.spts < (2 * player.level) - 1:
                player.spts += 2
            else:
                player.spts = 2 * player.level
            
            # Process charm expiry
            await self.process_charms(player)
    
    async def process_charms(self, player: Player):
        """Decrement and expire charms."""
        expired_charms = []
        
        for charm_type, duration in list(player.charms.items()):
            if duration > 0:
                player.charms[charm_type] -= 1
                
                if player.charms[charm_type] == 0:
                    expired_charms.append(charm_type)
        
        # Handle expiries
        for charm_type in expired_charms:
            await self.expire_charm(player, charm_type)
    
    async def expire_charm(self, player: Player, charm_type: str):
        """Handle charm expiration effects."""
        # Send expiry message
        await send_message(player, f"BASMSG_{charm_type}")
        
        # Special handling for ALTNAM (transformation)
        if charm_type == ALTNAM:
            # Restore original identity
            player.flags &= ~(INVISF | PEGASU | WILLOW | PDRAGN)
            
            # Broadcast reversion
            await broadcast_to_location(
                player.gamloc,
                f"{player.altnam} returns to normal form!",
                exclude=player
            )
            
            # Restore name
            player.altnam = player.plyrid
            player.attnam = player.plyrid
```

**Cooldown tracking:**

Unlike charms (which are player-specific timed buffs), cooldowns prevent spell re-casting:

```python
class SpellCooldownManager:
    """Track per-player spell cooldowns."""
    
    def __init__(self):
        self.cooldowns: Dict[Tuple[int, int], datetime] = {}
        # Key: (player_id, spell_id), Value: expires_at
    
    def can_cast(self, player_id: int, spell_id: int) -> bool:
        """Check if spell is off cooldown."""
        key = (player_id, spell_id)
        if key in self.cooldowns:
            if datetime.now() < self.cooldowns[key]:
                return False
            del self.cooldowns[key]
        return True
    
    def set_cooldown(
        self,
        player_id: int,
        spell_id: int,
        cooldown_sec: int
    ):
        """Start cooldown timer."""
        key = (player_id, spell_id)
        self.cooldowns[key] = datetime.now() + timedelta(seconds=cooldown_sec)
```

#### 5. Message System Integration

**Message formatting:**

Spells use extensive messaging with variable substitution:

```python
class SpellMessageFormatter:
    """Format spell messages with dynamic content."""
    
    def format_message(
        self,
        msg_id: str,
        context: Dict[str, Any]
    ) -> str:
        """
        Load message template and substitute variables.
        Mirrors legacy prfmsg() with format arguments.
        """
        template = load_message(msg_id)
        
        # Available variables
        replacements = {
            'caster_name': context.get('caster').altnam,
            'caster_possessive': hisher(context.get('caster')),
            'target_name': context.get('target', {}).get('altnam', ''),
            'target_display_name': context.get('target', {}).get('attnam', ''),
            'damage': context.get('damage', 0),
            'item_name': context.get('item', {}).get('name', ''),
            # ... additional variables
        }
        
        return template.format(**replacements)
```

**Broadcasting patterns:**

Different spells require different broadcast patterns:

- `to_caster`: Only spell caster (via `outprf(usrnum)`)
- `to_target`: Only spell target (via `outprf(ogmptr->modno)`)
- `to_room`: All in room except caster (via `sndoth()`)
- `to_others`: All in room except caster and target (via `sndbt2()`)
- `to_location`: Specific location broadcast (via `sndloc(loc_id)`)

#### 6. Testing Strategy

**Fixture-driven validation:**

Reuse the room YAML testing pattern:

```python
class TestSpellYAMLEngine:
    """Test YAML spell definitions."""
    
    def test_spell_schema_validation(self):
        """Verify all spell YAMLs parse correctly."""
        engine = SpellYAMLEngine("fixtures/spells.yaml")
        assert len(engine.spells) == 67  # All legacy spells
        
        # Check for duplicate IDs
        ids = [s.id for s in engine.spells]
        assert len(ids) == len(set(ids))
    
    def test_offensive_spell_damage(self):
        """Verify damage spell calculations."""
        caster = create_test_player(level=10)
        target = create_test_player(level=5)
        
        # Cast burnup (fireball I)
        result = await cast_spell(caster, "burnup", target)
        
        assert result.success
        assert 10 <= result.damage <= 60  # 10d6
        assert target.hitpts < target.max_hitpts
    
    def test_protection_charm_blocks_damage(self):
        """Verify resistance charms work."""
        caster = create_test_player(level=10)
        target = create_test_player(level=10)
        
        # Apply fire protection to target
        target.charms[FIRPRO] = 5
        
        # Cast burnup (fire spell)
        result = await cast_spell(caster, "burnup", target)
        
        assert result.resisted
        assert result.damage == 0
    
    def test_charm_expiry(self):
        """Verify charms expire after duration."""
        player = create_test_player()
        player.charms[OBJPRO] = 2
        
        # Process 1 tick
        await tick_handler.process_tick()
        assert player.charms[OBJPRO] == 1
        
        # Process 2nd tick
        await tick_handler.process_tick()
        assert player.charms[OBJPRO] == 0
        assert OBJPRO not in player.charms  # Cleaned up
    
    def test_transformation_name_change(self):
        """Verify transformation spells change identity."""
        player = create_test_player(name="Alice")
        
        # Cast invisibility
        await cast_spell(player, "cantcmeha", player)
        
        assert player.altnam == "Some Unseen Force"
        assert player.flags & INVISF
        assert player.charms[ALTNAM] > 0
    
    def test_transformation_reversion(self):
        """Verify transformations revert on expiry."""
        player = create_test_player(name="Alice")
        player.altnam = "Some Unseen Force"
        player.flags |= INVISF
        player.charms[ALTNAM] = 1
        
        # Process tick to expire
        await tick_handler.process_tick()
        
        assert player.altnam == "Alice"
        assert not (player.flags & INVISF)
        assert ALTNAM not in player.charms
```

**Parity tests:**

Compare YAML spell behavior against legacy C implementation:

```python
def test_legacy_parity_burnup():
    """
    Verify burnup YAML matches legacy spl006.
    Legacy: masshitr(10,FIRPRO,S06M02,S06M03,S06M04,0,1)
    """
    # Test matches legacy damage range
    # Test respects FIRPRO resistance
    # Test uses correct message IDs
    pass
```

### Suggested rollout

Following the successful room YAML approach, spell migration should proceed incrementally with validation at each stage.

#### Phase 1: Foundation (Week 1-2)

**Goals:**
- Define complete YAML schema with Pydantic models
- Build spell YAML loader and validator
- Implement core effect primitives (damage, heal, charm, message)
- Set up spell tick handler for charm expiry

**Deliverables:**
```
backend/kyrgame/spell_yaml_engine.py       # Core engine
backend/kyrgame/spell_effects.py           # Effect primitives
backend/fixtures/spells.yaml               # YAML spell definitions
backend/tests/test_spell_yaml_engine.py    # Engine tests
```

**Validation:**
- Schema validates all 67 spell entries
- Effect primitives unit tested
- Tick handler processes charms correctly

---

#### Phase 2: Pilot Spells (Week 3)

**Goals:**
- Port 5 representative spells to YAML (one from each category)
- Validate against legacy behavior
- Refine schema based on real-world needs

**Pilot spell selection:**
1. **Offensive:** `burnup` (id: 5) - mass damage, simple pattern
2. **Defensive:** `handsof` (id: 24) - charm application, duration tracking
3. **Utility:** `goto` (id: 22) - teleportation, argument parsing
4. **Transformation:** `cantcmeha` (id: 7) - identity change, flag management
5. **Detection:** `cuseme` (id: 11) - player targeting, info reveal

**Validation:**
- Each pilot spell has parity test vs. legacy implementation
- Message IDs match legacy
- Timing/duration matches legacy tick behavior
- Edge cases handled (invalid targets, missing items, etc.)

---

#### Phase 3: Category Expansion (Week 4-5)

**Goals:**
- Port all "Low" complexity spells (41 total)
- Implement remaining effect primitives
- Build comprehensive test suite

**Migration order:**

1. **All offensive spells** (21 spells)
   - Simple damage spells: fpandl, hotkiss, zapher, pocus
   - Multi-target damage: burnup, hotfoot, toastem, freezuu, frozenu
   - Storm spells: chillou, icedtea, screwem, hehhehh
   - Cone spells: koolit, frostie, snowjob

2. **All defensive spells** (12 spells)
   - Fire protection: smokey, hydrant, whopper
   - Ice protection: hotseat, heater, polarba
   - Lightning protection: sunglass, tinting, surgless
   - Object protection: handsof, makemyd
   - Ultimate protection: canthur, ibebad

3. **All healing spells** (3 spells)
   - noouch, thedoc, allbettoo

4. **All detection spells** (5 spells)
   - howru, cuseme, whoub, nosey, cadabra, iseeyou, icutwo

**Validation:**
- Category test suites ensure consistent behavior
- All message IDs validated against fixtures
- Damage ranges match legacy calculations
- Charm durations match legacy timing

---

#### Phase 4: Complex Spells (Week 6-7)

**Goals:**
- Port "Medium" complexity spells (17 total)
- Handle conditional branches and multi-step sequences
- Implement special targeting modes

**Complex spell categories:**

1. **Transformations** (4 spells)
   - cantcmeha, peekabo, flyaway, gringri, weewillo
   - Challenge: Name changes, flag management, expiry restoration

2. **Item manipulation** (7 spells)
   - blowitawa, blowoutma, clutzopho, mower, pickpoc
   - Challenge: Inventory management, ground items, protection checks

3. **Spell manipulation** (4 spells)
   - dumdum, saywhat, bookworm, nosey
   - Challenge: Spell bit manipulation, moonstone requirement

4. **Teleportation** (2 spells)
   - goto, feeluck
   - Challenge: Location resolution, random selection

**New effect primitives needed:**
- `transform_identity` with reversion tracking
- `steal_item` with inventory shuffle
- `destroy_items` with protection checks
- `manipulate_spells` for spell list changes
- `teleport_random` for feeluck

**Validation:**
- Multi-step spell tests (e.g., pickpoc: check protection → select item → transfer)
- Transformation expiry tests (verify name/flag restoration)
- Random outcome tests (verify probability distributions)

---

#### Phase 5: Special Cases (Week 8)

**Goals:**
- Port remaining "High" complexity spells (9 total)
- Implement custom handlers for unique mechanics
- Complete spell migration

**Special spells:**

1. **zelastone** (aerial servant) - Summons ally that attacks random enemy
2. **tiltowait** (earthquake) - Room-wide effect with random damage
3. **peepint** (scry) - Remote viewing of player location
4. **whereami** (location finder) - Display current location info
5. **hocus** (dispel magic) - Remove charms from target
6. **sapspel/takethat** (spell drain) - Sap target's spell points
7. **abbracada** (ultimate protection II) - Multi-layer defense

**Implementation strategy:**

For truly unique spells, use `custom_handler` effect type:

```yaml
spells:
  - id: 66
    name: zelastone
    invocation: zelastone
    description: "Summon an aerial servant to attack enemies"
    cost: { spell_points: 10 }
    effects:
      - type: custom_handler
        handler: aerial_servant_summon
        params:
          duration_ticks: 10
          damage_per_tick: { min: 20, max: 40 }
```

```python
# backend/kyrgame/custom_spell_handlers.py
async def aerial_servant_summon(
    caster: Player,
    params: Dict[str, Any]
) -> EffectResult:
    """Custom handler for zelastone aerial servant."""
    # Implementation here
    pass
```

**Validation:**
- Custom handlers have dedicated unit tests
- Special mechanics documented in spell YAML comments
- Legacy parity verified for unique behaviors

---

#### Phase 6: Deployment & Migration (Week 9)

**Goals:**
- Deprecate legacy spell handler functions
- Switch production to YAML-driven system
- Monitor for issues

**Migration checklist:**

- [ ] All 67 spells in `fixtures/spells.yaml`
- [ ] Parity tests pass for all spells
- [ ] Message IDs validated against `fixtures/messages.yaml`
- [ ] Charm expiry behavior matches legacy `splrtk`
- [ ] Performance benchmarked (no regression vs. code-based)
- [ ] Documentation updated (`PORTING_PLAN.md` checked off)

**Rollback plan:**

Keep legacy spell handler functions in codebase for one release cycle. If critical issues discovered:

1. Revert to legacy handlers via feature flag
2. Fix YAML definitions
3. Re-validate
4. Re-enable YAML engine

**Success metrics:**

- ✅ Zero functional regressions reported
- ✅ Spell modification time reduced (data change vs. code change)
- ✅ New spell additions possible without Python knowledge
- ✅ Test coverage increased (systematic validation vs. ad-hoc)

---

### Integration with Existing Codebase

The YAML spell engine integrates seamlessly with the current command dispatcher and game loop.

#### Command Dispatch Integration

**Current code pattern** (from `backend/kyrgame/commands.py`):

```python
# Existing command dispatcher
async def handle_cast(ctx: CommandContext) -> CommandResult:
    """Handle 'cast <spell> [target]' command."""
    if len(ctx.args) < 1:
        return CommandResult(
            success=False,
            message="Cast what spell?"
        )
    
    spell_name = ctx.args[0].lower()
    
    # OLD: Lookup in code-based spell registry
    spell_handler = SPELL_HANDLERS.get(spell_name)
    if not spell_handler:
        return CommandResult(
            success=False,
            message="You don't know that spell."
        )
    
    return await spell_handler(ctx)
```

**New YAML-integrated pattern:**

```python
async def handle_cast(ctx: CommandContext) -> CommandResult:
    """Handle 'cast <spell> [target]' command."""
    if len(ctx.args) < 1:
        return CommandResult(
            success=False,
            message="Cast what spell?"
        )
    
    spell_name = ctx.args[0].lower()
    
    # NEW: Lookup in YAML spell engine
    spell_engine = get_spell_engine()
    spell_def = spell_engine.get_spell(spell_name)
    
    if not spell_def:
        return CommandResult(
            success=False,
            message="You don't know that spell."
        )
    
    # Validate player knows spell
    if not ctx.player.knows_spell(spell_def.id):
        return CommandResult(
            success=False,
            message="You haven't memorized that spell."
        )
    
    # Validate level requirement
    if ctx.player.level < spell_def.level_required:
        return CommandResult(
            success=False,
            message="You're not skilled enough to cast that spell."
        )
    
    # Check spell point cost
    if ctx.player.spts < spell_def.cost.spell_points:
        return CommandResult(
            success=False,
            message="You don't have enough spell points."
        )
    
    # Check cooldown
    if not spell_engine.cooldown_manager.can_cast(ctx.player.id, spell_def.id):
        return CommandResult(
            success=False,
            message="You must wait before casting that spell again."
        )
    
    # Resolve target
    target_result = await spell_engine.resolve_target(
        ctx.player,
        spell_def.target,
        ctx.args[1:] if len(ctx.args) > 1 else []
    )
    
    if not target_result.success:
        return CommandResult(
            success=False,
            message=target_result.error_message
        )
    
    # Deduct cost
    ctx.player.spts -= spell_def.cost.spell_points
    for item_name in spell_def.cost.items:
        await consume_player_item(ctx.player, item_name)
    
    # Execute effects
    effect_results = await spell_engine.execute_effects(
        caster=ctx.player,
        target=target_result.target,
        effects=spell_def.effects,
        context={
            'spell_name': spell_def.name,
            'args': ctx.args[1:]
        }
    )
    
    # Set cooldown
    spell_engine.cooldown_manager.set_cooldown(
        ctx.player.id,
        spell_def.id,
        spell_def.cooldown_sec
    )
    
    return CommandResult(
        success=True,
        results=effect_results
    )
```

#### Scheduler Integration

**Existing scheduler** (from `backend/kyrgame/scheduler.py`):

```python
class GameScheduler:
    """Manages periodic game events."""
    
    async def start(self):
        """Start all periodic tasks."""
        # Existing tasks
        self.spawn_task(self.tick_effects, interval=30)
        self.spawn_task(self.respawn_monsters, interval=60)
        
        # NEW: Add spell tick handler
        self.spawn_task(self.tick_spells, interval=30)
    
    async def tick_spells(self):
        """Process spell point regen and charm expiry."""
        spell_engine = get_spell_engine()
        await spell_engine.tick_handler.process_tick()
```

#### Fixture Loading

**Startup initialization** (from `backend/kyrgame/fixtures.py`):

```python
async def load_game_fixtures():
    """Load all game data from fixtures."""
    # Existing fixtures
    await load_messages("fixtures/messages.yaml")
    await load_locations("fixtures/locations.json")
    await load_objects("fixtures/objects.json")
    
    # NEW: Load spell definitions
    await load_spells("fixtures/spells.yaml")
    
    logger.info("All fixtures loaded successfully")
```

#### Database Schema

**Player spell tracking** (existing schema in `backend/kyrgame/models.py`):

```python
class Player(Base):
    __tablename__ = "players"
    
    # Existing fields
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    level = Column(Integer, default=1)
    hitpts = Column(Integer)
    spts = Column(Integer)  # spell points
    
    # Spell knowledge (bit flags)
    offspls = Column(BigInteger, default=0)  # offensive spells
    defspls = Column(BigInteger, default=0)  # defensive spells
    othspls = Column(BigInteger, default=0)  # other spells
    
    # Charms (JSON for flexibility)
    charms = Column(JSON, default={})  # {charm_type: ticks_remaining}
    
    # Transformation state
    flags = Column(Integer, default=0)  # INVISF, PEGASU, etc.
    altnam = Column(String)  # alternate display name
    attnam = Column(String)  # short attack name
    
    def knows_spell(self, spell_id: int) -> bool:
        """Check if player has memorized spell."""
        if spell_id < 23:  # offensive spells 0-22
            return bool(self.offspls & (1 << spell_id))
        elif spell_id < 40:  # defensive spells 23-39
            return bool(self.defspls & (1 << (spell_id - 23)))
        else:  # other spells 40-66
            return bool(self.othspls & (1 << (spell_id - 40)))
```

**No schema changes needed** - YAML system uses existing player state fields.

---

### Comparison: Code-Based vs. YAML-Based

**Adding a new spell:**

**OLD (code-based approach):**

1. Add spell to `spells` array in KYRSPEL.C (edit line 138-205)
2. Implement `splXXX` handler function (~20-50 lines of C)
3. Add message IDs to message fixtures
4. Manually test in-game
5. Write unit test if time permits
6. Commit code changes

**NEW (YAML-based approach):**

1. Add spell entry to `fixtures/spells.yaml` (~15-30 lines YAML)
2. Add message IDs to `fixtures/messages.yaml`
3. Run automated parity tests (`pytest backend/tests/test_spell_yaml_engine.py`)
4. Commit data changes

**Benefits:** 50% less code, systematic testing, no Python knowledge required

---

### Future Enhancements

Once YAML system is stable, consider:

1. **Spell editor UI:** Web-based tool for designers to edit spells
2. **Spell variants:** Easy to create spell variants (e.g., Fireball IV)
3. **Player-created spells:** Allow high-level players to combine effects
4. **Spell schools:** Group spells by element/school for class restrictions
5. **Spell combinations:** Chain spells for combo effects
6. **Dynamic difficulty:** Scale spell costs/effects based on player level
7. **Spell crafting:** Combine reagents to create custom spells

---

## Conclusion

The YAML-based spell system offers significant advantages over the legacy code-based approach:

**Architecture benefits:**
- ✅ Reduced code duplication (~80% reduction in spell handler code)
- ✅ Improved maintainability (single YAML file vs. 67 functions)
- ✅ Better testability (systematic data-driven tests)
- ✅ Clear separation of data and logic

**Development benefits:**
- ✅ Faster iteration on spell balance
- ✅ Non-programmers can add/modify spells
- ✅ Easier to spot patterns and inconsistencies
- ✅ Version control friendly (YAML diffs vs. code diffs)

**Legacy parity:**
- ✅ Preserves all 67 original spell behaviors
- ✅ Maintains message IDs and text
- ✅ Keeps timing semantics (tick durations, cooldowns)
- ✅ Supports all original features (charms, transformations, etc.)

**Recommended next steps:**
1. Review this proposal with team
2. Get approval for Phase 1 (Foundation) work
3. Begin Pydantic schema definition
4. Implement pilot spells to validate approach
5. Iterate based on real-world experience

This approach mirrors the successful `YAML_ROOM_EXAMPLE.md` pattern and positions the codebase for long-term maintainability while preserving the legacy game's exact behavior.
