# Agent Instructions

- Before starting work, review `docs/PORTING_PLAN.md` for context on the tasks being performed.
- Before starting work, check for a repo-root `.agents.md` file and read it when present. That file is ignored by git and may contain local-only, machine-specific context for the current project directory.
- If the current branch is `master`, sync from GitHub before starting work. Check `git status` first; when clean, run `git fetch origin` and `git pull --ff-only`, then create a feature branch from the updated `master`. If `master` has local changes, stop and ask before moving or rebasing them.
- Review the legacy game implementation (the C sources) while making changes to ensure new behavior stays faithful to the original.
- Follow TDD practices: write failing tests first (red), then implement changes to make them pass (green) for all code modifications.
- Avoid re-inventing the wheel: use existing shared mechanisms/helpers in the codebase whenever possible before introducing new bespoke logic.
- When preparing pull requests, leverage the shared PR template documented in `docs/PR_TEMPLATE.md` to keep submissions consistent.
- Capture screenshots for any UI changes to demonstrate that the updated interfaces work correctly and include them with your changes.
- Maintain the new checklist in `docs/PORTING_PLAN.md` as part of every PR that touches backend/porting work—check off completed items and add any new gaps discovered.
- For every change summary and PR description, include a dedicated **Manual E2E Demo Checklist** section listing realistic end-to-end human test steps that can be executed after submission (when applicable).
- At the end of a task, final responses should typically state whether the completed changes are currently running on any known relevant live/local server locations, including the URL or service name when applicable.
- When porting legacy gameplay logic, add a short comment in the new code that points back to the legacy source location (file + line numbers) so reviewers can compare behavior quickly.
- When porting legacy messaging, verify both the C call site and the message catalog before choosing `message_id`s. Some routines use inline `prf(...)`/char-buffer text or separate caster, target, and room-facing messages; tests should assert each recipient surface when behavior fans out differently.
- Test users created for local/manual testing should have player IDs beginning with `zt` unless a specific test requires a different name. Delete those test users after the task that needed them is complete, and take care to delete or change only users that were specifically identified for that test cleanup.

## Local Operations Safety

- Before inspecting, starting, restarting, exposing, or stopping local servers, use the `local-dev-servers` skill and check repo-root `.agents.md` for machine-specific server details.
- Prefer shared runtime docs such as `docs/ALPHA_TESTING_RUNBOOK.md` and `compose.yaml` for portable Docker and Cloudflare workflow. Keep machine-specific project names, ports, hostnames, and one-off commands in ignored `.agents.md`.
- Do not use `docker compose down -v` or remove Docker volumes unless the user explicitly asks for data deletion and a verified backup exists.
- Back up live local databases before risky server, data, or migration operations. Store backups in ignored paths, use timestamped names, verify restore metadata or equivalent integrity, and never overwrite an existing dump.
- Do not open `.env` files for credentials; let scripts, containers, or shells load credentials themselves.
