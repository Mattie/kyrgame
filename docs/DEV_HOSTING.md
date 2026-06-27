# Development Hosting

This guide is for running Kyrgame locally for development, testing, and short
alpha-style previews. It uses the root `compose.yaml` development stack:
PostgreSQL, the FastAPI backend, and the Vite frontend with hot reload.

For an independent public server, use `docs/SELF_HOSTING.md`.

## Start The Local Stack

Run commands from the repository root.

Validate Compose:

```bash
docker compose --env-file .env.docker.example config
```

Start the stack with Docker directly:

```bash
docker compose --env-file .env.docker.example up -d --build
```

Or use the Make wrapper:

```bash
make ENV_FILE=.env.docker.example up
```

Default local endpoints:

- Frontend: `http://127.0.0.1:5173`
- Backend: `http://127.0.0.1:8000`
- Backend OpenAPI: `http://127.0.0.1:8000/openapi.json`

The root stack is a development stack. It bind-mounts `backend/` and
`frontend/`, exposes local service ports, and runs Vite with polling enabled.

## Local Env Files

Use `.env.docker.example` for default development runs. For local overrides,
copy it to a private file:

```bash
cp .env.docker.example .env.docker.local
```

Then run:

```bash
make ENV_FILE=.env.docker.local up
```

Do not commit `.env.docker.local`.

## Admin Allowlist

The development backend mounts `local-docker/` at `/config`. Create
`local-docker/admin-allowlist.yaml` when account-backed admin access is needed:

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

The key under `admins` must match the account userid that should receive admin
grants.

## Common Commands

```bash
make ENV_FILE=.env.docker.example config
make ENV_FILE=.env.docker.example logs
make ENV_FILE=.env.docker.example test
make ENV_FILE=.env.docker.example seed
make ENV_FILE=.env.docker.example package-content
```

Equivalent Docker commands:

```bash
docker compose --env-file .env.docker.example ps
docker compose --env-file .env.docker.example logs -f
docker compose --env-file .env.docker.example run --rm backend python -m kyrgame.scripts.seed_db
```

Stop containers while preserving named volumes:

```bash
docker compose --env-file .env.docker.example down
```

Use `down -v` only when deliberately deleting local database state.

## Health Checks

```bash
curl http://127.0.0.1:5173/
curl http://127.0.0.1:8000/world/locations
curl http://127.0.0.1:8000/public/runtime-mode
```

Expected result: the frontend returns HTML, and the backend endpoints return
JSON.

## Optional Tunnel Testing

The development stack includes an optional `cloudflared` profile for temporary
remote-device or preview testing. Keep real tunnel credentials in a private env
file.

Private env values usually include:

```dotenv
CLOUDFLARE_TUNNEL_TOKEN=<token>
KYRGAME_ALLOW_CLOUDFLARE_TUNNEL=1
KYRGAME_BACKEND_PROXY_TARGET=http://backend:8000
KYRGAME_VITE_ALLOWED_HOSTS=<your-tunnel-host>
VITE_API_BASE_URL=
VITE_WS_URL=
```

Start the base stack first, then the tunnel profile:

```bash
make ENV_FILE=.env.docker.local up
make ENV_FILE=.env.docker.local tunnel-up
```

Equivalent Docker commands:

```bash
docker compose --env-file .env.docker.local up -d --build
docker compose --env-file .env.docker.local --profile tunnel up -d cloudflared
```

The blank `VITE_API_BASE_URL` and `VITE_WS_URL` values make the browser use
same-origin paths. Vite proxies API and WebSocket paths to the backend service.

## Restart Order

For backend changes:

```bash
docker compose --env-file .env.docker.example restart backend
```

For frontend dependency, env, or server-process changes:

```bash
docker compose --env-file .env.docker.example restart frontend
```

If a tunnel is running and the frontend container is recreated, restart the
tunnel container after the frontend is healthy:

```bash
docker compose --env-file .env.docker.local stop cloudflared
docker compose --env-file .env.docker.local up -d --build frontend
docker compose --env-file .env.docker.local --profile tunnel up -d cloudflared
```

## Resets

For ordinary development restarts, keep:

```dotenv
KYRGAME_RESET_ON_BOOT=0
KYRGAME_SEED_IF_EMPTY=1
```

Set `KYRGAME_RESET_ON_BOOT=1` only when a fixture reload is intentional, then
return it to `0` after the reset boot.
