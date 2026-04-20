# API Smoke Checks

## One-command regression suite

Run full API regression in one command:

```powershell
.venv\Scripts\python.exe scratch/run_regression_suite.py
```

Run with browser E2E included:

```powershell
.venv\Scripts\python.exe scratch/run_regression_suite.py --with-e2e
```

Run auth/rate-limit checks forcibly (requires `TMA_AUTH`):

```powershell
$env:TMA_AUTH="<telegram_init_data>"; .venv\Scripts\python.exe scratch/run_regression_suite.py --with-auth-limits
```

Nightly/PR automation is configured in:

- `.github/workflows/reader-regression.yml`
- `.github/workflows/release-candidate.yml` (manual release gate)

Automation modes:

- Pull Request: fast smoke (`python scratch/run_regression_suite.py`)
- Nightly/manual: full regression (`python scratch/run_regression_suite.py --with-e2e --with-auth-limits`)
- Nightly/manual: builds KPI dashboard artifacts (`artifacts/kpi-dashboard.json`, `artifacts/kpi-dashboard.md`)
- Nightly/manual: enforces absolute KPI gate on current-window p95 metrics
- Auth/rate-limit API checks run automatically when repository secret `TMA_AUTH` is set
- Nightly/manual full job fails early if `TMA_AUTH` secret is missing
- Release-candidate workflow (`workflow_dispatch`) runs end-to-end checklist gate and uploads `artifacts/release-candidate/*`

## Release rollout tooling

Release/canary operations for Sprint F:

- `scratch/RELEASE_RUNBOOK.md` - checklist, canary plan, 48h monitoring, rollback playbook
- `scratch/canary_probe.py` - live canary probe (`/api/reader`, ETag/304, CORS, app shell, telemetry, p95)
- `scratch/run_canary_window.py` - repeated canary probes for rollout windows
- `scratch/release_health_report.py` - DB health summary (`webapp_telemetry`, `admin_audit_log`)
- `scratch/telemetry_kpi_dashboard.py` - weekly KPI comparison (current vs previous window)
- `scratch/run_release_candidate_gate.py` - single entrypoint for final release checklist gate

Canary probe example:

```powershell
$env:API_URL="http://localhost:8080"; $env:TEST_ALLOWED_ORIGIN="http://localhost:8080"; .venv\Scripts\python.exe scratch/canary_probe.py --samples 20 --interval-ms 500
```

48-hour health summary example:

```powershell
.venv\Scripts\python.exe scratch/release_health_report.py --hours 48
```

Automated 2-hour canary window (every 15 minutes):

```powershell
$env:API_URL="http://localhost:8080"; $env:TEST_ALLOWED_ORIGIN="http://localhost:8080"; .venv\Scripts\python.exe scratch/run_canary_window.py --duration-minutes 120 --probe-every-minutes 15
```

Weekly KPI dashboard (current vs previous 7 days):

```powershell
.venv\Scripts\python.exe scratch/telemetry_kpi_dashboard.py --window-days 7
```

Weekly KPI dashboard + absolute gate (CI-like):

```powershell
.venv\Scripts\python.exe scratch/telemetry_kpi_dashboard.py --window-days 7 --enforce-absolute-gate --min-client-chapter-open-events 1 --min-server-reader-events 3 --max-client-chapter-open-p95-ms 2500 --max-server-api-reader-p95-ms 1500
```

Final release-candidate gate (local run):

```powershell
$env:SERVER_READER_TELEMETRY_SAMPLE_RATE="1"; .venv\Scripts\python.exe scratch/run_release_candidate_gate.py --api-url "http://localhost:8080" --allowed-origin "http://localhost:8080" --with-e2e --with-auth-limits --output-dir artifacts/release-candidate
```

## WebApp E2E regression (Playwright)

Run browser-level regression suite:

```powershell
cd webapp
npm install
npm run test:e2e
```

What it validates:

- open reader, chapter navigation (`prev/next`)
- comment submit flow
- chapter reactions flow
- typo report submit
- admin flows: rename request, chapter URL edit, bulk add, sort sync

## Embedded integration (recommended)

Run a full API integration smoke without extra terminals:

```powershell
.venv\Scripts\python.exe scratch/test_api_embedded.py
```

What it validates:

- `/api/reader` + `ETag` + `If-None-Match -> 304`
- server telemetry metric write for `server_api_reader_ms` (sample-rate smoke)
- CORS allow/deny preflight behavior
- `413 payload_too_large` for oversized body
- `401 Unauthorized` for protected endpoints without auth
- `403 Forbidden` for admin endpoints with non-admin auth
- telemetry metric validation for `client_chapter_open_ms` (`200` valid, `400` invalid duration)
- comments/reactions validation and `429` rate-limit
- admin URL/order validation (`/api/chapters`, `/api/chapters/bulk`, `/api/sort`)
- admin `429` on `/api/rename/request` + audit-log write check

## Public security checks

Start API-only server in terminal #1:

```powershell
.venv\Scripts\python.exe scratch/run_api_only.py
```

Then run in terminal #2:

```powershell
.venv\Scripts\python.exe scratch/test_api_security.py
```

Optional env vars:

- `API_URL` (default: `http://localhost:8080`)
- `TEST_ALLOWED_ORIGIN` (default: `http://localhost:8080`)
- `TEST_BLOCKED_ORIGIN` (default: `https://evil.invalid`)
- `TEST_EXPECT_413` (default: `1`)

What it validates:

- `/api/reader` returns `ETag`
- `If-None-Match` yields `304`
- CORS allowlist blocks unknown origins
- oversized payload returns `413 payload_too_large`

## Auth + rate-limit checks

Start API-only server in terminal #1:

```powershell
.venv\Scripts\python.exe scratch/run_api_only.py
```

Then run in terminal #2:

```powershell
$env:TMA_AUTH="<telegram_init_data>"; .venv\Scripts\python.exe scratch/test_api_auth_limits.py
```

Optional env vars:

- `API_URL` (default: `http://localhost:8080`)
- `TEST_ALLOWED_ORIGIN` (default: `http://localhost:8080`)
- `TEST_CHAPTER_KEY` (default: `integration_limits_v1`)
- `TEST_RUN_REPORT_LIMIT` (default: `0`; keep disabled to avoid admin spam)

What it validates:

- `400` for invalid payloads (`comments/reactions/report`)
- `429` rate-limit behavior for comments/reactions
