# Spell/Object Effect Parity Checklist & Effect Engine Design

This document catalogs the legacy spell/object routines in `legacy/KYRSPEL.C`, `legacy/KYROBJS.C`, and `legacy/KYRANIM.C`, then maps each routine to expected modern behavior. It also proposes a backend effect engine design, data model changes, and integration points for the command dispatcher + WebSocket broadcasts.

## Legacy mechanics summary (spells, timers, targeting)

### Spell casting & resource rules
- **Spell points & cost**: Casting removes the spell from the memorized list and deducts spell points equal to the spell’s `level` (which is also the minimum level to cast). Failure occurs if `level > gmpptr->level` or `level > gmpptr->spts`.【legacy/KYRSPEL.C:L1508-L1532】
- **Spell point regen**: `splrtk` executes every 30 ticks via `rtkick`, regenerating spell points by 2 per tick up to `2 * level`.【legacy/KYRSPEL.C:L215-L238】

### Timers & charm durations
- **Charm timers**: `splrtk` decrements `charms[]` every tick; when a charm expires, it emits `BASMSG + charm_index` and clears transformation flags for `ALTNAM` expirations (invisibility/pegasus/willow/dragon).【legacy/KYRSPEL.C:L239-L255】
- **Duration encoding**: Most protection/visibility spells set charm values as `2 * duration` (e.g., `2*4`, `2*10`). `chgbod` also increments the `ALTNAM` charm by `2 * duration` when applying a transformation/invisibility flag.【legacy/KYRSPEL.C:L324-L336】

### Targeting constraints
- **Target-required spells**: `chkstf` enforces a second argument for targeted spells. If the target is not a player in the room, it checks for objects in room/inventory and emits a failure message (plus a special damage response when targeting the “dragon” object).【legacy/KYRSPEL.C:L266-L299】
- **Combat target gating**: Direct-damage spells use `striker`, which respects protection charms and mercy levels (no damage for targets at or below the mercy threshold).【legacy/KYRSPEL.C:L338-L371】
- **AoE gating**: Mass damage spells use `masshitr`, which respects protection charms, mercy levels, and optional self-hit toggles.【legacy/KYRSPEL.C:L399-L430】

## Spell parity checklist (per legacy routine)

**Legend**:
- **Spellbook** (`sbkref`): `1` = offensive, `2` = defensive, `3` = other (per `seesbk`/`memori`).【legacy/KYRSPEL.C:L139-L205】【legacy/KYRSPEL.C:L1403-L1426】
- **Cost**: spell points equal to `level` unless otherwise noted (consumed items listed separately).【legacy/KYRSPEL.C:L1508-L1532】
- **Refs**: Each row references the spell table entry and the routine definition.

