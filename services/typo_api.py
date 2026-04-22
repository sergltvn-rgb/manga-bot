"""WebApp API handler для репортов об опечатках.

`handle_typo_post(request)` — POST `/api/typos` с `{chapter_key, selected_text,
context_text, comment}` → запись в `chapter_typos` + Telegram-уведомление всем
админам с форматированным HTML-сообщением.

Валидация:
- Все три поля обязательны, длина ограничена (см. `services/validators`).
- Auth-required: без initData → 401.
- Rate-limit: `typo_report` (см. `services/rate_limit`).

Уведомления админам отправляются в цикле через `bot.send_message` с
`parse_mode="HTML"`. Ошибки отправки логируются, но не влияют на ответ клиенту.

Вынесено из `bot.py` как шаг Фазы 3 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import html
import logging

import aiohttp.web
import aiosqlite

from services.admin_audit import _api_error_response
from services.auth import get_auth_user
from services.rate_limit import _enforce_rate_limit
from services.validators import (
    MAX_CHAPTER_KEY_LENGTH,
    MAX_TYPO_COMMENT_LENGTH,
    MAX_TYPO_CONTEXT_TEXT_LENGTH,
    MAX_TYPO_SELECTED_TEXT_LENGTH,
)
from services.webapp_cors import CORS_HEADERS


async def handle_typo_post(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST `/api/typos` — отправить репорт об опечатке + уведомить админов."""
    from bot import DB_PATH, bot, get_admins

    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        limited = await _enforce_rate_limit(request, "typo_report", user_id=user_id)
        if limited:
            return limited
        user_name = user.get("first_name", "Аноним")

        data = await request.json()
        chapter_key = str(data.get("chapter_key", "")).strip()
        selected_text = str(data.get("selected_text", "")).strip()
        context_text = str(data.get("context_text", "")).strip()
        comment = str(data.get("comment", "")).strip()

        if not chapter_key or not selected_text or not context_text:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)
        if len(chapter_key) > MAX_CHAPTER_KEY_LENGTH:
            return aiohttp.web.json_response({"error": "invalid chapter_key"}, status=400, headers=CORS_HEADERS)
        if len(selected_text) > MAX_TYPO_SELECTED_TEXT_LENGTH:
            return aiohttp.web.json_response({"error": "selected_text too long"}, status=400, headers=CORS_HEADERS)
        if len(context_text) > MAX_TYPO_CONTEXT_TEXT_LENGTH:
            return aiohttp.web.json_response({"error": "context_text too long"}, status=400, headers=CORS_HEADERS)
        if len(comment) > MAX_TYPO_COMMENT_LENGTH:
            return aiohttp.web.json_response({"error": "comment too long"}, status=400, headers=CORS_HEADERS)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO chapter_typos (chapter_key, user_id, user_name, selected_text, context_text, comment) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (chapter_key, user_id, user_name, selected_text, context_text, comment),
            )
            await db.commit()

        def safe_html(t):
            return html.escape(str(t), quote=False)

        admins = await get_admins()
        logging.info(f"Typo report received from {user_name} ({user_id}).")
        report_text = (
            f"🚨 <b>Новая опечатка!</b>\n"
            f"От: {safe_html(user_name)} (ID: <code>{user_id}</code>)\n"
            f"Глава: <code>{safe_html(chapter_key)}</code>\n\n"
            f"<b>Текст:</b> <code>{safe_html(selected_text)}</code>\n"
            f"<b>Контекст:</b> <i>...{safe_html(context_text)}...</i>\n"
            f"<b>Комментарий:</b> {safe_html(comment)}"
        )
        for admin_id in admins:
            try:
                logging.info(f"Sending typo report to admin {admin_id}")
                await bot.send_message(admin_id, report_text, parse_mode="HTML")
            except Exception as e:  # noqa: BLE001 — aiogram-ошибка не должна фейлить HTTP-ответ.
                logging.error(f"Failed to notify admin {admin_id}: {e}")

        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:  # noqa: BLE001
        return _api_error_response(e, context=request.path)
