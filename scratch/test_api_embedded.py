import asyncio
import json
import logging
import sys
from pathlib import Path

import aiosqlite
import aiohttp
import aiohttp.web

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import bot  # noqa: E402
from database import init_db  # noqa: E402


ALLOWED_ORIGIN = "http://localhost:8080"
BLOCKED_ORIGIN = "https://evil.invalid"
USER_ID = 100500
ADMIN_ID = 6210312655
CHAPTER_KEY = "embedded_test_chapter"


def fail(message: str) -> None:
    raise AssertionError(message)


def ensure(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def auth_header(user_id: int, first_name: str = "Tester") -> dict:
    token = f"uid:{user_id}:name:{first_name}"
    return {"Authorization": f"tma {token}"}


def install_test_patches() -> None:
    def fake_validate(init_data: str, _bot_token: str):
        # Expected format: uid:<id>:name:<first_name>
        if not init_data.startswith("uid:"):
            return None
        parts = init_data.split(":")
        try:
            uid = int(parts[1])
        except Exception:
            return None
        first_name = "Tester"
        if len(parts) >= 4 and parts[2] == "name":
            first_name = parts[3]
        return {"user": json.dumps({"id": uid, "first_name": first_name})}

    async def fake_send_message(*_args, **_kwargs):
        return None

    async def fake_run_git_sync(*_args, **_kwargs):
        return True, "mocked"

    bot.validate_telegram_data = fake_validate
    bot.bot.send_message = fake_send_message
    bot.run_git_sync = fake_run_git_sync


async def start_embedded_server() -> tuple[aiohttp.web.AppRunner, str]:
    app = bot.create_webapp_api_app()
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = getattr(site, "_server", None).sockets
    port = sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


async def read_json(resp: aiohttp.ClientResponse) -> dict:
    try:
        return await resp.json()
    except Exception:
        return {"_raw": await resp.text()}


async def _count_telemetry_rows(event_type: str) -> int:
    async with aiosqlite.connect("manga.db") as db:
        async with db.execute(
            "SELECT COUNT(*) FROM webapp_telemetry WHERE event_type = ?",
            (event_type,),
        ) as cur:
            row = await cur.fetchone()
    return int((row or [0])[0] or 0)


async def test_reader_etag_and_304(session: aiohttp.ClientSession, api_url: str) -> None:
    print("1) /api/reader should provide ETag and support 304")
    async with session.get(f"{api_url}/api/reader") as resp:
        ensure(resp.status == 200, f"/api/reader expected 200, got {resp.status}")
        etag = resp.headers.get("ETag", "").strip()
        ensure(bool(etag), "ETag header is required")
    async with session.get(f"{api_url}/api/reader", headers={"If-None-Match": etag}) as resp:
        ensure(resp.status == 304, f"/api/reader If-None-Match expected 304, got {resp.status}")


async def test_server_reader_metric_written(session: aiohttp.ClientSession, api_url: str) -> None:
    print("2) server_api_reader_ms metric should be written when sampling=1")
    before = await _count_telemetry_rows("server_api_reader_ms")
    original_sample_rate = float(getattr(bot, "SERVER_READER_TELEMETRY_SAMPLE_RATE", 0.0))
    bot.SERVER_READER_TELEMETRY_SAMPLE_RATE = 1.0
    try:
        async with session.get(f"{api_url}/api/reader") as resp:
            ensure(resp.status == 200, f"/api/reader metric smoke expected 200, got {resp.status}")
        await asyncio.sleep(0.15)
    finally:
        bot.SERVER_READER_TELEMETRY_SAMPLE_RATE = original_sample_rate

    after = await _count_telemetry_rows("server_api_reader_ms")
    ensure(after > before, "expected server_api_reader_ms telemetry row after /api/reader request")


async def test_cors_allow_and_block(session: aiohttp.ClientSession, api_url: str) -> None:
    print("3) CORS should allow known Origin and block unknown Origin")
    async with session.options(
        f"{api_url}/api/reader",
        headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "GET"},
    ) as resp:
        ensure(resp.status == 204, f"allowed preflight expected 204, got {resp.status}")
        ensure(
            resp.headers.get("Access-Control-Allow-Origin", "") == ALLOWED_ORIGIN,
            "allowed preflight should echo allowed origin",
        )
    async with session.options(
        f"{api_url}/api/reader",
        headers={"Origin": BLOCKED_ORIGIN, "Access-Control-Request-Method": "GET"},
    ) as resp:
        ensure(resp.status == 403, f"blocked preflight expected 403, got {resp.status}")
        payload = await read_json(resp)
        ensure(payload.get("error") == "origin_not_allowed", "blocked preflight error mismatch")


