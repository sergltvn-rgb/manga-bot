from __future__ import annotations

import asyncio
import json

import aiosqlite


def run(coro):
    return asyncio.run(coro)


def test_init_db_migrates_ranobe_urls_to_volume_primary_key(tmp_path, monkeypatch):
    import database

    db_path = tmp_path / "ranobe-volume-migration.db"

    async def setup_legacy_db():
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "CREATE TABLE ranobe_urls (chapter_number TEXT, lang TEXT, url TEXT, sort_order INTEGER DEFAULT 0, PRIMARY KEY (chapter_number, lang))"
            )
            await db.execute(
                "INSERT INTO ranobe_urls (chapter_number, lang, url, sort_order) VALUES (?, ?, ?, ?)",
                ("1", "alya", "https://example.org/old-v1", 7),
            )
            await db.commit()

    run(setup_legacy_db())
    monkeypatch.setattr(database, "DB_PATH", str(db_path))

    run(database.init_db())

    async def read_state():
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("PRAGMA table_info(ranobe_urls)") as cursor:
                columns = await cursor.fetchall()
            await db.execute(
                "INSERT INTO ranobe_urls (chapter_number, lang, volume, url, sort_order) VALUES (?, ?, ?, ?, ?)",
                ("1", "alya", 2, "https://example.org/new-v2", 1),
            )
            await db.commit()
            async with db.execute("SELECT chapter_number, lang, volume, url, sort_order FROM ranobe_urls ORDER BY volume") as cursor:
                rows = await cursor.fetchall()
            return columns, rows

    columns, rows = run(read_state())
    assert "volume" in [row[1] for row in columns]
    assert rows == [
        ("1", "alya", 1, "https://example.org/old-v1", 7),
        ("1", "alya", 2, "https://example.org/new-v2", 1),
    ]


def test_ranobe_upload_link_stores_selected_volume(tmp_path, monkeypatch):
    import bot
    import services.admin_content as admin_content
    from services.admin_content import uc_upload_link

    db_path = tmp_path / "ranobe-upload-volume.db"
    workdir = tmp_path / "work"
    (workdir / "webapp").mkdir(parents=True)

    async def setup_db():
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                CREATE TABLE ranobe_urls (
                    chapter_number TEXT,
                    lang TEXT,
                    volume INTEGER DEFAULT 1,
                    url TEXT,
                    sort_order INTEGER DEFAULT 0,
                    PRIMARY KEY (chapter_number, lang, volume)
                )
                """
            )
            await db.commit()

    run(setup_db())
    monkeypatch.chdir(workdir)
    monkeypatch.setattr(bot, "DB_PATH", str(db_path))
    monkeypatch.setattr(admin_content, "invalidate_reader_cache", lambda *_args, **_kwargs: None)

    async def fake_reader_data(force_refresh=False):
        return {"series": []}, "etag", False

    async def fake_git_sync(_message):
        return True, "ok"

    def fake_spawn_bg(coro, *_args, **_kwargs):
        if hasattr(coro, "close"):
            coro.close()

    monkeypatch.setattr(bot, "get_cached_reader_data", fake_reader_data)
    monkeypatch.setattr(admin_content, "run_git_sync", fake_git_sync)
    monkeypatch.setattr(admin_content, "spawn_bg", fake_spawn_bg)

    class FakeState:
        async def get_data(self):
            return {"content_type": "ranobe", "content_id": "alya", "volume": 2, "chapter": "1"}

        async def set_state(self, _state):
            return None

        async def update_data(self, **_kwargs):
            return None

    class FakeMessage:
        html_text = "https://example.org/alya-v2-c1"

        async def answer(self, *_args, **_kwargs):
            return None

    run(uc_upload_link(FakeMessage(), FakeState()))

    async def fetch_rows():
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT chapter_number, lang, volume, url FROM ranobe_urls") as cursor:
                return await cursor.fetchall()

    assert run(fetch_rows()) == [("1", "alya", 2, "https://example.org/alya-v2-c1")]
    assert json.loads((workdir / "webapp" / "chapters_data.json").read_text(encoding="utf-8")) == {"series": []}


def test_reader_data_groups_ranobe_chapters_by_volume(tmp_path, monkeypatch):
    import bot
    import database

    db_path = tmp_path / "reader-ranobe-volumes.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    monkeypatch.setattr(bot, "DB_PATH", str(db_path))
    run(database.init_db())

    async def seed():
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "INSERT INTO ranobe_urls (chapter_number, lang, volume, url, sort_order) VALUES (?, ?, ?, ?, ?)",
                ("1", "alya", 1, "https://example.org/v1-c1", 1),
            )
            await db.execute(
                "INSERT INTO ranobe_urls (chapter_number, lang, volume, url, sort_order) VALUES (?, ?, ?, ?, ?)",
                ("1", "alya", 2, "https://example.org/v2-c1", 1),
            )
            await db.execute("INSERT INTO custom_names (id, name) VALUES (?, ?)", ("vol_ranobe_alya_2", "Том 2"))
            await db.commit()

    run(seed())

    payload = run(bot.build_reader_data())
    alya = next(series for series in payload["series"] if series["id"] == "ranobe_alya")

    assert [(volume["volume"], volume["custom_name"]) for volume in alya["volumes"]] == [(1, "Том 1"), (2, "Том 2")]
    assert alya["volumes"][0]["chapters"][0]["url"] == "https://example.org/v1-c1"
    assert alya["volumes"][1]["chapters"][0]["url"] == "https://example.org/v2-c1"
