"""Чистые утилиты кэша: ETag-сравнение и ключи.

Используются хендлерами WebApp API (`handle_reader_data`, `handle_chapter_content`)
и подсистемами кэша в `bot.py`. Сами не хранят стейт — только функции.

Вынесено из `bot.py` как микро-шаг Фазы 3 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
Основной стейт reader-cache (`_reader_data_cache`, `_chapter_content_cache`)
пока остаётся в `bot.py` — его вынос требует отдельной сессии с канареечным
прогоном, т. к. он связан с БД и 10+ точками инвалидации.
"""

from __future__ import annotations


def _normalize_etag(tag: str) -> str:
    """Убирает `W/`-префикс weak-ETag и обрезает whitespace.
    Нужен для сравнения нашего ETag с клиентским `If-None-Match`.
    """
    value = (tag or "").strip()
    if value.startswith("W/"):
        value = value[2:]
    return value


def _if_none_match_matches(if_none_match_header: str, etag: str) -> bool:
    """True если клиентский `If-None-Match` (может содержать список через запятую
    или `*`) совпадает с нашим ETag. Учитывает weak-prefix.
    """
    if not if_none_match_header:
        return False
    etag_norm = _normalize_etag(etag)
    for raw_tag in if_none_match_header.split(","):
        tag = raw_tag.strip()
        if not tag:
            continue
        if tag == "*":
            return True
        if _normalize_etag(tag) == etag_norm:
            return True
    return False


def _build_chapter_content_cache_key(series_id: str, volume: str, chapter: str) -> str:
    """Композитный ключ для `_chapter_content_cache` в `bot.py`.
    Формат: `series_id::volume::chapter`.
    """
    return f"{str(series_id)}::{str(volume)}::{str(chapter)}"
