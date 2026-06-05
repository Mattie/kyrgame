# Kyrandia Frontend UI Notes

## Goals
- Preserve the text-first, MUD-style presentation seen in the legacy MajorBBS client while delivering it in a modern browser.
- Keep navigation and interaction centered on typed commands with a retro CRT aesthetic and monospaced lettering.
- Surface live state through the main command transcript so room text, inventory, spellbook, and spell output stay readable in one primary play surface.

## Core Requirements
- **Public route shell:** `/` is the public landing page, `/enter` is the temporary Player-ID interstitial, `/play` is the player console, `/about` carries history/context, `/leaderboard` ranks public players, and `/admin` retains development/admin tooling.
- **Primary interaction via prompt:** A bottom-aligned command prompt is the main input for movement and actions; keyboard focus steers the experience.
- **Legacy-inspired output:** Room descriptions and command responses appear in a green-on-dark CRT log with subtle scanlines to echo the DOS-era display.
- **Console-first layout:** The internal inventory/spells/self-look HUD sidebars are disabled for the solo-play milestone; those responses render in the CRT transcript, and the console uses the full primary column up to the admin tool column.
- **Navigation toggle:** A compass button next to the prompt enables navigation mode; WASD maps to north/west/south/east respectively until the user clicks back into the prompt, with the active mode clearly highlighted.
- **Public player summaries:** Landing and leaderboard data come from `/public/player-activity` and `/public/leaderboard`, using level, legacy rank title, active/recent status, and owned spellbook count from spell bitfields.

## Interaction Model
- Command submissions echo into the log before being relayed over the WebSocket, matching the feel of typed BBS commands.
- Room changes and broadcasts stream into the CRT window while an occupants line keeps local presence visible.
- Inventory, spellbook, spells, and character output stay in chronological command order. The client no longer sends silent status-card refresh commands after normal player input or reconnect.
- First-login Player-ID claims fetch the legacy `GETALS` prompt from the public message bundle, disable room overrides so new players enter at room 0, and append only `GOODPD` after claim. Blank ENTER or typed input then advances one intro page at a time (`INTROA` through `INTROD`), with normal commands, WASD navigation, and room rendering held until the final lifecycle advance opens the room socket. Player names are decorated from backend player flags as male/female wizard labels in the same inline rendering path used for gems and legacy creatures, keeping raw command text intact while making live players stand out.

## Design Touchstones
- Monospaced fonts (`DM Mono`, `VT323`, `Press Start 2P`) and neon-cyan/green palette reinforce the late-80s terminal vibe.
- Panels use dark glassmorphism with faint gradients to keep surrounding tools (session form, room info, activity log) readable without detracting from the console.
- Mode hints remind users when navigation is mapped to WASD versus free typing.

## Development Helpers
- Dev/test builds stretch the navigator across the viewport so the CRT console can breathe on ultra-wide screens while page-level scrollbars stay hidden.
- Session and admin helper cards remain available at `/admin` while `/play` renders the same `MudConsole` effect without admin panels.
- CRT styling, prompt focus, disabled HUD behavior, and the navigation compass are mirrored in tests via the `MudConsole` component to ensure the development shell aligns with the retro experience.
- `frontend/tests/solo-play.spec.ts` launches the FastAPI backend and Vite frontend together on isolated test ports, creates a browser session, runs core adventure commands, grants spell access through the admin API, and reloads to confirm persisted room state.

## Manual E2E Demo Checklist
- Start the backend and frontend.
- Claim a new 3-9 letter Player-ID from the session form and confirm only the `GOODPD` first-login text appears in the console with the wizard-styled player name.
- Press ENTER four times and confirm `INTROA`, `INTROB`, `INTROC`, and `INTROD` appear one page at a time while no room description appears.
- Press ENTER once more and confirm the room opens at room 0; with another player watching room 0, confirm the first entry broadcast says the player appeared in a flash.
- Reconnect with that Player-ID in room 12.
- Run `look`, `west`, `east`, `north`, `south`, `get garnet`, `inv`, `drop garnet`, `say hello`, `read spellbook`, `memorize whereami`, `spells`, and `cast whereami`.
- Refresh the page, reconnect with the same player and a blank room field, and confirm the player resumes in the persisted room.
- Visit `/`, confirm active/recent players and the leaderboard preview load with legacy rank titles.
- Visit `/enter`, start a session with an existing Player ID, and confirm navigation lands on `/play`.
- Visit `/play`, confirm the fire/CRT console renders and admin controls are absent.
- Visit `/leaderboard`, confirm players sort by level, then spellbook count, then Player ID.
- Visit `/admin`, confirm the session form, mob tracker, admin controls, and activity log remain available.

## Screenshots
- Screenshot capture should include the landing page, `/play` player console with the fire border, and `/leaderboard`.