| ID | Invocation | Spellbook | Level/Cost | Targeting & constraints | Resource cost | Effects/timers | Legacy refs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | `abbracada` | 2 | 10 SP | Self-cast | None | Adds `OBJPRO` charm `+ (2*4)` (other protection II). | KYRSPEL.C L138-L145, L437-L441 |
| 1 | `allbettoo` | 2 | 17 SP | Self-cast | None | Sets HP to `4 * level` (ultimate heal). | KYRSPEL.C L139-L146, L444-L448 |
| 2 | `blowitawa` | 3 | 5 SP | Targeted player via `chkstf`; fails if target has `OBJPRO` or no items. | None | Deletes target’s first inventory item. | KYRSPEL.C L140-L146, L451-L467 |
| 3 | `blowoutma` | 3 | 12 SP | Targeted player via `chkstf`; fails if target has `OBJPRO` or no items. | None | Clears target inventory count (`npobjs=0`). | KYRSPEL.C L141-L146, L471-L485 |
| 4 | `bookworm` | 3 | 21 SP | Targeted player via `chkstf`; fails if target has `OBJPRO`. | Consumes `moonstone` from caster inventory. | Clears target spellbook bitflags (`offspls/defspls/othspls`). | KYRSPEL.C L142-L147, L490-L512 |
| 5 | `burnup` | 1 | 6 SP | AoE in room via `masshitr`. | None | Fireball I: damage 10, `FIRPRO` blocks, mercy for targets `<=1`. | KYRSPEL.C L143-L149, L517-L521 |
| 6 | `cadabra` | 2 | 4 SP | Self-cast | None | Adds `CINVIS` charm `= 2*4` (see invisibility I). | KYRSPEL.C L144-L150, L524-L528 |
| 7 | `cantcmeha` | 2 | 7 SP | Self-cast | None | Invisibility I: `chgbod` to “Unseen Force”, set `INVISF` flag, duration `2` (`ALTNAM` charm +4). | KYRSPEL.C L145-L150, L531-L538 |
| 8 | `canthur` | 2 | 16 SP | Self-cast | None | Ultimate protection I: sets `FIRPRO/ICEPRO/LIGPRO/OBJPRO` to `2*2`. | KYRSPEL.C L146-L152, L541-L548 |
| 9 | `chillou` | 1 | 20 SP | AoE in room via `masshitr`. | Consumes `pearl`. | Ice storm II: damage 30, `ICEPRO` blocks, hits self, mercy for targets `<=3`. | KYRSPEL.C L147-L153, L551-L560 |
| 10 | `clutzopho` | 3 | 5 SP | Targeted player via `chkstf`; fails if target `OBJPRO`, no items, or room full. | None | Forces target to drop all items onto room ground (up to `MXLOBS`). | KYRSPEL.C L148-L154, L564-L589 |
| 11 | `cuseme` | 3 | 3 SP | Targeted player via `chkstf`. | None | Reveals target spell points. | KYRSPEL.C L149-L155, L593-L602 |
| 12 | `dumdum` | 3 | 17 SP | Targeted player via `chkstf`; fails if target `OBJPRO` or no spells. | None | Clears target memorized spells (`nspells=0`). | KYRSPEL.C L150-L156, L606-L615 |
| 13 | `feeluck` | 3 | 10 SP | Self-cast | None | Teleports to random location `0-218`. | KYRSPEL.C L151-L157, L620-L631 |
| 14 | `firstai` | 2 | 10 SP | Self-cast | None | Heal III: +25 HP, cap at `4*level`. | KYRSPEL.C L152-L158, L634-L640 |
| 15 | `flyaway` | 3 | 10 SP | Self-cast | None | Transform to pegasus (`PEGASU` flag), duration `2` (`ALTNAM` charm +4). | KYRSPEL.C L153-L159, L644-L651 |
| 16 | `fpandl` | 1 | 2 SP | Targeted player via `striker`. | None | Firebolt I: damage 4, `FIRPRO` blocks, mercy for targets `<=0`. | KYRSPEL.C L154-L160, L654-L657 |
| 17 | `freezuu` | 1 | 14 SP | AoE in room via `masshitr`. | None | Ice ball II: damage 26, `ICEPRO` blocks, mercy for targets `<=2`. | KYRSPEL.C L155-L161, L660-L664 |
| 18 | `frostie` | 1 | 8 SP | Targeted player via `striker`. | None | Cone of cold II: damage 16, `ICEPRO` blocks, mercy for targets `<=1`. | KYRSPEL.C L156-L162, L667-L670 |
| 19 | `frozenu` | 1 | 7 SP | AoE in room via `masshitr`. | None | Ice ball I: damage 12, `ICEPRO` blocks, mercy for targets `<=1`. | KYRSPEL.C L157-L163, L673-L677 |
| 20 | `frythes` | 1 | 13 SP | Targeted player via `striker`. | None | Firebolt III: damage 22, `FIRPRO` blocks, mercy for targets `<=1`. | KYRSPEL.C L158-L164, L680-L683 |
| 21 | `gotcha` | 1 | 9 SP | Targeted player via `striker`. | None | Lightning bolt II: damage 18, `LIGPRO` blocks, mercy for targets `<=2`. | KYRSPEL.C L159-L165, L686-L689 |
| 22 | `goto` | 3 | 13 SP | Requires numeric location argument; fails if out of range `0-218`. | None | Teleport to specified location with red cloud messaging. | KYRSPEL.C L160-L166, L692-L715 |
| 23 | `gringri` | 3 | 12 SP | Self-cast | None | Transform to pseudo dragon (`PDRAGN` flag), duration `2` (`ALTNAM` charm +4). | KYRSPEL.C L161-L167, L719-L726 |
| 24 | `handsof` | 2 | 3 SP | Self-cast | None | Object protection I: `OBJPRO` charm `= 2*2`. | KYRSPEL.C L162-L168, L729-L733 |
| 25 | `heater` | 2 | 7 SP | Self-cast | None | Ice protection II: `ICEPRO` charm `= 2*8`. | KYRSPEL.C L163-L169, L736-L740 |
| 26 | `hehhehh` | 1 | 22 SP | AoE in room via `masshitr`. | Consumes `opal`. | Lightning storm: damage 32, `LIGPRO` blocks, hits self, mercy for targets `<=2`. | KYRSPEL.C L164-L170, L743-L754 |
| 27 | `hocus` | 3 | 18 SP | Targeted player via `chkstf`. | Consumes `bloodstone`. | Dispel magic: clears target `FIRPRO/ICEPRO/LIGPRO/OBJPRO` charms. | KYRSPEL.C L165-L171, L758-L777 |
| 28 | `holyshe` | 1 | 14 SP | Targeted player via `striker`. | None | Lightning bolt III: damage 24, `LIGPRO` blocks, mercy for targets `<=2`. | KYRSPEL.C L166-L172, L782-L785 |
| 29 | `hotflas` | 1 | 8 SP | AoE in room via `masshitr`. | None | Lightning ball: damage 16, `LIGPRO` blocks, mercy for targets `<=2`. | KYRSPEL.C L167-L173, L788-L792 |
| 30 | `hotfoot` | 1 | 12 SP | AoE in room via `masshitr`. | None | Fireball II: damage 22, `FIRPRO` blocks, mercy for targets `<=2`. | KYRSPEL.C L168-L174, L795-L799 |
| 31 | `hotkiss` | 1 | 5 SP | Targeted player via `striker`. | None | Firebolt II: damage 10, `FIRPRO` blocks, mercy for targets `<=1`. | KYRSPEL.C L169-L175, L802-L805 |
| 32 | `hotseat` | 2 | 3 SP | Self-cast | None | Ice protection I: `ICEPRO` charm `= 2*3`. | KYRSPEL.C L170-L176, L808-L812 |
| 33 | `howru` | 3 | 2 SP | Targeted player via `chkstf`. | None | Detect health: reports target hit points. | KYRSPEL.C L171-L177, L815-L824 |
| 34 | `hydrant` | 2 | 6 SP | Self-cast | None | Fire protection II: `FIRPRO` charm `= 2*8`. | KYRSPEL.C L172-L178, L828-L832 |
| 35 | `ibebad` | 2 | 24 SP | Self-cast | Consumes `sapphire`. | Ultimate protection II: sets `FIRPRO/ICEPRO/LIGPRO/OBJPRO` to `2*4`. | KYRSPEL.C L173-L179, L835-L851 |
| 36 | `icedtea` | 1 | 15 SP | AoE in room via `masshitr`. | None | Ice storm I: damage 20, `ICEPRO` blocks, hits self, mercy for targets `<=2`. | KYRSPEL.C L174-L180, L855-L859 |
| 37 | `icutwo` | 3 | 16 SP | Self-cast | None | See invisibility III: `CINVIS` charm `= 2*8`. | KYRSPEL.C L175-L181, L862-L866 |
| 38 | `iseeyou` | 3 | 3 SP | Self-cast | None | See invisibility II: `CINVIS` charm `= 2*4`. | KYRSPEL.C L176-L182, L869-L873 |
| 39 | `koolit` | 1 | 3 SP | Targeted player via `striker`. | None | Cone of cold I: damage 6, `ICEPRO` blocks, mercy for targets `<=0`. | KYRSPEL.C L177-L183, L876-L879 |
| 40 | `makemyd` | 2 | 8 SP | Self-cast | None | Object protection II: `OBJPRO` charm `= 2*3`. | KYRSPEL.C L178-L184, L882-L886 |
| 41 | `mower` | 3 | 7 SP | Self-cast | None | Destroy ground items: removes all `PICKUP` objects in room. | KYRSPEL.C L179-L185, L888-L905 |
| 42 | `noouch` | 2 | 1 SP | Self-cast | None | Heal I: +4 HP, cap at `4*level`. | KYRSPEL.C L180-L186, L908-L915 |
| 43 | `nosey` | 3 | 5 SP | Targeted player via `chkstf`. | None | Lists target’s memorized spells. | KYRSPEL.C L181-L187, L918-L949 |
| 44 | `peekabo` | 2 | 15 SP | Self-cast | None | Invisibility II: `chgbod` to “Unseen Force”, `INVISF` flag, duration `4` (`ALTNAM` charm +8). | KYRSPEL.C L182-L188, L954-L961 |
| 45 | `peepint` | 3 | 7 SP | Targeted player name required; fails if target not found or `OBJPRO`. | None | Scry: prints target location description and notifies both players. | KYRSPEL.C L183-L189, L964-L983 |
| 46 | `pickpoc` | 3 | 8 SP | Targeted player via `chkstf`; fails if target `OBJPRO`, no items, or caster inventory full. | None | Steals target’s first inventory item. | KYRSPEL.C L184-L190, L987-L1010 |
| 47 | `pocus` | 1 | 1 SP | Targeted player via `striker`. | None | Magic missile: damage 2, `OBJPRO` blocks, mercy for targets `<=0`. | KYRSPEL.C L185-L191, L1014-L1018 |
| 48 | `polarba` | 2 | 13 SP | Self-cast | None | Ice protection III: `ICEPRO` charm `= 2*10`. | KYRSPEL.C L186-L192, L1021-L1024 |
| 49 | `sapspel` | 1 | 11 SP | Targeted player via `chkstf`; fails if target `OBJPRO` or `spts=0`. | None | Sap spell points II: `spts -= 16` (min 0). | KYRSPEL.C L187-L193, L1027-L1040 |
| 50 | `saywhat` | 3 | 6 SP | Targeted player via `chkstf`; fails if target `OBJPRO` or no spells. | None | Forget one spell: `nspells--`. | KYRSPEL.C L188-L194, L1044-L1054 |
| 51 | `screwem` | 1 | 16 SP | AoE in room via `masshitr`. | None | Fire storm: damage 26, `FIRPRO` blocks, hits self, mercy for targets `<=2`. | KYRSPEL.C L189-L195, L1058-L1063 |
| 52 | `smokey` | 2 | 2 SP | Self-cast | None | Fire protection I: `FIRPRO` charm `= 2*3`. | KYRSPEL.C L190-L196, L1066-L1070 |
| 53 | `snowjob` | 1 | 13 SP | Targeted player via `striker`. | None | Cone of cold III: damage 20, `ICEPRO` blocks, mercy for targets `<=2`. | KYRSPEL.C L191-L197, L1073-L1076 |
| 54 | `sunglass` | 2 | 3 SP | Self-cast | None | Lightning protection I: `LIGPRO` charm `= 2*3`. | KYRSPEL.C L192-L198, L1079-L1083 |
| 55 | `surgless` | 2 | 12 SP | Self-cast | None | Lightning protection III: `LIGPRO` charm `= 2*10`. | KYRSPEL.C L193-L199, L1086-L1089 |
| 56 | `takethat` | 1 | 4 SP | Targeted player via `chkstf`; fails if target `OBJPRO` or `spts=0`. | None | Sap spell points I: `spts -= 8` (min 0). | KYRSPEL.C L194-L200, L1093-L1105 |
| 57 | `thedoc` | 2 | 5 SP | Self-cast | None | Heal II: +12 HP, cap at `4*level`. | KYRSPEL.C L195-L201, L1110-L1116 |
| 58 | `tiltowait` | 1 | 24 SP | Room-wide effect; requires `rose` in inventory. | Consumes `rose`. | Earthquake: broadcasts to room/game, damages occupants (50 if level >3), removes all pickup items in room. | KYRSPEL.C L196-L202, L1119-L1163 |
| 59 | `tinting` | 2 | 8 SP | Self-cast | None | Lightning protection II: `LIGPRO` charm `= 2*8`. | KYRSPEL.C L197-L203, L1166-L1170 |
| 60 | `toastem` | 1 | 18 SP | AoE in room via `masshitr`. | Consumes `diamond`. | Fireball III: damage 32, `FIRPRO` blocks, mercy for targets `<=2`. | KYRSPEL.C L198-L205, L1173-L1184 |
| 61 | `weewillo` | 3 | 7 SP | Self-cast | None | Transform to willowisp (`WILLOW` flag), duration `2` (`ALTNAM` charm +4). | KYRSPEL.C L199-L205, L1187-L1195 |
| 62 | `whereami` | 3 | 6 SP | Self-cast | None | Reports current location ID. | KYRSPEL.C L200-L205, L1198-L1204 |
| 63 | `whopper` | 2 | 12 SP | Self-cast | None | Fire protection III: `FIRPRO` charm `= 2*10`. | KYRSPEL.C L201-L205, L1207-L1211 |
| 64 | `whoub` | 3 | 3 SP | Targeted player via `chkstf`. | None | Detect true identity: reveals target `plyrid`. | KYRSPEL.C L202-L205, L1214-L1223 |
| 65 | `zapher` | 1 | 4 SP | Targeted player via `striker`. | None | Lightning bolt I: damage 8, `LIGPRO` blocks, mercy for targets `<=1`. | KYRSPEL.C L203-L205, L1226-L1230 |
| 66 | `zelastone` | 1 | 10 SP | Targeted player name required; if target missing, caster is hit; if target found, 90% hit chance unless target `OBJPRO`. | None | Aerial servant: deals 20–40 damage to target on success; misfire damages caster. | KYRSPEL.C L204-L205, L1233-L1272 |

