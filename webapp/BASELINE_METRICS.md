# Baseline Metrics (Step 1)

This file describes the baseline telemetry added for the Reader WebApp.

## What is tracked

- `client_tti_ms`: time-to-interactive for the first rendered reader screen.
- `client_chapter_open_ms`: chapter open/render time on client.
- `client_api_call_ms`: latency of client API requests.
- `client_api_error`: client-visible API/network error counter.
- `server_api_call_ms`: server-side latency for all `/api/*` endpoints (except `/api/metrics/*`).
- `server_api_error`: server-side API error counter.
- `server_api_reader_ms`: server-side latency for `/api/reader`.
- `server_api_reader_payload_bytes`: response size of `/api/reader`.

## API endpoints

- `POST /api/metrics/client`: client event batch ingest (requires Telegram auth).
- `GET /api/metrics/summary?hours=24`: summary for admins.

## Quick checks

1. Open Reader in Telegram and navigate chapters for a few minutes.
2. Request summary:
   - `GET /api/metrics/summary?hours=24`
3. Validate KPI presence:
   - `client_tti_ms.p95`
   - `client_chapter_open_ms.p95`
   - `server_reader_api_ms.p95`
   - `server_reader_payload_bytes.avg`
   - `client_api_error_rate_pct`
   - `server_api_error_rate_pct`

## Storage

Metrics are persisted in SQLite table `webapp_metrics`.
