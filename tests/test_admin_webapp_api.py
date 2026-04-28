from __future__ import annotations

import asyncio
import json

import aiosqlite


def run(coro):
    return asyncio.run(coro)


def body_json(response):
    return json.loads(response.body.decode("utf-8"))


async def seed_admin_api_db(db_path):
    import database

    await database.init_db()
    async with aiosqlite.connect(db_path) as db:
        await db.execute("INSERT INTO users_stats (user_id, messages_count, balance) VALUES (1, 7, 100)")
        await db.execute("INSERT INTO users_stats (user_id, messages_count, balance) VALUES (2, 3, 50)")
        await db.execute("INSERT INTO chapters_urls (chapter_number, lang, url) VALUES ('1', 'ru', 'https://m/1')")
        await db.execute("INSERT INTO ranobe_urls (chapter_number, lang, url) VALUES ('1', 'ru', 'https://r/1')")
        await db.execute("INSERT INTO akashic_ranobe (volume, chapter, url) VALUES (1, '1', 'https://a/1')")
        await db.execute("INSERT INTO british_ranobe (volume, chapter, url) VALUES (1, '1', 'https://b/1')")
        await db.execute("INSERT INTO arts (file_id, source, is_hidden) VALUES ('art-visible', 'admin_upload', 0)")
        await db.execute("INSERT INTO arts (file_id, source, is_hidden) VALUES ('art-hidden', 'admin_upload', 1)")
        await db.execute("INSERT INTO suggested_arts (user_id, file_id, status) VALUES (42, 'suggested', 'pending')")
        await db.execute(
            """
            INSERT INTO giveaways
            (status, channel_id, prize, post_text, winners_count, ends_at_utc, created_by, created_at)
            VALUES ('active', '@channel', 'VIP', 'Post', 1, '2099-01-01T00:00:00+00:00', 10, '2026-01-01T00:00:00+00:00')
            """
        )
        await db.execute("UPDATE giveaways SET message_id = 321 WHERE channel_id = '@channel'")
        await db.execute(
            """
            INSERT INTO giveaway_required_channels (giveaway_id, channel_id, title, url)
            VALUES (1, '@required', '@required', 'https://t.me/required')
            """
        )
        await db.execute("INSERT INTO chapter_comments (chapter_key, user_id, user_name, text) VALUES ('manga_ru_1', '1', 'A', 'Hi')")
        await db.execute("INSERT INTO webapp_telemetry (event_type, message, stack) VALUES ('client_runtime_error', 'boom', 'trace')")
        await db.execute(
            """
            INSERT INTO webapp_telemetry (event_type, message, stack, created_at)
            VALUES ('client_runtime_error', 'old boom', 'trace', '2026-01-01 00:00:00')
            """
        )
        await db.execute(
            """
            INSERT INTO admin_audit_log (action, actor_user_id, target, payload_json, result, error, created_at)
            VALUES ('older', '10', 'x', '{}', 'ok', '', '2026-01-01 10:00:00')
            """
        )
        await db.execute(
            """
            INSERT INTO admin_audit_log (action, actor_user_id, target, payload_json, result, error, created_at)
            VALUES ('newer', '10', 'y', '{"id":1}', 'ok', '', '2026-01-02 10:00:00')
            """
        )
        await db.commit()


def install_auth(monkeypatch, *, user_id=10, admins=(10,)):
    import services.admin_webapp_api as admin_api

    monkeypatch.setattr(admin_api, "get_auth_user", lambda _request: {"id": user_id, "first_name": "Admin"})
    monkeypatch.setattr(admin_api, "get_admins", lambda: asyncio.sleep(0, result=list(admins)))


def test_admin_summary_returns_operator_counts(tmp_path, monkeypatch):
    from aiohttp.test_utils import make_mocked_request

    import database
    import services.admin_webapp_api as admin_api

    db_path = tmp_path / "admin.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    run(seed_admin_api_db(db_path))
    install_auth(monkeypatch)

    response = run(admin_api.handle_admin_summary(make_mocked_request("GET", "/api/admin/summary")))
    payload = body_json(response)

    assert response.status == 200
    assert payload["ok"] is True
    assert payload["counts"]["users_total"] == 2
    assert payload["counts"]["chapters_total"] == 5
    assert payload["counts"]["arts_visible"] == 1
    assert payload["counts"]["arts_hidden"] == 1
    assert payload["counts"]["suggestions_pending"] == 1
    assert payload["counts"]["giveaways_active"] == 1
    assert payload["counts"]["giveaways_running"] == 1
    assert payload["counts"]["giveaways_scheduled"] == 0
    assert payload["counts"]["giveaways_finished"] == 0
    assert payload["counts"]["comments_total"] == 1
    assert payload["counts"]["webapp_errors"] == 1


def test_admin_api_forbids_non_admin(tmp_path, monkeypatch):
    from aiohttp.test_utils import make_mocked_request

    import database
    import services.admin_webapp_api as admin_api

    db_path = tmp_path / "admin.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    run(seed_admin_api_db(db_path))
    install_auth(monkeypatch, user_id=99, admins=(10,))

    response = run(admin_api.handle_admin_summary(make_mocked_request("GET", "/api/admin/summary")))
    payload = body_json(response)

    assert response.status == 403
    assert payload["ok"] is False
    assert payload["error"]["code"] == "forbidden"
    assert payload["error"]["message"]
    assert payload["error"]["recovery"]
    assert payload["request_id"]


