"""WebApp API handlers для reader-эндпоинтов.

Два публичных aiohttp-хендлера, регистрируемых в `bot.py:create_webapp_api_app()`:

- `handle_reader_data(request)` — GET `/api/reader-data` → payload со всеми
  series/volumes/chapters. Поддерживает `If-None-Match` → 304 Not Modified.
  Пишет server-side telemetry в background.

- `handle_chapter_content(request)` — GET `/api/chapter-content?series_id=...`
  → HTML-контент главы (inline / telegra.ph / teletype.in). Возвращает
  `cache_status: hit|miss`.

Lazy-импорты: `get_cached_reader_data`, `_record_server_reader_metric`,
`spawn_bg` тянут БД и bot-специфичную телеметрию, импортируются внутри
функций через `from bot import ...`.

Вынесено из `bot.py` как шаг Фазы 3 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import logging
import re
import time

import aiohttp.web

from services.cache_utils import _if_none_match_matches
from services.reader_pipeline import get_cached_chapter_content
from services.validators import _is_valid_chapter_token, _is_valid_series_id
from services.webapp_cors import CORS_HEADERS


async def handle_chapter_content(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """GET `/api/chapter-content?series_id=&volume=&chapter=`.

    Валидирует query-параметры (whitelist-серия, формат тома, чистый chapter-id),
    затем делегирует в `services.reader_pipeline.get_cached_chapter_content`.

    Ответы:
    - 200 + payload (с `cache_status: hit|miss`) — успех.
    - 400 — невалидные query-параметры.
    - 404 — серия/том/глава не найдены.
    - 500 — внутренняя ошибка (логируется).
    """
    series_id = str(request.query.get("series_id", "")).strip()
    volume = str(request.query.get("volume", "")).strip()
    chapter = str(request.query.get("chapter", "")).strip()

    if not _is_valid_series_id(series_id):
        return aiohttp.web.json_response({"error": "invalid series_id"}, status=400, headers=CORS_HEADERS)
    if not volume or len(volume) > 32 or not re.fullmatch(r"[A-Za-z0-9._-]+", volume):
        return aiohttp.web.json_response({"error": "invalid volume"}, status=400, headers=CORS_HEADERS)
    if not _is_valid_chapter_token(chapter):
        return aiohttp.web.json_response({"error": "invalid chapter"}, status=400, headers=CORS_HEADERS)

    try:
        payload, cache_hit, status_code = await get_cached_chapter_content(series_id, volume, chapter, force_refresh=False)
        if payload is None:
            return aiohttp.web.json_response({"error": "not found"}, status=status_code, headers=CORS_HEADERS)

        headers = dict(CORS_HEADERS)
        headers["Cache-Control"] = "no-cache"
        payload_with_cache = dict(payload)
        payload_with_cache["cache_status"] = "hit" if cache_hit else "miss"
        return aiohttp.web.json_response(payload_with_cache, status=status_code, headers=headers)
    except Exception as e:  # noqa: BLE001 — логируем любую ошибку и отвечаем 500, чтобы клиент не падал.
        logging.error("Chapter content API Error for %s/%s/%s: %s", series_id, volume, chapter, e)
        return aiohttp.web.json_response({"error": "internal"}, status=500, headers=CORS_HEADERS)


async def handle_reader_data(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """GET `/api/reader-data` — весь reader-snapshot (series+volumes+chapters).

    Поддерживает conditional GET через `If-None-Match` → 304 Not Modified.
    Пишет server-side telemetry (duration + status + cache_hit) в фоне,
    чтобы не блокировать ответ.

    Lazy-импорты bot-зависимостей (`get_cached_reader_data` тянет БД,
    `_record_server_reader_metric` тянет телеметрию-writer, `spawn_bg`
    регистрирует background task в глобальной очереди бота).
    """
    # Lazy-import чтобы избежать цикла bot.py ↔ services/.
    from bot import _record_server_reader_metric, get_cached_reader_data, spawn_bg

    started_at = time.perf_counter()
    status_code = 500
    cache_hit = False
    try:
        result, etag, cache_hit = await get_cached_reader_data(force_refresh=False)
        headers = dict(CORS_HEADERS)
        headers.update(
            {
                "ETag": etag,
                "Cache-Control": "no-cache",
                "Vary": "If-None-Match",
            }
        )
        if_none_match = request.headers.get("If-None-Match", "")
        if _if_none_match_matches(if_none_match, etag):
            status_code = 304
            return aiohttp.web.Response(status=304, headers=headers)
        status_code = 200
        return aiohttp.web.json_response(result, headers=headers)
    except Exception as e:  # noqa: BLE001 — любая БД/JSON/etc. ошибка → 500, клиент получает корректный JSON.
        logging.error(f"Reader API Error: {e}")
        status_code = 500
        logging.exception("API error in %s", request.path, exc_info=e)
        return aiohttp.web.json_response({"error": "Internal error", "code": 500, "series": []}, status=500, headers=CORS_HEADERS)
    finally:
        duration_ms = (time.perf_counter() - started_at) * 1000.0
        spawn_bg(
            _record_server_reader_metric(
                request,
                duration_ms=duration_ms,
                status_code=status_code,
                cache_hit=cache_hit,
            )
        )