## Object routine checklist (legacy `gmobjs`)

**Flag legend** (from `kyrandia.h`): `NEEDAN`, `VISIBL`, `PICKUP`, `REDABL`, `AIMABL`, `THIABL`, `RUBABL`, `DRIABL`.【legacy/KYRANDIA.H:L96-L109】

| ID | Object | Flags | Routine | Notes | Legacy refs |
| --- | --- | --- | --- | --- | --- |
| 0 | ruby | VISIBL + PICKUP | `k_nulrou` | Gem item. | KYROBJS.C L63-L66 |
| 1 | emerald | VISIBL + PICKUP + NEEDAN | `k_nulrou` | Gem item. | KYROBJS.C L67-L69 |
| 2 | garnet | VISIBL + PICKUP | `k_nulrou` | Gem item. | KYROBJS.C L70-L72 |
| 3 | pearl | VISIBL + PICKUP | `k_nulrou` | Gem item. | KYROBJS.C L73-L75 |
| 4 | aquamarine | VISIBL + PICKUP + NEEDAN | `k_nulrou` | Gem item. | KYROBJS.C L76-L78 |
| 5 | moonstone | VISIBL + PICKUP | `k_nulrou` | Gem item. | KYROBJS.C L79-L81 |
| 6 | sapphire | VISIBL + PICKUP | `k_nulrou` | Gem item. | KYROBJS.C L82-L84 |
| 7 | diamond | VISIBL + PICKUP | `k_nulrou` | Gem item. | KYROBJS.C L85-L87 |
| 8 | amethyst | VISIBL + PICKUP + NEEDAN | `k_nulrou` | Gem item. | KYROBJS.C L88-L90 |
| 9 | onyx | VISIBL + PICKUP + NEEDAN | `k_nulrou` | Gem item. | KYROBJS.C L91-L93 |
| 10 | opal | VISIBL + PICKUP + NEEDAN | `k_nulrou` | Gem item. | KYROBJS.C L94-L96 |
| 11 | bloodstone | VISIBL + PICKUP | `k_nulrou` | Gem item. | KYROBJS.C L97-L99 |
| 12 | elixir | VISIBL + PICKUP + NEEDAN + DRIABL | `k_nulrou` | Drinkable. | KYROBJS.C L100-L102 |
| 13 | staff | VISIBL + PICKUP | `k_nulrou` | Equipment. | KYROBJS.C L103-L105 |
| 14 | key | VISIBL + PICKUP | `k_nulrou` | Key item. | KYROBJS.C L106-L108 |
| 15 | locket | VISIBL + PICKUP | `k_nulrou` | Jewelry. | KYROBJS.C L109-L111 |
| 16 | amulet | VISIBL + PICKUP + NEEDAN | `k_nulrou` | Jewelry. | KYROBJS.C L112-L114 |
| 17 | pendant | VISIBL + PICKUP | `k_nulrou` | Jewelry. | KYROBJS.C L115-L117 |
| 18 | charm | VISIBL + PICKUP | `k_nulrou` | Jewelry. | KYROBJS.C L118-L120 |
| 19 | bracelet | VISIBL + PICKUP | `k_nulrou` | Jewelry. | KYROBJS.C L121-L123 |
| 20 | coronet | VISIBL + PICKUP | `k_nulrou` | Jewelry. | KYROBJS.C L124-L126 |
| 21 | tiara | VISIBL + PICKUP | `k_nulrou` | Jewelry. | KYROBJS.C L127-L129 |
| 22 | necklace | VISIBL + PICKUP | `k_nulrou` | Jewelry. | KYROBJS.C L130-L132 |
| 23 | broach | VISIBL + PICKUP | `k_nulrou` | Jewelry. | KYROBJS.C L133-L135 |
| 24 | sceptre | VISIBL + PICKUP | `k_nulrou` | Equipment. | KYROBJS.C L136-L138 |
| 25 | rod | VISIBL + PICKUP | `k_nulrou` | Equipment. | KYROBJS.C L139-L141 |
| 26 | wand | VISIBL + PICKUP | `k_nulrou` | Equipment. | KYROBJS.C L142-L144 |
| 27 | trinket | VISIBL + PICKUP | `k_nulrou` | Curio. | KYROBJS.C L145-L147 |
| 28 | soulstone | VISIBL + PICKUP | `k_nulrou` | Curio. | KYROBJS.C L148-L150 |
| 29 | kyragem | VISIBL + PICKUP | `k_nulrou` | Curio. | KYROBJS.C L151-L153 |
| 30 | dragonstaff | VISIBL + PICKUP + RUBABL | `zaritm` | Rub to summon Zar; consumes staff. | KYROBJS.C L154-L156; KYRANIM.C L176-L198 |
| 31 | potion | VISIBL + PICKUP + DRIABL | `k_nulrou` | Drinkable. | KYROBJS.C L157-L159 |
| 32 | pinecone | VISIBL + PICKUP | `k_nulrou` | Quest item. | KYROBJS.C L160-L162 |
| 33 | dagger | VISIBL + PICKUP | `k_nulrou` | Weapon. | KYROBJS.C L163-L165 |
| 34 | sword | VISIBL + PICKUP | `k_nulrou` | Weapon. | KYROBJS.C L166-L168 |
| 35 | scroll | VISIBL + PICKUP + REDABL | `k_nulrou` | Readable. | KYROBJS.C L169-L171 |
| 36 | codex | VISIBL + PICKUP + REDABL | `k_nulrou` | Readable. | KYROBJS.C L172-L174 |
| 37 | tome | VISIBL + PICKUP + REDABL | `k_nulrou` | Readable. | KYROBJS.C L175-L177 |
| 38 | parchment | VISIBL + PICKUP + REDABL | `k_nulrou` | Readable. | KYROBJS.C L178-L180 |
| 39 | ring | VISIBL + PICKUP | `k_nulrou` | Jewelry. | KYROBJS.C L181-L183 |
| 40 | rose | VISIBL + PICKUP | `k_nulrou` | Used by `tiltowait`. | KYROBJS.C L184-L186 |
| 41 | lilac | VISIBL + PICKUP | `k_nulrou` | Flower. | KYROBJS.C L187-L189 |
| 42 | orchid | VISIBL + PICKUP + NEEDAN | `k_nulrou` | Flower. | KYROBJS.C L190-L192 |
| 43 | shard | VISIBL + PICKUP | `k_nulrou` | Curio. | KYROBJS.C L193-L195 |
| 44 | tulip | VISIBL + PICKUP | `k_nulrou` | Flower. | KYROBJS.C L196-L198 |
| 45 | dryad | 0 | `k_nulrou` | NPC prop. | KYROBJS.C L199-L201 |
| 46 | tree (willow) | 0 | `k_nulrou` | Scenery prop. | KYROBJS.C L202-L204 |
| 47 | altar (temple) | 0 | `k_nulrou` | Scenery prop. | KYROBJS.C L205-L207 |
| 48 | sign (spell shop) | 0 | `k_nulrou` | Scenery prop. | KYROBJS.C L208-L210 |
| 49 | statue | 0 | `k_nulrou` | Scenery prop. | KYROBJS.C L211-L213 |
| 50 | shrine | 0 | `k_nulrou` | Scenery prop. | KYROBJS.C L214-L216 |
| 51 | machine | 0 | `k_nulrou` | Slot machine prop. | KYROBJS.C L217-L219 |
| 52 | dragon (Zar) | 0 | `k_nulrou` | Spawned by animation routines; targeting triggers backlash in `chkstf`. | KYROBJS.C L220-L222; KYRSPEL.C L266-L285 |
| 53 | altar (chamber of life) | 0 | `k_nulrou` | Scenery prop. | KYROBJS.C L223-L225 |