async def test_payload_too_large(session: aiohttp.ClientSession, api_url: str) -> None:
    print("4) Huge payload should return 413 payload_too_large")
    huge_payload = {
        "event_type": "client_runtime_error",
        "payload": {"module": "embedded", "message": "X" * 500_000},
        "page_url": f"{api_url}/webapp/reader.html",
    }
    headers = {"Origin": ALLOWED_ORIGIN, "Content-Type": "application/json"}
    async with session.post(f"{api_url}/api/telemetry", data=json.dumps(huge_payload), headers=headers) as resp:
        ensure(resp.status == 413, f"huge telemetry expected 413, got {resp.status}")
        payload = await read_json(resp)
        ensure(payload.get("error") == "payload_too_large", "413 error code mismatch")


async def test_client_metric_telemetry(session: aiohttp.ClientSession, api_url: str) -> None:
    print("5) client_chapter_open_ms telemetry should validate payload")
    headers = {"Origin": ALLOWED_ORIGIN, "Content-Type": "application/json", **auth_header(USER_ID)}

    good_payload = {
        "event_type": "client_chapter_open_ms",
        "payload": {
            "module": "reader.js",
            "source": "network",
            "duration_ms": 123.45,
            "series_id": "manga_ru",
            "volume": "1",
            "chapter": "1",
            "chapter_idx": 0,
            "used_prefetch": False,
        },
        "page_url": f"{api_url}/webapp/reader.html",
    }
    async with session.post(f"{api_url}/api/telemetry", data=json.dumps(good_payload), headers=headers) as resp:
        ensure(resp.status == 200, f"valid client_chapter_open_ms expected 200, got {resp.status}")
        payload = await read_json(resp)
        ensure(payload.get("ok") is True, "valid client_chapter_open_ms should return ok=true")

    bad_payload = {
        "event_type": "client_chapter_open_ms",
        "payload": {"duration_ms": "not-a-number"},
        "page_url": f"{api_url}/webapp/reader.html",
    }
    async with session.post(f"{api_url}/api/telemetry", data=json.dumps(bad_payload), headers=headers) as resp:
        ensure(resp.status == 400, f"invalid client_chapter_open_ms expected 400, got {resp.status}")
        payload = await read_json(resp)
        ensure(payload.get("error") == "invalid duration_ms", "invalid duration error mismatch")


async def test_auth_and_permissions(session: aiohttp.ClientSession, api_url: str) -> None:
    print("6) Auth and permission checks should return 401/403")
    no_auth_headers = {"Origin": ALLOWED_ORIGIN, "Content-Type": "application/json"}
    unauthorized_payload = {"chapter_key": CHAPTER_KEY, "text": "unauthorized comment"}
    async with session.post(
        f"{api_url}/api/comments",
        data=json.dumps(unauthorized_payload),
        headers=no_auth_headers,
    ) as resp:
        ensure(resp.status == 401, f"/api/comments without auth expected 401, got {resp.status}")

    user_headers = {"Origin": ALLOWED_ORIGIN, "Content-Type": "application/json", **auth_header(USER_ID)}
    forbidden_edit_payload = {
        "series_id": "manga_ru",
        "volume": 1,
        "chapter": "1",
        "url": "https://example.org/forbidden-edit",
    }
    async with session.put(
        f"{api_url}/api/chapters",
        data=json.dumps(forbidden_edit_payload),
        headers=user_headers,
    ) as resp:
        ensure(resp.status == 403, f"/api/chapters non-admin expected 403, got {resp.status}")

    forbidden_sort_payload = {"series_id": "manga_ru", "volume": 1, "order": ["1"]}
    async with session.put(
        f"{api_url}/api/sort",
        data=json.dumps(forbidden_sort_payload),
        headers=user_headers,
    ) as resp:
        ensure(resp.status == 403, f"/api/sort non-admin expected 403, got {resp.status}")


async def test_comment_validation_and_rate_limit(session: aiohttp.ClientSession, api_url: str) -> None:
    print("7) /api/comments should validate and then rate-limit")
    headers = {"Origin": ALLOWED_ORIGIN, "Content-Type": "application/json", **auth_header(USER_ID)}
    invalid_payload = {"chapter_key": CHAPTER_KEY, "text": "x" * 501}
    async with session.post(f"{api_url}/api/comments", data=json.dumps(invalid_payload), headers=headers) as resp:
        ensure(resp.status == 400, f"long comment expected 400, got {resp.status}")

    statuses = []
    for i in range(12):
        payload = {"chapter_key": CHAPTER_KEY, "text": f"embedded-comment-{i}"}
        async with session.post(f"{api_url}/api/comments", data=json.dumps(payload), headers=headers) as resp:
            statuses.append(resp.status)
            if resp.status == 429:
                break
    ensure(429 in statuses, f"comments rate-limit expected 429, got {statuses}")


