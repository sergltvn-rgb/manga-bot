"""WebApp API handler для клиентской телеметрии.

`handle_telemetry_post(request)` — POST `/api/telemetry` с
`{event_type, payload, page_url}` → запись в `webapp_telemetry`.

Валидация:
- `event_type` должен быть в whitelist `WEBAPP_TELEMETRY_EVENTS`.
- `client_chapter_open_ms` проходит через `_sanitize_client_chapter_open_payload`
  (проверка duration в разумных пределах; отбрасывает шумные аутлаеры).
- Все текстовые поля truncate'ятся (см. `_clip_telemetry_text` в services/telemetry_utils).

Auth необязательна (клиентские метрики пишутся даже для анонимных юзеров),
но если initData валидный — `user_id` берётся из него.

Вынесено из `bot.py` как шаг Фазы 3 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import json
import logging

import aiohttp.web

from services.auth import get_auth_user
from services.telemetry import (
    WEBAPP_TELEMETRY_EVENTS,
    _insert_webapp_telemetry_event,
)
from services.telemetry_utils import _clip_telemetry_text, _sanitize_client_chapter_open_payload
from services.webapp_cors import CORS_HEADERS


async def handle_telemetry_post(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST `/api/telemetry` — приёмник клиентских событий WebApp.

    Поддерживаемые события — `services.telemetry.WEBAPP_TELEMETRY_EVENTS`
    (runtime errors, unhandled rejections, chapter_open latency, и пр.).
    Любое другое `event_type` → 400.
    """
    try:
        user = get_auth_user(request)
        data = await request.json()
        if not isinstance(data, dict):
            return aiohttp.web.json_response({"error": "invalid payload"}, status=400, headers=CORS_HEADERS)

        event_type = _clip_telemetry_text(data.get("event_type"), 64)
        if event_type not in WEBAPP_TELEMETRY_EVENTS:
            return aiohttp.web.json_response({"error": "unsupported event_type"}, status=400, headers=CORS_HEADERS)

        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            payload = {"value": str(payload)}

        user_id = str(user.get("id", "")) if user else _clip_telemetry_text(payload.get("user_id"), 64)
        source_module = _clip_telemetry_text(payload.get("module") or payload.get("source"), 256)
        message = _clip_telemetry_text(payload.get("message"), 1200)
        stack = _clip_telemetry_text(payload.get("stack"), 4000)
        page_url = _clip_telemetry_text(data.get("page_url") or payload.get("page_url"), 2048)
        user_agent = _clip_telemetry_text(request.headers.get("User-Agent", ""), 512)

        if event_type == "client_chapter_open_ms":
            sanitized_payload = _sanitize_client_chapter_open_payload(payload)
            if sanitized_payload is None:
                return aiohttp.web.json_response({"error": "invalid duration_ms"}, status=400, headers=CORS_HEADERS)
            payload = sanitized_payload
            source_module = source_module or "reader.js"
            message = f"{payload['duration_ms']}ms"
            stack = ""

        await _insert_webapp_telemetry_event(
            event_type=event_type,
            user_id=user_id,
            source_module=source_module,
            message=message,
            stack=stack,
            page_url=page_url,
            user_agent=user_agent,
            payload=payload,
        )

        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except json.JSONDecodeError:
        return aiohttp.web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)
    except Exception as e:  # noqa: BLE001 — любая БД/IO ошибка → 500, клиент получает корректный JSON.
        logging.error(f"Telemetry API Error: {e}")
        return aiohttp.web.json_response({"error": "internal"}, status=500, headers=CORS_HEADERS)
