# Agent Instructions

- Before starting work, review `docs/PORTING_PLAN.md` for context on the tasks being performed.
- If the current branch is `master`, sync from GitHub before starting work. Check `git status` first; when clean, run `git fetch origin` and `git pull --ff-only`, then create a feature branch from the updated `master`. If `master` has local changes, stop and ask before moving or rebasing them.
- Review the legacy game implementation (the C sources) while making changes to ensure new behavior stays faithful to the original.
- Follow TDD practices: write failing tests first (red), then implement changes to make them pass (green) for all code modifications.
- Avoid re-inventing the wheel: use existing shared mechanisms/helpers in the codebase whenever possible before introducing new bespoke logic.
- When preparing pull requests, leverage the shared PR template documented in `docs/PR_TEMPLATE.md` to keep submissions consistent.
- Capture screenshots for any UI changes to demonstrate that the updated interfaces work correctly and include them with your changes.
- Maintain the new checklist in `docs/PORTING_PLAN.md` as part of every PR that touches backend/porting work—check off completed items and add any new gaps discovered.
- For every change summary and PR description, include a dedicated **Manual E2E Demo Checklist** section listing realistic end-to-end human test steps that can be executed after submission (when applicable).
- When porting legacy gameplay logic, add a short comment in the new code that points back to the legacy source location (file + line numbers) so reviewers can compare behavior quickly.
- When porting legacy messaging, verify both the C call site and the message catalog before choosing `message_id`s. Some routines use inline `prf(...)`/char-buffer text or separate caster, target, and room-facing messages; tests should assert each recipient surface when behavior fans out differently.
- Test users created for local/manual testing should have player IDs beginning with `zt` unless a specific test requires a different name. Delete those test users after the task that needed them is complete, and take care to delete or change only users that were specifically identified for that test cleanup.

## Local Live Server Operations

- Before inspecting, starting, restarting, exposing, or stopping local servers, use the `local-dev-servers` skill and run its registry check from the repo root:
  `python.exe <local-dev-servers-skill>\scripts\devservers.py status --refresh --scan-ports`
- The normal long-lived local instance is the Docker Compose project `kyrgame-local` from `compose.yaml`.
  Expected services:
  - `kyrgame-local-backend-1` on `http://127.0.0.1:8000`
  - `kyrgame-local-frontend-1` on `http://127.0.0.1:5173`
  - `kyrgame-local-db-1` on port `5432`
- Check the live Compose state with:
  `docker compose -p kyrgame-local ps backend frontend db`
  and, when needed:
  `docker ps --format "table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Ports}}"`
- Do not use `docker compose down -v` or remove Docker volumes unless the user explicitly asks for data deletion and a verified backup exists.
- After backend Python changes, restart only the backend container so the bind-mounted source is reloaded while the database and frontend stay up:
  `docker compose -p kyrgame-local restart backend`
  Existing WebSocket sessions may disconnect and should reconnect against the restarted backend.
- Frontend Vite source changes usually hot-reload through the running frontend container. Restart `frontend` only for dependency, env, or server-process changes.
- Verify the live server is in good shape with:
  - `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/openapi.json`
  - `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5173/`
  - `docker compose -p kyrgame-local ps backend frontend db`
  - For code-specific confirmation, prefer in-container Python inspection such as:
    `docker exec kyrgame-local-backend-1 python -c "import inspect; from kyrgame import rooms; print('marker' in inspect.getsource(rooms))"`
- Avoid complex `docker inspect --format` Go templates in PowerShell; quoting is fragile. Prefer `docker compose -p kyrgame-local ps`, `docker ps --format ...`, or inspect JSON through a safer parser.

## Local Database Backups

- Back up the live local Postgres database before risky live-server operations, before data migrations, and whenever the user asks. Use `pg_dump` from inside `kyrgame-local-db-1`; do not open `.env` files for credentials. Let the container use its own `POSTGRES_USER` and `POSTGRES_DB` environment.
- Store local dumps under `.local-backups/postgres/`, which is ignored by git. Use timestamped filenames and never overwrite an existing dump.
- Use a custom-format dump plus a restore-list verification:
  1. Create the host directory:
     `New-Item -ItemType Directory -Force -Path .local-backups\postgres`
  2. Create a timestamped dump inside the db container with `pg_dump -Fc`.
  3. Run `pg_restore -l` against the dump before copying it out.
  4. Copy both the `.dump` and `.list.txt` files to `.local-backups/postgres/` with `docker cp`.
  5. Run `Get-FileHash` on the copied dump and report the path, size, hash, and restore-list path.
  6. Remove only the temporary dump/list files from `/tmp` inside the container after the host copy succeeds.
- A safe PowerShell pattern is:
  `$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'; $dir = Join-Path (Resolve-Path .) '.local-backups\postgres'; New-Item -ItemType Directory -Force -Path $dir | Out-Null; $name = "kyrgame-local-$stamp.dump"; $tmp = "/tmp/$name"; $cmd = 'set -eu; pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "' + $tmp + '"; pg_restore -l "' + $tmp + '" > "' + $tmp + '.list"; ls -lh "' + $tmp + '" "' + $tmp + '.list"'; docker exec kyrgame-local-db-1 sh -lc $cmd; docker cp "kyrgame-local-db-1:$tmp" (Join-Path $dir $name); docker cp "kyrgame-local-db-1:$tmp.list" (Join-Path $dir "$name.list.txt"); docker exec kyrgame-local-db-1 sh -lc ('rm -f "' + $tmp + '" "' + $tmp + '.list"'); Get-FileHash -Algorithm SHA256 (Join-Path $dir $name)`
