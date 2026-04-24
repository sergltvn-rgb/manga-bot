"""Pipeline сборки контента главы для WebApp-читалки.

Бизнес-логика `/api/chapter-content`:

1. `_resolve_reader_chapter_entry(series, volume, chapter)` — находит главу
   в cached reader-payload (lookup по `series_id -> volume -> chapter`).
2. `_fetch_telegra_ph_html(url)` — получает HTML-контент с telegra.ph через
   публичное API (`/getPage/{path}?return_content=true`).
3. `_fetch_teletype_html(url)` — парсит HTML-страницу teletype.in (regex вырез
   `<article>`, нормализация noscript-img, whitelist-санитизация).
4. `_render_inline_chapter_html(text)` — plain-text глава → `<p>...</p>`-HTML.
5. `_build_chapter_content_payload(...)` — оркестратор всех источников:
   `inline-text > telegra.ph > teletype.in > fallback_url`. Возвращает лучший
   вариант по `_score_html_fragment` (баллы за картинки, текст, блоки).

Зависимости bot.py (`get_cached_reader_data`, `get_http_session`) загружаются
lazy-импортом внутри функций — так избегаем цикл.

Вынесено из `bot.py` как шаг 8 Фазы 3 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import html
import logging
import re
import time

from services.cache_utils import _build_chapter_content_cache_key
from services.html_rendering import (
    _extract_teletype_article_fragment,
    _normalize_teletype_article_fragment,
    _render_telegraph_nodes_server,
    _sanitize_html_fragment,
)
from services.html_utils import (
    _html_fragment_has_visible_content,
    _is_low_value_html_fragment,
    _score_html_fragment,
)
from services.reader_cache import (
    CHAPTER_CONTENT_CACHE_TTL_SECONDS,
    _chapter_content_cache,
    _chapter_content_cache_lock,
    _store_chapter_content_cache_entry,
)
from services.validators import _extract_chapter_urls


def _render_inline_chapter_html(text: str) -> str:
    """Превращает plain-text главы в безопасный HTML.

    Каждый параграф (отделённый пустой строкой) оборачивается в `<p>`.
    Переносы строк внутри параграфа → `<br>`. Текст HTML-escape'ится.

    Используется в `_build_chapter_content_payload`, когда у главы есть
    `text`-поле (inline-режим, без внешних ссылок).
    """
    parts = []
    for block in re.split(r"\n\s*\n", str(text or "").strip()):
        line = block.strip()
        if not line:
            continue
        escaped = html.escape(line, quote=False).replace("\n", "<br>")
        parts.append(f"<p>{escaped}</p>")
    return "".join(parts)


async def _resolve_reader_chapter_entry(series_id: str, volume: str, chapter: str) -> tuple[dict | None, dict | None, dict | None]:
    """Ищет главу в cached reader-payload по `(series_id, volume, chapter)`.

    Возвращает `(payload, series, chapter_data)`:
    - Если серия не найдена → `(payload, None, None)`.
    - Если том не найден → `(payload, series, None)`.
    - Если глава не найдена → `(payload, series, None)`.
    - Найдено всё → `(payload, series, chapter_data)`.

    Lazy-импорт `get_cached_reader_data` избегает цикла bot.py ↔ services/.
    """
    # Lazy-import, см. комментарий в модуле.
    from bot import get_cached_reader_data

    payload, _, _ = await get_cached_reader_data(force_refresh=False)
    for series in payload.get("series", []):
        if str(series.get("id")) != str(series_id):
            continue
        for vol in series.get("volumes", []):
            if str(vol.get("volume")) != str(volume):
                continue
            for chapter_data in vol.get("chapters", []):
                if str(chapter_data.get("chapter")) == str(chapter):
                    return payload, series, chapter_data
            return payload, series, None
        return payload, series, None
    return payload, None, None


async def _fetch_telegra_ph_html(source_url: str) -> str:
    """Скачивает content главы с telegra.ph через публичное API.

    Преобразует JSON-nodes → HTML через `_render_telegraph_nodes_server`.
    Возвращает пустую строку при любой ошибке (network, non-200, bad JSON).
    """
    match = re.search(r"telegra\.ph/(.+)$", str(source_url or ""), flags=re.IGNORECASE)
    if not match:
        return ""
    api_url = f"https://api.telegra.ph/getPage/{match.group(1)}?return_content=true"
    # Lazy-import (bot.py ↔ services/).
    from bot import get_http_session

    session = await get_http_session()
    async with session.get(api_url, headers={"Accept": "application/json"}) as resp:
        if resp.status != 200:
            return ""
        data = await resp.json(content_type=None)
    if not data or not data.get("ok"):
        return ""
    return _render_telegraph_nodes_server(data.get("result", {}).get("content") or [])


async def _fetch_teletype_html(source_url: str) -> str:
    """Скачивает и парсит статью с teletype.in → безопасный HTML-фрагмент.

    Шаги: GET → вырез `<article>` → разворот `<noscript><img>` → whitelist-санация →
    проверка visible-content. Возвращает пустую строку при любой ошибке или
    если content «пустой» (нет текста и картинок).
    """
    # Lazy-import (bot.py ↔ services/).
    from bot import get_http_session

    session = await get_http_session()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "ru,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml",
    }
    async with session.get(source_url, headers=headers) as resp:
        if resp.status != 200:
            return ""
        page_html = await resp.text()
    article_fragment = _extract_teletype_article_fragment(page_html)
    if not article_fragment:
        return ""
    normalized_fragment = _normalize_teletype_article_fragment(article_fragment, source_url=source_url)
    if not normalized_fragment:
        return ""
    sanitized_fragment = _sanitize_html_fragment(normalized_fragment, base_url=source_url)
    if not _html_fragment_has_visible_content(sanitized_fragment):
        return ""
    return sanitized_fragment


async def _build_chapter_content_payload(series_id: str, volume: str, chapter: str) -> tuple[dict | None, int]:
    """Главный оркестратор сборки контента главы для `/api/chapter-content`.

    Стратегия:
    - Если у главы есть inline `text` — рендерим его в HTML и возвращаем.
    - Иначе перебираем URL'ы главы в приоритете `telegra.ph > teletype.in > other`,
      скачиваем контент, выбираем лучший по `_score_html_fragment`.
    - Если ни один URL не дал visible-content — возвращаем `ok=False` fallback
      (клиент откроет `fallback_url` в iframe/новой вкладке).

    Возвращает `(payload, status_code)`. Статус 404 — если серия или глава
    не найдены в reader-cache.
    """
    _, series, chapter_data = await _resolve_reader_chapter_entry(series_id, volume, chapter)
    if not series:
        return None, 404
    if not chapter_data:
        return None, 404

    chapter_text = str(chapter_data.get("text") or "").strip()
    source_urls = _extract_chapter_urls(chapter_data)
    fallback_url = source_urls[0] if source_urls else None
    chapter_name = str(chapter_data.get("custom_name") or f"Глава {chapter}")

    if chapter_text:
        return {
            "ok": True,
            "source_type": "inline",
            "html": _render_inline_chapter_html(chapter_text),
            "fallback_url": fallback_url,
            "series_id": str(series_id),
            "volume": str(volume),
            "chapter": str(chapter),
            "chapter_name": chapter_name,
        }, 200

    preferred_urls = sorted(
        source_urls,
        key=lambda value: (0 if "telegra.ph" in value else 1 if "teletype.in" in value else 2, source_urls.index(value)),
    )

    best_payload: dict | None = None
    best_score: tuple[int, int, int, int] | None = None

    for url in preferred_urls:
        try:
            html_fragment = ""
            source_type = "fallback"
            if "telegra.ph" in url:
                html_fragment = await _fetch_telegra_ph_html(url)
                source_type = "telegraph"
            elif "teletype.in" in url:
                html_fragment = await _fetch_teletype_html(url)
                source_type = "teletype"

            if html_fragment and _html_fragment_has_visible_content(html_fragment):
                candidate_payload = {
                    "ok": True,
                    "source_type": source_type,
                    "html": html_fragment,
                    "fallback_url": url,
                    "series_id": str(series_id),
                    "volume": str(volume),
                    "chapter": str(chapter),
                    "chapter_name": chapter_name,
                }
                candidate_score = _score_html_fragment(html_fragment)
                if best_score is None or candidate_score > best_score:
                    best_payload = candidate_payload
                    best_score = candidate_score

                if not _is_low_value_html_fragment(html_fragment):
                    return candidate_payload, 200
        except Exception as fetch_error:  # noqa: BLE001 — сеть/парсинг/JSON могут бросить что угодно, логируем и пробуем следующий URL.
            logging.warning("Chapter content fetch failed for %s: %s", url, fetch_error)

    if best_payload is not None:
        return best_payload, 200

    return {
        "ok": False,
        "source_type": "fallback",
        "html": "",
        "fallback_url": fallback_url,
        "series_id": str(series_id),
        "volume": str(volume),
        "chapter": str(chapter),
        "chapter_name": chapter_name,
    }, 200


async def get_cached_chapter_content(
    series_id: str, volume: str, chapter: str, force_refresh: bool = False
) -> tuple[dict | None, bool, int]:
    """Кэш-обёртка над `_build_chapter_content_payload`.

    Возвращает `(payload, cache_hit, status_code)`. TTL —
    `CHAPTER_CONTENT_CACHE_TTL_SECONDS` (5 минут).

    Double-checked locking: проверка cache → lock → повторная проверка →
    сборка. Это защищает от thundering-herd, когда TTL истёк и несколько
    клиентов одновременно запрашивают одну и ту же главу.

    Инвалидация — через `services.reader_cache.invalidate_chapter_content_cache`
    (вызывается внутри `invalidate_reader_cache` при любой правке контента).
    """
    cache_key = _build_chapter_content_cache_key(series_id, volume, chapter)
    now = time.time()
    cached_entry = _chapter_content_cache.get(cache_key)
    if (
        not force_refresh
        and isinstance(cached_entry, dict)
        and (now - float(cached_entry.get("built_at") or 0.0)) < CHAPTER_CONTENT_CACHE_TTL_SECONDS
    ):
        if hasattr(_chapter_content_cache, "move_to_end"):
            _chapter_content_cache.move_to_end(cache_key)
        return cached_entry.get("payload"), True, int(cached_entry.get("status") or 200)

    async with _chapter_content_cache_lock:
        now = time.time()
        cached_entry = _chapter_content_cache.get(cache_key)
        if (
            not force_refresh
            and isinstance(cached_entry, dict)
            and (now - float(cached_entry.get("built_at") or 0.0)) < CHAPTER_CONTENT_CACHE_TTL_SECONDS
        ):
            if hasattr(_chapter_content_cache, "move_to_end"):
                _chapter_content_cache.move_to_end(cache_key)
            return cached_entry.get("payload"), True, int(cached_entry.get("status") or 200)

        payload, status_code = await _build_chapter_content_payload(series_id, volume, chapter)
        if payload is not None:
            _store_chapter_content_cache_entry(cache_key, payload, status=status_code, built_at=time.time())
        else:
            _chapter_content_cache.pop(cache_key, None)
        return payload, False, status_code
