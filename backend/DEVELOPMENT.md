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

- **Route:** `POST /auth/session`
- **Headers:** `Content-Type: application/json`
- **Body:**

  ```json
  {
    "player_id": "hero",
    "resume_token": "...",
    "allow_multiple": false,
    "room_id": 7
  }
  ```

- **Responses:**
  - `201 Created` for new sessions, `200 OK` when resuming with `resume_token`.
  - Envelope:

    ```json
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

    When resuming, `status` becomes `recovered`, `resumed` is `true`, and `first_login` is `false`.

```bash
curl -X POST http://localhost:8000/auth/session \
  -H 'Content-Type: application/json' \
  -d '{"player_id": "hero", "room_id": 7}'
```

> TODO: The repository tracks `expires_at`/`last_seen` for session tokens, but those fields are not yet surfaced in the HTTP response. A contract test guards the gap until the API is updated.

**Validate an active session**

- **Route:** `GET /auth/session`
- **Headers:** `Authorization: Bearer <token>`
- **Response:**

  ```json
  {
    "status": "active",
    "session": {
      "token": "<bearer-token>",
      "player_id": "hero",
      "room_id": 7,
      "first_login": false,
      "resumed": false,
      "replaced_sessions": 0
    }
  }
  ```

```bash
curl http://localhost:8000/auth/session \
  -H 'Authorization: Bearer <token>'
```

**Logout**

- **Route:** `POST /auth/logout`
- **Headers:** `Authorization: Bearer <token>`
- **Response:** `{ "status": "logged_out" }` and any connected WebSocket is closed.

### Fixture lookups

Unless you add your own auth layer, the lookup routes are open for ease of fixture inspection.

**List commands**

- **Route:** `GET /commands`
- **Response:** array of command entries with `id`, `command` text, `payonl` flag (pay-only), and optional handler `cmdrou`:

  ```json
  [
    { "id": 1, "command": "north", "payonl": false, "cmdrou": "lcrous" },
    { "id": 2, "command": "south", "payonl": false, "cmdrou": "lcrous" }
  ]
  ```

```bash
curl http://localhost:8000/commands | jq '.[0]'
```

**List locations**

- **Route:** `GET /world/locations`
- **Response:** array of `LocationModel` entries, mirroring `KYRLOCS` fields with exit pointers:

  ```json
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

```bash
curl http://localhost:8000/world/locations | jq '.[0].brfdes'
```

**List objects**

- **Route:** `GET /objects`
- **Response:** array of object catalog entries with legacy message references and behavior hooks:

  ```json
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

```bash
curl http://localhost:8000/objects | jq '.[0]'
```

**Localization bundles**

- **Route:** `GET /i18n/<locale>/messages`
- **Response:** locale metadata plus the raw catalog map keyed by legacy message IDs:

  ```json
  {
    "version": "1.0.0",
    "locale": "en-US",
    "catalog_id": "kyrandia",
    "messages": {
      "WELCOME": "Welcome to Kyrandia!",
      "CMD001": "You walk north"
    }
  }
  ```

```bash
curl http://localhost:8000/i18n/en-US/messages | jq '.messages.WELCOME'
```

### WebSocket room gateway

Connect with the bearer token returned by `/auth/session`:

```
ws://localhost:8000/ws/rooms/<room_id>?token=<bearer-token>
```

On connect, the server sends `room_welcome` and caches the token/socket pairing. If a player switches rooms, the gateway emits `room_change` to that socket before broadcasting to the new room.

Room fan-out messages share a stable envelope. Movement or entry events resemble:

```json
{
  "type": "room_broadcast",
  "room": 7,
  "payload": {
    "event": "player_enter",
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

Chat fan-out swaps the movement fields for text and mode:

```json
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

Command acknowledgements are delivered privately to the sender in the same envelope shape but with `type: "command_response"` and a payload that echoes `command_id`/`message_id` for the initiating verb.

