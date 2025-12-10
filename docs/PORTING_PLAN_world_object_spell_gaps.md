# World/Object/Spell Service Gap Inventory

This appendix enumerates the missing parity items for the world/object/spell services that must be ported from the legacy C sources. It mirrors the routine vectors and spell/object tables in `legacy/KYRLOCS.C`, `legacy/KYROBJS.C`, and `legacy/KYRSPEL.C`.

## Room routines still to port
The modern `RoomScriptEngine` currently wires routines for rooms 0 (willow), 7 (temple), 32 (spring), 38 (magic fountain), and 101 (heart-and-soul ritual). When adding new room behaviors, prefer authoring them in the YAML room scripts under `backend/fixtures/room_scripts/` so they run through the shared `YamlRoomEngine`; only fall back to bespoke Python handlers when the YAML engine would be too complex to enhance to support some of the behavior. Check off the remaining legacy routines as parity is implemented:

- [x] Room 8: `getgol` (gem-for-gold exchange)【F:legacy/KYRLOCS.C†L60-L90】
- [x] Room 9: `buyspl` (spell vendor)【F:legacy/KYRLOCS.C†L60-L90】
- [x] Room 10: `vhealr` (healer)【F:legacy/KYRLOCS.C†L60-L90】
- [x] Room 12: `gquest` (quest board)【F:legacy/KYRLOCS.C†L60-L90】
- [x] Room 14: `gpcone` (pinecone grove interactions)【F:legacy/KYRLOCS.C†L60-L90】
- [x] Room 16: `fearno` (fearsome forest obstacle)【F:legacy/KYRLOCS.C†L60-L90】
- [ ] Room 18: `stumpr` (stump puzzle)【F:legacy/KYRLOCS.C†L76-L98】
- [x] Room 19: `fthick` (thicket)【F:legacy/KYRLOCS.C†L76-L98】
- [ ] Room 20: `rubies` (ruby cache)【F:legacy/KYRLOCS.C†L76-L98】
- [x] Room 24: `silver` (silver mine/event)【F:legacy/KYRLOCS.C†L82-L99】
- [ ] Room 26: `ashtre` (ash tree)【F:legacy/KYRLOCS.C†L82-L99】
- [ ] Room 27: `swrock` (switch rock)【F:legacy/KYRLOCS.C†L82-L99】
- [ ] Room 34: `druids` (druid grove)【F:legacy/KYRLOCS.C†L92-L104】
- [ ] Room 35: `terrac` (terrace)【F:legacy/KYRLOCS.C†L92-L104】
- [ ] Room 36: `waterf` (waterfall)【F:legacy/KYRLOCS.C†L94-L104】
- [ ] Room 181: `tashas` (Tashanna shrine)【F:legacy/KYRLOCS.C†L238-L250】
- [ ] Room 182: `refpoo` (reflection pool)【F:legacy/KYRLOCS.C†L238-L250】
- [ ] Room 183: `panthe` (pantheon chamber)【F:legacy/KYRLOCS.C†L238-L250】
- [ ] Room 184: `portal` (portal hub)【F:legacy/KYRLOCS.C†L238-L250】
- [ ] Room 185: `waller` (wall event)【F:legacy/KYRLOCS.C†L238-L250】
- [ ] Room 186: `slotma` (slot machine cave)【F:legacy/KYRLOCS.C†L241-L250】
- [ ] Room 188: `mistyr` (misty ridge)【F:legacy/KYRLOCS.C†L247-L259】
- [ ] Room 189: `sanman` (sandman encounter)【F:legacy/KYRLOCS.C†L247-L259】
- [ ] Room 199: `tulips` (tulip grove)【F:legacy/KYRLOCS.C†L258-L265】
- [ ] Room 201: `crystt` (crystal tunnel)【F:legacy/KYRLOCS.C†L259-L265】
- [ ] Room 204: `rainbo` (rainbow bridge)【F:legacy/KYRLOCS.C†L262-L270】
- [ ] Room 213: `sunshi` (sunshine chamber)【F:legacy/KYRLOCS.C†L272-L276】
- [ ] Room 218: `demong` (demon gate)【F:legacy/KYRLOCS.C†L276-L283】
- [ ] Room 252: `singer` (singing contest)【F:legacy/KYRLOCS.C†L312-L320】
- [ ] Room 253: `forgtr` (forgetful NPC)【F:legacy/KYRLOCS.C†L312-L320】
- [ ] Room 255: `oflove` (goddess of love altar)【F:legacy/KYRLOCS.C†L312-L320】
- [ ] Room 257: `believ` (faith challenge)【F:legacy/KYRLOCS.C†L312-L320】
- [ ] Room 264: `philos` (philosopher)【F:legacy/KYRLOCS.C†L324-L334】
- [ ] Room 280: `truthy` (truth maze)【F:legacy/KYRLOCS.C†L337-L343】
- [ ] Room 282: `bodyma` (body mastery)【F:legacy/KYRLOCS.C†L340-L348】
- [ ] Room 285: `mindma` (mind mastery)【F:legacy/KYRLOCS.C†L342-L349】
- [ ] Room 288: `heartm` (heart mastery)【F:legacy/KYRLOCS.C†L348-L353】
- [ ] Room 291: `soulma` (soul mastery)【F:legacy/KYRLOCS.C†L349-L356】
- [ ] Room 293: `fanbel` (faith and belief)【F:legacy/KYRLOCS.C†L352-L356】
- [ ] Room 295: `devote` (devotion trial)【F:legacy/KYRLOCS.C†L353-L360】
- [ ] Room 302: `wingam` (wing animation chamber)【F:legacy/KYRLOCS.C†L360-L364】

