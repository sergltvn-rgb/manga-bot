from __future__ import annotations

import asyncio
import json

import aiosqlite


def run(coro):
    return asyncio.run(coro)


def body_json(response):
    return json.loads(response.body.decode("utf-8"))


async def seed_webapp_contract_db(db_path):
    import database

    await database.init_db()
    async with aiosqlite.connect(db_path) as db:
        await db.execute("INSERT INTO chapters_urls (chapter_number, lang, url) VALUES ('1', 'ru', 'https://m/1')")
        await db.execute("INSERT INTO ranobe_urls (chapter_number, lang, url) VALUES ('1', 'ru', 'https://r/1')")
        await db.execute("INSERT INTO webapp_telemetry (event_type, message, stack) VALUES ('client_runtime_error', 'boom', 'trace')")
        await db.commit()


async def async_return(value):
    return value


def test_webapp_error_response_has_recovery_and_request_id():
    from services.webapp_api_utils import webapp_error

    response = webapp_error("forbidden", status=403)
    payload = body_json(response)

    assert response.status == 403
    assert payload["ok"] is False
    assert payload["error"]["code"] == "forbidden"
    assert payload["error"]["message"] == "Нет доступа."
    assert payload["error"]["recovery"] == "Откройте WebApp из Telegram под аккаунтом с нужными правами."
    assert isinstance(payload["request_id"], str)
    assert len(payload["request_id"]) >= 8


def test_admin_forbidden_uses_unified_error_shape(tmp_path, monkeypatch):
    from aiohttp.test_utils import make_mocked_request

    import database
    import services.admin_webapp_api as admin_api

    db_path = tmp_path / "admin.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    run(seed_webapp_contract_db(db_path))
    monkeypatch.setattr(admin_api, "get_auth_user", lambda _request: {"id": 99})
    monkeypatch.setattr(admin_api, "get_admins", lambda: async_return([10]))

    response = run(admin_api.handle_admin_summary(make_mocked_request("GET", "/api/admin/summary")))
    payload = body_json(response)

    assert response.status == 403
    assert payload["ok"] is False
    assert payload["error"]["code"] == "forbidden"
    assert payload["error"]["message"]
    assert payload["error"]["recovery"]
    assert payload["request_id"]


def test_public_webapp_health_exposes_reader_cache_without_secrets(tmp_path, monkeypatch):
    from aiohttp.test_utils import make_mocked_request

    import database
    import services.admin_webapp_api as admin_api

    db_path = tmp_path / "admin.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    monkeypatch.setenv("BOT_TOKEN", "123456:SECRET_TOKEN")
    run(seed_webapp_contract_db(db_path))

    response = run(admin_api.handle_webapp_health(make_mocked_request("GET", "/api/webapp/health")))
    payload = body_json(response)
    serialized = json.dumps(payload, ensure_ascii=False)

    assert response.status == 200
    assert payload["ok"] is True
    assert payload["health"]["database"]["ok"] is True
    assert payload["health"]["reader"]["chapters_total"] >= 1
    assert payload["health"]["webapp_errors_window_hours"] == 24
    assert "SECRET_TOKEN" not in serialized
