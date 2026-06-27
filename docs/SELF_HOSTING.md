# Self Hosting

This guide is for running a public Kyrgame server that is independent from the
project's local development stack. The default shape is one public HTTPS host:
the browser loads the built frontend from that host, and the same host proxies
API and WebSocket traffic to the backend service.

## Prerequisites

- A server with Docker Compose v2.
- A DNS name such as `game.example.test` pointed at the server.
- Inbound TCP ports 80 and 443 open to the server.
- A checkout of this repository.

Run commands from the repository root.

## Private Configuration

Copy the example env file and edit the copy:

```bash
cp deploy/self-host/.env.selfhost.example deploy/self-host/.env.selfhost.local
```

Set these values before first boot:

```dotenv
KYRGAME_PUBLIC_HOST=game.example.test
KYRGAME_CORS_ORIGINS=https://game.example.test
POSTGRES_PASSWORD=<long-random-password>
KYRGAME_RESET_ON_BOOT=0
KYRGAME_SEED_IF_EMPTY=1
```

Do not commit `deploy/self-host/.env.selfhost.local`. Keep
`KYRGAME_RESET_ON_BOOT=0` for public servers so ordinary restarts do not reload
fixtures over live data.

Create the admin allowlist mounted by `deploy/self-host/compose.yaml`:

```bash
mkdir -p selfhost/config selfhost/backups
```

`selfhost/config/admin-allowlist.yaml`:

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

## Start And Verify

Review the generated Compose config:

```bash
docker compose --env-file deploy/self-host/.env.selfhost.local -f deploy/self-host/compose.yaml config
```

Start the stack:

```bash
docker compose --env-file deploy/self-host/.env.selfhost.local -f deploy/self-host/compose.yaml up -d --build
```

The public service is Caddy. It serves the built frontend, handles HTTPS for
`KYRGAME_PUBLIC_HOST`, and proxies backend paths to the internal backend
container. Postgres has no public host port in this stack.

Smoke checks:

```bash
curl -I https://game.example.test/
curl https://game.example.test/world/locations
curl https://game.example.test/public/runtime-mode
```

Replace `game.example.test` with `KYRGAME_PUBLIC_HOST`.

## Admin Bootstrap

1. Open the site and create the account named in
   `selfhost/config/admin-allowlist.yaml`.
2. Log in with `session_kind: "admin"` through the UI or an API client.
3. Verify an admin endpoint:

```bash
curl -H "Authorization: Bearer <admin-session-token>" \
  https://game.example.test/admin/fixtures
```

Static emergency admin tokens are still supported through `KYRGAME_ADMIN_TOKEN`,
but account allowlists are preferred for normal hosting.

## Operations

Follow logs:

```bash
docker compose --env-file deploy/self-host/.env.selfhost.local -f deploy/self-host/compose.yaml logs -f
```

Restart after config or code updates:

```bash
docker compose --env-file deploy/self-host/.env.selfhost.local -f deploy/self-host/compose.yaml up -d --build
```

Stop without removing data:

```bash
docker compose --env-file deploy/self-host/.env.selfhost.local -f deploy/self-host/compose.yaml down
```

Back up Postgres before upgrades, resets, and risky admin work. Use
`pg_dump -Fc` so the backup is a custom-format dump that can be inspected with
`pg_restore -l` before restore:

```bash
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p selfhost/backups
docker compose --env-file deploy/self-host/.env.selfhost.local -f deploy/self-host/compose.yaml exec -T db \
  sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "selfhost/backups/kyrgame-$stamp.dump"
pg_restore -l "selfhost/backups/kyrgame-$stamp.dump" \
  > "selfhost/backups/kyrgame-$stamp.dump.list.txt"
```

Restore into a fresh database only after stopping the app services and saving a
new backup of the current database:

```bash
docker compose --env-file deploy/self-host/.env.selfhost.local -f deploy/self-host/compose.yaml stop backend web
docker compose --env-file deploy/self-host/.env.selfhost.local -f deploy/self-host/compose.yaml exec -T db \
  sh -lc 'dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose --env-file deploy/self-host/.env.selfhost.local -f deploy/self-host/compose.yaml exec -T db \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists \
  < selfhost/backups/kyrgame-YYYYMMDD-HHMMSS.dump
docker compose --env-file deploy/self-host/.env.selfhost.local -f deploy/self-host/compose.yaml up -d
```

Use `down -v` only when intentionally deleting the database and Caddy state.
Create and verify a backup first.

## Updates

1. Back up Postgres.
2. Pull or checkout the desired revision.
3. Review config with `docker compose ... config`.
4. Rebuild and start with `docker compose ... up -d --build`.
5. Re-run the smoke checks.

## License

Hosting and forks must follow the repository license and additional terms. Read
`LICENSE.txt` before publishing a public instance.