## Object effects missing from ObjectEffectEngine
`ObjectEffectEngine` only defines behaviors for object IDs 32 (pinecone) and 33 (dagger). Check off catalog entries from `gmobjs` as effect mappings, cooldowns, and target/resource rules are implemented:

- [ ] IDs 0–11: gems (ruby, emerald, garnet, pearl, aquamarine, moonstone, sapphire, diamond, amethyst, onyx, opal, bloodstone)【F:legacy/KYROBJS.C†L63-L99】
- [ ] ID 12: elixir (drinkable)【F:legacy/KYROBJS.C†L100-L103】
- [ ] IDs 13–29: equipment/curios (staff, key, locket, amulet, pendant, charm, bracelet, coronet, tiara, necklace, broach, sceptre, rod, wand, trinket, soulstone, kyragem)【F:legacy/KYROBJS.C†L103-L154】
- [ ] ID 30: dragonstaff (rub-to-summon Zar behavior via `zaritm`)【F:legacy/KYROBJS.C†L154-L157】【F:legacy/KYRANIM.C†L206-L237】
- [ ] ID 31: potion (drinkable)【F:legacy/KYROBJS.C†L157-L160】
- [ ] ID 34: sword (attack item)【F:legacy/KYROBJS.C†L165-L169】
- [ ] IDs 35–38: readables (scroll, codex, tome, parchment)【F:legacy/KYROBJS.C†L169-L178】
- [ ] IDs 39–44: jewelry/flowers (ring, rose, lilac, orchid, shard, tulip)【F:legacy/KYROBJS.C†L181-L197】
- [ ] IDs 45–53: scenery/NPC props (dryad, willow tree, temple altar, spell-shop sign, forest statue, hidden shrine, slot machine, Zar dragon, chamber-of-life altar)【F:legacy/KYROBJS.C†L199-L225】

## Spell behaviors, timers, and animations still to model
`SpellEffectEngine` currently applies generic costs/cooldowns and only specializes the `flyaway` (ID 16) and `weewillo` (ID 62) transformations. Check off each legacy `spells` entry once explicit effect handling (including timers/charms/animations) is implemented:

