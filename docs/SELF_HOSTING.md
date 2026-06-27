# Self Hosting

This guide is for running an independent public Kyrgame server. It documents
the deployment contract: one public HTTPS origin, an internal backend, a private
Postgres database, admin bootstrap, backups, restore, and upgrade habits.

This repository does not ship a production reverse-proxy stack in this PR. Use
Caddy, nginx, Traefik, a managed load balancer, or your platform's routing layer
to implement the same-origin routing described below.

Run commands from the repository root unless your deployment wrapper says
otherwise.

## Target Shape

- Public origin: `https://<your-domain>`
- Frontend: built static files served from the public origin.
- Backend: FastAPI service reachable only from the proxy or private network.
- Database: private Postgres with no public host port.
- Browser traffic: same-origin HTTP and WebSocket paths through the public
  origin, so the frontend can keep `VITE_API_BASE_URL` and `VITE_WS_URL` blank.

## Prerequisites

- A server or platform account that can run the backend, frontend static files,
  and Postgres.
- A DNS name such as `<your-domain>` pointed at the public edge.
- TLS enabled for the public origin.
- A private place for env files, secrets, admin allowlists, and backups.

## Private Configuration

Keep deployment secrets outside git. A typical production env needs:

```dotenv
DATABASE_URL=postgresql+psycopg://<postgres-user>:<url-encoded-password>@<postgres-host>:5432/<postgres-db>
KYRGAME_CORS_ORIGINS=https://<your-domain>
KYRGAME_ADMIN_ALLOWLIST_PATH=/config/admin-allowlist.yaml
KYRGAME_RESET_ON_BOOT=0
KYRGAME_SEED_IF_EMPTY=1
KYRGAME_TRUST_PROXY_HEADERS=1
KYRGAME_TELEMETRY_DIR=/data/telemetry
VITE_API_BASE_URL=
VITE_WS_URL=
```

URL-encode the password portion of `DATABASE_URL` if it contains characters such
as `@`, `:`, `/`, `?`, `#`, or `%`.

Enable `KYRGAME_TRUST_PROXY_HEADERS=1` only when the reverse proxy overwrites or
strips incoming `CF-Connecting-IP`, `X-Forwarded-For`, and `X-Real-IP` headers
before requests reach the backend.

Keep `KYRGAME_RESET_ON_BOOT=0` for public servers so ordinary restarts do not
reload fixtures over live data. Use `KYRGAME_SEED_IF_EMPTY=1` for first boot so
an empty database gets the packaged fixtures.

## Admin Allowlist

Create an allowlist in your private deployment config. For file-based hosting,
`selfhost/config/admin-allowlist.yaml` is a reasonable local path to keep ignored
by git and mount into the backend at `/config/admin-allowlist.yaml`.

Example:

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

The `sysop` key is the account userid that should receive admin grants.

## Build And Runtime

Build the frontend and serve the generated static files from your public web
service:

```bash
cd frontend
npm ci
npm run build
```

Run the backend behind the private proxy network. The checked-in
`backend/Dockerfile` is suitable for container deployments, or the equivalent
process command is:

```bash
cd backend
python -m uvicorn kyrgame.webapp:create_app --factory --host 0.0.0.0 --port 8000
```

## Reverse Proxy Contract

The proxy should route API and WebSocket paths to the backend service and serve
the frontend for everything else.

Route these HTTP paths to the backend:

```text
/auth*
/public*
/i18n*
/world*
/objects*
/spells*
/commands*
/players*
/content*
/openapi.json
/docs*
/redoc*
```

Backend admin API subpaths under `/admin/` should also route to the backend.
That includes paths such as `/admin/fixtures`, `/admin/players*`,
`/admin/rooms*`, `/admin/mobs*`, `/admin/content*`, and `/admin/i18n*`.
Keep the frontend `/admin` page on the SPA fallback. This lets the browser load
the admin console route directly.

Route `/ws*` to the backend with WebSocket upgrade support.

Serve all other paths from the built frontend with an SPA fallback to
`index.html`.

If the proxy forwards client IP headers, overwrite them at the edge before they
reach the backend. Do not pass through client-supplied forwarding headers.

## Start And Verify

Start the services with your deployment wrapper, Compose file, or platform
dashboard. Then verify the public origin:

```bash
curl -I https://<your-domain>/
curl https://<your-domain>/world/locations
curl https://<your-domain>/public/runtime-mode
```

The frontend should return HTML, and the backend endpoints should return JSON.

## Admin Bootstrap

1. Open the site and create the account named in the admin allowlist.
2. Log in with `session_kind: "admin"` through the UI or an API client.
3. Verify an admin endpoint:

```bash
curl -H "Authorization: Bearer <admin-session-token>" \
  https://<your-domain>/admin/fixtures
```

Static emergency admin tokens are still supported through `KYRGAME_ADMIN_TOKEN`,
but account allowlists are preferred for normal hosting.

## Backups

Back up Postgres before upgrades, resets, migrations, and risky admin work. Use
`pg_dump -Fc` so the backup is a custom-format dump that can be inspected with
`pg_restore -l` before restore.

Generic host-side pattern:

```bash
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p selfhost/backups
final="selfhost/backups/kyrgame-$stamp.dump"
tmp="$final.tmp"
PGHOST=<postgres-host> PGUSER=<postgres-user> PGDATABASE=<postgres-db> \
  pg_dump -Fc > "$tmp"
mv "$tmp" "$final"
pg_restore -l "$final" > "$final.list.txt"
```

Use your deployment's secret manager or private shell environment to provide the
database password. Do not commit database credentials or backup dumps.

## Restore

Restore only after taking a fresh backup of the current database and stopping
app traffic to the backend.

Generic host-side pattern:

```bash
pg_restore -l selfhost/backups/kyrgame-YYYYMMDD-HHMMSS.dump
dropdb -h <postgres-host> -U <postgres-user> <postgres-db>
createdb -h <postgres-host> -U <postgres-user> <postgres-db>
pg_restore -h <postgres-host> -U <postgres-user> -d <postgres-db> \
  --clean --if-exists selfhost/backups/kyrgame-YYYYMMDD-HHMMSS.dump
```

Restart the backend after restore and rerun the smoke checks.

## Updates

1. Back up Postgres and verify `pg_restore -l` can read the dump.
2. Pull or checkout the desired revision.
3. Rebuild the frontend and backend image or runtime environment.
4. Apply any deployment config changes in your private env.
5. Restart the services.
6. Re-run the smoke checks.

## Safe Resets

Database resets are destructive. Only enable `KYRGAME_RESET_ON_BOOT=1` when an
intentional fixture reload is the goal and a verified backup exists. Return it
to `0` after the reset boot.

Do not remove Postgres volumes, managed database instances, or backup folders
unless the goal is permanent data deletion.

## License

Hosting and forks must follow the repository license and additional terms. Read
`LICENSE.txt` before publishing a public instance.