## Animation routine checklist (legacy `KYRANIM.C`)

These routines support object effects (Zar) and world ambience; they should be mirrored by scheduler-driven services in the backend.

| Routine | Purpose | Timing | Legacy refs |
| --- | --- | --- | --- |
| `inianm` | Initializes animations, spawns Zar at home, starts `animat` tick. | `rtkick(30)` | KYRANIM.C L88-L93 |
| `animat` | Main animation loop: calls `chkzar` and rotates dryads/elves/gem drops/zar warnings/brownies; clears one-shot room flags. | `rtkick(15)` | KYRANIM.C L110-L152 |
| `chkzar` | Moves Zar between rooms, checks for attacks; resets every 25 ticks. | Uses `zarctr` counter. | KYRANIM.C L154-L173 |
| `zaritm` | Dragonstaff use: summons Zar to room or triggers attack; consumes staff. | Immediate | KYRANIM.C L176-L198 |
| `zarfood` + `dthbyz` | Zar attack loop: cycles through BITE/BREATH/CLAW/LIGHTN; applies protections. | On Zar presence | KYRANIM.C L201-L322 |
| `pzinlc` + `rmvzar` | Place/remove Zar and associated props in rooms (dryad/tree/altars/signs/etc). | On Zar move | KYRANIM.C L211-L267 |
| `dryads` | Moves dryad NPC between forest rooms; evicts last object if room full. | Rotating tick | KYRANIM.C L325-L348 |
| `elves` | Random elf encounter: alternates between hints and gold reward. | Rotating tick | KYRANIM.C L351-L389 |
| `browns` | Brownie encounter: steals gold or inventory, or taunts. | Rotating tick | KYRANIM.C L392-L426 |
| `gemakr` | Spawns gems in random forest rooms; every 10th tick spawns random gem, otherwise garnet. | Rotating tick | KYRANIM.C L428-L449 |
| `zarapp` | Broadcasts Zar sighted warning in random room. | Rotating tick | KYRANIM.C L452-L459 |

