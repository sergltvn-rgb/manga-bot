import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
PYTHON = str(VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable))


@dataclass
class StepResult:
    name: str
    command: list[str]
    required: bool
    status: str
    exit_code: int
    duration_s: float
    note: str = ""


def run_step(name: str, command: list[str], required: bool = True) -> StepResult:
    print(f"\n==> {name}")
    print(" ".join(command))
    started_at = time.perf_counter()
    completed = subprocess.run(command, cwd=str(ROOT_DIR), env=os.environ.copy())
    duration_s = time.perf_counter() - started_at
    status = "pass" if completed.returncode == 0 else "fail"
    result = StepResult(
        name=name,
        command=command,
        required=required,
        status=status,
        exit_code=completed.returncode,
        duration_s=round(duration_s, 2),
    )
    if status == "pass":
        print(f"[OK] {name} ({result.duration_s:.2f}s)")
    else:
        print(f"[FAIL] {name} (exit={completed.returncode}, {result.duration_s:.2f}s)")
    return result


def should_manage_local_api(api_url: str) -> bool:
    try:
        parsed = urlparse(api_url)
    except Exception:
        return False
    host = (parsed.hostname or "").strip().lower()
    return host in {"localhost", "127.0.0.1", "0.0.0.0"}


def terminate_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def write_report(output_dir: Path, results: list[StepResult]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "release-candidate-report.json"
    md_path = output_dir / "release-candidate-report.md"

    required_failures = [r for r in results if r.required and r.status == "fail"]
    report = {
        "generated_at_unix": int(time.time()),
        "overall_passed": len(required_failures) == 0,
        "required_failures": [r.name for r in required_failures],
        "steps": [asdict(r) for r in results],
    }
    json_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")

    lines = []
    lines.append("# Release Candidate Gate")
    lines.append("")
    lines.append(f"- overall_passed: `{report['overall_passed']}`")
    if required_failures:
        lines.append(
            "- required_failures: "
            + ", ".join(f"`{name}`" for name in report["required_failures"])
        )
    else:
        lines.append("- required_failures: `none`")
    lines.append("")
    lines.append("## Checklist")
    for step in results:
        mark = "x" if step.status == "pass" else " "
        lines.append(
            f"- [{mark}] `{step.name}` (required={step.required}, status={step.status}, "
            f"exit={step.exit_code}, duration_s={step.duration_s})"
        )
        if step.note:
            lines.append(f"  - note: {step.note}")
    lines.append("")
    lines.append("## Commands")
    for step in results:
        lines.append(f"- `{step.name}`")
        lines.append(f"  - `{ ' '.join(step.command) }`")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run release-candidate gate and generate checklist report.")
    parser.add_argument("--api-url", default=os.getenv("API_URL", "http://localhost:8080").rstrip("/"))
    parser.add_argument(
        "--allowed-origin",
        default=os.getenv("TEST_ALLOWED_ORIGIN", os.getenv("WEBAPP_URL", "http://localhost:8080")),
    )
    parser.add_argument("--with-e2e", action="store_true", help="Include Playwright E2E in regression step.")
    parser.add_argument(
        "--with-auth-limits",
        action="store_true",
        help="Include auth/rate-limit smoke in regression step (requires TMA_AUTH).",
    )
    parser.add_argument("--canary-samples", type=int, default=20)
    parser.add_argument("--canary-interval-ms", type=int, default=500)
    parser.add_argument("--canary-p95-budget-ms", type=float, default=1200.0)
    parser.add_argument("--kpi-window-days", type=int, default=7)
    parser.add_argument("--kpi-client-p95-ms", type=float, default=2500.0)
    parser.add_argument("--kpi-server-p95-ms", type=float, default=1500.0)
    parser.add_argument("--kpi-min-client-events", type=int, default=1)
    parser.add_argument("--kpi-min-server-events", type=int, default=3)
    parser.add_argument("--output-dir", default="artifacts/release-candidate")
    args = parser.parse_args()

    if not Path(PYTHON).exists():
        print(f"ERROR: python not found at {PYTHON}")
        return 1
    if args.canary_samples <= 0 or args.canary_interval_ms < 0:
        print("ERROR: invalid canary sampling settings")
        return 1
    if args.kpi_window_days <= 0:
        print("ERROR: --kpi-window-days must be > 0")
        return 1

    results: list[StepResult] = []
    blocked = False

    regression_cmd = [PYTHON, "scratch/run_regression_suite.py"]
    if args.with_e2e:
        regression_cmd.append("--with-e2e")
    if args.with_auth_limits:
        regression_cmd.append("--with-auth-limits")
    regression_result = run_step("Regression Suite", regression_cmd, required=True)
    results.append(regression_result)
    if regression_result.status == "fail":
        blocked = True

    local_api_process: subprocess.Popen | None = None
    manage_local_api = should_manage_local_api(args.api_url)
    if manage_local_api and not blocked:
        print("\n==> Starting local API-only server for canary probe")
        local_api_process = subprocess.Popen([PYTHON, "scratch/run_api_only.py"], cwd=str(ROOT_DIR), env=os.environ.copy())
        time.sleep(3)

    try:
        if blocked:
            results.append(
                StepResult(
                    name="Canary Probe",
                    command=[],
                    required=True,
                    status="skipped",
                    exit_code=0,
                    duration_s=0.0,
                    note="Skipped because Regression Suite failed.",
                )
            )
        else:
            canary_cmd = [
                PYTHON,
                "scratch/canary_probe.py",
                "--api-url",
                args.api_url,
                "--origin",
                args.allowed_origin,
                "--samples",
                str(args.canary_samples),
                "--interval-ms",
                str(args.canary_interval_ms),
                "--p95-budget-ms",
                str(args.canary_p95_budget_ms),
            ]
            canary_result = run_step("Canary Probe", canary_cmd, required=True)
            results.append(canary_result)
            if canary_result.status == "fail":
                blocked = True
    finally:
        if local_api_process is not None:
            terminate_process(local_api_process)

    if blocked:
        results.append(
            StepResult(
                name="KPI Gate",
                command=[],
                required=True,
                status="skipped",
                exit_code=0,
                duration_s=0.0,
                note="Skipped because previous required step failed.",
            )
        )
    else:
        output_dir = Path(args.output_dir)
        kpi_json = output_dir / "kpi-dashboard.json"
        kpi_md = output_dir / "kpi-dashboard.md"
        kpi_cmd = [
            PYTHON,
            "scratch/telemetry_kpi_dashboard.py",
            "--window-days",
            str(args.kpi_window_days),
            "--output-json",
            str(kpi_json),
            "--output-md",
            str(kpi_md),
            "--enforce-absolute-gate",
            "--min-client-chapter-open-events",
            str(args.kpi_min_client_events),
            "--min-server-reader-events",
            str(args.kpi_min_server_events),
            "--max-client-chapter-open-p95-ms",
            str(args.kpi_client_p95_ms),
            "--max-server-api-reader-p95-ms",
            str(args.kpi_server_p95_ms),
        ]
        kpi_result = run_step("KPI Gate", kpi_cmd, required=True)
        results.append(kpi_result)
        if kpi_result.status == "fail":
            blocked = True

    health_output = Path(args.output_dir) / "release-health-48h.txt"
    if blocked:
        results.append(
            StepResult(
                name="Release Health Snapshot",
                command=[],
                required=False,
                status="skipped",
                exit_code=0,
                duration_s=0.0,
                note="Skipped because previous required step failed.",
            )
        )
    else:
        health_cmd = [
            PYTHON,
            "scratch/release_health_report.py",
            "--hours",
            "48",
        ]
        started_at = time.perf_counter()
        print("\n==> Release Health Snapshot")
        print(" ".join(health_cmd))
        completed = subprocess.run(
            health_cmd,
            cwd=str(ROOT_DIR),
            env=os.environ.copy(),
            capture_output=True,
            text=True,
        )
        duration_s = round(time.perf_counter() - started_at, 2)
        if completed.returncode == 0:
            health_output.parent.mkdir(parents=True, exist_ok=True)
            health_output.write_text(completed.stdout, encoding="utf-8")
            status = "pass"
            note = f"Wrote {health_output}"
            print(f"[OK] Release Health Snapshot ({duration_s:.2f}s)")
        else:
            status = "fail"
            note = (completed.stderr or completed.stdout or "").strip()[:400]
            print(f"[FAIL] Release Health Snapshot (exit={completed.returncode}, {duration_s:.2f}s)")
        results.append(
            StepResult(
                name="Release Health Snapshot",
                command=health_cmd,
                required=False,
                status=status,
                exit_code=completed.returncode,
                duration_s=duration_s,
                note=note,
            )
        )

    report_json, report_md = write_report(Path(args.output_dir), results)
    print(f"\nRelease candidate report JSON: {report_json}")
    print(f"Release candidate report MD:   {report_md}")

    required_failures = [r for r in results if r.required and r.status == "fail"]
    if required_failures:
        print("Release candidate gate FAILED.")
        for failed in required_failures:
            print(f" - {failed.name} (exit={failed.exit_code})")
        return 2

    print("Release candidate gate PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
