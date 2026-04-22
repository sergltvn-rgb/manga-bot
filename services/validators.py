"""Валидаторы и санитайзеры входных данных.

Используются:
- хендлерами WebApp API (для проверки `series_id`, `chapter` из запросов);
- парсерами HTML для Telegraph (валидация `href`/`src`);
- сборщиком данных читалки (извлечение URL из текста глав).

Вынесено из `bot.py` как шаг 3 Фазы 3 распила монолита (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit, urlunsplit

# --- Лимиты ---

MAX_SERIES_ID_LENGTH = 64
MAX_CHAPTER_ID_LENGTH = 32
MAX_AUDIT_PAYLOAD_LENGTH = 4000


# --- URL-утилиты ---


def _normalize_external_url(raw_url: str, max_len: int = 2048) -> str | None:
    """Нормализует внешний URL для использования в `<a href>`, `<img src>`, хранении.

    Возвращает канонический `scheme://host/path?query#fragment` или `None`, если:
    - строка пустая / длиннее `max_len`;
    - есть управляющие символы;
    - scheme не http/https;
    - нет хоста;
    - присутствуют credentials (`user:pass@`).
    """
    candidate = str(raw_url or "").strip()
    if not candidate or len(candidate) > max_len:
        return None
    if any(ord(ch) < 32 for ch in candidate):
        return None
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        # urlsplit кидает ValueError на некоторые битые строки (например, с NUL).
        return None
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None
    if parsed.username or parsed.password:
        return None
    normalized = urlunsplit((scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment))
    return normalized if len(normalized) <= max_len else None


def _clean_urls(url_text: str) -> list:
    """Извлекает все валидные HTTP(S)-ссылки из произвольного текста.
    Возвращает уникальный список в порядке первого вхождения.
    """
    links: list[str] = []
    for raw in re.findall(r'(https?://[^\s<"\'>]+)', str(url_text or "")):
        normalized = _normalize_external_url(raw)
        if normalized and normalized not in links:
            links.append(normalized)
    return links


# --- JSON-утилиты ---


def _safe_json_dumps(value: object, max_len: int = MAX_AUDIT_PAYLOAD_LENGTH) -> str:
    """Сериализует в компактный JSON. При ошибке — fallback на `str(value)`.
    Результат обрезается до `max_len` символов (для audit-лога).
    """
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        # TypeError — несериализуемый объект; ValueError — NaN/Inf без allow_nan.
        encoded = str(value)
    return encoded[:max_len] if len(encoded) > max_len else encoded


# --- Идентификаторы контента ---


def _is_valid_series_id(series_id: str) -> bool:
    """True если `series_id` — это одна из известных серий:
    - `akashic_records`, `british_belle` — ранобэ-спецпроекты;
    - `manga_<lang>` / `ranobe_<lang>` — где `<lang>` это [A-Za-z0-9_] ≤ 48 символов.
    """
    sid = str(series_id or "").strip()
    if not sid or len(sid) > MAX_SERIES_ID_LENGTH:
        return False
    if sid in {"akashic_records", "british_belle"}:
        return True
    if sid.startswith("manga_") or sid.startswith("ranobe_"):
        return bool(re.fullmatch(r"[A-Za-z0-9_]{1,48}", sid.split("_", 1)[1] if "_" in sid else ""))
    return False


def _is_valid_chapter_token(chapter: object) -> bool:
    """True если `chapter` — безопасный идентификатор главы.

    Разрешаем любые печатные символы (включая кириллицу и пробелы),
    кроме управляющих и DEL (0x7F), а также HTML/JS-опасных (< > & " ' ` \\).
    SQL не ломается, так как запросы параметризованы. Сам chapter используется
    как идентификатор строк в БД и в URL (client-side encoded).
    """
    token = str(chapter or "").strip()
    if not token or len(token) > MAX_CHAPTER_ID_LENGTH:
        return False
    return bool(re.fullmatch(r"[^\x00-\x1f\x7f<>&\"'`\\]+", token))
