"""Валидация Telegram-пользователя для WebApp API.

Все API-хендлеры WebApp'а идентифицируют юзера через `Authorization: tma <initData>`
(предпочтительно) или `?initData=...` (legacy fallback).

`get_auth_user(request)` → распарсенный dict с полями юзера (`id`, `first_name`,
`username`, ...) или `None`, если initData пустой, невалидный подписью, или
не содержит `user`-поле.

`validate_telegram_data(init_data, bot_token)` (из `utils`) проверяет HMAC-SHA256
подпись с секретом `bot_token`, защищая от подделки.

Вынесено из `bot.py` как шаг Фазы 3 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import json

import aiohttp.web

from config import BOT_TOKEN
from utils import validate_telegram_data


def get_auth_user(request: aiohttp.web.Request) -> dict | None:
    """Извлекает и валидирует Telegram-юзера из заголовка `Authorization: tma <initData>`.

    Также поддерживается fallback `?initData=...` в query (legacy клиенты).
    Возвращает dict с полями Telegram-юзера или `None` при любой ошибке
    (нет initData, невалидная подпись, нет user-поля, битый JSON).
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("tma "):
        init_data = auth_header[4:]
    else:
        # Fallback to initData parameter for backward compatibility if we want it,
        # but header is preferred.
        init_data = request.query.get("initData", "")

    if not init_data:
        return None

    parsed = validate_telegram_data(init_data, BOT_TOKEN)
    if not parsed or "user" not in parsed:
        return None
    try:
        return json.loads(parsed["user"])
    except Exception:  # noqa: BLE001 — битый JSON → None, не роняем handler.
        return None
