import argparse
import json
import sqlite3
import sys
from pathlib import Path


def query_count(conn: sqlite3.Connection, sql: str, params: tuple) -> int:
    cursor = conn.execute(sql, params)
    row = cursor.fetchone()
    return int(row[0] if row else 0)


def query_rows(conn: sqlite3.Connection, sql: str, params: tuple) -> list[tuple]:
    cursor = conn.execute(sql, params)
    return list(cursor.fetchall())


def build_report(db_path: Path, hours: int, top: int) -> dict:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    window = f"-{hours} hours"
    with sqlite3.connect(str(db_path)) as conn:
        telemetry_total = query_count(
            conn,
            "SELECT COUNT(*) FROM webapp_telemetry WHERE created_at >= datetime('now', ?)",
            (window,),
        )
        telemetry_by_type_rows = query_rows(
            conn,
            """
            SELECT event_type, COUNT(*) AS cnt
            FROM webapp_telemetry
            WHERE created_at >= datetime('now', ?)
            GROUP BY event_type
            ORDER BY cnt DESC
            """,
            (window,),
        )
        telemetry_by_source_rows = query_rows(
            conn,
            """
            SELECT source_module, COUNT(*) AS cnt
            FROM webapp_telemetry
            WHERE created_at >= datetime('now', ?)
              AND source_module != ''
            GROUP BY source_module
            ORDER BY cnt DESC
            LIMIT ?
            """,
            (window, top),
        )
        telemetry_users = query_count(
            conn,
            """
            SELECT COUNT(DISTINCT user_id)
            FROM webapp_telemetry
            WHERE created_at >= datetime('now', ?)
              AND user_id != ''
            """,
            (window,),
        )

        audit_total = query_count(
            conn,
            "SELECT COUNT(*) FROM admin_audit_log WHERE created_at >= datetime('now', ?)",
            (window,),
        )
        audit_errors = query_count(
            conn,
            """
            SELECT COUNT(*)
            FROM admin_audit_log
            WHERE created_at >= datetime('now', ?)
              AND result != 'ok'
            """,
            (window,),
        )
        audit_by_action_rows = query_rows(
            conn,
            """
            SELECT action, COUNT(*) AS cnt
            FROM admin_audit_log
            WHERE created_at >= datetime('now', ?)
            GROUP BY action
            ORDER BY cnt DESC
            """,
            (window,),
        )
        audit_recent_errors = query_rows(
            conn,
            """
            SELECT created_at, action, actor_user_id, target, error
            FROM admin_audit_log
            WHERE created_at >= datetime('now', ?)
              AND result != 'ok'
            ORDER BY id DESC
            LIMIT ?
            """,
            (window, top),
        )

    audit_error_rate = (audit_errors / audit_total * 100.0) if audit_total else 0.0
    return {
        "window_hours": hours,
        "db_path": str(db_path),
        "telemetry": {
            "total_events": telemetry_total,
            "distinct_users": telemetry_users,
            "by_event_type": [{"event_type": row[0], "count": int(row[1])} for row in telemetry_by_type_rows],
            "top_sources": [{"source_module": row[0], "count": int(row[1])} for row in telemetry_by_source_rows],
        },
        "admin_audit": {
            "total_actions": audit_total,
            "errors": audit_errors,
            "error_rate_pct": round(audit_error_rate, 2),
            "by_action": [{"action": row[0], "count": int(row[1])} for row in audit_by_action_rows],
            "recent_errors": [
                {
                    "created_at": row[0],
                    "action": row[1],
                    "actor_user_id": row[2],
                    "target": row[3],
                    "error": row[4],
                }
                for row in audit_recent_errors
            ],
        },
    }


def print_human_report(report: dict) -> None:
    telemetry = report["telemetry"]
    admin = report["admin_audit"]

    print(f"Release health report ({report['window_hours']}h)")
    print(f"DB: {report['db_path']}")
    print("")
    print("Telemetry")
    print(f"- total_events: {telemetry['total_events']}")
    print(f"- distinct_users: {telemetry['distinct_users']}")
    print("- by_event_type:")
    if telemetry["by_event_type"]:
        for row in telemetry["by_event_type"]:
            print(f"  - {row['event_type']}: {row['count']}")
    else:
        print("  - none")
    print("- top_sources:")
    if telemetry["top_sources"]:
        for row in telemetry["top_sources"]:
            print(f"  - {row['source_module']}: {row['count']}")
    else:
        print("  - none")

    print("")
    print("Admin audit")
    print(f"- total_actions: {admin['total_actions']}")
    print(f"- errors: {admin['errors']}")
    print(f"- error_rate_pct: {admin['error_rate_pct']}")
    print("- by_action:")
    if admin["by_action"]:
        for row in admin["by_action"]:
            print(f"  - {row['action']}: {row['count']}")
    else:
        print("  - none")
    print("- recent_errors:")
    if admin["recent_errors"]:
        for row in admin["recent_errors"]:
            print(
                "  - "
                f"{row['created_at']} action={row['action']} actor={row['actor_user_id']} "
                f"target={row['target']} error={row['error']}"
            )
    else:
        print("  - none")


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize release health signals from sqlite DB.")
    parser.add_argument(
        "--db-path",
        default="manga.db",
        help="Path to sqlite DB (default: manga.db).",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=48,
        help="Trailing window in hours (default: 48).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Top-N rows for grouped outputs (default: 10).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output only.",
    )
    args = parser.parse_args()

    if args.hours <= 0:
        print("ERROR: --hours must be > 0")
        return 1
    if args.top <= 0:
        print("ERROR: --top must be > 0")
        return 1

    try:
        report = build_report(Path(args.db_path), args.hours, args.top)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        print_human_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
