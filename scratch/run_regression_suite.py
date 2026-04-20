import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
PYTHON = str(VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable))


def run_step(name: str, command: list[str], cwd: Path, env: dict[str, str] | None = None) -> bool:
    print(f"\n==> {name}")
    print(" ".join(command))
    process = subprocess.run(command, cwd=str(cwd), env=env)
    if process.returncode != 0:
        print(f"[FAIL] {name} (exit={process.returncode})")
        return False
    print(f"[OK] {name}")
    return True


def terminate_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_api_only_sequence(run_auth_limits: bool) -> bool:
    print("\n==> Starting API-only server for external smoke checks")
    api_server = subprocess.Popen([PYTHON, "scratch/run_api_only.py"], cwd=str(ROOT_DIR))
    time.sleep(3)
    try:
        if not run_step(
            "Public security smoke (external API)",
            [PYTHON, "scratch/test_api_security.py"],
            ROOT_DIR,
            env=os.environ.copy(),
        ):
            return False

        if run_auth_limits:
            if not run_step(
                "Auth/rate-limit smoke (external API)",
                [PYTHON, "scratch/test_api_auth_limits.py"],
                ROOT_DIR,
                env=os.environ.copy(),
            ):
                return False
        else:
            print("[SKIP] Auth/rate-limit smoke (TMA_AUTH is not set)")
    finally:
        terminate_process(api_server)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run reader API/webapp regression suite.")
    parser.add_argument(
        "--with-e2e",
        action="store_true",
        help="Run Playwright WebApp regression (npm run test:e2e).",
    )
    parser.add_argument(
        "--with-auth-limits",
        action="store_true",
        help="Force auth/rate-limit smoke (requires TMA_AUTH env).",
    )
    args = parser.parse_args()

    if not Path(PYTHON).exists():
        print(f"ERROR: python not found at {PYTHON}")
        return 1

    auth_available = bool(os.environ.get("TMA_AUTH", "").strip())
    run_auth_limits = args.with_auth_limits or auth_available
    if args.with_auth_limits and not auth_available:
        print("ERROR: --with-auth-limits requested but TMA_AUTH env var is missing.")
        return 1

    if not run_step(
        "Embedded API integration smoke",
        [PYTHON, "scratch/test_api_embedded.py"],
        ROOT_DIR,
        env=os.environ.copy(),
    ):
        return 1

    if not run_api_only_sequence(run_auth_limits=run_auth_limits):
        return 1

    if args.with_e2e:
        npm_cmd = ["cmd", "/c", "npm", "run", "test:e2e"] if os.name == "nt" else ["npm", "run", "test:e2e"]
        if not run_step(
            "WebApp Playwright E2E smoke",
            npm_cmd,
            ROOT_DIR / "webapp",
            env=os.environ.copy(),
        ):
            return 1
    else:
        print("[SKIP] WebApp Playwright E2E smoke (use --with-e2e to enable)")

    print("\nRegression suite completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
