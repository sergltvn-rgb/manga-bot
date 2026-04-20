import aiohttp
import asyncio
import json
import os
import sys
import time

API_URL = os.getenv("API_URL", "http://localhost:8080").rstrip("/")
ALLOWED_ORIGIN = os.getenv("TEST_ALLOWED_ORIGIN", "http://localhost:8080")
TMA_AUTH = os.getenv("TMA_AUTH", "").strip()

TEST_CHAPTER_KEY = os.getenv("TEST_CHAPTER_KEY", "integration_limits_v1")
RUN_REPORT_LIMIT_TEST = os.getenv("TEST_RUN_REPORT_LIMIT", "0") in {"1", "true", "True"}


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
        return {"_raw": await resp.text()}


def build_headers() -> dict:
    return {
        "Authorization": f"tma {TMA_AUTH}",
        "Content-Type": "application/json",
        "Origin": ALLOWED_ORIGIN,
    }


async def test_auth_limits() -> None:
    if not TMA_AUTH:
        print("SKIPPED: set TMA_AUTH env var to run auth/429 checks.")
        return

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        headers = build_headers()

        print("1) POST /api/comments with too long text -> 400")
        long_comment = {
            "chapter_key": TEST_CHAPTER_KEY,
            "text": "x" * 501,
        }
        async with session.post(
            f"{API_URL}/api/comments",
            headers=headers,
            data=json.dumps(long_comment),
        ) as resp:
            ensure(resp.status == 400, f"expected 400 for too long comment, got {resp.status}")

        print("2) POST /api/comments rate limit -> 429")
        statuses = []
        for i in range(12):
            payload = {
                "chapter_key": TEST_CHAPTER_KEY,
                "text": f"limits-smoke-{i}-{int(time.time() * 1000)}",
            }
            async with session.post(
                f"{API_URL}/api/comments",
                headers=headers,
                data=json.dumps(payload),
            ) as resp:
                statuses.append(resp.status)
                if resp.status == 429:
                    break
        ensure(429 in statuses, f"expected at least one 429 for comments, got statuses={statuses}")

        print("3) POST /api/reactions with invalid reaction -> 400")
        invalid_reaction = {
            "chapter_key": TEST_CHAPTER_KEY,
            "reaction": "x" * 100,
        }
        async with session.post(
            f"{API_URL}/api/reactions",
            headers=headers,
            data=json.dumps(invalid_reaction),
        ) as resp:
            ensure(resp.status == 400, f"expected 400 for invalid reaction, got {resp.status}")

        print("4) POST /api/reactions rate limit -> 429")
        statuses = []
        for i in range(36):
            payload = {
                "chapter_key": TEST_CHAPTER_KEY,
                "reaction": "like" if i % 2 == 0 else "fire",
            }
            async with session.post(
                f"{API_URL}/api/reactions",
                headers=headers,
                data=json.dumps(payload),
            ) as resp:
                statuses.append(resp.status)
                if resp.status == 429:
                    break
        ensure(429 in statuses, f"expected at least one 429 for reactions, got statuses={statuses}")

        print("5) POST /api/comments/report validation -> 400")
        invalid_report = {
            "comment_id": 1,
            "reason": "x" * 301,
            "comment_text": "test",
        }
        async with session.post(
            f"{API_URL}/api/comments/report",
            headers=headers,
            data=json.dumps(invalid_report),
        ) as resp:
            ensure(resp.status == 400, f"expected 400 for invalid report reason, got {resp.status}")

        if RUN_REPORT_LIMIT_TEST:
            print("6) POST /api/comments/report rate limit -> 429")
            statuses = []
            for _ in range(10):
                payload = {"comment_id": 1, "reason": "spam", "comment_text": "smoke"}
                async with session.post(
                    f"{API_URL}/api/comments/report",
                    headers=headers,
                    data=json.dumps(payload),
                ) as resp:
                    statuses.append(resp.status)
                    if resp.status == 429:
                        break
            ensure(429 in statuses, f"expected 429 for comments/report, got statuses={statuses}")
        else:
            print("6) SKIPPED report 429 spam-check (set TEST_RUN_REPORT_LIMIT=1 to enable).")

    print("Auth/limit checks passed.")


if __name__ == "__main__":
    try:
        asyncio.run(test_auth_limits())
    except Exception as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
