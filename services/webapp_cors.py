"""CORS-утилиты для WebApp API.

Чистые функции без зависимостей от `bot` instance, `Dispatcher` или БД.
Раньше жили в `bot.py` среди БЛОКа 11. Вынос сюда — первый шаг Фазы 3
распила монолита (см. `C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).

Тесты: `pytest tests/ -q` прогоняет smoke `import bot` — он импортирует
этот модуль транзитивно, и если тут что-то сломается — smoke упадёт.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import aiohttp.web

from config import API_HOST, WEBAPP_URL

# --- Константы ---

CORS_BASE_HEADERS: dict[str, str] = {
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Expose-Headers": "ETag",
}

# Копия, используемая хендлерами, которые добавляют Access-Control-Allow-Origin
# динамически. Именно ссылка на dict попадает в ответы, так что не заменяй
# `dict(...)` на прямое присваивание — иначе мутация будет видна всем.
CORS_HEADERS: dict[str, str] = dict(CORS_BASE_HEADERS)

# Суффиксы доменов, для которых Origin разрешён автоматически (subdomain match).
# `web.telegram.org`, `t.me`, любые `*.telegram.org` — для Telegram WebApp.
_CORS_ALLOWED_ORIGIN_SUFFIXES: tuple[str, ...] = ("telegram.org",)


def _extract_origin(url_value: str) -> str:
    """Приводит произвольную URL-строку к каноническому `scheme://host` в нижнем регистре.
    Возвращает пустую строку, если URL невалиден или не http(s).
    """
    try:
        parsed = urlsplit(str(url_value or "").strip())
    except ValueError:
        # urlsplit может кинуть ValueError на NUL-символы и другие крайние случаи.
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _load_cors_allowed_origins() -> set[str]:
    """Собирает whitelist CORS-origin'ов из:
    - `WEBAPP_URL` и `API_HOST` (config.py)
    - Переменной окружения `WEBAPP_CORS_ALLOWLIST` (CSV)
    - Локалхоста для dev.
    """
    origins: set[str] = set()
    for raw in (WEBAPP_URL, API_HOST):
        origin = _extract_origin(raw)
        if origin:
            origins.add(origin)
    extra = os.getenv("WEBAPP_CORS_ALLOWLIST", "")
    for item in extra.split(","):
        origin = _extract_origin(item)
        if origin:
            origins.add(origin)
    origins.update(
        {
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        }
    )
    return origins


# Singleton. Вычисляется один раз при импорте модуля — так же было в `bot.py`.
CORS_ALLOWED_ORIGINS: set[str] = _load_cors_allowed_origins()


def _origin_allowed(origin: str) -> bool:
    """True если Origin явно в whitelist'е или матчит разрешённый домен-суффикс."""
    normalized = _extract_origin(origin)
    if not normalized:
        return False
    if normalized in CORS_ALLOWED_ORIGINS:
        return True
    host = (urlsplit(normalized).hostname or "").lower()
    for suffix in _CORS_ALLOWED_ORIGIN_SUFFIXES:
        sfx = suffix.lower()
        if host == sfx or host.endswith(f".{sfx}"):
            return True
    return False


def _resolve_allowed_origin(request: aiohttp.web.Request) -> str:
    """Возвращает нормализованный Origin заголовка запроса если он разрешён, иначе ''."""
    origin = request.headers.get("Origin", "").strip()
    if not origin:
        return ""
    return _extract_origin(origin) if _origin_allowed(origin) else ""


def _build_cors_headers(request: aiohttp.web.Request) -> dict:
    """Строит словарь CORS-заголовков под конкретный request.
    Добавляет `Access-Control-Allow-Origin` только если Origin из whitelist'а.
    """
    headers = dict(CORS_BASE_HEADERS)
    headers["Vary"] = "Origin"
    allowed_origin = _resolve_allowed_origin(request)
    if allowed_origin:
        headers["Access-Control-Allow-Origin"] = allowed_origin
        headers["Access-Control-Allow-Credentials"] = "true"
    return headers


def _merge_vary_header(existing_value: str, token: str) -> str:
    """Аккуратно добавляет токен в `Vary`-заголовок, не дублируя существующие."""
    values = [v.strip() for v in str(existing_value or "").split(",") if v.strip()]
    token_norm = token.strip()
    if token_norm and token_norm not in values:
        values.append(token_norm)
    return ", ".join(values) if values else token_norm