## Backend effect engine design (proposed)

### Goals
- Apply spell/object effects consistently with legacy rules (costs, timers, targeting, protections).
- Persist active effects across sessions without inventing new gameplay restrictions.
- Emit WebSocket updates for real-time UI changes (HP/SP, room events, transformations).
- Support scheduled/timer-based expirations (charms, animations, Zar movement).

### Core services
1. **EffectEngine** (new):
   - Entry point for applying spell/object effects (`apply_spell`, `apply_object_use`).
   - Validates costs, resolves targets, and enforces protections/mercy rules.
   - Emits domain events (`EffectApplied`, `EffectExpired`, `DamageApplied`, `InventoryChanged`).
2. **EffectTimerService**:
   - Maintains ticking timers aligned with `splrtk` (spell points regen + charm decrement).
   - Drives animation ticks (`animat`) and special routines (Zar, dryads, gems).
   - Intended to run as a background task or scheduled job.
3. **EffectRepository**:
   - Persists active effects and cooldowns in DB; supports querying by player/location.

### Data model changes (new/updated tables)
- **`player_state` additions**:
  - `spell_points` (already exists as `spts`).
  - `charms` stored as tick-based counters (matching `splrtk` cadence) or an equivalent normalized table that preserves the same decrement timing.
  - `transformation` (enum: none/invisible/pegasus/willow/pseudo_dragon) + `transformation_expires_at`, ensuring identity resets mirror the legacy `ALTNAM` charm behavior.
