"""Unit-тесты для `ask_ai` с автофоллбеком Gemma → Groq.

Покрывают ключевые сценарии:

1. `GEMMA_URL` не задан → провайдер=gemma всё равно уходит на Groq (без warning).
2. Gemma отвечает 200 → возвращается её ответ, Groq не зовётся.
3. Gemma бросает timeout → fallback на Groq.
4. Gemma отвечает 503 → fallback на Groq.
5. `provider="groq"` форсирует Groq, даже если Gemma жива.
6. `get_chat_ai_provider` default = "gemma" (без записи в БД).

Не трогаем реальный сетевой стек — патчим `bot._ask_gemma` / `bot._ask_groq`.
Под capotом — `asyncio.run()`, чтобы не тащить зависимость pytest-asyncio.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def bot_module():
    import bot

    return bot


def test_gemma_empty_url_goes_to_groq_without_warning(bot_module, caplog):
    """Если `GEMMA_URL=""` — `ask_ai` с default-провайдером уходит сразу на Groq.

    Warning НЕ должен логироваться: это штатный режим "Gemma отключена".
    """
    gemma_mock = AsyncMock(return_value="should-not-be-called")
    groq_mock = AsyncMock(return_value="groq-reply")
    with (
        patch.object(bot_module, "GEMMA_URL", ""),
        patch.object(bot_module, "_ask_groq", new=groq_mock),
        patch.object(bot_module, "_ask_gemma", new=gemma_mock),
    ):
        caplog.clear()
        reply = asyncio.run(bot_module.ask_ai("hi", "sys", history=None, provider="gemma"))
    assert reply == "groq-reply"
    gemma_mock.assert_not_called()
    groq_mock.assert_awaited_once_with("hi", "sys", None)
    assert "Gemma failed" not in caplog.text


def test_gemma_success_does_not_call_groq(bot_module):
    """Если Gemma живая и отвечает — Groq вообще не дёргается."""
    gemma_mock = AsyncMock(return_value="gemma-reply")
    groq_mock = AsyncMock(return_value="groq-fallback")
    with (
        patch.object(bot_module, "GEMMA_URL", "https://test.example.com"),
        patch.object(bot_module, "_ask_gemma", new=gemma_mock),
        patch.object(bot_module, "_ask_groq", new=groq_mock),
    ):
        reply = asyncio.run(bot_module.ask_ai("hi", "sys", history=None, provider="gemma"))
    assert reply == "gemma-reply"
    gemma_mock.assert_awaited_once_with("hi", "sys", None)
    groq_mock.assert_not_called()


def test_gemma_timeout_falls_back_to_groq(bot_module, caplog):
    """Timeout внутри `_ask_gemma` → warning в логах + вызов Groq."""
    gemma_mock = AsyncMock(side_effect=asyncio.TimeoutError())
    groq_mock = AsyncMock(return_value="groq-fallback")
    with (
        patch.object(bot_module, "GEMMA_URL", "https://test.example.com"),
        patch.object(bot_module, "_ask_gemma", new=gemma_mock),
        patch.object(bot_module, "_ask_groq", new=groq_mock),
    ):
        caplog.clear()
        with caplog.at_level("WARNING"):
            reply = asyncio.run(bot_module.ask_ai("hi", "sys", history=None, provider="gemma"))
    assert reply == "groq-fallback"
    groq_mock.assert_awaited_once_with("hi", "sys", None)
    assert "Gemma failed" in caplog.text
    assert "fallback to Groq" in caplog.text


def test_gemma_non_200_falls_back_to_groq(bot_module, caplog):
    """`_ask_gemma` сам raise'ит RuntimeError на HTTP ≠ 200 → fallback на Groq."""
    gemma_mock = AsyncMock(side_effect=RuntimeError("Gemma HTTP 503"))
    groq_mock = AsyncMock(return_value="groq-fallback")
    with (
        patch.object(bot_module, "GEMMA_URL", "https://test.example.com"),
        patch.object(bot_module, "_ask_gemma", new=gemma_mock),
        patch.object(bot_module, "_ask_groq", new=groq_mock),
    ):
        caplog.clear()
        with caplog.at_level("WARNING"):
            reply = asyncio.run(bot_module.ask_ai("hi", "sys", history=None, provider="gemma"))
    assert reply == "groq-fallback"
    groq_mock.assert_awaited_once()
    assert "Gemma HTTP 503" in caplog.text


def test_provider_groq_forces_groq_even_if_gemma_alive(bot_module):
    """`provider="groq"` должен форсировать Groq, минуя Gemma."""
    gemma_mock = AsyncMock(return_value="should-not-be-called")
    groq_mock = AsyncMock(return_value="groq-reply")
    with (
        patch.object(bot_module, "GEMMA_URL", "https://test.example.com"),
        patch.object(bot_module, "_ask_gemma", new=gemma_mock),
        patch.object(bot_module, "_ask_groq", new=groq_mock),
    ):
        reply = asyncio.run(bot_module.ask_ai("hi", "sys", history=None, provider="groq"))
    assert reply == "groq-reply"
    gemma_mock.assert_not_called()
    groq_mock.assert_awaited_once()


def test_get_chat_ai_provider_default_is_gemma(tmp_path, monkeypatch):
    """Пустая БД → `get_chat_ai_provider` возвращает "gemma" (новый default)."""
    import aiosqlite

    import database

    # Подменяем DB_PATH на временный файл, чтобы не трогать prod manga.db.
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(database, "DB_PATH", db_path)

    async def _run():
        async with aiosqlite.connect(db_path) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS chat_ai_provider ' '(chat_id INTEGER PRIMARY KEY, provider TEXT DEFAULT "gemma")')
            await db.commit()
        return await database.get_chat_ai_provider(chat_id=99999999)

    provider = asyncio.run(_run())
    assert provider == "gemma"
