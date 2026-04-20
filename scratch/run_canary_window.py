import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
PYTHON = str(VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable))


def run_probe(args: argparse.Namespace) -> int:
    cmd = [
        PYTHON,
        "scratch/canary_probe.py",
        "--api-url",
        args.api_url,
        "--origin",
        args.origin,
        "--samples",
        str(args.samples),
        "--interval-ms",
        str(args.interval_ms),
        "--p95-budget-ms",
        str(args.p95_budget_ms),
        "--timeout-seconds",
        str(args.timeout_seconds),
    ]
    if args.skip_telemetry:
        cmd.append("--skip-telemetry")

    print("Running probe command:", flush=True)
    print(" ".join(cmd), flush=True)
    completed = subprocess.run(cmd, cwd=str(ROOT_DIR), env=os.environ.copy())
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run canary_probe repeatedly for a rollout monitoring window."
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("API_URL", "http://localhost:8080").rstrip("/"),
        help="Base API/WebApp URL.",
    )
    parser.add_argument(
        "--origin",
        default=os.getenv("TEST_ALLOWED_ORIGIN", os.getenv("WEBAPP_URL", "http://localhost:8080")),
        help="Origin header used for CORS checks.",
    )
    parser.add_argument(
        "--duration-minutes",
        type=float,
        default=120.0,
        help="Total monitoring window duration in minutes (default: 120).",
    )
    parser.add_argument(
        "--probe-every-minutes",
        type=float,
        default=15.0,
        help="Run one canary probe every N minutes (default: 15).",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=20,
        help="Latency samples per probe run (default: 20).",
    )
    parser.add_argument(
        "--interval-ms",
        type=int,
        default=500,
        help="Delay between /api/reader samples in milliseconds (default: 500).",
    )
    parser.add_argument(
        "--p95-budget-ms",
        type=float,
        default=float(os.getenv("CANARY_P95_BUDGET_MS", "1200")),
        help="p95 latency budget for /api/reader in milliseconds.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=20.0,
        help="HTTP timeout per request in seconds (default: 20).",
    )
    parser.add_argument(
        "--skip-telemetry",
        action="store_true",
        help="Skip telemetry smoke event checks in each probe.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Do not stop on first failed probe; continue until end of window.",
    )
    args = parser.parse_args()

    if args.duration_minutes <= 0:
        print("ERROR: --duration-minutes must be > 0")
        return 1
    if args.probe_every_minutes <= 0:
        print("ERROR: --probe-every-minutes must be > 0")
        return 1
    if args.samples <= 0:
        print("ERROR: --samples must be > 0")
        return 1
    if not Path(PYTHON).exists():
        print(f"ERROR: python not found at {PYTHON}")
        return 1

    deadline = time.time() + args.duration_minutes * 60.0
    sleep_seconds = args.probe_every_minutes * 60.0
    run_index = 0
    failed_runs = 0

    while time.time() <= deadline:
        run_index += 1
        now_human = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n=== Canary window run #{run_index} at {now_human} ===", flush=True)
        rc = run_probe(args)
        if rc != 0:
            failed_runs += 1
            print(f"[FAIL] Probe run #{run_index} exited with code {rc}", flush=True)
            if not args.keep_going:
                return rc
        else:
            print(f"[OK] Probe run #{run_index}", flush=True)

        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(sleep_seconds, max(0.0, remaining)))

    print("\nCanary window completed.", flush=True)
    print(f"Total runs: {run_index}", flush=True)
    print(f"Failed runs: {failed_runs}", flush=True)
    return 1 if failed_runs > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