- **`active_effects` table**:
  - `id`, `player_id`, `effect_type`, `source_spell_id`, `source_player_id`, `starts_at`, `expires_at`, `stackable`, `metadata` (JSON for damage values, etc.).
- **`cooldowns` table** (optional, off by default):
  - `id`, `player_id`, `spell_id`/`object_id`, `cooldown_expires_at` (only enable if a legacy routine explicitly requires a cooldown).
- **`room_state` / `world_state`**:
  - `room_flags` for one-shot messages (e.g., `sesame`, `chantd`, `rockpr`).
  - `npc_state` table for Zar, dryads, brownies, elves (location + timers).

### Expected effect engine behaviors (parity requirements)
- **Casting flow**: Check spell ownership, level, spell points; deduct spell points and remove spell from memorized list before applying effect (legacy `caster`).
- **Target resolution**: Enforce `chkstf` semantics for targeted spells; if no player target, allow object lookup for failure messaging and dragon backlash (Zar). Respect `OBJPRO` blocks.
- **Damage resolution**: Implement `striker` and `masshitr` semantics with protection blocks and mercy levels (low-level immunity). Apply `hitoth` style death handling (respawn at location 0 on death) or modern equivalent logic.
- **Charm timers**: Mirror `splrtk` cadence: decrement charm counters, emit expiry messages, and reset identity/flags when the transformation charm expires.
- **Item consumptions**: Enforce gem requirements for specific spells (pearl, moonstone, opal, bloodstone, sapphire, diamond, rose), removing items on successful cast.
- **Room cleanup**: Implement pickup removal for `mower` and `tiltowait`.

