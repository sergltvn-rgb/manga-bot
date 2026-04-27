from __future__ import annotations

import asyncio

import aiosqlite


def run(coro):
    return asyncio.run(coro)


def test_art_migration_preserves_legacy_rows_and_adds_metadata(tmp_path, monkeypatch):
    import database

    from services import arts

    db_path = str(tmp_path / "arts.db")
    monkeypatch.setattr(database, "DB_PATH", db_path)

    async def seed_legacy_db():
        async with aiosqlite.connect(db_path) as db:
            await db.execute("CREATE TABLE arts (id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT)")
            await db.execute("INSERT INTO arts (file_id) VALUES (?)", ("legacy-file",))
            await db.execute("CREATE TABLE suggested_arts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, file_id TEXT)")
            await db.commit()

    run(seed_legacy_db())
    run(database.init_db())

    page = run(arts.list_arts_page(limit=10, offset=0, include_hidden=True))

    assert page.total == 1
    assert page.items[0].file_id == "legacy-file"
    assert page.items[0].source == "legacy"
    assert page.items[0].is_hidden is False

    async def fetch_columns(table: str) -> set[str]:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(f"PRAGMA table_info({table})") as cursor:
                return {row[1] for row in await cursor.fetchall()}

    assert {"added_by", "source", "created_at", "accepted_at", "is_hidden", "tags", "note"} <= run(fetch_columns("arts"))
    assert {"status", "reviewed_by", "reviewed_at", "accepted_art_id", "reject_reason", "created_at"} <= run(
        fetch_columns("suggested_arts")
    )


def test_list_arts_page_filters_hidden_and_paginates(tmp_path, monkeypatch):
    import database

    from services import arts

    db_path = str(tmp_path / "arts.db")
    monkeypatch.setattr(database, "DB_PATH", db_path)
    run(database.init_db())
    run(database.add_admin(1))

    for idx in range(5):
        run(arts.add_art(f"file-{idx}", added_by=100, source="admin_upload"))
    run(arts.hide_art(2, actor_id=1))

    first = run(arts.list_arts_page(limit=2, offset=0))
    second = run(arts.list_arts_page(limit=2, offset=2))
    hidden = run(arts.list_arts_page(limit=10, offset=0, include_hidden=True, only_hidden=True))

    assert first.total == 4
    assert [item.file_id for item in first.items] == ["file-4", "file-3"]
    assert [item.file_id for item in second.items] == ["file-2", "file-0"]
    assert [item.id for item in hidden.items] == [2]


def test_suggestion_approve_and_reject_status_roundtrip(tmp_path, monkeypatch):
    import database

    from services import arts

    db_path = str(tmp_path / "arts.db")
    monkeypatch.setattr(database, "DB_PATH", db_path)
    run(database.init_db())

    accept_id = run(arts.add_suggested_art(user_id=2001, file_id="suggest-ok"))
    reject_id = run(arts.add_suggested_art(user_id=2002, file_id="suggest-no"))

    accepted = run(arts.approve_suggested_art(accept_id, reviewed_by=1))
    rejected = run(arts.reject_suggested_art(reject_id, reviewed_by=1, reason="low quality"))
    pending = run(arts.list_suggestions_page(status="pending", limit=10, offset=0))
    all_suggestions = run(arts.list_suggestions_page(status="all", limit=10, offset=0))

    assert accepted is not None
    assert accepted.source == "suggestion"
    assert rejected is True
    assert pending.total == 0
    assert {item.status for item in all_suggestions.items} == {"accepted", "rejected"}


def test_art_admin_actions_require_admin(tmp_path, monkeypatch):
    import database

    from services import arts

    db_path = str(tmp_path / "arts.db")
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(arts, "get_admins", lambda: asyncio.sleep(0, result=[10]))
    run(database.init_db())
    art_id = run(arts.add_art("file-admin", added_by=10, source="admin_upload"))

    assert run(arts.hide_art(art_id, actor_id=5)) is False
    assert run(arts.hide_art(art_id, actor_id=10)) is True


