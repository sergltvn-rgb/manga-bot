import argparse
import asyncio
import json
import math
import os
import statistics
import sys
import time
from collections import Counter

import aiohttp


def fail(message: str) -> None:
    raise AssertionError(message)


def ensure(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = max(0, min(len(sorted_values) - 1, math.ceil(len(sorted_values) * ratio) - 1))
    return sorted_values[index]


async def read_json(response: aiohttp.ClientResponse) -> dict:
    try:
        return await response.json()
    except Exception:
        return {"_raw": await response.text()}


async def request_reader(
    session: aiohttp.ClientSession,
    api_url: str,
    origin: str,
    if_none_match: str = "",
) -> tuple[int, aiohttp.typedefs.LooseHeaders, dict, float]:
    headers = {"Origin": origin}
    if if_none_match:
        headers["If-None-Match"] = if_none_match

    started_at = time.perf_counter()
    async with session.get(f"{api_url}/api/reader", headers=headers) as response:
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        payload = await read_json(response)
        # Keep case-insensitive header lookups (e.g. ETag/etag).
        return response.status, response.headers.copy(), payload, elapsed_ms


async def run_probe(args: argparse.Namespace) -> int:
    timeout = aiohttp.ClientTimeout(total=args.timeout_seconds)
    latencies_ms: list[float] = []
    statuses: Counter[int] = Counter()

    async with aiohttp.ClientSession(timeout=timeout) as session:
        print("1) Baseline GET /api/reader")
        status, headers, payload, elapsed_ms = await request_reader(
            session=session,
            api_url=args.api_url,
            origin=args.origin,
        )
        ensure(status == 200, f"/api/reader expected 200, got {status}")
        ensure(isinstance(payload, dict), "/api/reader payload must be a JSON object")
        ensure("series" in payload, "/api/reader payload must contain series")
        etag = headers.get("ETag", "").strip()
        ensure(bool(etag), "ETag header is required on /api/reader")
        print(f"   status=200 elapsed_ms={elapsed_ms:.1f} etag={etag}")

        print("2) ETag revalidation GET /api/reader (If-None-Match)")
        status_304, _, payload_304, _ = await request_reader(
            session=session,
            api_url=args.api_url,
            origin=args.origin,
            if_none_match=etag,
        )
        ensure(status_304 == 304, f"Expected 304 for matching If-None-Match, got {status_304}")
        ensure(not payload_304 or "_raw" in payload_304, "304 response should not include JSON payload")

        print("3) CORS preflight OPTIONS /api/reader")
        async with session.options(
            f"{args.api_url}/api/reader",
            headers={"Origin": args.origin, "Access-Control-Request-Method": "GET"},
        ) as response:
            ensure(response.status == 204, f"Preflight expected 204, got {response.status}")
            allow_origin = response.headers.get("Access-Control-Allow-Origin", "")
            ensure(
                allow_origin == args.origin,
                f"Preflight must echo origin ({args.origin}), got {allow_origin!r}",
            )

        print("4) GET /webapp/reader.html")
        async with session.get(f"{args.api_url}/webapp/reader.html") as response:
            ensure(response.status == 200, f"/webapp/reader.html expected 200, got {response.status}")

        if not args.skip_telemetry:
            print("5) POST /api/telemetry smoke event")
            telemetry_payload = {
                "event_type": "client_runtime_error",
                "payload": {
                    "module": "scratch/canary_probe.py",
                    "message": "canary_probe telemetry smoke event",
                },
                "page_url": f"{args.api_url}/webapp/reader.html",
            }
            async with session.post(
                f"{args.api_url}/api/telemetry",
                headers={"Origin": args.origin, "Content-Type": "application/json"},
                data=json.dumps(telemetry_payload),
            ) as response:
                ensure(response.status == 200, f"Telemetry smoke expected 200, got {response.status}")
                payload = await read_json(response)
                ensure(payload.get("ok") is True, "Telemetry smoke should return ok=true")

        print(f"6) Sample /api/reader latency ({args.samples} requests)")
        for idx in range(args.samples):
            status, _, _, elapsed = await request_reader(
                session=session,
                api_url=args.api_url,
                origin=args.origin,
            )
            statuses[status] += 1
            if status == 200:
                latencies_ms.append(elapsed)
            else:
                print(f"   sample={idx + 1} status={status}")
            await asyncio.sleep(args.interval_ms / 1000.0)

    ensure(latencies_ms, "No successful latency samples collected")

    p50 = statistics.median(latencies_ms)
    p95 = percentile(latencies_ms, 0.95)
    status_total = sum(statuses.values())
    non_200 = status_total - statuses.get(200, 0)
    summary = {
        "api_url": args.api_url,
        "origin": args.origin,
        "samples_total": status_total,
        "samples_ok": statuses.get(200, 0),
        "samples_non_200": non_200,
        "status_counts": dict(statuses),
        "latency_ms": {
            "p50": round(p50, 2),
            "p95": round(p95, 2),
            "max": round(max(latencies_ms), 2),
            "budget_p95": args.p95_budget_ms,
        },
    }
    print("\nProbe summary:")
    print(json.dumps(summary, indent=2, ensure_ascii=True))

    if non_200 > 0:
        print("\nFAILED: non-200 responses detected during canary probe.")
        return 1
    if p95 > args.p95_budget_ms:
        print(
            f"\nFAILED: p95 /api/reader latency {p95:.2f}ms "
            f"is above budget {args.p95_budget_ms:.2f}ms."
        )
        return 2

    print("\nCanary probe passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Canary health probe for reader API/WebApp.")
    parser.add_argument(
        "--api-url",
        default=os.getenv("API_URL", "http://localhost:8080").rstrip("/"),
        help="Base API/WebApp URL (default: API_URL env or http://localhost:8080).",
    )
    parser.add_argument(
        "--origin",
        default=os.getenv("TEST_ALLOWED_ORIGIN", os.getenv("WEBAPP_URL", "http://localhost:8080")),
        help="Origin header used for CORS checks.",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=30,
        help="Number of /api/reader latency samples (default: 30).",
    )
    parser.add_argument(
        "--interval-ms",
        type=int,
        default=1000,
        help="Delay between samples in milliseconds (default: 1000).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=20.0,
        help="HTTP request timeout in seconds (default: 20).",
    )
    parser.add_argument(
        "--p95-budget-ms",
        type=float,
        default=float(os.getenv("CANARY_P95_BUDGET_MS", "1200")),
        help="p95 latency budget for /api/reader in milliseconds.",
    )
    parser.add_argument(
        "--skip-telemetry",
        action="store_true",
        help="Skip telemetry smoke event check.",
    )
    args = parser.parse_args()

    if args.samples <= 0:
        print("ERROR: --samples must be > 0")
        return 1
    if args.interval_ms < 0:
        print("ERROR: --interval-ms must be >= 0")
        return 1

    try:
        return asyncio.run(run_probe(args))
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
