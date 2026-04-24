from __future__ import annotations

import asyncio
import builtins
import json
from unittest.mock import AsyncMock

import aiosqlite

ADMIN_USER_ID = 6210312655


class SortRequest:
    path = "/api/sort"

    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self) -> dict:
        return self._payload


def run(coro):
    return asyncio.run(coro)


async def create_sort_db(db_path, chapters):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE akashic_ranobe (
                volume INTEGER,
                chapter TEXT,
                url TEXT,
                sort_order INTEGER DEFAULT 0,
                PRIMARY KEY (volume, chapter)
            )
            """
        )
        for sort_order, chapter in enumerate(chapters):
            await db.execute(
                "INSERT INTO akashic_ranobe (volume, chapter, url, sort_order) VALUES (11, ?, '', ?)",
                (chapter, sort_order),
            )
        await db.commit()


async def fetch_order(db_path):
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT chapter, sort_order FROM akashic_ranobe WHERE volume = 11 ORDER BY sort_order, chapter") as cursor:
            return await cursor.fetchall()


def patch_sort_dependencies(monkeypatch, bot_module, db_path):
    monkeypatch.setattr(bot_module, "DB_PATH", str(db_path))
    monkeypatch.setattr(bot_module, "get_auth_user", lambda _request: {"id": ADMIN_USER_ID})
    monkeypatch.setattr(bot_module, "get_admins", AsyncMock(return_value=[ADMIN_USER_ID]))
    monkeypatch.setattr(bot_module, "_enforce_rate_limit", AsyncMock(return_value=None))
    monkeypatch.setattr(bot_module, "_audit_admin_action", AsyncMock(return_value=None))
    monkeypatch.setattr(bot_module, "invalidate_reader_cache", lambda _reason: None)
    monkeypatch.setattr(bot_module, "get_cached_reader_data", AsyncMock(return_value=({"series": []}, '"etag"', False)))
    real_open = builtins.open
    reader_snapshot = db_path.parent / "chapters_data.json"

    def fake_open(path, *args, **kwargs):
        if str(path).replace("\\", "/") == "webapp/chapters_data.json":
            return real_open(reader_snapshot, *args, **kwargs)
        return real_open(path, *args, **kwargs)

    async def fake_git_sync(_message):
        return True, "ok"

    def close_background_coro(coro, name=None):
        del name
        coro.close()

    monkeypatch.setattr(bot_module, "run_git_sync", fake_git_sync)
    monkeypatch.setattr(bot_module, "spawn_bg", close_background_coro)
    monkeypatch.setattr(builtins, "open", fake_open)


def test_sort_rejects_missing_chapter_without_partial_update(tmp_path, monkeypatch):
    import bot

    db_path = tmp_path / "sort.db"
    run(create_sort_db(db_path, ["0", "1", "2"]))
    patch_sort_dependencies(monkeypatch, bot, db_path)

    request = SortRequest(
        {
            "series_id": "akashic_records",
            "volume": 11,
            "order": ["2", "Иллюстрации", "1", "0"],
        }
    )

    response = run(bot.handle_sort_chapters(request))

    assert response.status == 409
    body = json.loads(response.body.decode("utf-8"))
    assert body["unmatched"] == ["Иллюстрации"]
    assert run(fetch_order(db_path)) == [("0", 0), ("1", 1), ("2", 2)]


def test_sort_valid_full_akashic_volume_order_persists_all_positions(tmp_path, monkeypatch):
    import bot

    order = ["0", "Эпилог", "Послесловие", "Иллюстрации", "1", "2", "3", "4", "5", "6"]
    db_path = tmp_path / "sort.db"
    run(create_sort_db(db_path, list(reversed(order))))
    patch_sort_dependencies(monkeypatch, bot, db_path)

    request = SortRequest(
        {
            "series_id": "akashic_records",
            "volume": 11,
            "order": order,
        }
    )

    response = run(bot.handle_sort_chapters(request))

    assert response.status == 200
    assert run(fetch_order(db_path)) == [(chapter, idx) for idx, chapter in enumerate(order)]


def test_akashic_volume_11_repair_inserts_illustrations_once(tmp_path, monkeypatch):
    import database

    db_path = tmp_path / "repair.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))

    async def seed():
        async with aiosqlite.connect(db_path) as db:
            await db.execute("CREATE TABLE bot_settings (key TEXT PRIMARY KEY, value TEXT)")
            await db.execute(
                """
                CREATE TABLE akashic_ranobe (
                    volume INTEGER,
                    chapter TEXT,
                    url TEXT,
                    sort_order INTEGER DEFAULT 0,
                    PRIMARY KEY (volume, chapter)
                )
                """
            )
            for chapter in ["0", "Эпилог", "Послесловие", "1", "2", "3", "4", "5", "6"]:
                await db.execute(
                    "INSERT INTO akashic_ranobe (volume, chapter, url, sort_order) VALUES (11, ?, 'u', 0)",
                    (chapter,),
                )
            await db.commit()

    run(seed())

    async def repair_and_read():
        async with aiosqlite.connect(db_path) as db:
            await database.repair_akashic_volume_11_illustrations(db)
            await db.commit()
            async with db.execute("SELECT chapter, url, sort_order FROM akashic_ranobe WHERE volume = 11 ORDER BY sort_order") as cursor:
                first = await cursor.fetchall()
            await database.repair_akashic_volume_11_illustrations(db)
            await db.commit()
            async with db.execute("SELECT COUNT(*) FROM akashic_ranobe WHERE volume = 11 AND chapter = 'Иллюстрации'") as cursor:
                count = (await cursor.fetchone())[0]
            return first, count

    rows, illustration_count = run(repair_and_read())

    assert illustration_count == 1
    assert rows == [
        ("0", "u", 0),
        ("Эпилог", "u", 1),
        ("Послесловие", "u", 2),
        ("Иллюстрации", "", 3),
        ("1", "u", 4),
        ("2", "u", 5),
        ("3", "u", 6),
        ("4", "u", 7),
        ("5", "u", 8),
        ("6", "u", 9),
    ]