def test_admin_health_does_not_expose_secrets(tmp_path, monkeypatch):
    from aiohttp.test_utils import make_mocked_request

    import database
    import services.admin_webapp_api as admin_api

    db_path = tmp_path / "admin.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    monkeypatch.setenv("GROQ_API_KEY", "secret-groq-key")
    monkeypatch.setenv("BOT_TOKEN", "123456:SECRET_TOKEN")
    run(seed_admin_api_db(db_path))
    install_auth(monkeypatch)

    response = run(admin_api.handle_admin_health(make_mocked_request("GET", "/api/admin/health")))
    payload = body_json(response)
    serialized = json.dumps(payload)

    assert response.status == 200
    assert payload["ok"] is True
    assert payload["health"]["database"]["ok"] is True
    assert "git" in payload["health"]
    assert "secret-groq-key" not in serialized
    assert "SECRET_TOKEN" not in serialized
    assert [item["message"] for item in payload["health"]["recent_errors"]] == ["boom"]


def test_admin_audit_is_paginated_newest_first(tmp_path, monkeypatch):
    from aiohttp.test_utils import make_mocked_request

    import database
    import services.admin_webapp_api as admin_api

    db_path = tmp_path / "admin.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    run(seed_admin_api_db(db_path))
    install_auth(monkeypatch)

    first = run(admin_api.handle_admin_audit(make_mocked_request("GET", "/api/admin/audit?limit=1&offset=0")))
    second = run(admin_api.handle_admin_audit(make_mocked_request("GET", "/api/admin/audit?limit=1&offset=1")))

    assert body_json(first)["items"][0]["action"] == "newer"
    assert body_json(second)["items"][0]["action"] == "older"
    assert body_json(first)["total"] == 2


def test_admin_audit_filters_by_result_and_search(tmp_path, monkeypatch):
    from aiohttp.test_utils import make_mocked_request

    import database
    import services.admin_webapp_api as admin_api

    db_path = tmp_path / "admin.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    run(seed_admin_api_db(db_path))
    install_auth(monkeypatch)

    response = run(admin_api.handle_admin_audit(make_mocked_request("GET", "/api/admin/audit?result=ok&q=y")))
    payload = body_json(response)

    assert response.status == 200
    assert payload["total"] == 1
    assert payload["items"][0]["action"] == "newer"


def test_admin_sync_runs_job_and_writes_audit(tmp_path, monkeypatch):
    from aiohttp.test_utils import make_mocked_request

    import database
    import services.admin_webapp_api as admin_api

    db_path = tmp_path / "admin.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    run(seed_admin_api_db(db_path))
    install_auth(monkeypatch)

    async def fake_sync():
        return {"status": "queued", "message": "sync started"}

    monkeypatch.setattr(admin_api, "_run_webapp_sync", fake_sync)
    response = run(admin_api.handle_admin_sync(make_mocked_request("POST", "/api/admin/sync")))
    payload = body_json(response)

    assert response.status == 200
    assert payload == {"ok": True, "status": "queued", "message": "sync started"}

    async def read_last_action():
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT action, actor_user_id, result FROM admin_audit_log ORDER BY id DESC LIMIT 1") as cursor:
                return await cursor.fetchone()

    assert run(read_last_action()) == ("webapp_sync", "10", "queued")


def test_admin_giveaways_returns_list_without_giveaway_id(tmp_path, monkeypatch):
    from aiohttp.test_utils import make_mocked_request

    import database
    import services.admin_webapp_api as admin_api

    db_path = tmp_path / "admin.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    run(seed_admin_api_db(db_path))
    install_auth(monkeypatch)

    response = run(admin_api.handle_admin_giveaways(make_mocked_request("GET", "/api/admin/giveaways")))
    payload = body_json(response)

    assert response.status == 200
    assert payload["ok"] is True
    assert payload["active"][0]["id"] > 0
    assert payload["active"][0]["participants"] == 0
    assert payload["active"][0]["status"] == "active"
    assert payload["active"][0]["channel_url"] == "https://t.me/channel"
    assert payload["active"][0]["post_url"] == "https://t.me/channel/321"
    assert payload["active"][0]["required_channels"][0]["url"] == "https://t.me/required"
    assert payload["active"][0]["subscription"] == "1 доп. канал"
    assert payload["status_counts"]["active"] == 1
    assert payload["status_counts"]["all"] == 1
    assert payload["recent"][0]["prize"] == "VIP"


def test_admin_giveaways_filters_recent_by_status(tmp_path, monkeypatch):
    from aiohttp.test_utils import make_mocked_request

    import database
    import services.admin_webapp_api as admin_api

    db_path = tmp_path / "admin.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    run(seed_admin_api_db(db_path))
    install_auth(monkeypatch)

    async def add_finished():
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                INSERT INTO giveaways
                (status, channel_id, prize, post_text, winners_count, ends_at_utc, created_by, created_at)
                VALUES ('finished', '@done', 'Coins', 'Done', 1, '2026-01-01T00:00:00+00:00', 10, '2026-01-01T00:00:00+00:00')
                """
            )
            await db.commit()

    run(add_finished())

    response = run(admin_api.handle_admin_giveaways(make_mocked_request("GET", "/api/admin/giveaways?status=finished")))
    payload = body_json(response)

    assert response.status == 200
    assert payload["status"] == "finished"
    assert payload["total"] == 1
    assert payload["recent"][0]["status"] == "finished"
    assert payload["status_counts"]["finished"] == 1
