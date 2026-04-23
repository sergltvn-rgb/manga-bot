"""Unit-тесты для персистентной AI-памяти (database.py: ai_memory).

Покрывают:
1. append + get — записанные сообщения читаются обратно в хронологическом порядке.
2. limit — get_ai_memory возвращает только последние N сообщений.
3. content truncation — длинные строки обрезаются до _AI_MEMORY_MAX_CONTENT_LEN.
4. invalid role — append_ai_memory молча пропускает.
5. empty content — append_ai_memory молча пропускает.
6. clear_ai_memory(char_id=None) — удаляет всё для (chat_id, user_id).
7. clear_ai_memory(char_id=...) — удаляет только конкретного персонажа.
8. Изолированность ключей — разные (chat_id, user_id, char_id) не пересекаются.

Используют tmp_path для временной SQLite БД, без pytest-asyncio.
"""

from __future__ import annotations

import asyncio

import aiosqlite
import pytest

import database


@pytest.fixture
def mem_db(tmp_path, monkeypatch):
    """Создаёт временную SQLite-БД с таблицей ai_memory и подменяет DB_PATH."""
    db_path = str(tmp_path / "test_mem.db")
    monkeypatch.setattr(database, "DB_PATH", db_path)

    async def _init():
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                '''CREATE TABLE IF NOT EXISTS ai_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    char_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    ts INTEGER NOT NULL)'''
            )
            await db.execute('CREATE INDEX IF NOT EXISTS idx_ai_memory_lookup ' 'ON ai_memory(chat_id, user_id, char_id, ts)')
            await db.commit()

    asyncio.run(_init())
    return db_path


# ── append + get ───────────────────────────────────────────────────


def test_append_and_get_chronological(mem_db):
    """Записанные user+assistant сообщения читаются в хронологическом порядке."""

    async def _run():
        await database.append_ai_memory(1, 10, "alya", "user", "привет")
        await database.append_ai_memory(1, 10, "alya", "assistant", "здравствуй")
        await database.append_ai_memory(1, 10, "alya", "user", "как дела?")
        await database.append_ai_memory(1, 10, "alya", "assistant", "нормально")
        return await database.get_ai_memory(1, 10, "alya", limit=20)

    history = asyncio.run(_run())
    assert len(history) == 4
    assert history[0] == {"role": "user", "content": "привет"}
    assert history[1] == {"role": "assistant", "content": "здравствуй"}
    assert history[2] == {"role": "user", "content": "как дела?"}
    assert history[3] == {"role": "assistant", "content": "нормально"}


def test_get_limit(mem_db):
    """get_ai_memory с limit=2 возвращает только 2 последних сообщения."""

    async def _run():
        for i in range(6):
            role = "user" if i % 2 == 0 else "assistant"
            await database.append_ai_memory(1, 10, "alya", role, f"msg-{i}")
        return await database.get_ai_memory(1, 10, "alya", limit=2)

    history = asyncio.run(_run())
    assert len(history) == 2
    # Должны быть 2 последних сообщения в хронологическом порядке
    assert history[0]["content"] == "msg-4"
    assert history[1]["content"] == "msg-5"


# ── truncation / validation ───────────────────────────────────────


def test_content_truncation(mem_db):
    """Длинный content обрезается до _AI_MEMORY_MAX_CONTENT_LEN."""
    long_text = "x" * 5000

    async def _run():
        await database.append_ai_memory(1, 10, "alya", "user", long_text)
        return await database.get_ai_memory(1, 10, "alya", limit=1)

    history = asyncio.run(_run())
    assert len(history) == 1
    assert len(history[0]["content"]) == database._AI_MEMORY_MAX_CONTENT_LEN


def test_invalid_role_ignored(mem_db):
    """Некорректная роль (не user/assistant) — запись пропускается."""

    async def _run():
        await database.append_ai_memory(1, 10, "alya", "system", "hack")
        return await database.get_ai_memory(1, 10, "alya", limit=10)

    history = asyncio.run(_run())
    assert history == []


def test_empty_content_ignored(mem_db):
    """Пустой content — запись пропускается."""

    async def _run():
        await database.append_ai_memory(1, 10, "alya", "user", "")
        return await database.get_ai_memory(1, 10, "alya", limit=10)

    history = asyncio.run(_run())
    assert history == []


# ── clear ──────────────────────────────────────────────────────────


def test_clear_all_characters(mem_db):
    """clear_ai_memory(char_id=None) удаляет память по всем персонажам."""

    async def _run():
        await database.append_ai_memory(1, 10, "alya", "user", "a")
        await database.append_ai_memory(1, 10, "masachika", "user", "b")
        deleted = await database.clear_ai_memory(1, 10, char_id=None)
        alya = await database.get_ai_memory(1, 10, "alya", limit=10)
        masa = await database.get_ai_memory(1, 10, "masachika", limit=10)
        return deleted, alya, masa

    deleted, alya, masa = asyncio.run(_run())
    assert deleted == 2
    assert alya == []
    assert masa == []


def test_clear_single_character(mem_db):
    """clear_ai_memory(char_id='alya') удаляет только Алю, масачику не трогает."""

    async def _run():
        await database.append_ai_memory(1, 10, "alya", "user", "a")
        await database.append_ai_memory(1, 10, "masachika", "user", "b")
        deleted = await database.clear_ai_memory(1, 10, char_id="alya")
        alya = await database.get_ai_memory(1, 10, "alya", limit=10)
        masa = await database.get_ai_memory(1, 10, "masachika", limit=10)
        return deleted, alya, masa

    deleted, alya, masa = asyncio.run(_run())
    assert deleted == 1
    assert alya == []
    assert len(masa) == 1


def test_clear_empty_returns_zero(mem_db):
    """clear на пустой памяти возвращает 0."""
    deleted = asyncio.run(database.clear_ai_memory(1, 10, char_id=None))
    assert deleted == 0


# ── key isolation ──────────────────────────────────────────────────


def test_different_keys_isolated(mem_db):
    """Разные (chat_id, user_id, char_id) не видят чужих сообщений."""

    async def _run():
        await database.append_ai_memory(1, 10, "alya", "user", "user1-chat1")
        await database.append_ai_memory(2, 10, "alya", "user", "user1-chat2")
        await database.append_ai_memory(1, 20, "alya", "user", "user2-chat1")
        h1 = await database.get_ai_memory(1, 10, "alya", limit=10)
        h2 = await database.get_ai_memory(2, 10, "alya", limit=10)
        h3 = await database.get_ai_memory(1, 20, "alya", limit=10)
        return h1, h2, h3

    h1, h2, h3 = asyncio.run(_run())
    assert len(h1) == 1 and h1[0]["content"] == "user1-chat1"
    assert len(h2) == 1 and h2[0]["content"] == "user1-chat2"
    assert len(h3) == 1 and h3[0]["content"] == "user2-chat1"