async def test_reactions_validation_and_rate_limit(session: aiohttp.ClientSession, api_url: str) -> None:
    print("8) /api/reactions should validate and then rate-limit")
    headers = {"Origin": ALLOWED_ORIGIN, "Content-Type": "application/json", **auth_header(USER_ID)}
    invalid_payload = {"chapter_key": CHAPTER_KEY, "reaction": "R" * 99}
    async with session.post(f"{api_url}/api/reactions", data=json.dumps(invalid_payload), headers=headers) as resp:
        ensure(resp.status == 400, f"invalid reaction expected 400, got {resp.status}")

    statuses = []
    for i in range(40):
        payload = {"chapter_key": CHAPTER_KEY, "reaction": "like" if i % 2 == 0 else "fire"}
        async with session.post(f"{api_url}/api/reactions", data=json.dumps(payload), headers=headers) as resp:
            statuses.append(resp.status)
            if resp.status == 429:
                break
    ensure(429 in statuses, f"reactions rate-limit expected 429, got {statuses}")


async def test_admin_validation_errors(session: aiohttp.ClientSession, api_url: str) -> None:
    print("9) Admin endpoints should reject invalid input with 400")
    headers = {"Origin": ALLOWED_ORIGIN, "Content-Type": "application/json", **auth_header(ADMIN_ID, "Admin")}

    bad_chapter_edit = {
        "series_id": "manga_ru",
        "volume": 1,
        "chapter": "1",
        "url": "javascript:alert(1)",
    }
    async with session.put(f"{api_url}/api/chapters", data=json.dumps(bad_chapter_edit), headers=headers) as resp:
        ensure(resp.status == 400, f"/api/chapters invalid url expected 400, got {resp.status}")

    bad_bulk = {
        "series_id": "manga_ru",
        "volume": 1,
        "start_chapter": 1,
        "urls": ["https://ok.example/ch1", "not-a-url"],
    }
    async with session.post(f"{api_url}/api/chapters/bulk", data=json.dumps(bad_bulk), headers=headers) as resp:
        ensure(resp.status == 400, f"/api/chapters/bulk invalid url expected 400, got {resp.status}")

    bad_sort = {
        "series_id": "manga_ru",
        "volume": 1,
        "order": ["1", "bad chapter id !"],
    }
    async with session.put(f"{api_url}/api/sort", data=json.dumps(bad_sort), headers=headers) as resp:
        ensure(resp.status == 400, f"/api/sort invalid order expected 400, got {resp.status}")


async def _count_admin_audit_rows(action: str, actor_user_id: int) -> int:
    async with aiosqlite.connect("manga.db") as db:
        async with db.execute(
            "SELECT COUNT(*) FROM admin_audit_log WHERE action = ? AND actor_user_id = ?",
            (action, str(actor_user_id)),
        ) as cur:
            row = await cur.fetchone()
    return int((row or [0])[0] or 0)


async def test_admin_rate_limit_and_audit(session: aiohttp.ClientSession, api_url: str) -> None:
    print("10) Admin endpoint should hit 429 and write audit rows")
    headers = {"Origin": ALLOWED_ORIGIN, "Content-Type": "application/json", **auth_header(ADMIN_ID, "Admin")}

    action = "rename_request_cache"
    before = await _count_admin_audit_rows(action, ADMIN_ID)
    original_rule = dict(bot.RATE_LIMIT_RULES.get("admin_rename_request", {}))
    bot.RATE_LIMIT_RULES["admin_rename_request"] = {"limit": 2, "window": 60}

    try:
        statuses = []
        for i in range(5):
            payload = {"obj_id": f"manga_ru:1:{i + 1}"}
            async with session.post(
                f"{api_url}/api/rename/request",
                data=json.dumps(payload),
                headers=headers,
            ) as resp:
                statuses.append(resp.status)
                if resp.status == 429:
                    break
        ensure(429 in statuses, f"/api/rename/request expected 429, got {statuses}")
    finally:
        if original_rule:
            bot.RATE_LIMIT_RULES["admin_rename_request"] = original_rule
        else:
            bot.RATE_LIMIT_RULES.pop("admin_rename_request", None)

    after = await _count_admin_audit_rows(action, ADMIN_ID)
    ensure(after > before, "expected at least one admin audit log row to be written")


async def main() -> None:
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    install_test_patches()
    await init_db()

    runner, api_url = await start_embedded_server()
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            await test_reader_etag_and_304(session, api_url)
            await test_server_reader_metric_written(session, api_url)
            await test_cors_allow_and_block(session, api_url)
            await test_payload_too_large(session, api_url)
            await test_client_metric_telemetry(session, api_url)
            await test_auth_and_permissions(session, api_url)
            await test_comment_validation_and_rate_limit(session, api_url)
            await test_reactions_validation_and_rate_limit(session, api_url)
            await test_admin_validation_errors(session, api_url)
            await test_admin_rate_limit_and_audit(session, api_url)
    finally:
        await runner.cleanup()

    print("Embedded API integration checks passed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise
