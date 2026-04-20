import aiohttp
import asyncio
import json
import os
import sys

API_URL = os.getenv("API_URL", "http://localhost:8080").rstrip("/")
ALLOWED_ORIGIN = os.getenv("TEST_ALLOWED_ORIGIN", "http://localhost:8080")
BLOCKED_ORIGIN = os.getenv("TEST_BLOCKED_ORIGIN", "https://evil.invalid")
EXPECT_413 = os.getenv("TEST_EXPECT_413", "1") not in {"0", "false", "False"}


def fail(message: str) -> None:
    print(f"FAILED: {message}")
    raise AssertionError(message)


def ensure(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


async def read_json(resp: aiohttp.ClientResponse) -> dict:
    try:
        return await resp.json()
    except Exception:
        raw = await resp.text()
        return {"_raw": raw}


async def test_api_security() -> None:
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        print("1) GET /api/reader")
        async with session.get(f"{API_URL}/api/reader") as resp:
            ensure(resp.status == 200, f"/api/reader status expected 200, got {resp.status}")
            reader_payload = await read_json(resp)
            ensure(isinstance(reader_payload, dict), "reader payload must be object")
            ensure("series" in reader_payload, "reader payload must contain series")
            etag = resp.headers.get("ETag", "").strip()
            ensure(bool(etag), "ETag header is required on /api/reader")
            vary = resp.headers.get("Vary", "")
            ensure("Origin" in vary, "Vary must include Origin for /api/*")

        print("2) GET /api/reader with If-None-Match")
        async with session.get(f"{API_URL}/api/reader", headers={"If-None-Match": etag}) as resp:
            ensure(resp.status == 304, f"expected 304 for matching If-None-Match, got {resp.status}")

        print("3) OPTIONS /api/reader with allowed Origin")
        async with session.options(
            f"{API_URL}/api/reader",
            headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "GET"},
        ) as resp:
            ensure(resp.status == 204, f"allowed preflight expected 204, got {resp.status}")
            allow_origin = resp.headers.get("Access-Control-Allow-Origin", "")
            ensure(
                allow_origin == ALLOWED_ORIGIN,
                f"allowed preflight must echo origin ({ALLOWED_ORIGIN}), got {allow_origin!r}",
            )

        print("4) OPTIONS /api/reader with blocked Origin")
        async with session.options(
            f"{API_URL}/api/reader",
            headers={"Origin": BLOCKED_ORIGIN, "Access-Control-Request-Method": "GET"},
        ) as resp:
            ensure(resp.status == 403, f"blocked preflight expected 403, got {resp.status}")
            payload = await read_json(resp)
            ensure(payload.get("error") == "origin_not_allowed", "blocked preflight must return origin_not_allowed")

        print("5) GET /api/reader with blocked Origin")
        async with session.get(f"{API_URL}/api/reader", headers={"Origin": BLOCKED_ORIGIN}) as resp:
            ensure(resp.status == 403, f"blocked simple request expected 403, got {resp.status}")
            payload = await read_json(resp)
            ensure(payload.get("error") == "origin_not_allowed", "blocked request must return origin_not_allowed")

        print("6) POST /api/telemetry small payload")
        telemetry_payload = {
            "event_type": "client_runtime_error",
            "payload": {
                "module": "scratch/test_api_security.py",
                "message": "smoke telemetry event",
            },
            "page_url": f"{API_URL}/webapp/reader.html",
        }
        async with session.post(
            f"{API_URL}/api/telemetry",
            headers={"Origin": ALLOWED_ORIGIN, "Content-Type": "application/json"},
            data=json.dumps(telemetry_payload),
        ) as resp:
            ensure(resp.status == 200, f"telemetry POST expected 200, got {resp.status}")
            payload = await read_json(resp)
            ensure(payload.get("ok") is True, "telemetry POST should return ok=true")

        print("7) POST /api/telemetry huge payload (expect 413)")
        huge_payload = {
            "event_type": "client_runtime_error",
            "payload": {
                "module": "scratch/test_api_security.py",
                "message": "X" * 400_000,
            },
            "page_url": f"{API_URL}/webapp/reader.html",
        }
        async with session.post(
            f"{API_URL}/api/telemetry",
            headers={"Origin": ALLOWED_ORIGIN, "Content-Type": "application/json"},
            data=json.dumps(huge_payload),
        ) as resp:
            if EXPECT_413:
                ensure(resp.status == 413, f"huge payload expected 413, got {resp.status}")
                payload = await read_json(resp)
                ensure(payload.get("error") == "payload_too_large", "413 response should return payload_too_large")
            else:
                print(f"   NOTE: TEST_EXPECT_413=0, actual status={resp.status}")

    print("API security checks passed.")


if __name__ == "__main__":
    try:
        asyncio.run(test_api_security())
    except Exception as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
