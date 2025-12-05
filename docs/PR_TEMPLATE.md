# Summary

<!-- 1–3 sentences about the goal of this change. -->

# Changes

- [ ] ...

# Motivation & Context

- Issue / ticket: <!-- e.g. Fixes #123 -->

# Legacy code being ported

<!--
Describe what legacy code is being ported or replaced in this PR.

Be explicit:
- Source files / modules (old code)
- Target files / modules (new code)
- Key functions / classes / logic that moved
- Any behavior that intentionally changed vs. original
- Any known gaps or TODOs that still need to be addressed
-->

- **Source (legacy) locations:**
  - `path/to/old/file.ext` — functions/classes: `foo()`, `BarService`, ...
- **New locations:**
  - `path/to/new/file.ext` — functions/classes: `foo_v2()`, `NewBarService`, ...
- **Intentional differences from legacy behavior:**
  - ...
- **Known missing pieces / follow-ups:**
  - ...

# Testing

- [ ] `cd legacy && make -f ELWKYR` (Worldgroup build)
- [ ] `pytest backend/tests`
- [ ] `python -m kyrgame.scripts.package_content --output legacy/Dist/offline-content.json`
- [ ] Other:

Details:

- ...

# Risk & Rollback

- Risk level: ☐ low ☐ medium ☐ high
- Rollback plan:
  - ...

# UI Changes

- Screenshots / description:
  - ...
