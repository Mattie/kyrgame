# Solo Level Journey Checklist

This checklist tracks the command-level coverage for a solo player leveling from
1 through 25. The automated journey test is
`backend/tests/test_solo_level_journey.py::test_solo_level_journey_reaches_level_25_with_in_game_commands`.

The test uses the real `/auth/session` endpoint and room WebSocket command
envelope for every level-up command. Quest items are obtained through their
room commands before the level trigger. Dev setup is limited to room placement,
ordinary gemstone setup, spouse state, and the deterministic truth-maze branch.

| Target | Room | Command coverage | Setup / item path | Status |
| --- | ---: | --- | --- | --- |
| 2 | 0 | `kneel` | Start in willow room | Tested |
| 3 | 7 | `say glory be to tashanna` | Start in temple | Tested |
| 4 | 24 | `offer ruby`, `offer emerald`, `offer garnet`, `offer pearl` | Seed matching birthstone order and those stones | Tested |
| 5 | 16 | `fear no evil` | Start in fear glade | Tested |
| 6 | 18 | Full stump sequence, 12 individual `drop <gem>` commands | Seed only the next required gem before each drop | Tested |
| 7 | 101 | `offer heart and soul to tashanna` | Start in heart-and-soul room | Tested |
| 8 | 188 | `drop dagger orb` | First get dagger in room 181 with `imagine dagger` | Tested |
| 9 | 7 | Five `chant tashanna` commands, then `put charm` | First get charm in room 188 with `think orb`; use a fresh altar glow window | Tested |
| 10 | 7 | Five `chant tashanna` commands, then `put tiara` | Wait for the altar glow to reset after level 9; get dagger in room 181 with `imagine dagger`; turn it into sword in room 182 with `toss dagger pool`; pray at room 27 rock; drop sword on rock to receive tiara | Tested |
| 11 | 201 | `aim wand tree` | Get tulip in room 199 with `get tulip`; turn it into wand in room 213 with `cast zapher tulip` | Tested |
| 12 | 213 | `offer kyragem` | Carry wand from level 11; break it in room 204 with `break wand` to receive kyragem | Tested |
| 13 | 282 | `jump chasm` | Get golden key in room 183 with `say legends of the time and space are true forever and never die`; cast memorized `abbracada` for object protection | Tested |
| 14 | 285 | `answer time` | Carry key from room 183 and broach from level 13 | Tested |
| 15 | 288 | `offer heart Juliet` | Set spouse; carry key, broach, and pendant from level 14 | Tested |
| 16 | 291 | `ignore time` | Carry key, broach, pendant, and locket from level 15 | Tested |
| 17 | 295 | `devote` | Carry broach, pendant, locket, and ring earned by levels 13-16 | Tested |
| 18 | 280 | `seek truth` | Carry key from room 183; deterministic successful truth roll | Tested |
| 19 | 252 | `sing` | Carry key from room 183 | Tested |
| 20 | 253 | `forget` | Carry key from room 183 | Tested |
| 21 | 257 | `believe magic` | Carry key from room 183 | Tested |
| 22 | 255 | `offer love` | Carry key from room 183 | Tested |
| 23 | 264 | `wonder` | Carry key from room 183 | Tested |
| 24 | 293 | `believe in fantasy` | Start in belief room | Tested |
| 25 | 302 | `answer cast the spells and cross the seas, heart, soul, mind, and body are the keys` | Keep Zar room state at 302 | Tested |

## Allowed Dev Bypasses

- Level 4 birthstones: the test sets a known stone order and seeds ordinary
  gemstones for the silver offering sequence.
- Level 6 stump: the test performs all 12 individual drops, while seeding only
  the next ordinary gemstone before that drop to avoid exceeding the inventory
  cap.
- Level 18 truth maze: the test uses a deterministic successful random roll;
  manual testing can retry after death by restoring level/spellbook/state.

## Manual E2E Demo Checklist

- Start the backend and frontend.
- Create a fresh solo player session.
- Use admin setup to place the player in each listed room, then obtain quest
  items through the listed room commands.
- Run each command in order and confirm the level increases exactly once.
- For level 6, grant only the next gem before each stump drop and confirm
  `stumpi` progresses through all 12 offerings.
- For level 18, retry `seek truth` after a death branch by restoring the player
  to level 17 with the golden key.
- Reconnect after a late-game level-up and confirm the persisted player level,
  room, inventory, and spellbook state resume.
