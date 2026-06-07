# Admin and Editing Workflows

These endpoints mirror the KYRSYSP.C sysop editor while adding modern
bearer-token authorization and validation. Use them to manage players,
content fixtures, and localized message bundles without bypassing the
runtime caches.

## Authorization model

- **Tokens**
  - `KYRGAME_ADMIN_TOKEN`: single token seeded with all roles/flags.
  - `KYRGAME_ADMIN_TOKENS`: JSON map of `{token: {"roles": [...], "flags": [...]}}`.
  - `KYRGAME_ADMIN_ALLOWLIST_PATH`: YAML map of account userids to roles/flags.
  - Admin endpoints are locked until an env token is configured or an authenticated account session has allowlist grants.
  - The API auto-loads `backend/.env` at startup; override the path with `KYRGAME_ENV_FILE`.
- **Roles**
  - `player_admin`: CRUD on players.
  - `content_admin`: Location/object/spell maintenance and script reloads.
  - `message_admin`: Message bundle replacement.
- **Flags**
  - `allow_player_rename`: required to change a player alias during update.
  - `allow_delete_players`: required for player deletion.

Example token map:

```bash
export KYRGAME_ADMIN_TOKENS='{"sysop":{"roles":["player_admin","content_admin","message_admin"],"flags":["allow_delete_players","allow_player_rename"]}}'
```

Example account allowlist:

```yaml
admins:
  sysop:
    roles:
      - player_admin
      - content_admin
      - message_admin
    flags:
      - allow_delete_players
      - allow_player_rename
```

An allowlisted userid can call `POST /auth/login` with `session_kind: "admin"` and then use the returned session token as the admin bearer token. Admin account sessions are hidden from public activity, room occupants, and player counts.

For local development, copy the sample `.env` file and source it before running the API:

```bash
cp backend/.env.example backend/.env
set -a
source backend/.env
set +a
```


## Runtime bootstrap seeding flags

Use these environment variables to control startup fixture behavior:

- `KYRGAME_RESET_ON_BOOT` (default: `0`)
  - `0`: no forced reset/reload on startup.
  - `1`: **destructive fixture reset + reload** at boot via `loader.load_all_from_fixtures(...)`; persisted content is replaced by fixture state.
- `KYRGAME_SEED_IF_EMPTY` (default: `1`)
  - Only applies when `KYRGAME_RESET_ON_BOOT=0`.
  - `1`: seed fixtures when the database is empty (no locations present).
  - `0`: do not auto-seed on startup, even if the database is empty.

### Public demo / production recommendation

Keep `KYRGAME_RESET_ON_BOOT=0` for public demo/prod deployments so restarts are non-destructive. Use explicit seed scripts and migrations when you intentionally need controlled data changes.

## HTTP endpoints

| Endpoint | Role | Notes |
| --- | --- | --- |
| `GET /admin/fixtures` | player_admin or content_admin | Returns current cache counts. |
| `GET /admin/mobs` | player_admin or content_admin | Returns the admin-only animation/mob tracker snapshot, including dryad room, brownie path state, elf last sighting, and Zar object presence. |
| `POST /admin/mobs/elf/trigger` | player_admin or content_admin | Forces the legacy Elf encounter in the requesting admin session room for parity testing; uses the same hint/gold alternation as the scheduled animation tick. |
| `POST /admin/reload-scripts` | content_admin | Hot-reloads room scripts. |
| `GET /admin/players` | player_admin | Lists cached player models. |
| `GET /admin/players/{alias}` | player_admin | Fetches a single player by canonical player id or original login alias. |
| `POST /admin/players` | player_admin | Creates a new player (full `PlayerModel` body). |
| `PUT /admin/players/{alias}` | player_admin (+`allow_player_rename` to change alias) | Validates and replaces a player by canonical player id or original login alias; keeps fixture cache in sync. |
| `DELETE /admin/players/{alias}` | player_admin + `allow_delete_players` | Deactivates active sessions, disconnects sockets, and removes the player by canonical player id or original login alias. |
| `PUT /admin/content/locations/{id}` | content_admin | Replaces a location; updates location index. |
| `PUT /admin/content/objects/{id}` | content_admin | Replaces an object; normalizes flag strings. |
| `PUT /admin/content/spells/{id}` | content_admin | Replaces a spell definition. |
| `PUT /admin/i18n/{locale}` | message_admin | Replaces a message bundle; updating the default locale also refreshes DB rows and command vocabulary. |

All payloads reuse the existing Pydantic models so validation mirrors the
legacy buffers from `KYRANDIA.H`.

## CLI helpers

The `admin_cli` script wraps the secured endpoints for operators who prefer
terminal workflows:

```bash
python -m kyrgame.scripts.admin_cli --token "$ADMIN_TOKEN" \
  push-player --file backend/fixtures/players.json --create

python -m kyrgame.scripts.admin_cli --token "$ADMIN_TOKEN" \
  update-bundle --locale en-US --file backend/fixtures/messages/en-US.legacy.json
```

Point `--base-url` at the running API if it is not on `http://localhost:8000`.
