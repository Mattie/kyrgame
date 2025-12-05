# Agent Instructions

- Before starting work, review `docs/PORTING_PLAN.md` for context on the tasks being performed.
- Review the legacy game implementation (the C sources) while making changes to ensure new behavior stays faithful to the original.
- Follow TDD practices: write failing tests first (red), then implement changes to make them pass (green) for all code modifications.
- When preparing pull requests, leverage the shared PR template documented in `docs/PR_TEMPLATE.md` to keep submissions consistent.
- Maintain the new checklist in `docs/PORTING_PLAN.md` as part of every PR that touches backend/porting work—check off completed items and add any new gaps discovered.
