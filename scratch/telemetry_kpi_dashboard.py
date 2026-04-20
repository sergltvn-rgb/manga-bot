import argparse
import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


CLIENT_ERROR_EVENTS = {"client_runtime_error", "client_unhandled_rejection"}
EVENT_CLIENT_CHAPTER_OPEN = "client_chapter_open_ms"
EVENT_SERVER_READER = "server_api_reader_ms"


def _safe_round(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def to_finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number


def percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    index = max(0, min(len(sorted_values) - 1, math.ceil(len(sorted_values) * ratio) - 1))
    return sorted_values[index]


def parse_db_datetime(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def parse_payload_json(raw: str) -> dict:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


@dataclass
class WindowStats:
    name: str
    client_chapter_open_durations: list[float] = field(default_factory=list)
    server_reader_durations: list[float] = field(default_factory=list)
    client_error_events: int = 0
    server_reader_total: int = 0
    server_reader_errors: int = 0
    active_users: set[str] = field(default_factory=set)
    users_with_client_errors: set[str] = field(default_factory=set)

    def add_client_chapter_duration(self, value: float, user_id: str) -> None:
        self.client_chapter_open_durations.append(value)
        if user_id:
            self.active_users.add(user_id)

    def add_client_error(self, user_id: str) -> None:
        self.client_error_events += 1
        if user_id:
            self.users_with_client_errors.add(user_id)

    def add_server_reader_event(self, duration: float | None, status: int | None) -> None:
        self.server_reader_total += 1
        if duration is not None:
            self.server_reader_durations.append(duration)
        if status is not None and status >= 400:
            self.server_reader_errors += 1

    def to_metrics(self) -> dict:
        chapter_events = len(self.client_chapter_open_durations)
        client_p95 = percentile(self.client_chapter_open_durations, 0.95)
        server_p95 = percentile(self.server_reader_durations, 0.95)
        client_error_rate = (self.client_error_events / chapter_events * 100.0) if chapter_events > 0 else None
        server_error_rate = (
            self.server_reader_errors / self.server_reader_total * 100.0
            if self.server_reader_total > 0
            else None
        )
        crash_free_users_pct = None
        if self.active_users:
            crash_free_users = len(self.active_users - self.users_with_client_errors)
            crash_free_users_pct = crash_free_users / len(self.active_users) * 100.0

        return {
            "window": self.name,
            "counts": {
                "client_chapter_open_events": chapter_events,
                "client_error_events": self.client_error_events,
                "server_reader_events": self.server_reader_total,
                "active_users": len(self.active_users),
            },
            "kpi": {
                "client_chapter_open_p95_ms": round(client_p95, 2) if client_p95 is not None else None,
                "server_api_reader_p95_ms": round(server_p95, 2) if server_p95 is not None else None,
                "client_error_rate_pct_proxy": round(client_error_rate, 3) if client_error_rate is not None else None,
                "server_error_rate_pct": round(server_error_rate, 3) if server_error_rate is not None else None,
                "crash_free_user_pct_proxy": round(crash_free_users_pct, 3) if crash_free_users_pct is not None else None,
            },
        }


def improvement_pct(previous_value: float | None, current_value: float | None) -> float | None:
    if previous_value is None or current_value is None:
        return None
    if previous_value <= 0:
        return None
    return (previous_value - current_value) / previous_value * 100.0


def build_comparison(previous: dict, current: dict) -> dict:
    prev_kpi = previous["kpi"]
    curr_kpi = current["kpi"]

    client_p95_gain = improvement_pct(prev_kpi["client_chapter_open_p95_ms"], curr_kpi["client_chapter_open_p95_ms"])
    server_p95_gain = improvement_pct(prev_kpi["server_api_reader_p95_ms"], curr_kpi["server_api_reader_p95_ms"])

    return {
        "comparison": {
            "client_chapter_open_p95_improvement_pct": round(client_p95_gain, 2) if client_p95_gain is not None else None,
            "server_api_reader_p95_improvement_pct": round(server_p95_gain, 2) if server_p95_gain is not None else None,
        },
        "targets": {
            "client_chapter_open_p95_improvement_gte_25": (
                client_p95_gain >= 25.0 if client_p95_gain is not None else None
            ),
            "server_api_reader_p95_improvement_gte_30": (
                server_p95_gain >= 30.0 if server_p95_gain is not None else None
            ),
            "client_error_rate_lt_1": (
                curr_kpi["client_error_rate_pct_proxy"] < 1.0
                if curr_kpi["client_error_rate_pct_proxy"] is not None
                else None
            ),
            "server_error_rate_lt_1": (
                curr_kpi["server_error_rate_pct"] < 1.0
                if curr_kpi["server_error_rate_pct"] is not None
                else None
            ),
            "crash_free_gt_99_5": (
                curr_kpi["crash_free_user_pct_proxy"] > 99.5
                if curr_kpi["crash_free_user_pct_proxy"] is not None
                else None
            ),
        },
    }


def evaluate_absolute_gate(
    report: dict,
    *,
    max_client_chapter_open_p95_ms: float,
    max_server_api_reader_p95_ms: float,
    min_client_chapter_open_events: int,
    min_server_reader_events: int,
) -> dict:
    current = report["current"]
    current_counts = current["counts"]
    current_kpi = current["kpi"]

    checks: list[dict] = []

    client_events = int(current_counts.get("client_chapter_open_events", 0) or 0)
    client_p95 = current_kpi.get("client_chapter_open_p95_ms")
    client_check = {
        "name": "client_chapter_open_p95_ms",
        "threshold": max_client_chapter_open_p95_ms,
        "value": client_p95,
        "min_events": min_client_chapter_open_events,
        "events": client_events,
        "status": "skipped",
        "reason": "",
    }
    if client_events >= min_client_chapter_open_events and client_p95 is not None:
        if client_p95 <= max_client_chapter_open_p95_ms:
            client_check["status"] = "pass"
        else:
            client_check["status"] = "fail"
            client_check["reason"] = (
                f"p95={client_p95}ms is above threshold {max_client_chapter_open_p95_ms}ms"
            )
    else:
        client_check["reason"] = "insufficient samples"
    checks.append(client_check)

    server_events = int(current_counts.get("server_reader_events", 0) or 0)
    server_p95 = current_kpi.get("server_api_reader_p95_ms")
    server_check = {
        "name": "server_api_reader_p95_ms",
        "threshold": max_server_api_reader_p95_ms,
        "value": server_p95,
        "min_events": min_server_reader_events,
        "events": server_events,
        "status": "skipped",
        "reason": "",
    }
    if server_events >= min_server_reader_events and server_p95 is not None:
        if server_p95 <= max_server_api_reader_p95_ms:
            server_check["status"] = "pass"
        else:
            server_check["status"] = "fail"
            server_check["reason"] = (
                f"p95={server_p95}ms is above threshold {max_server_api_reader_p95_ms}ms"
            )
    else:
        server_check["reason"] = "insufficient samples"
    checks.append(server_check)

    failed_checks = [check for check in checks if check["status"] == "fail"]
    return {
        "passed": len(failed_checks) == 0,
        "checks": checks,
        "failed_checks": failed_checks,
    }


def load_rows(db_path: Path, previous_start: datetime) -> list[tuple]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.execute(
            """
            SELECT event_type, user_id, payload_json, created_at
            FROM webapp_telemetry
            WHERE created_at >= ?
              AND event_type IN (?, ?, ?, ?)
            ORDER BY created_at ASC
            """,
            (
                previous_start.strftime("%Y-%m-%d %H:%M:%S"),
                EVENT_CLIENT_CHAPTER_OPEN,
                EVENT_SERVER_READER,
                "client_runtime_error",
                "client_unhandled_rejection",
            ),
        )
        return list(cursor.fetchall())


def compute_report(db_path: Path, window_days: int) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    current_start = now - timedelta(days=window_days)
    previous_start = now - timedelta(days=window_days * 2)

    previous = WindowStats(name=f"previous_{window_days}d")
    current = WindowStats(name=f"current_{window_days}d")

    rows = load_rows(db_path, previous_start)
    for event_type, user_id_raw, payload_json_raw, created_at_raw in rows:
        created_at = parse_db_datetime(created_at_raw)
        if created_at is None:
            continue
        if created_at < previous_start:
            continue
        target = current if created_at >= current_start else previous

        user_id = str(user_id_raw or "").strip()
        payload = parse_payload_json(str(payload_json_raw or ""))

        if event_type == EVENT_CLIENT_CHAPTER_OPEN:
            duration = to_finite_float(payload.get("duration_ms"))
            if duration is not None and 0 <= duration <= 120000:
                target.add_client_chapter_duration(duration, user_id)
            continue

        if event_type in CLIENT_ERROR_EVENTS:
            target.add_client_error(user_id)
            continue

        if event_type == EVENT_SERVER_READER:
            duration = to_finite_float(payload.get("duration_ms"))
            if duration is not None and (duration < 0 or duration > 120000):
                duration = None
            status_raw = payload.get("status")
            status = None
            try:
                if status_raw is not None:
                    status = int(status_raw)
            except Exception:
                status = None
            target.add_server_reader_event(duration, status)

    previous_metrics = previous.to_metrics()
    current_metrics = current.to_metrics()
    comparison = build_comparison(previous_metrics, current_metrics)

    return {
        "generated_at_utc": now.strftime("%Y-%m-%d %H:%M:%S"),
        "window_days": window_days,
        "previous": previous_metrics,
        "current": current_metrics,
        **comparison,
    }


def print_human_report(report: dict) -> None:
    w = report["window_days"]
    prev = report["previous"]
    curr = report["current"]
    cmp_data = report["comparison"]
    targets = report["targets"]

    print(f"Telemetry KPI dashboard (weekly comparison, window={w}d)")
    print(f"Generated at (UTC): {report['generated_at_utc']}")
    print("")

    print("Current window KPI")
    print(f"- client_chapter_open_p95_ms: {curr['kpi']['client_chapter_open_p95_ms']}")
    print(f"- server_api_reader_p95_ms: {curr['kpi']['server_api_reader_p95_ms']}")
    print(f"- client_error_rate_pct_proxy: {curr['kpi']['client_error_rate_pct_proxy']}")
    print(f"- server_error_rate_pct: {curr['kpi']['server_error_rate_pct']}")
    print(f"- crash_free_user_pct_proxy: {curr['kpi']['crash_free_user_pct_proxy']}")
    print("")

    print("Event volumes")
    print(f"- current client_chapter_open_events: {curr['counts']['client_chapter_open_events']}")
    print(f"- current server_reader_events: {curr['counts']['server_reader_events']}")
    print(f"- current active_users: {curr['counts']['active_users']}")
    print("")

    print("Week-over-week change")
    print(f"- client_chapter_open_p95 improvement %: {cmp_data['client_chapter_open_p95_improvement_pct']}")
    print(f"- server_api_reader_p95 improvement %: {cmp_data['server_api_reader_p95_improvement_pct']}")
    print("")

    print("Target checks")
    print(f"- client_chapter_open_p95_improvement_gte_25: {targets['client_chapter_open_p95_improvement_gte_25']}")
    print(f"- server_api_reader_p95_improvement_gte_30: {targets['server_api_reader_p95_improvement_gte_30']}")
    print(f"- client_error_rate_lt_1: {targets['client_error_rate_lt_1']}")
    print(f"- server_error_rate_lt_1: {targets['server_error_rate_lt_1']}")
    print(f"- crash_free_gt_99_5: {targets['crash_free_gt_99_5']}")
    print("")

    print("Notes")
    print("- *_proxy metrics are approximations from telemetry events, not full session analytics.")
    print("- If values are null, collect more telemetry for at least one full window.")
    print(f"- Previous window label: {prev['window']}, current window label: {curr['window']}")
    absolute_gate = report.get("absolute_gate")
    if absolute_gate:
        print("")
        print("Absolute gate")
        print(f"- passed: {absolute_gate['passed']}")
        for check in absolute_gate.get("checks", []):
            status = check.get("status")
            value = check.get("value")
            threshold = check.get("threshold")
            events = check.get("events")
            min_events = check.get("min_events")
            reason = check.get("reason", "")
            print(
                f"- {check.get('name')}: status={status}, value={value}, threshold={threshold}, "
                f"events={events}/{min_events}, reason={reason}"
            )


def build_markdown_report(report: dict) -> str:
    curr = report["current"]
    cmp_data = report["comparison"]
    targets = report["targets"]
    absolute_gate = report.get("absolute_gate", {})

    lines = []
    lines.append("# Telemetry KPI Dashboard")
    lines.append("")
    lines.append(f"- Generated at (UTC): `{report['generated_at_utc']}`")
    lines.append(f"- Window days: `{report['window_days']}`")
    lines.append("")
    lines.append("## Current KPI")
    lines.append(f"- `client_chapter_open_p95_ms`: `{curr['kpi']['client_chapter_open_p95_ms']}`")
    lines.append(f"- `server_api_reader_p95_ms`: `{curr['kpi']['server_api_reader_p95_ms']}`")
    lines.append(f"- `client_error_rate_pct_proxy`: `{curr['kpi']['client_error_rate_pct_proxy']}`")
    lines.append(f"- `server_error_rate_pct`: `{curr['kpi']['server_error_rate_pct']}`")
    lines.append(f"- `crash_free_user_pct_proxy`: `{curr['kpi']['crash_free_user_pct_proxy']}`")
    lines.append("")
    lines.append("## Volumes")
    lines.append(f"- `client_chapter_open_events`: `{curr['counts']['client_chapter_open_events']}`")
    lines.append(f"- `server_reader_events`: `{curr['counts']['server_reader_events']}`")
    lines.append(f"- `active_users`: `{curr['counts']['active_users']}`")
    lines.append("")
    lines.append("## Week-over-week")
    lines.append(
        f"- `client_chapter_open_p95_improvement_pct`: `{cmp_data['client_chapter_open_p95_improvement_pct']}`"
    )
    lines.append(
        f"- `server_api_reader_p95_improvement_pct`: `{cmp_data['server_api_reader_p95_improvement_pct']}`"
    )
    lines.append("")
    lines.append("## Target checks")
    lines.append(
        f"- `client_chapter_open_p95_improvement_gte_25`: `{targets['client_chapter_open_p95_improvement_gte_25']}`"
    )
    lines.append(
        f"- `server_api_reader_p95_improvement_gte_30`: `{targets['server_api_reader_p95_improvement_gte_30']}`"
    )
    lines.append(f"- `client_error_rate_lt_1`: `{targets['client_error_rate_lt_1']}`")
    lines.append(f"- `server_error_rate_lt_1`: `{targets['server_error_rate_lt_1']}`")
    lines.append(f"- `crash_free_gt_99_5`: `{targets['crash_free_gt_99_5']}`")
    if absolute_gate:
        lines.append("")
        lines.append("## Absolute gate")
        lines.append(f"- `passed`: `{absolute_gate.get('passed')}`")
        for check in absolute_gate.get("checks", []):
            lines.append(
                f"- `{check.get('name')}`: status=`{check.get('status')}`, value=`{check.get('value')}`, "
                f"threshold=`{check.get('threshold')}`, events=`{check.get('events')}/{check.get('min_events')}`, "
                f"reason=`{check.get('reason')}`"
            )
    lines.append("")
    lines.append("> Notes: `*_proxy` metrics are approximations from telemetry events and not full session analytics.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build weekly KPI comparison from webapp telemetry.")
    parser.add_argument("--db-path", default="manga.db", help="Path to sqlite database (default: manga.db).")
    parser.add_argument(
        "--window-days",
        type=int,
        default=7,
        help="Window size in days for current/previous comparison (default: 7).",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    parser.add_argument("--output-json", default="", help="Write JSON report to file.")
    parser.add_argument("--output-md", default="", help="Write Markdown report to file.")
    parser.add_argument(
        "--max-client-chapter-open-p95-ms",
        type=float,
        default=2500.0,
        help="Absolute gate threshold for current client chapter open p95 (ms).",
    )
    parser.add_argument(
        "--max-server-api-reader-p95-ms",
        type=float,
        default=1200.0,
        help="Absolute gate threshold for current server /api/reader p95 (ms).",
    )
    parser.add_argument(
        "--min-client-chapter-open-events",
        type=int,
        default=5,
        help="Minimum current window events for client p95 gate.",
    )
    parser.add_argument(
        "--min-server-reader-events",
        type=int,
        default=5,
        help="Minimum current window events for server p95 gate.",
    )
    parser.add_argument(
        "--enforce-absolute-gate",
        action="store_true",
        help="Exit with non-zero code when absolute gate fails.",
    )
    args = parser.parse_args()

    if args.window_days <= 0:
        print("ERROR: --window-days must be > 0")
        return 1
    if args.max_client_chapter_open_p95_ms <= 0:
        print("ERROR: --max-client-chapter-open-p95-ms must be > 0")
        return 1
    if args.max_server_api_reader_p95_ms <= 0:
        print("ERROR: --max-server-api-reader-p95-ms must be > 0")
        return 1
    if args.min_client_chapter_open_events <= 0:
        print("ERROR: --min-client-chapter-open-events must be > 0")
        return 1
    if args.min_server_reader_events <= 0:
        print("ERROR: --min-server-reader-events must be > 0")
        return 1

    try:
        report = compute_report(Path(args.db_path), args.window_days)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    report["absolute_gate"] = evaluate_absolute_gate(
        report,
        max_client_chapter_open_p95_ms=args.max_client_chapter_open_p95_ms,
        max_server_api_reader_p95_ms=args.max_server_api_reader_p95_ms,
        min_client_chapter_open_events=args.min_client_chapter_open_events,
        min_server_reader_events=args.min_server_reader_events,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        print_human_report(report)

    if args.output_json:
        output_json_path = Path(args.output_json)
        output_json_path.parent.mkdir(parents=True, exist_ok=True)
        output_json_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
        print(f"Wrote JSON report to: {output_json_path}")

    if args.output_md:
        output_md_path = Path(args.output_md)
        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        output_md_path.write_text(build_markdown_report(report), encoding="utf-8")
        print(f"Wrote Markdown report to: {output_md_path}")

    if args.enforce_absolute_gate and not report["absolute_gate"]["passed"]:
        print("ERROR: absolute KPI gate failed.")
        for failed in report["absolute_gate"]["failed_checks"]:
            print(f" - {failed['name']}: {failed['reason']}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
