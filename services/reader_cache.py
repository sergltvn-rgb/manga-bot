"""State-модуль для reader-кэшей.

Хранит ДВА in-process-кэша с их locks и функциями инвалидации:

1. **Reader-data cache** (`_reader_data_cache`) — закэшированный payload всех
   series/volumes/chapters для `/api/reader-data`. TTL = 30s. Инвалидируется
   при любой правке главы/обложки/имени (см. `invalidate_reader_cache`).

2. **Chapter-content cache** (`_chapter_content_cache`) — HTML-контент главы,
   уже скачанный с Telegraph/Teletype и нормализованный. TTL = 300s. Ключ —
   `series::volume::chapter` (см. `_build_chapter_content_cache_key` в
   `services/cache_utils.py`).

Функции `build_reader_data` / `get_cached_reader_data` / `build_chapter_content`
остаются в `bot.py` — они тянут `aiosqlite`/`DB_PATH` и много других bot-зависимостей.
Здесь — только чистое состояние + инвалидация.

Вынесено из `bot.py` как шаг Фазы 3 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import asyncio
import logging

# --- TTL-константы -----------------------------------------------------------

# Reader-payload (series+volumes+chapters) живёт 30s в кэше.
# Инвалидируется на запись (новая глава, новое имя и т. п.).
READER_CACHE_TTL_SECONDS: int = 30

# HTML-контент главы (после fetch+sanitize) живёт 5 минут.
# Инвалидация — только через `invalidate_chapter_content_cache` (не по TTL).
CHAPTER_CONTENT_CACHE_TTL_SECONDS: int = 300


# --- State (in-process, read/write из bot.py) -------------------------------

# payload → dict с series; etag → SHA256 от payload; built_at → time.time().
_reader_data_cache: dict = {
    "payload": None,
    "etag": "",
    "built_at": 0.0,
}

# Lock для защиты от thundering-herd: если TTL только что истёк, только один
# coroutine пересобирает payload, остальные ждут.
_reader_cache_lock: asyncio.Lock = asyncio.Lock()

# `<series_id>::<volume>::<chapter>` → dict(payload, status, built_at).
_chapter_content_cache: dict = {}
_chapter_content_cache_lock: asyncio.Lock = asyncio.Lock()


# --- Инвалидация -------------------------------------------------------------


def invalidate_chapter_content_cache(reason: str = "") -> None:
    """Очищает кэш HTML-контента глав полностью.

    Вызывается:
    - внутри `invalidate_reader_cache` (при правке списка глав);
    - в `scratch/test_api_embedded.py` (setup/teardown).

    `reason` — опциональная причина для логирования (видно в journalctl).
    """
    _chapter_content_cache.clear()
    if reason:
        logging.info("Chapter content cache invalidated: %s", reason)


def invalidate_reader_cache(reason: str = "") -> None:
    """Сбрасывает оба кэша: reader-payload + chapter-content.

    Вызывается при любом изменении, которое может отразиться на /api/reader-data:
    - добавление/удаление главы;
    - правка URL главы;
    - смена обложки серии;
    - изменение кастомного имени.

    `reason` — человекочитаемая причина для логов (напр. "chapter_added").
    """
    _reader_data_cache["payload"] = None
    _reader_data_cache["etag"] = ""
    _reader_data_cache["built_at"] = 0.0
    invalidate_chapter_content_cache(reason)
    if reason:
        logging.info("Reader cache invalidated: %s", reason)
