# PR Diff (webapp/* only)

## Scope
- This PR includes only `webapp/*` changes.
- Non-webapp changes (`bot.py`, `database.py`) are intentionally excluded from staged diff.

## Staged Diff Snapshot
- Files: `34`
- Insertions: `6090`
- Deletions: `2917`

## Included Changes
- New modular frontend architecture under `webapp/modules/*`.
- Refactored `webapp/reader.js` into orchestration/glue layer.
- Updated `webapp/reader.html` script wiring and module loading order.
- Added JS syntax checker: `webapp/scripts/check-js.mjs`.
- Added docs: `webapp/BASELINE_METRICS.md`, `webapp/MODULES_OVERVIEW.md`.

## Review Commands
```bash
git diff --cached --stat -- webapp
git diff --cached --name-status -- webapp
git diff --cached -- webapp
```

## Suggested PR Title
`refactor(webapp): modularize reader frontend and add lifecycle/telemetry wiring`
