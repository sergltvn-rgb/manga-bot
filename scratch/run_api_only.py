import asyncio
import os
import signal
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from database import init_db
from bot import start_webapp_api_server


async def run_api_only() -> None:
    await init_db()

    host = os.getenv("API_BIND_HOST", "0.0.0.0")
    port = int(os.getenv("API_BIND_PORT", "8080"))

    runner = await start_webapp_api_server(host=host, port=port)
    print(f"API-only server is running on {host}:{port}. Press Ctrl+C to stop.")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Windows fallback: KeyboardInterrupt will stop asyncio.run().
            pass

    try:
        await stop_event.wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(run_api_only())
    except KeyboardInterrupt:
        pass
