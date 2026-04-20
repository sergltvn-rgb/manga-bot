# Reader Release Runbook

This runbook covers Sprint F release operations:

- pre-release quality gates
- canary rollout
- 48-hour monitoring
- rollback playbook

## 1) Pre-release gates

Complete all steps before deploying:

- [ ] Regression suite is green locally:
  - `python scratch/run_regression_suite.py --with-e2e --with-auth-limits`
- [ ] CI workflow `.github/workflows/reader-regression.yml` is green:
  - PR smoke job
  - nightly/manual full job
- [ ] Manual workflow `.github/workflows/release-candidate.yml` passed for candidate SHA
- [ ] `TMA_AUTH` repository secret is configured (required for full regression)
- [ ] Backup `manga.db` on the target host
- [ ] Release SHA/tag is written down before deploy

Suggested DB backup command (Linux server):

```bash
mkdir -p backups
cp manga.db "backups/manga-$(date +%F-%H%M%S).db"
```

## 2) Canary rollout

For single-node deployment, use time-based canary (no full traffic split):

1. Deploy new release SHA to production host.
2. Restart service.
3. Run canary probe immediately.
4. Observe for 30-60 minutes before full confirmation.

Canary probe command:

```bash
API_URL="https://<your-domain>" \
TEST_ALLOWED_ORIGIN="https://<your-domain>" \
python scratch/canary_probe.py --samples 30 --interval-ms 1000 --p95-budget-ms 1200
```

Optional: temporarily increase server-side reader metric sampling during canary:

```bash
export SERVER_READER_TELEMETRY_SAMPLE_RATE=1
```

Automated first canary window (2h, one probe every 15m):

```bash
API_URL="https://<your-domain>" \
TEST_ALLOWED_ORIGIN="https://<your-domain>" \
python scratch/run_canary_window.py --duration-minutes 120 --probe-every-minutes 15
```

Canary pass criteria:

- functional checks are all green (`/api/reader`, `ETag/304`, CORS preflight, app shell, telemetry POST)
- no non-200 responses in sampled `/api/reader` calls
- `/api/reader` p95 latency is within budget (`<= 1200ms`, or your project target)

## 3) 48-hour monitoring plan

### Cadence

- First 2 hours: run `canary_probe.py` every 15 minutes.
- Next 46 hours: run `canary_probe.py` every 1 hour.
- Every 6 hours: generate DB-based health report.

Automated next monitoring window (46h, one probe every 60m):

```bash
API_URL="https://<your-domain>" \
TEST_ALLOWED_ORIGIN="https://<your-domain>" \
python scratch/run_canary_window.py --duration-minutes 2760 --probe-every-minutes 60 --samples 10
```

Health report command:

```bash
python scratch/release_health_report.py --hours 48
```

Optional machine-readable report:

```bash
python scratch/release_health_report.py --hours 48 --json
```

Weekly KPI comparison (current 7d vs previous 7d):

```bash
python scratch/telemetry_kpi_dashboard.py --window-days 7
```

KPI report files (JSON + Markdown):

```bash
python scratch/telemetry_kpi_dashboard.py --window-days 7 --output-json artifacts/kpi-dashboard.json --output-md artifacts/kpi-dashboard.md
```

Absolute KPI gate (for CI/nightly guardrails):

```bash
python scratch/telemetry_kpi_dashboard.py --window-days 7 --enforce-absolute-gate --min-client-chapter-open-events 1 --min-server-reader-events 3 --max-client-chapter-open-p95-ms 2500 --max-server-api-reader-p95-ms 1500
```

Single-command release checklist gate (local):

```bash
SERVER_READER_TELEMETRY_SAMPLE_RATE=1 \
python scratch/run_release_candidate_gate.py \
  --api-url "http://localhost:8080" \
  --allowed-origin "http://localhost:8080" \
  --with-e2e \
  --with-auth-limits \
  --output-dir artifacts/release-candidate
```

### What to watch

- Canary probe:
  - non-200 status spikes
  - p95 latency regressions
- Telemetry (`webapp_telemetry`):
  - growth of `client_runtime_error`
  - growth of `client_unhandled_rejection`
  - repeated errors from the same `source_module`
- Admin audit (`admin_audit_log`):
  - non-`ok` results
  - repeated failure of same action

Suggested server log checks (adapt service name):

```bash
journalctl -u <service_name> --since "15 minutes ago" | grep -E "ERROR|Traceback|Reader API Error|Telemetry API Error"
```

## 4) Rollback playbook

Trigger rollback when any of the following is true:

- repeated canary probe failures
- severe functional regression in reader flow
- sustained p95 regression above agreed budget
- elevated error signals in telemetry/audit/logs with user impact

Rollback steps:

1. Record incident time and failing SHA.
2. Backup current DB snapshot.
3. Re-deploy last known stable SHA/tag.
4. Restart service.
5. Re-run quick validation:
   - `python scratch/canary_probe.py --samples 10 --interval-ms 500`
6. Keep monitoring at 15-minute cadence for 2 hours.
7. Document root cause and corrective action before next rollout.

## 5) Release exit criteria

After 48 hours, release is considered stable when:

- no open P0/P1 incidents related to reader/WebApp API
- canary probes remain green
- telemetry error signals are stable or improving
- admin audit error rate is not elevated vs pre-release baseline
