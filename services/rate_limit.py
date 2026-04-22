"""Rate-limiter для WebApp API.

Token-bucket в памяти процесса. Используется хендлерами в БЛОКе 11
`bot.py` (admin_chapter_edit, comments_post, typo_report и т. п.) через
`_enforce_rate_limit(request, scope, user_id)`.

Вынесено из `bot.py` как шаг 2 Фазы 3 распила монолита (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).

Стейт (`_rate_limit_buckets`, `_rate_limit_lock`) живёт модульно —
ровно как было в `bot.py`. Перезапуск процесса обнуляет лимиты.
Это ок: rate-limit — не security-boundary, а DDoS-щит.
"""

from __future__ import annotations

import asyncio
import time

import aiohttp.web

from services.webapp_cors import _build_cors_headers

# Правила: {scope: {"limit": N, "window": seconds}}.
# `scope` задаётся в call-site'е (например "comments_post").
# Если scope нет в словаре — `_enforce_rate_limit` пропускает запрос без проверки.
RATE_LIMIT_RULES: dict[str, dict[str, int]] = {
    "comments_post": {"limit": 8, "window": 60},
    "comments_update": {"limit": 20, "window": 60},
    "comments_react": {"limit": 30, "window": 60},
    "reactions_post": {"limit": 30, "window": 60},
    "comments_report": {"limit": 6, "window": 300},
    "typo_report": {"limit": 8, "window": 300},
    "admin_rename_delete": {"limit": 30, "window": 60},
    "admin_chapter_edit": {"limit": 30, "window": 60},
    "admin_chapter_bulk": {"limit": 12, "window": 60},
    "admin_chapter_add": {"limit": 30, "window": 60},
    "admin_chapter_delete": {"limit": 20, "window": 60},
    "admin_series_update": {"limit": 20, "window": 60},
    "admin_sort": {"limit": 20, "window": 60},
    "admin_rename_request": {"limit": 40, "window": 60},
}

# Стейт: {f"{scope}:{identity}": [timestamp, ...]}.
# Запись храним пока не пройдёт `window`, потом отсекается.
_rate_limit_buckets: dict[str, list[float]] = {}
_rate_limit_lock = asyncio.Lock()


def _rate_limit_identity(request: aiohttp.web.Request, user_id: str = "") -> str:
    """Строит ключ identity: авторизованный юзер по его id, иначе по IP.
    Учитывает `X-Forwarded-For` (если бот за nginx/cloudflare).
    """
    if user_id:
        return f"user:{user_id}"
    xff = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if xff:
        return f"ip:{xff}"
    if request.remote:
        return f"ip:{request.remote}"
    return "ip:unknown"


async def _enforce_rate_limit(
    request: aiohttp.web.Request,
    scope: str,
    user_id: str = "",
) -> aiohttp.web.Response | None:
    """Проверяет лимит для (scope, identity). Возвращает:
      - `None` если лимит не превышен (запрос пропускаем);
      - готовый 429 `aiohttp.web.Response` с Retry-After если превышен.

    Хендлер должен вернуть этот Response напрямую: `return limited`.
    """
    rule = RATE_LIMIT_RULES.get(scope)
    if not rule:
        return None
    now = time.time()
    window = int(rule["window"])
    limit = int(rule["limit"])
    key = f"{scope}:{_rate_limit_identity(request, user_id)}"
    async with _rate_limit_lock:
        events = [ts for ts in _rate_limit_buckets.get(key, []) if now - ts < window]
        if len(events) >= limit:
            retry_after = max(1, int(window - (now - events[0])))
            headers = _build_cors_headers(request)
            headers["Retry-After"] = str(retry_after)
            return aiohttp.web.json_response(
                {"error": "rate_limit_exceeded", "retry_after": retry_after},
                status=429,
                headers=headers,
            )
        events.append(now)
        _rate_limit_buckets[key] = events
    return None
