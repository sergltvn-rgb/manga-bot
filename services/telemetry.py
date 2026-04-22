"""Серверная телеметрия WebApp: БД-запись + sampling + оркестрация метрик.

Дополняет `services/telemetry_utils.py` (чистые функции clip/sanitize/to_float)
функциями с I/O:

- `_serialize_telemetry_payload(payload)` — JSON + truncation до 16KB.
- `_insert_webapp_telemetry_event(...)` — INSERT в `webapp_telemetry` (SQLite).
- `_record_server_reader_metric(...)` — helper для `handle_reader_data`:
  sample-rate гейт + извлечение юзера + запись события.

Константы (env-configurable):
- `SERVER_READER_TELEMETRY_SAMPLE_RATE` — доля запросов к `/api/reader-data`,
  для которых пишется метрика (по умолчанию 0.2 = 20%).
- `MAX_TELEMETRY_PAYLOAD_JSON_LENGTH` — 16KB, жёсткий лимит.
- `WEBAPP_TELEMETRY_EVENTS` — whitelist-типов событий от клиента (не для
  записи — для валидации в `handle_webapp_telemetry`).

Вынесено из `bot.py` как шаг Фазы 3 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import json
import logging
import os
import random

import aiohttp.web
import aiosqlite

from services.auth import get_auth_user
from services.telemetry_utils import _clip_telemetry_text


# --- Константы -----------------------------------------------------------------

WEBAPP_TELEMETRY_EVENTS = {
    "client_runtime_error",
    "client_unhandled_rejection",
    "client_state_contract_violation",
    "client_chapter_open_ms",
    "series_selected",
    "chapters_screen_opened",
    "chapter_click",
    "chapter_content_load_failed",
    "cache_version_mismatch",
}

MAX_TELEMETRY_PAYLOAD_JSON_LENGTH = 16000

try:
    SERVER_READER_TELEMETRY_SAMPLE_RATE = float(os.getenv("SERVER_READER_TELEMETRY_SAMPLE_RATE", "0.2"))
except Exception:  # noqa: BLE001 — env может быть битым; берём default.
    SERVER_READER_TELEMETRY_SAMPLE_RATE = 0.2
SERVER_READER_TELEMETRY_SAMPLE_RATE = max(0.0, min(1.0, SERVER_READER_TELEMETRY_SAMPLE_RATE))

SERVER_READER_TELEMETRY_EVENT = "server_api_reader_ms"


# --- Функции -------------------------------------------------------------------


def _serialize_telemetry_payload(payload: dict) -> str:
    """Сериализует payload в JSON с жёсткой truncation'ой на 16KB.

    Дальше этот JSON кладётся в BLOB-поле `webapp_telemetry.payload_json`.
    Truncation (плохой JSON на выходе!) намеренно — защищает от OOM при
    случайно огромных payload'ах; потери не критичны, телеметрия best-effort.
    """
    payload_json = json.dumps(payload, ensure_ascii=False)
    if len(payload_json) > MAX_TELEMETRY_PAYLOAD_JSON_LENGTH:
        payload_json = payload_json[:MAX_TELEMETRY_PAYLOAD_JSON_LENGTH]
    return payload_json


async def _insert_webapp_telemetry_event(
    *,
    event_type: str,
    user_id: str = "",
    source_module: str = "",
    message: str = "",
    stack: str = "",
    page_url: str = "",
    user_agent: str = "",
    payload: dict | None = None,
) -> None:
    """INSERT одной строки в `webapp_telemetry`.

    Все текстовые поля проходят через `_clip_telemetry_text` с разными
    лимитами (event_type=64, user_id=64, source_module=256, message=1200,
    stack=4000, page_url=2048, user_agent=512). Защита от раздувания БД.

    DB path — lazy через `bot.DB_PATH` чтобы не хардкодить `"manga.db"`.
    """
    # Lazy-import (bot.py ↔ services/).
    from bot import DB_PATH

    payload_json = _serialize_telemetry_payload(payload if payload is not None else {})
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO webapp_telemetry
            (event_type, user_id, source_module, message, stack, page_url, user_agent, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _clip_telemetry_text(event_type, 64),
                _clip_telemetry_text(user_id, 64),
                _clip_telemetry_text(source_module, 256),
                _clip_telemetry_text(message, 1200),
                _clip_telemetry_text(stack, 4000),
                _clip_telemetry_text(page_url, 2048),
                _clip_telemetry_text(user_agent, 512),
                payload_json,
            ),
        )
        await db.commit()


async def _record_server_reader_metric(
    request: aiohttp.web.Request,
    *,
    duration_ms: float,
    status_code: int,
    cache_hit: bool,
) -> None:
    """Пишет одно событие `server_api_reader_ms` в телеметрию (с sampling).

    Используется в `services.reader_api.handle_reader_data`:finally, чтобы
    отслеживать latency reader-API без overhead на каждый запрос (sample rate
    по умолчанию 20%).

    Любая ошибка подавляется (warning-лог) — телеметрия не должна ронять
    основной запрос.
    """
    if SERVER_READER_TELEMETRY_SAMPLE_RATE <= 0:
        return
    if random.random() > SERVER_READER_TELEMETRY_SAMPLE_RATE:
        return

    try:
        user = get_auth_user(request)
        user_id = str(user.get("id", "")) if user else ""
        payload = {
            "duration_ms": round(max(0.0, duration_ms), 2),
            "status": int(status_code),
            "cache_hit": bool(cache_hit),
            "path": _clip_telemetry_text(request.path, 128),
            "method": _clip_telemetry_text(request.method, 16),
        }
        await _insert_webapp_telemetry_event(
            event_type=SERVER_READER_TELEMETRY_EVENT,
            user_id=user_id,
            source_module="bot.py:handle_reader_data",
            message=f"{payload['duration_ms']}ms status={payload['status']}",
            page_url=_clip_telemetry_text(request.path_qs, 2048),
            user_agent=request.headers.get("User-Agent", ""),
            payload=payload,
        )
    except Exception as telemetry_error:  # noqa: BLE001 — телеметрия best-effort.
        logging.warning(f"Server reader telemetry write failed: {telemetry_error}")
