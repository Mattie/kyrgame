# Kyrandia Frontend UI Notes

## Goals
- Preserve the text-first, MUD-style presentation seen in the legacy MajorBBS client while delivering it in a modern browser.
- Keep navigation and interaction centered on typed commands with a retro CRT aesthetic and monospaced lettering.
- Surface live state through the main command transcript so room text, inventory, spellbook, and spell output stay readable in one primary play surface.

## Core Requirements
- **Primary interaction via prompt:** A bottom-aligned command prompt is the main input for movement and actions; keyboard focus steers the experience.
- **Legacy-inspired output:** Room descriptions and command responses appear in a green-on-dark CRT log with subtle scanlines to echo the DOS-era display.
- **Console-first layout:** The internal inventory/spells/self-look HUD sidebars are disabled for the solo-play milestone; those responses render in the CRT transcript, and the console uses the full primary column up to the admin tool column.
- **Navigation toggle:** A compass button next to the prompt enables navigation mode; WASD maps to north/west/south/east respectively until the user clicks back into the prompt, with the active mode clearly highlighted.

## Interaction Model
- Command submissions echo into the log before being relayed over the WebSocket, matching the feel of typed BBS commands.
- Room changes and broadcasts stream into the CRT window while an occupants line keeps local presence visible.
- Inventory, spellbook, spells, and character output stay in chronological command order. The client no longer sends silent status-card refresh commands after normal player input or reconnect.

## Design Touchstones
- Monospaced fonts (`DM Mono`, `VT323`, `Press Start 2P`) and neon-cyan/green palette reinforce the late-80s terminal vibe.
- Panels use dark glassmorphism with faint gradients to keep surrounding tools (session form, room info, activity log) readable without detracting from the console.
- Mode hints remind users when navigation is mapped to WASD versus free typing.

## Development Helpers
- Dev/test builds stretch the navigator across the viewport so the CRT console can breathe on ultra-wide screens while page-level scrollbars stay hidden.
- Session and admin helper cards remain available in the right-side development column while the primary column is reserved for the playable console.
- CRT styling, prompt focus, disabled HUD behavior, and the navigation compass are mirrored in tests via the `MudConsole` component to ensure the development shell aligns with the retro experience.
- `frontend/tests/solo-play.spec.ts` launches the FastAPI backend and Vite frontend together on isolated test ports, creates a browser session, runs core adventure commands, grants spell access through the admin API, and reloads to confirm persisted room state.

## Manual E2E Demo Checklist
- Start the backend and frontend.
- Create a player session in room 12.
- Run `look`, `west`, `east`, `north`, `south`, `get garnet`, `inv`, `drop garnet`, `say hello`, `read spellbook`, `memorize whereami`, `spells`, and `cast whereami`.
- Refresh the page, reconnect with the same player and a blank room field, and confirm the player resumes in the persisted room.
- Capture a screenshot showing the console using the full primary space and the admin tools still available on the right.

## Screenshots
- Screenshot capture should show the console layout with the command prompt, navigation toggle, no internal status HUD, and the admin tool column retained for development setup.
