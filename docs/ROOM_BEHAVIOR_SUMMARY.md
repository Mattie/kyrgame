# Room Routine Behavior Summary and YAML Feasibility

## Legacy Room Behaviors (from `KYRROUS.C`)

- **Room 8 — `getgol` (gem-for-gold exchange):** Trading verbs let players hand over gems; recognized gem types are removed and convert to their gold values, while a `kyragem` converts into a `kyragem`-specific reward object; other items produce a rejection message.【F:legacy/KYRROUS.C†L198-L239】
- **Room 9 — `buyspl` (spell vendor):** Buying keywords let players purchase one of 16 stocked spells; gold is deducted if affordable and the spell’s bitflag is set based on its book (offense/defense/other), otherwise an insufficient-funds flow runs.【F:legacy/KYRROUS.C†L242-L286】
- **Room 10 — `vhealr` (healer):** Offering a rose heals 10 HP up to 4 × level; missing roses or other offers are rejected.【F:legacy/KYRROUS.C†L410-L436】
- **Room 12 — `gquest` (brook/quest board):** Dig/search verbs targeting brook/water terms can yield 2–101 gold if under 10 on a random roll and player has <101 gold; otherwise nothing; also reuses drink/rose helpers for water/rose interactions.【F:legacy/KYRROUS.C†L439-L469】
- **Room 14 — `gpcone` (pinecone grove):** “Get pinecone” has a 40% chance to grant pinecone object if inventory space remains, otherwise failure text.【F:legacy/KYRROUS.C†L492-L509】
- **Room 16 — `fearno` (fearsome forest obstacle):** Saying the secret phrase from message `EGLADE` checks level 5: success levels up and prints fear-removal messaging; otherwise rejects.【F:legacy/KYRROUS.C†L660-L676】
- **Room 18 — `stumpr` (stump puzzle):** Dropping objects onto stump advances a 12-item sequence only for level-5 players; correct sequence increments stump index toward awarding spell bit SBD032 at level 6, otherwise resets or rejects with hints.【F:legacy/KYRROUS.C†L511-L546】
- **Room 19 — `fthick` (flaming thicket):** Walking into thicket triggers burn text and 10 HP damage broadcast to others.【F:legacy/KYRROUS.C†L642-L656】
- **Room 20 — `rubies` (ruby cache):** Getting a ruby can grant a ruby object 20% of the time if inventory space allows, otherwise produce failure text and deal 8 damage to a random other player.【F:legacy/KYRROUS.C†L576-L592】
- **Room 24 — `silver` (silver mine):** Offering objects checks against a four-gem sequence; correct order increments `gemidx`, and at completion (level 4 gate) grants a defensive spell bit; wrong item/order resets with flavor; praying/meditating broadcasts prayer text.【F:legacy/KYRROUS.C†L548-L575】
- **Room 26 — `ashtre` (ash tree):** Cry/weep at ashes/trees drops a shard object on the ground if room has space; otherwise warns about space. Implemented via `backend/fixtures/room_scripts/room_0026.yaml`.【F:legacy/KYRROUS.C†L677-L696】
- **Room 27 — `swrock` (switch rock):** Praying increments a rock counter and emits room message; dropping a sword on the rock after prayers grants a tiara object while missing swords trigger an error message. Implemented via `backend/fixtures/room_scripts/room_0027.yaml`.【F:legacy/KYRROUS.C†L678-L711】
- **Room 34 — `druids` (druid grove):** Touching orb with sceptre consumes the sceptre and randomly grants one of five offensive spell bits (now wired via `backend/fixtures/room_scripts/room_0034.yaml` using weighted random selection); missing sceptre yields failure text with room broadcast.【F:legacy/KYRROUS.C†L620-L639】
- **Room 35 — `terrac` (terrace):** Only special behavior is drinking water helper (implemented in `backend/fixtures/room_scripts/room_0035.yaml`); otherwise passive.【F:legacy/KYRROUS.C†L471-L478】
- **Room 36 — `waterf` (waterfall):** Allows drink-water helper and rose-gathering helper; otherwise passive.【F:legacy/KYRROUS.C†L480-L489】
- **Room 181 — `tashas` (Tashanna shrine):** Imagining a dagger spawns dagger if inventory space; examining statue prints lore; otherwise passive.【F:legacy/KYRROUS.C†L834-L857】
- **Room 182 — `refpoo` (reflection pool):** Toss dagger into pool transforms it into sword; looking at pool prints descriptive message.【F:legacy/KYRROUS.C†L859-L880】
- **Room 183 — `panthe` (pantheon chamber):** Speaking full multi-word phrase awards amulet item if inventory space; seeing symbols/pillars prints description.【F:legacy/KYRROUS.C†L882-L911】
- **Room 184 — `portal` (portal hub):** Entering the portal plays randomized descriptive sequence and broadcasts entrance to others.【F:legacy/KYRROUS.C†L913-L932】
- **Room 185 — `waller` (wall event):** Dropping a key into crevice after sesame chant teleports player to room 186; wrong actions give guidance; chanting “open sesame” arms the wall event.【F:legacy/KYRROUS.C†L934-L961】
- **Room 186 — `slotma` (slot machine cave):** Dropping a garnet into the slot consumes it; ~18% chance to award random gem, otherwise loss message.【F:legacy/KYRROUS.C†L963-L988】
- **Room 188 — `mistyr` (misty ridge):** Touch/get orb teleports to room 34; thinking/meditating on orb grants an orb object if space; dropping dagger on orb (with level 8 gate) consumes dagger and levels up.【F:legacy/KYRROUS.C†L990-L1030】
- **Room 189 — `sanman` (sandman encounter):** Digging sand has 10% chance to grant 1 gold; otherwise nothing.【F:legacy/KYRROUS.C†L1032-L1049】
- **Room 199 — `tulips` (tulip grove):** Getting a tulip grants tulip object if inventory space; otherwise failure message.【F:legacy/KYRROUS.C†L1051-L1064】
- **Room 201 — `crystt` (crystal tunnel):** Aiming wand at tree (with crystal keyword setup) and level 11 gate grants progression messaging; requires wand possession.【F:legacy/KYRROUS.C†L1066-L1084】
- **Room 204 — `rainbo` (rainbow bridge):** Breaking wand consumes it; if player already has Kyragem flag set, gives messaging; else awards Kyragem object and sets flag.【F:legacy/KYRROUS.C†L1086-L1101】
- **Room 213 — `sunshi` (sunshine chamber):** Casting `zapher` on tulip converts tulip to Kyragem shard; casting `zennyra` prints lore; offering Kyragem at level 12 triggers level-up messaging.【F:legacy/KYRROUS.C†L1103-L1131】
- **Room 218 — `demong` (demon gate):** Dropping soulstone into niche teleports player to room 219 with messaging.【F:legacy/KYRROUS.C†L1133-L1149】
- **Room 252 — `singer` (singing contest):** Singing/humming/whistling with level 19 gate levels up and prints success text.【F:legacy/KYRROUS.C†L1308-L1318】
- **Room 253 — `forgtr` (forgetful NPC):** Saying “forget” checks level 20 gate to level up with messaging.【F:legacy/KYRROUS.C†L1320-L1329】
- **Room 255 — `oflove` (goddess of love altar):** Offering love keyword at level 22 grants level-up messaging.【F:legacy/KYRROUS.C†L1331-L1340】
- **Room 257 — `believ` (faith challenge):** Saying “believe in magic” at level 21 grants level-up messaging.【F:legacy/KYRROUS.C†L1342-L1353】
- **Room 264 — `philos` (philosopher):** Saying “wonder”/“consider” at level 23 grants level-up messaging.【F:legacy/KYRROUS.C†L1355-L1364】
- **Room 280 — `truthy` (truth maze):** “Seek truth” at level 18 either damages player for 100 HP (50% chance) or levels up with messaging.【F:legacy/KYRROUS.C†L1366-L1380】
- **Room 282 — `bodyma` (body mastery):** Jump/leap chasm checks object protection charm; on success and level 13 gate grants object and level-up (dropping oldest item if full), otherwise deals 100 damage and failure text.【F:legacy/KYRROUS.C†L1155-L1180】
- **Room 285 — `mindma` (mind mastery):** Answering “time” with level 14 gate grants bracelet object, optionally dropping oldest item if inventory full, then levels up.【F:legacy/KYRROUS.C†L1182-L1198】
- **Room 288 — `heartm` (heart mastery):** Offering heart of spouse name with level 15 gate grants necklace object (dropping oldest if necessary) and levels up.【F:legacy/KYRROUS.C†L1200-L1216】
- **Room 291 — `soulma` (soul mastery):** Ignoring time at level 16 grants ring object (dropping oldest if needed) and levels up.【F:legacy/KYRROUS.C†L1218-L1230】
- **Room 293 — `fanbel` (faith and belief):** Saying the BELINF phrase at level 24 grants level-up messaging.【F:legacy/KYRROUS.C†L1377-L1392】
- **Room 295 — `devote` (devotion trial):** Saying “devote” at level 17 checks for four jewelry items (broach, pendant, locket, ring); if all present, consumes them and levels up, else failure text.【F:legacy/KYRROUS.C†L1232-L1258】
- **Room 302 — `wingam` (wing animation finale):** Answering the RIDDLE correctly in room 302 with level 25 gate triggers win broadcast and level-up reward path.【F:legacy/KYRROUS.C†L1394-L1410】

