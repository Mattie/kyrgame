# Legacy Command Porting Guide

This document enumerates the legacy Kyrandia player commands so the modern dispatcher and client can be verified against the original behavior. Each entry notes the command verbs, the legacy handler, and a summary of its effects. Use the porting checklist columns to track completion and ensure that each command not only triggers on the server but also renders its final text properly in the frontend client.

## Primary command handlers

| Commands | Legacy handler | Behavioral summary | Ported & server parity | Frontend rendering verified |
| --- | --- | --- | --- | --- |
| `?`, `help` | `helper` | Displays contextual help screens or the general help message depending on optional topic flags. | [ ] | [ ] |
| `aim`, `point` | `aimer` | Aims an item at a target and routes through object-specific logic when the item supports aiming. | [ ] | [ ] |
| `brief` / `unbrief` | `briefr` / `ubrief` | Toggles brief room descriptions on or off for the player. | [ ] | [ ] |
| `cast`, `chant` | `caster` | Validates spell knowledge, level, and spell points before invoking the spell routine and deducting costs. | [ ] | [ ] |
| `check`, `count` (incl. `count gold`) | `countr` / `gldcnt` | Shows generic count feedback or gold-specific totals. | [ ] | [ ] |
| `comfort`, `cuddle`, `embrace`, `french`, `hold`, `love`, `rape`, `romance`, `squeeze`, `tickle` | `kissr1` | Performs friendly/intimate emotes toward targets using the shared kissing utility. | [ ] | [ ] |
| `hug`, `kick`, `kiss`, `pinch`, `punch`, `slap`, `smack`, `smooch` | `kissr2` | Performs the alternate kissing/physical interaction flow with target validation. | [ ] | [ ] |
| `concentrate`, `meditate`, `think` | `thinkr` | Thinks about an item (or telepathically via amulet), delegating to item logic when allowed. | [ ] | [ ] |
| `drink`, `swallow` | `drinkr` | Consumes a drinkable item, triggering its effect when allowed. | [ ] | [ ] |
| `drop` | `dropit` | Drops an item from inventory into the room, with checks for ownership, curses, and room capacity. | [ ] | [ ] |
| `east`, `e`, `west`, `w`, `north`, `n`, `south`, `s` | `gi_east` / `gi_west` / `gi_north` / `gi_south` | Moves the player via room exits using `movutl`, broadcasting departure/arrival text. | [ ] | [ ] |
| `examine`, `look`, `see` | `looker` | Describes objects, players, or room state (including brief descriptions) depending on arguments. | [ ] | [ ] |
| `fly` | `flyrou` | Handles flight attempts, delegating to will-o-wisp or pegasus routines when available. | [ ] | [ ] |
| `get`, `grab`, `pickpocket`, `pilfer`, `snatch`, `steal`, `take` | `getter` | Gets items from the room or another player with theft chance handling and inventory limits. | [ ] | [ ] |
| `give`, `hand`, `pass`, `toss` | `giveit` | Gives items or gold to another player, handling currency parsing and item transfers. | [ ] | [ ] |
| `gold` | `gldcnt` | Shortcut to display current gold total with singular/plural handling. | [ ] | [ ] |
| `hits` | `hitctr` | Displays hit point totals/status. | [ ] | [ ] |
| `inv` | `gi_invrou` | Shows the player’s inventory contents. | [ ] | [ ] |
| `learn`, `memorize` | `memori` | Learns or memorizes spells through the spellbook logic. | [ ] | [ ] |
| `note`, `say`, `comment` | `speakr` | Sends a spoken message to the room with local echo and nearby broadcast text. | [ ] | [ ] |
| `pray` | `prayer` | Performs the prayer routine. | [ ] | [ ] |
| `push`, `shove` | `shover` | Attempts to shove another player, including resistance and state updates. | [ ] | [ ] |
| `read` | `reader` | Reads items such as scrolls or the spellbook, invoking `scroll` for magical items. | [ ] | [ ] |
| `rub` | `rubber` | Rubs an item and triggers its rub-enabled effect when applicable. | [ ] | [ ] |
| `scream`, `shout`, `shriek`, `yell`, `yell` | `yeller` | Delivers shouted messages with uppercase emphasis and broadcasts. | [ ] | [ ] |
| `spells` | `shwpsp` | Lists known spells for the player. | [ ] | [ ] |
| `think` variants (already covered) | `thinkr` | See above. | [ ] | [ ] |
| `what?`, `where?`, `why?`, `how?` | `ponder` | Responds with rhetorical/pondering text. | [ ] | [ ] |
| `whisper` | `whispr` | Sends a directed whisper to a specific player if present. | [ ] | [ ] |
| `wink` | `winker` | Performs a wink emote toward another player. | [ ] | [ ] |