def test_public_art_payload_excludes_hidden_items(tmp_path, monkeypatch):
    import database

    from services import arts

    db_path = str(tmp_path / "arts.db")
    monkeypatch.setattr(database, "DB_PATH", db_path)
    run(database.init_db())
    run(database.add_admin(1))

    visible_id = run(arts.add_art("visible", added_by=1, source="admin_upload"))
    hidden_id = run(arts.add_art("hidden", added_by=1, source="admin_upload"))
    run(arts.hide_art(hidden_id, actor_id=1))

    payload = run(arts.get_arts_webapp_payload(user_id=100, is_admin=False, limit=20, offset=0))

    assert payload["ok"] is True
    assert payload["total"] == 1
    assert [item["id"] for item in payload["items"]] == [visible_id]


def test_art_webapp_payload_uses_gallery_numbers_not_database_ids(tmp_path, monkeypatch):
    import database

    from services import arts

    db_path = str(tmp_path / "arts.db")
    monkeypatch.setattr(database, "DB_PATH", db_path)

    async def seed_with_gaps():
        async with aiosqlite.connect(db_path) as db:
            await database.ensure_art_schema(db)
            for idx in range(6):
                await db.execute(
                    "INSERT INTO arts (file_id, source, is_hidden) VALUES (?, 'admin_upload', 0)",
                    (f"file-{idx}",),
                )
            await db.execute("DELETE FROM arts WHERE id IN (2, 4)")
            await db.commit()

    run(seed_with_gaps())

    payload = run(arts.get_arts_webapp_payload(user_id=100, is_admin=False, limit=3, offset=0))
    next_page = run(arts.get_arts_webapp_payload(user_id=100, is_admin=False, limit=3, offset=3))

    assert [item["id"] for item in payload["items"]] == [6, 5, 3]
    assert [item["display_number"] for item in payload["items"]] == [1, 2, 3]
    assert [item["display_number"] for item in next_page["items"]] == [4]


def test_arts_api_delete_removes_art_for_admin(tmp_path, monkeypatch):
    import database
    from aiohttp.test_utils import make_mocked_request

    from services import art_webapp_api, arts

    db_path = str(tmp_path / "arts.db")
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(art_webapp_api, "get_auth_user", lambda _request: {"id": 10})
    monkeypatch.setattr(art_webapp_api, "get_admins", lambda: asyncio.sleep(0, result=[10]))
    monkeypatch.setattr(arts, "get_admins", lambda: asyncio.sleep(0, result=[10]))
    run(database.init_db())
    art_id = run(arts.add_art("delete-me", added_by=10, source="admin_upload"))

    request = make_mocked_request("DELETE", f"/api/arts/{art_id}", match_info={"id": str(art_id)})
    response = run(art_webapp_api.handle_art_delete(request))
    page = run(arts.list_arts_page(limit=10, offset=0, include_hidden=True))

    assert response.status == 200
    assert page.total == 0


def test_arts_api_requires_authenticated_user(monkeypatch):
    from aiohttp.test_utils import make_mocked_request

    from services import art_webapp_api

    monkeypatch.setattr(art_webapp_api, "get_auth_user", lambda _request: None)

    response = run(art_webapp_api.handle_arts_list(make_mocked_request("GET", "/api/arts")))

    assert response.status == 401


def test_arts_api_rejects_non_admin_suggestion_queue(monkeypatch):
    from aiohttp.test_utils import make_mocked_request

    from services import art_webapp_api

    monkeypatch.setattr(art_webapp_api, "get_auth_user", lambda _request: {"id": 123})
    monkeypatch.setattr(art_webapp_api, "get_admins", lambda: asyncio.sleep(0, result=[999]))

    response = run(art_webapp_api.handle_art_suggestions_list(make_mocked_request("GET", "/api/arts/suggestions")))

    assert response.status == 403