## Feasibility of YAML-Driven Room Definitions

The above routines largely follow consistent patterns—command keyword matching, item presence/consumption, probabilistic rewards, level gating with standardized `chklvl` helper, inventory capacity checks, and teleport/location changes—making them good candidates for structured data-driven handling. A YAML schema could express:

- **Triggers:** command verbs/arguments, optional required phrases, proximity of nouns (e.g., target objects/rooms).
- **Conditions:** level thresholds, possession of objects/flags/charms, inventory space, prior state counters (e.g., rock prayers, gem index, stump sequence position).
- **Actions:** item removal/addition (to player/room/random location), gold adjustments, teleportation, damage, broadcasts (self/others/room), flag mutations (e.g., `BLESSD`, `GOTKYG`), and random branches with weighted odds.
- **State Tracking:** simple counters (scroll/shard steps, stump/gem indices) stored on player or room context and incremented/reset via actions.
- **Messaging:** references to message IDs for prompt/response flows and broadcast variants.

Given these recurring structures, a room YAML with declarative triggers plus a lightweight expression/templating layer for random rolls and conditional branches would cover most behaviors without bespoke code per room. Only a handful of edge cases (multi-step prayers, complex item-sequence puzzles) need small script hooks, but even those map to reusable action primitives (counter increment, sequence validation). Overall, implementing a YAML-driven room engine appears practical and would substantially reduce future code churn for new or modified rooms while keeping parity with the legacy logic so long as the engine supports the above primitives and message lookups.