### Legacy fidelity considerations (player-facing)
- Avoid adding spell or object cooldowns unless the legacy code explicitly uses one; introducing cooldown UX would change pacing and player expectations.
- Keep charm and transformation timers aligned to the tick cadence (`splrtk`/`animat`) so durations feel identical to legacy play.
- Preserve legacy identity changes (invisibility/transformations) by swapping `altnam`/`attnam` and clearing flags on expiration, not merely toggling a UI state.

### Integration points
- **Command dispatcher**:
  - `cast <spell> [target]` should call `EffectEngine.apply_spell` and include the parser arguments (target name, location ID for `goto`).
  - `use`/`rub`/`drink` commands should route to `EffectEngine.apply_object_use` (e.g., dragonstaff triggers `zaritm`).
- **WebSocket payloads**:
  - `room_broadcast`: for AoE damage, item destruction, transformations, or NPC/animation events.
  - `command_response`: per-caster feedback when casting or failing a spell.
  - `player_state_update`: for HP/SP changes, charms, transformations, inventory changes, and location updates (`goto`, `feeluck`).
  - `effect_update`: optional event for timers (`effect_started`, `effect_refreshed`, `effect_expired`).

### Suggested event payload fields
- `effect_id`, `effect_type`, `source_spell_id`, `source_object_id`, `source_player_id`.
- `target_player_id`, `target_location_id` (for mass effects), `damage`, `blocked_by` (protection/mercy).
- `expires_at` for active effects; `cooldown_expires_at` for future cooldown logic.

## Implementation notes & next steps
- Use the spell/object tables as authoritative: write tests that compare the modern effect lookup against the legacy catalog above.
- For each ported spell/object, add a comment in new code linking back to the legacy source lines (per porting guidelines).
- Implement animation ticks (`animat`) in the scheduler; align `rtkick` intervals to preserve encounter cadence.
- Update `docs/PORTING_PLAN_world_object_spell_gaps.md` as each spell/object/animation is implemented.
