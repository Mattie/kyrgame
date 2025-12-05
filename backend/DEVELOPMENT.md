# Backend Development Environment

This guide captures the minimal steps to install the PyYAML, Pydantic, and SQLAlchemy tooling we rely on for fixture validation and database tests.

## Install dependencies

These packages are already pinned in `requirements.txt` for use by both the application code and the tests:

- `PyYAML>=6.0,<7`
- `pydantic>=2.6,<3`
- `SQLAlchemy>=2.0,<3`

Set up a fresh virtual environment and install everything with pip:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
python -m pip install pytest
```

The final `pytest` install ensures the test runner itself is available locally even though the core dependencies are already listed for production use.

## Sanity checks

Run the test suite to confirm the tools are present and working:

```bash
pytest backend/tests/test_dependency_health.py
```

The `test_dependency_health` module exercises all three libraries:

- PyYAML parses a sample YAML payload
- Pydantic validates and coerces values into a typed model
- SQLAlchemy creates an in-memory SQLite table and round-trips a row

If you want to run the broader fixture tests after installing the dependencies, execute:

```bash
pytest backend/tests
```

## Build an offline content bundle

To package localized messages and other fixtures for offline-capable clients, run:

```bash
python -m kyrgame.scripts.package_content --output legacy/Dist/offline-content.json
```

The command emits a single JSON file with the default locale message bundle, static content fixtures, and a timestamp clients can use to validate cache freshness.

## HTTP + WebSocket API reference (fixture-driven)

These routes are backed by the in-memory fixtures loaded during app startup. Unless noted otherwise, they do **not** require authentication. Bearer session tokens are created via `/auth/session` and reused for the validation endpoint and WebSocket joins.

### Authentication

**Create or resume a session**

```
POST /auth/session
Content-Type: application/json

{
  "player_id": "hero",                # required string
  "resume_token": "...",              # optional existing token to resume
  "allow_multiple": false,             # optional; defaults to false for single-session enforcement
  "room_id": 7                         # optional starting room override
}
```

Successful creation returns `201 Created`; resumes return `200 OK`:

```
{
  "status": "created",
  "session": {
    "token": "<bearer-token>",
    "player_id": "hero",
    "room_id": 7,
    "first_login": true,
    "resumed": false,
    "replaced_sessions": 0
  }
}
```

> TODO: The repository tracks `expires_at`/`last_seen` for session tokens, but those fields are not yet surfaced in the HTTP response. A contract test has been added to guard the gap until the API is updated.

Example cURL:

```bash
curl -X POST http://localhost:8000/auth/session \
  -H 'Content-Type: application/json' \
  -d '{"player_id": "hero", "room_id": 7}'
```

**Validate an active session**

```
GET /auth/session
Authorization: Bearer <token>
```

Returns the same envelope shape as creation with `status: "active"` and the stored `room_id`.

**Logout**

```
POST /auth/logout
Authorization: Bearer <token>
```

Returns `{ "status": "logged_out" }` and closes any active WebSocket associated with the token.

### Fixture lookups

**List commands**

```
GET /commands
```

Response: an array of command definitions with IDs and optional handler routes:

```
[
  { "id": 1, "command": "north", "payonl": false, "cmdrou": "lcrous" },
  ...
]
```

**List locations**

```
GET /world/locations
```

Response: an array of location entries mirroring `KYRLOCS` fields:

```
[
  {
    "id": 0,
    "brfdes": "Edge of the Forest",
    "objlds": "The path is narrow and mossy...",
    "nlobjs": 1,
    "objects": [101],
    "gi_north": 1,
    "gi_south": -1,
    "gi_east": -1,
    "gi_west": -1
  }
]
```

**List objects**

```
GET /objects
```

Response: an array of object catalog entries:

```
[
  {
    "id": 101,
    "name": "Key",
    "objdes": 42,
    "auxmsg": 900,
    "flags": ["can_pick_up"],
    "objrou": "obj_key"
  }
]
```

**Localization bundles**

```
GET /i18n/<locale>/messages
```

Response: the locale metadata plus the message catalog map:

```
{
  "version": "1.0.0",
  "locale": "en-US",
  "catalog_id": "kyrandia",
  "messages": {
    "WELCOME": "Welcome to Kyrandia!",
    "CMD001": "You walk north",
    ...
  }
}
```

Example cURL (with locale discovery):

```bash
curl http://localhost:8000/i18n/locales
curl http://localhost:8000/i18n/en-US/messages | jq '.messages.WELCOME'
```

### WebSocket room gateway

Connect with the bearer token returned by `/auth/session`:

```
ws://localhost:8000/ws/rooms/<room_id>?token=<bearer-token>
```

Upon connection, the gateway emits `room_welcome` followed by broadcasts when other players enter or chat. Room fan-out messages use a common envelope:

```
{
  "type": "room_broadcast",
  "room": 7,
  "payload": {
    "event": "player_enter",       # or "chat", "player_moved", etc.
    "type": "player_moved",
    "player": "hero",
    "from": 6,
    "to": 7,
    "description": "Edge of the Forest",
    "command_id": 1,
    "message_id": "CMD001"
  }
}
```

Chat events carry the text and mode in the payload instead of movement fields:

```
{
  "type": "room_broadcast",
  "room": 7,
  "payload": {
    "event": "chat",
    "type": "chat",
    "from": "hero",
    "text": "hi",
    "args": { "text": "hi" },
    "mode": "say",
    "location": 7,
    "command_id": 53,
    "message_id": "CMD053"
  }
}
```

Command acknowledgements are delivered privately to the sender as `{ "type": "command_response", "room": <id>, "payload": { ... } }` envelopes.
