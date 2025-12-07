# Kyrandia Frontend UI Notes

## Goals
- Preserve the text-first, MUD-style presentation seen in the legacy MajorBBS client while delivering it in a modern browser.
- Keep navigation and interaction centered on typed commands with a retro CRT aesthetic and monospaced lettering.
- Surface live state (room text, occupants, stats) in ways that mirror legacy outputs without overwhelming the console feed.

## Core Requirements
- **Primary interaction via prompt:** A bottom-aligned command prompt is the main input for movement and actions; keyboard focus steers the experience.
- **Legacy-inspired output:** Room descriptions and command responses appear in a green-on-dark CRT log with subtle scanlines to echo the DOS-era display.
- **Conditional HUD:** A right-hand status card stays hidden until the player first emits data about hitpoints, description (with inventory and effects), spell points, or spellbook via console commands. Afterward it stays pinned and live-updates.
- **Navigation toggle:** A compass button next to the prompt enables navigation mode; WASD maps to north/west/south/east respectively until the user clicks back into the prompt, with the active mode clearly highlighted.

## Interaction Model
- Command submissions echo into the log before being relayed over the WebSocket, matching the feel of typed BBS commands.
- Room changes and broadcasts stream into the CRT window while an occupants line keeps local presence visible.
- HUD data is inferred from command responses (payload fields or textual summaries) so the UI mirrors the first time stats are printed rather than assuming defaults.

## Design Touchstones
- Monospaced fonts (`DM Mono`, `VT323`, `Press Start 2P`) and neon-cyan/green palette reinforce the late-80s terminal vibe.
- Panels use dark glassmorphism with faint gradients to keep surrounding tools (session form, room info, activity log) readable without detracting from the console.
- Mode hints remind users when navigation is mapped to WASD versus free typing.

## Development Helpers
- Dev/test builds stretch the navigator across the viewport so the CRT console can breathe on ultra-wide screens while page-level scrollbars stay hidden.
- The SESSION, ROOM, and ROOM ACTIVITY helper cards are collapsible to keep the console dominant; the room command list scrolls within its card so it does not overwhelm the layout.
- CRT styling, prompt focus, and the navigation compass are mirrored in tests via the `MudConsole` component to ensure the development shell aligns with the retro experience.

## Screenshots
- Screenshot capture pending; the console layout features the command prompt, navigation toggle, and HUD after stats have been revealed.
