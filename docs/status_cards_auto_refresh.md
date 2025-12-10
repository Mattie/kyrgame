# Status Cards Auto-Refresh Design

## Context
The navigator UI currently builds its HUD opportunistically from recent activity log entries. Inventory data renders inline as text and there is no lifecycle for other status panes. Commands always append to the console and there is no way to resend them silently for background refreshes.

## Goals
- Treat HUD status panes (inventory now, spellbook/description/hitpoints later) as command-driven cards that appear after their first successful response.
- Add an auto-refresh toggle per card (checked by default) that silently reissues its command after player commands and on a fixed cadence while connected.
- Keep silent refresh traffic out of the console log while still updating HUD state.
- Ensure the design extends to future status commands without rewriting the HUD plumbing.

## Proposed Approach (pre-implementation)
1. **Navigator transport**
   - Add a `silent` metadata flag to outbound WebSocket commands; echo that metadata on acknowledgments and downstream events so the client can suppress logging for silent refreshes.
   - Expose a `sendCommand` option for silent dispatch without adding a command entry to the activity log.
   - Preserve the existing command acknowledgment payload shape for compatibility while layering metadata on the envelope.

2. **Status card model**
   - Track cards by status event (`inventory`, `spellbook`, `description`, `hitpoints`, `effects`). Each card stores its verb (e.g., `inv`), `autoRefresh` flag (default `true`), visibility, and the last payload/text to render.
   - Initialize cards lazily when their status event is first observed in a command response, capturing the command verb to reuse for refreshes.

3. **HUD rendering**
   - Replace the monolithic HUD block with discrete card components rendered only after activation. Each card shows its latest payload and a top-right auto-refresh checkbox (recycle emoji + tooltip).
   - Inventory remains structured (list), while other cards render text/fields from the last payload until richer data exists.

4. **Auto-refresh scheduling**
   - On each manual command submission, queue silent refreshes for all active cards with `autoRefresh` enabled.
   - Start a 5-second interval while connected that fires silent refresh commands for active auto-refresh cards; stop when disconnected or no cards are initialized.
   - Guard so no refreshes occur before a card is first activated.

5. **Testing**
   - Add NavigatorContext tests asserting metadata passthrough for silent commands and suppression of activity log entries when `silent` is set.
   - Add MudConsole/HUD tests covering card activation from command responses, auto-refresh toggle behavior, and rendering of the auto-refresh controls without polluting the console log.

## Open Questions
- Future verbs for spellbook/description/hitpoints may differ across server revisions; store the command text from the activation event to avoid hard-coding beyond defaults.
- If the server does not echo metadata, the client may need to infer silent responses; the current plan assumes metadata echoing can be wired in the gateway.

## Implementation Summary (post-implementation)
- Added WebSocket metadata echoing for `silent`/`status_card` flags in `backend/kyrgame/webapp.py` so HUD refresh traffic can be filtered out of the activity log while still updating card state.
- Expanded `NavigatorContext.sendCommand` to accept `{ silent, skipLog, meta }`, forward metadata on the wire, and mark silent responses as hidden entries for HUD processing.
- Refactored `MudConsole` HUD into discrete status cards (inventory, spellbook, description, hitpoints/effects) with per-card auto-refresh toggles defaulting to on once the card activates. Cards render only after a relevant command response arrives.
- Added silent auto-refresh scheduling after every manual command and on a 5-second interval while connected, reusing the card’s command verb and tagging requests with `status_card` metadata for traceability.
- Inventory cards now render the exact server response text (with GemstoneText styling), keeping the heading lowercase to mirror the command verb.
- Updated styles to present the HUD cards with headers, checkboxes (♻️), and clearer layout while keeping the CRT log untouched by silent refreshes.
