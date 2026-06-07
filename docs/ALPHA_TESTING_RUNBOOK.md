# Kyrgame Alpha Testing Runbook

This runbook keeps the local Docker Desktop alpha stack running with the named Cloudflare tunnel.

Run commands from the repository root:

```powershell
Set-Location -LiteralPath 'C:\Users\matti\Documents\kyrgame'
```

## URLs

- Local frontend: http://127.0.0.1:5173
- Local backend: http://127.0.0.1:8000
- Public alpha URL: https://willow.eventscripts.com

Cloudflare terminates HTTPS at the edge. The tunnel then forwards plain HTTP to the Vite frontend inside Docker. The Cloudflare dashboard route for `willow.eventscripts.com` should use service `http://localhost:5173` or `http://127.0.0.1:5173`; the `cloudflared` container shares the frontend container network namespace, so loopback resolves to the frontend container.

## Private Config

Keep the real tunnel token in `.env.docker.local`. This file is local-only and should stay uncommitted.

Expected local values:

```dotenv
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare>
KYRGAME_ALLOW_CLOUDFLARE_TUNNEL=1
KYRGAME_BACKEND_PROXY_TARGET=http://backend:8000
VITE_API_BASE_URL=
VITE_WS_URL=
```

The blank `VITE_API_BASE_URL` and `VITE_WS_URL` make the browser use same-origin paths. Vite proxies backend HTTP and WebSocket routes to the backend container.

## Start Or Recreate The Alpha Stack

Use the private env file every time the tunnel profile is involved:

```powershell
docker compose --env-file .env.docker.local -p kyrgame-local --profile tunnel up -d --build
```

Equivalent Make wrapper:

```powershell
make ENV_FILE=.env.docker.local tunnel-up
```

The Compose services use `restart: unless-stopped`, so Docker Desktop will keep them running after ordinary process exits and restart them when Docker starts again, unless the containers were explicitly stopped.

## Fast Frontend Edit Loop

The Docker frontend enables Vite polling with `KYRGAME_VITE_USE_POLLING=1`, so ordinary React, CSS, and copy edits should hot reload without restarting the tunnel or backend.

For small frontend edits:

1. Save the file.
2. Hard refresh the browser if the update is not visible.
3. Restart only the frontend if Vite still serves stale code:

   ```powershell
   docker compose --env-file .env.docker.local -p kyrgame-local restart frontend
   ```

Use the full safe restart order only for tunnel failures, backend changes, Compose/env changes, or a frontend restart that leaves `cloudflared` disconnected.

## Check Health

Container status:

```powershell
docker compose --env-file .env.docker.local -p kyrgame-local ps
```

Local frontend:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5173/ | Select-Object StatusCode
```

Local backend:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/world/locations | Select-Object StatusCode
```

Public tunnel:

```powershell
Invoke-WebRequest -UseBasicParsing https://willow.eventscripts.com/ | Select-Object StatusCode
Invoke-WebRequest -UseBasicParsing https://willow.eventscripts.com/world/locations | Select-Object StatusCode
```

Expected result for all checks above is `200`.

## Logs

Follow all services:

```powershell
docker compose --env-file .env.docker.local -p kyrgame-local logs -f
```

Follow only the tunnel:

```powershell
docker compose --env-file .env.docker.local -p kyrgame-local logs -f cloudflared
```

Useful log signals:

- Frontend is ready when logs include `VITE` and `ready`.
- Tunnel is connected when cloudflared logs include `Registered tunnel connection`.
- A missing token usually appears as `cloudflared tunnel run requires the ID or name of the tunnel`.

## Safe Restart Order

Use this order when frontend code looks stale, Vite hot reload stops responding, or Cloudflare returns `502 Bad Gateway`:

```powershell
docker compose --env-file .env.docker.local -p kyrgame-local stop cloudflared
docker compose --env-file .env.docker.local -p kyrgame-local up -d --build backend frontend
docker compose --env-file .env.docker.local -p kyrgame-local --profile tunnel up -d cloudflared
```

Reason: `cloudflared` uses `network_mode: service:frontend`. It must join a running frontend container network namespace.

After restarting, wait for the frontend `VITE ... ready` log line:

```powershell
docker compose --env-file .env.docker.local -p kyrgame-local logs --tail=80 frontend
```

Then rerun the health checks.

## Update The Alpha Stack After Pulling Code

```powershell
git status --short --branch
git pull --ff-only
docker compose --env-file .env.docker.local -p kyrgame-local --profile tunnel up -d --build
```

If local work exists, preserve it before pulling.

## Stop The Alpha Stack

Stop the containers while preserving named volumes:

```powershell
docker compose --env-file .env.docker.local -p kyrgame-local --profile tunnel stop
```

Remove containers while preserving named volumes:

```powershell
docker compose --env-file .env.docker.local -p kyrgame-local --profile tunnel down
```

Remove the database and app data volumes only when an alpha reset is intentional:

```powershell
docker compose --env-file .env.docker.local -p kyrgame-local --profile tunnel down -v
```

## Local Dev Server Registry

The running alpha ports should be tracked by the shared local-dev-servers registry:

```powershell
python.exe C:\Users\matti\.agents\skills\local-dev-servers\scripts\devservers.py status --refresh --scan-ports
```

The expected tracked ports are:

- `8000` for the backend
- `5173` for the frontend

## Common Recovery

Cloudflare `502 Bad Gateway`:

1. Confirm `docker compose --env-file .env.docker.local -p kyrgame-local ps` shows `frontend` and `cloudflared` running.
2. Confirm the Cloudflare dashboard route points to `http://localhost:5173` or `http://127.0.0.1:5173`.
3. Run the safe restart order.
4. Check `https://willow.eventscripts.com/` and `https://willow.eventscripts.com/world/locations`.

Frontend serves stale code:

1. Stop `cloudflared`.
2. Recreate `frontend` with `docker compose --env-file .env.docker.local -p kyrgame-local up -d --build frontend`.
3. Start `cloudflared`.
4. Hard refresh the browser.

Cloudflared exits immediately:

1. Start with `.env.docker.local`.
2. Check that `CLOUDFLARE_TUNNEL_TOKEN` is set in that private file.
3. Recreate with `docker compose --env-file .env.docker.local -p kyrgame-local --profile tunnel up -d cloudflared`.

Database needs a clean alpha reset:

1. Stop the stack with `down -v`.
2. Start again with `KYRGAME_RESET_ON_BOOT=1` for one boot if fixture reload is desired.
3. Return `KYRGAME_RESET_ON_BOOT=0` after the reset.