## Simple emote commands

These commands route through the `smparr` table, emitting a short message to the player and room. Most simply echo canned text; those with `speak` set to `1` can piggyback on `speakr` when extra text is supplied.

| Command | Player text | Room text | Speak flag | Ported & server parity | Frontend rendering verified |
| --- | --- | --- | --- | --- | --- |
| blink | "Blink!" | "blinking %s eyes in disbelief!" | 0 | [ ] | [ ] |
| blush | "Blush." | "blushing and turning bright red!" | 0 | [ ] | [ ] |
| boo | "BOO!" | "booing and yelling for the hook!" | 1 | [ ] | [ ] |
| bow | "Bow." | "bowing rather modestly." | 0 | [ ] | [ ] |
| burp | "Urrrrp!" | "belching rudely!" | 1 | [ ] | [ ] |
| cackle | "Cackle, cackle!" | "cackling frighteningly!" | 1 | [ ] | [ ] |
| cheer | "Rah, rah, rah!" | "cheering enthusiastically!" | 1 | [ ] | [ ] |
| chuckle | "Heh, heh, heh." | "chuckling under %s breath." | 1 | [ ] | [ ] |
| clap | "Clap, clap." | "clapping in admiration." | 0 | [ ] | [ ] |
| cough | "Ahem." | "coughing loud and harshly." | 1 | [ ] | [ ] |
| cry | "Awwwww." | "crying %s little heart out." | 1 | [ ] | [ ] |
| dance | "How graceful!" | "dancing with soaring spirits!" | 0 | [ ] | [ ] |
| fart | "Yuck." | "emanating a horrible odor." | 0 | [ ] | [ ] |
| frown | "Frown." | "frowning unhappily." | 0 | [ ] | [ ] |
| gasp | "WOW!" | "gasping in total amazement!" | 1 | [ ] | [ ] |
| giggle | "Giggle, giggle!" | "giggling like a hyena." | 1 | [ ] | [ ] |
| grin | "What a grin!" | "grinning from ear to ear." | 0 | [ ] | [ ] |
| groan | "Groan!" | "groaning with disgust." | 1 | [ ] | [ ] |
| growl | "Growl!" | "growling like a rabid bear!" | 1 | [ ] | [ ] |
| hiss | "Hisss!" | "hissing like an angry snake!" | 1 | [ ] | [ ] |
| howl | "Howl!" | "howling like a dog in heat!" | 1 | [ ] | [ ] |
| laugh | "What's so funny?" | "laughing %s head off!" | 1 | [ ] | [ ] |
| lie | "Comfortable?" | "lying down comfortably." | 1 | [ ] | [ ] |
| moan | "Moan!" | "moaning loudly." | 1 | [ ] | [ ] |
| nod | "Nod." | "nodding in agreement." | 0 | [ ] | [ ] |
| piss | "If you say so." | "lifting %s leg strangely." | 0 | [ ] | [ ] |
| pout | "Wasdamatta?" | "pouting with tearful eyes." | 1 | [ ] | [ ] |
| shit | "Find a toilet!" | "grunting on %s knees." | 0 | [ ] | [ ] |
| shrug | "Shrug." | "shrugging with indifference." | 0 | [ ] | [ ] |
| sigh | "Sigh." | "sighing wistfully." | 1 | [ ] | [ ] |
| sing | "Lalalala." | "singing a cheerful melody." | 1 | [ ] | [ ] |
| sit | "Ok, now what?" | "sitting down for a bit." | 0 | [ ] | [ ] |
| smile | "Smile!" | "smiling kindly." | 0 | [ ] | [ ] |
| smirk | "Smirk." | "smirking in disdain." | 0 | [ ] | [ ] |
| sneeze | "Waaacho!" | "sneezing %s brains out!" | 0 | [ ] | [ ] |
| snicker | "Snicker, snicker." | "snickering evily." | 1 | [ ] | [ ] |
| sniff | "Sniff." | "sniffling woefully." | 0 | [ ] | [ ] |
| sob | "Sob!" | "sobbing pitifully." | 1 | [ ] | [ ] |
| whistle | "Whistle." | "whistling a faintly familiar tune." | 1 | [ ] | [ ] |
| yawn | "Aaarhh." | "yawning with boredom." | 1 | [ ] | [ ] |

## Porting checkpoints

- [ ] For each command above, confirm the modern dispatcher enforces the same preconditions (items present, spell costs, inventory limits, level gates) noted in the legacy handlers.
- [ ] Validate that each command’s output text appears correctly in the client UI (including nearby/whisper/yell scopes), not just in server logs.
- [ ] Add tests that assert both server-side effects and client-visible payloads for every ported command.
- [ ] Update fixtures or message catalogs when legacy text is surfaced so the frontend can render localized output faithfully.
