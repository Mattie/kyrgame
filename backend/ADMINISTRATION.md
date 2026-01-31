# Admin and Editing Workflows

These endpoints mirror the KYRSYSP.C sysop editor while adding modern
bearer-token authorization and validation. Use them to manage players,
content fixtures, and localized message bundles without bypassing the
runtime caches.

## Authorization model

- **Tokens**
  - `KYRGAME_ADMIN_TOKEN`: single token seeded with all roles/flags.
  - `KYRGAME_ADMIN_TOKENS`: JSON map of `{token: {"roles": [...], "flags": [...]}}`.
  - Admin endpoints are locked until one of the tokens above is configured.
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

For local development, copy the sample `.env` file and source it before running the API:

```bash
cp backend/.env.example backend/.env
set -a
source backend/.env
set +a
```

## HTTP endpoints

| Endpoint | Role | Notes |
| --- | --- | --- |
| `GET /admin/fixtures` | player_admin or content_admin | Returns current cache counts. |
| `POST /admin/reload-scripts` | content_admin | Hot-reloads room scripts. |
| `GET /admin/players` | player_admin | Lists cached player models. |
| `GET /admin/players/{alias}` | player_admin | Fetches a single player. |
| `POST /admin/players` | player_admin | Creates a new player (full `PlayerModel` body). |
| `PUT /admin/players/{alias}` | player_admin (+`allow_player_rename` to change alias) | Validates and replaces a player; keeps fixture cache in sync. |
| `DELETE /admin/players/{alias}` | player_admin + `allow_delete_players` | Deactivates active sessions, disconnects sockets, and removes the player. |
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
