"""Мелкие Telegram-UI-хелперы без зависимостей от bot.py.

Чистые функции, которые собирают inline-markup / форматируют теги пользователей.
Вынесены из `bot.py` чтобы services/ могли использовать их top-level import'ом
(без триггера `from bot import ...` и связанных re-import проблем).

Bot.py re-export'ит эти функции через `from services.telegram_helpers import ...`,
поэтому все существующие usage'ы в bot.py остаются без изменений.
"""

from __future__ import annotations

import html

from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder


def escape_html_text(value) -> str:
    """Escape user/content text before embedding into HTML parse_mode messages."""
    return html.escape(str(value), quote=False)


def format_user_tag(
    username: str | None,
    first_name: str | None,
    fallback_id: int | str | None = None,
) -> str:
    """Безопасный display пользователя для HTML-сообщений.

    Приоритет: @username → экранированное first_name → fallback_id → "Пользователь".
    """
    if username:
        return f"@{escape_html_text(username)}"
    if first_name:
        return escape_html_text(first_name)
    if fallback_id is None:
        return "Пользователь"
    return escape_html_text(str(fallback_id))


def get_back_button(callback_data: str = "main_menu", text: str = "⬅️ Назад"):
    """Inline-клавиатура с одной кнопкой "Назад" (или произвольным текстом)."""
    return InlineKeyboardBuilder().row(types.InlineKeyboardButton(text=text, callback_data=callback_data)).as_markup()
