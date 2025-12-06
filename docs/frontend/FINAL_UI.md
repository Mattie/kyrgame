# Kyrandia Frontend: Final UI Summary

## Purpose
The new interface delivers a modern web rendering of Kyrandia's text-first MajorBBS experience. It keeps the command-prompt-centric flow while layering minimal affordances for navigation, session control, and live status displays.

## Experience Goals
- **Text-forward terminal:** Present room text, command outputs, and system activity in a retro terminal viewport using green-on-black styling inspired by the original CRT screenshots.
- **Prompt-first interaction:** Input lives at the bottom of the terminal card; every action is initiated by typing commands, keeping parity with the legacy flow.
- **Optional helper controls:** A compass toggle enables WASD navigation when desired, but clicking back into the prompt restores pure typing mode.
- **Progressive disclosure:** The status sidebar remains hidden until the player issues a command that returns character details (hitpoints, description, spell points, spellbook/effects). Once revealed, it stays pinned on the right and live-updates as new payloads arrive.
- **Faithful text rendering:** Activity lines echo legacy phrasing and sequencing; payloads surface inline so testers can validate parity with the original message catalogs.

## Core Requirements Captured
- MUD-style prompt beneath scrollback with monochrome terminal styling.
- Room and activity text flow from WebSocket messages and command responses, echoing the legacy MajorBBS output cadence.
- Navigation mode mapped to WASD → NWSE, toggled via a compass button beside the prompt; deactivates when the prompt is focused to prevent accidental moves.
- Right-hand status card (hidden until first status payload) showing hitpoints, spell points, self-description with bolded inventory items, active spell effects, and the spellbook.

## Component Overview
- **CommandConsole:** Retro terminal viewport with scrollback, prompt, compass toggle, mode indicators, and live connection status.
- **RoomPanel:** Snapshot of the current room (title, look text, exits, occupants, ground objects) matching fixture-driven descriptions.
- **StatusSidebar:** Sticky card that activates after the first status payload; highlights inventory terms inside the self-description and lists spell effects/spellbook entries.
- **SessionForm & ActivityLog:** Lightweight session bootstrap plus a structured log to audit raw payloads alongside the terminal view.

## Visual/Interaction Notes
- Colors draw from teal/green CRT hues; text uses monospace faces to mirror the legacy terminal aesthetic.
- Cards layer subtle glows and scanline-style shadows to keep the retro feel without sacrificing readability.
- Layout: primary column for session + terminal + room details; secondary column for the persistent status card once unlocked.

## Testing Hooks
- `data-testid="status-card"` gates the status sidebar.
- Command prompt labeled for accessibility; compass toggle labeled “Navigation mode toggle” to support automated WASD routing tests.
- Navigation mode highlights via the `mode-chip` pill; activity lines stream through the console viewport for snapshot-style assertions.
