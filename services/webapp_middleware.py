"""Middleware и response-хуки WebApp API.

Содержит:
- `API_MAX_BODY_BYTES` — лимит размера body, задаётся через env `API_MAX_BODY_BYTES`;
- `api_security_middleware` — проверяет Origin и Content-Length до хендлера;
- `apply_webapp_response_headers` — on_response_prepare hook: Cache-Control,
  gzip compression, финальные CORS-заголовки;
- вспомогательные утилиты cache-control и определение compressible-ответов.

Вынесено из `bot.py` как шаг 4 Фазы 3 распила монолита (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import logging
import os

import aiohttp.web

from services.webapp_cors import (
    CORS_BASE_HEADERS,
    _build_cors_headers,
    _merge_vary_header,
    _resolve_allowed_origin,
)

# --- Константы ---

# Максимальный размер body API-запроса. По умолчанию 256 KiB.
# Настраивается переменной окружения API_MAX_BODY_BYTES в `codes.env`.
API_MAX_BODY_BYTES: int = int(os.getenv("API_MAX_BODY_BYTES", "262144"))

# Расширения, которые можно кэшировать на 24 часа в браузере (immutable-like).
# HTML/JSON сюда не входят — они всегда revalidate.
_STATIC_LONG_CACHE_EXTENSIONS: tuple[str, ...] = (
    ".css",
    ".js",
    ".mjs",
    ".map",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
)


# --- Cache-Control ---


def _webapp_cache_control_for_request(request: aiohttp.web.Request) -> str:
    """Подбирает строку `Cache-Control` для статики WebApp.
    HTML/app shell — no-cache. Версионированные ассеты (`?v=...`) — immutable.
    Остальное — 24 часа для известных статических расширений, 1 час по дефолту.
    """
    path = request.path.lower()
    # HTML/app shell and frequently changing metadata must revalidate.
    if path.endswith(("/reader.html", "/index.html", "/manifest.json", "/sw.js", "/chapters_data.json")):
        return "no-cache"
    # Versioned assets (?v=12) can be cached aggressively.
    if "v" in request.rel_url.query:
        return "public, max-age=31536000, immutable"
    if path.endswith(_STATIC_LONG_CACHE_EXTENSIONS):
        return "public, max-age=86400"
    return "public, max-age=3600"


def _response_is_compressible(response: aiohttp.web.StreamResponse) -> bool:
    """True если Content-Type стоит сжимать gzip'ом (текстовый/JSON/SVG),
    и при этом это не бинарное изображение (в котором сжатие бесполезно).
    """
    content_type = str(response.headers.get("Content-Type", "")).lower()
    if not content_type:
        return False
    if content_type.startswith("image/") and "svg" not in content_type:
        return False
    return (
        content_type.startswith("text/")
        or "json" in content_type
        or "javascript" in content_type
        or "xml" in content_type
        or "svg" in content_type
    )


# --- Hooks / Middleware ---


async def apply_webapp_response_headers(
    request: aiohttp.web.Request,
    response: aiohttp.web.StreamResponse,
) -> None:
    """Устанавливает Cache-Control, gzip и финальные CORS-заголовки на ответы.

    Подключается через `app.on_response_prepare.append(apply_webapp_response_headers)`.
    """
    if request.path.startswith("/webapp/"):
        response.headers.setdefault("Cache-Control", _webapp_cache_control_for_request(request))
    if request.path.startswith(("/webapp/", "/api/")):
        response.headers["Vary"] = _merge_vary_header(response.headers.get("Vary", ""), "Accept-Encoding")
        if "Content-Encoding" not in response.headers and _response_is_compressible(response):
            try:
                response.enable_compression()
            except Exception as e:  # noqa: BLE001 — aiohttp может бросить разные RuntimeError в зависимости от версии.
                logging.debug(f"apply_webapp_response_headers: enable_compression failed: {e}")
    if request.path.startswith("/api/"):
        cors_headers = _build_cors_headers(request)
        response.headers["Access-Control-Allow-Methods"] = CORS_BASE_HEADERS["Access-Control-Allow-Methods"]
        response.headers["Access-Control-Allow-Headers"] = CORS_BASE_HEADERS["Access-Control-Allow-Headers"]
        response.headers["Access-Control-Expose-Headers"] = CORS_BASE_HEADERS["Access-Control-Expose-Headers"]
        if "Access-Control-Allow-Origin" in cors_headers:
            response.headers["Access-Control-Allow-Origin"] = cors_headers["Access-Control-Allow-Origin"]
            response.headers["Access-Control-Allow-Credentials"] = cors_headers["Access-Control-Allow-Credentials"]
        elif "Access-Control-Allow-Origin" in response.headers:
            del response.headers["Access-Control-Allow-Origin"]
            response.headers.pop("Access-Control-Allow-Credentials", None)
        response.headers["Vary"] = _merge_vary_header(response.headers.get("Vary", ""), "Origin")


@aiohttp.web.middleware
async def api_security_middleware(request: aiohttp.web.Request, handler):
    """Security-барьер для всех `/api/*` запросов:
    - отсекает неизвестные Origin'ы с 403;
    - отсекает превышение `API_MAX_BODY_BYTES` с 413;
    - ловит `HTTPRequestEntityTooLarge` из aiohttp и возвращает 413 в JSON.
    """
    if request.path.startswith("/api/"):
        origin = request.headers.get("Origin", "").strip()
        if origin and not _resolve_allowed_origin(request):
            return aiohttp.web.json_response(
                {"error": "origin_not_allowed"},
                status=403,
                headers=_build_cors_headers(request),
            )
        content_length = request.content_length
        if content_length is not None and content_length > API_MAX_BODY_BYTES:
            return aiohttp.web.json_response(
                {"error": "payload_too_large"},
                status=413,
                headers=_build_cors_headers(request),
            )
    try:
        return await handler(request)
    except aiohttp.web.HTTPRequestEntityTooLarge:
        return aiohttp.web.json_response(
            {"error": "payload_too_large"},
            status=413,
            headers=_build_cors_headers(request),
        )