- [ ] ID 0 `abbracada` (other protection II)【F:legacy/KYRSPEL.C†L138-L145】
- [ ] ID 1 `allbettoo` (ultimate heal)【F:legacy/KYRSPEL.C†L138-L145】
- [ ] ID 2 `blowitawa` (destroy one item)【F:legacy/KYRSPEL.C†L140-L146】
- [ ] ID 3 `blowoutma` (destroy all items)【F:legacy/KYRSPEL.C†L140-L146】
- [ ] ID 4 `bookworm` (zap other's spell book)【F:legacy/KYRSPEL.C†L141-L148】
- [ ] ID 5 `burnup` (fireball I)【F:legacy/KYRSPEL.C†L142-L149】
- [ ] ID 6 `cadabra` (see invisibility I)【F:legacy/KYRSPEL.C†L143-L150】
- [ ] ID 7 `cantcmeha` (invisibility I)【F:legacy/KYRSPEL.C†L143-L150】
- [ ] ID 8 `canthur` (ultimate protection I)【F:legacy/KYRSPEL.C†L145-L152】
- [ ] ID 9 `chillou` (ice storm II)【F:legacy/KYRSPEL.C†L147-L154】
- [ ] ID 10 `clutzopho` (drop all items)【F:legacy/KYRSPEL.C†L148-L155】
- [ ] ID 11 `cuseme` (detect power)【F:legacy/KYRSPEL.C†L149-L156】
- [ ] ID 12 `dumdum` (forget all spells)【F:legacy/KYRSPEL.C†L150-L157】
- [ ] ID 13 `feeluck` (teleport random)【F:legacy/KYRSPEL.C†L151-L158】
- [ ] ID 14 `firstai` (heal III)【F:legacy/KYRSPEL.C†L152-L159】
- [ ] ID 15 `flyaway` (pegasus transformation; needs timers/flags beyond current stub)【F:legacy/KYRSPEL.C†L153-L160】
- [ ] ID 16 `fpandl` (firebolt I)【F:legacy/KYRSPEL.C†L154-L161】
- [ ] ID 17 `freezuu` (ice ball II)【F:legacy/KYRSPEL.C†L155-L162】
- [ ] ID 18 `frostie` (cone of cold II)【F:legacy/KYRSPEL.C†L156-L163】
- [ ] ID 19 `frozenu` (ice ball I)【F:legacy/KYRSPEL.C†L157-L164】
- [ ] ID 20 `frythes` (firebolt III)【F:legacy/KYRSPEL.C†L158-L165】
- [ ] ID 21 `gotcha` (lightning bolt II)【F:legacy/KYRSPEL.C†L159-L166】
- [ ] ID 22 `goto` (teleport specific)【F:legacy/KYRSPEL.C†L160-L167】
- [ ] ID 23 `gringri` (pseudo-dragon form)【F:legacy/KYRSPEL.C†L161-L168】
- [ ] ID 24 `handsof` (object protection I)【F:legacy/KYRSPEL.C†L162-L169】
- [ ] ID 25 `heater` (ice protection II)【F:legacy/KYRSPEL.C†L163-L170】
- [ ] ID 26 `hehhehh` (lightning storm)【F:legacy/KYRSPEL.C†L164-L171】
- [ ] ID 27 `hocus` (dispel magic)【F:legacy/KYRSPEL.C†L165-L172】
- [ ] ID 28 `holyshe` (lightning bolt III)【F:legacy/KYRSPEL.C†L166-L173】
- [ ] ID 29 `hotflas` (lightning ball)【F:legacy/KYRSPEL.C†L167-L174】
- [ ] ID 30 `hotfoot` (fireball II)【F:legacy/KYRSPEL.C†L168-L175】
- [ ] ID 31 `hotkiss` (firebolt II)【F:legacy/KYRSPEL.C†L169-L176】
- [ ] ID 32 `hotseat` (ice protection I)【F:legacy/KYRSPEL.C†L170-L177】
- [ ] ID 33 `howru` (detect health)【F:legacy/KYRSPEL.C†L171-L178】
- [ ] ID 34 `hydrant` (fire protection II)【F:legacy/KYRSPEL.C†L172-L179】
- [ ] ID 35 `ibebad` (ultimate protection II)【F:legacy/KYRSPEL.C†L173-L180】
- [ ] ID 36 `icedtea` (ice storm I)【F:legacy/KYRSPEL.C†L174-L181】
- [ ] ID 37 `icutwo` (see invisibility III)【F:legacy/KYRSPEL.C†L175-L182】
- [ ] ID 38 `iseeyou` (see invisibility II)【F:legacy/KYRSPEL.C†L176-L183】
- [ ] ID 39 `koolit` (cone of cold I)【F:legacy/KYRSPEL.C†L177-L184】
- [ ] ID 40 `makemyd` (object protection II)【F:legacy/KYRSPEL.C†L178-L185】
- [ ] ID 41 `mower` (destroy ground items)【F:legacy/KYRSPEL.C†L179-L186】
- [ ] ID 42 `noouch` (heal I)【F:legacy/KYRSPEL.C†L180-L187】
- [ ] ID 43 `nosey` (read memorized spells)【F:legacy/KYRSPEL.C†L181-L188】
- [ ] ID 44 `peekabo` (invisibility II)【F:legacy/KYRSPEL.C†L182-L189】
- [ ] ID 45 `peepint` (scry someone)【F:legacy/KYRSPEL.C†L183-L190】
- [ ] ID 46 `pickpoc` (steal item)【F:legacy/KYRSPEL.C†L184-L191】
- [ ] ID 47 `pocus` (magic missile)【F:legacy/KYRSPEL.C†L185-L192】
- [ ] ID 48 `polarba` (ice protection III)【F:legacy/KYRSPEL.C†L186-L193】
- [ ] ID 49 `sapspel` (sap spell points II)【F:legacy/KYRSPEL.C†L187-L194】
- [ ] ID 50 `saywhat` (forget one spell)【F:legacy/KYRSPEL.C†L188-L195】
- [ ] ID 51 `screwem` (fire storm)【F:legacy/KYRSPEL.C†L189-L196】
- [ ] ID 52 `smokey` (fire protection I)【F:legacy/KYRSPEL.C†L190-L197】
- [ ] ID 53 `snowjob` (cone of cold III)【F:legacy/KYRSPEL.C†L191-L198】
- [ ] ID 54 `sunglass` (lightning protection I)【F:legacy/KYRSPEL.C†L192-L199】
- [ ] ID 55 `surgless` (lightning protection III)【F:legacy/KYRSPEL.C†L193-L200】
- [ ] ID 56 `takethat` (sap spell points I)【F:legacy/KYRSPEL.C†L194-L201】
- [ ] ID 57 `thedoc` (heal II)【F:legacy/KYRSPEL.C†L195-L202】
- [ ] ID 58 `tiltowait` (earthquake)【F:legacy/KYRSPEL.C†L196-L203】
- [ ] ID 59 `tinting` (lightning protection II)【F:legacy/KYRSPEL.C†L197-L204】
- [ ] ID 60 `toastem` (fireball III)【F:legacy/KYRSPEL.C†L198-L205】
- [ ] ID 61 `weewillo` (willowisp transformation; needs timer/animation)【F:legacy/KYRSPEL.C†L199-L205】
- [ ] ID 62 `whereami` (location finder)【F:legacy/KYRSPEL.C†L200-L204】
- [ ] ID 63 `whopper` (fire protection III)【F:legacy/KYRSPEL.C†L201-L205】
- [ ] ID 64 `whoub` (detect true identity)【F:legacy/KYRSPEL.C†L202-L205】
- [ ] ID 65 `zapher` (lightning bolt I)【F:legacy/KYRSPEL.C†L203-L206】
- [ ] ID 66 `zelastone` (aerial servant)【F:legacy/KYRSPEL.C†L203-L206】

Each spell entry above also ties to timers/charms processed in `splrtk` (regen and expiration logic) that need to be mirrored when wiring the Python spell timer repository.【F:legacy/KYRSPEL.C†L215-L259】
