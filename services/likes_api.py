"""WebApp API handlers для лайков глав.

Два endpoints:
- `handle_likes_get(request)` — GET `/api/likes?chapter_key=...` → `{count, liked}`.
- `handle_likes_post(request)` — POST `/api/likes` с `{chapter_key}` → toggle like.

Таблица `chapter_likes (chapter_key, user_id)` — уникальный композитный ключ.
`chapter_key` не валидируется формально: это произвольная строка, формируемая
клиентом в формате `series/volume/chapter` (и иногда `arts/N`).

Lazy-импорт `DB_PATH` из bot.py, остальное — из services/.

Вынесено из `bot.py` как шаг Фазы 3 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import aiohttp.web
import aiosqlite

from services.admin_audit import _api_error_response
from services.auth import get_auth_user
from services.webapp_cors import CORS_HEADERS


async def handle_likes_get(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """GET `/api/likes?chapter_key=...` → `{count, liked}`.

    `liked` = True только если юзер аутентифицирован (есть валидный initData)
    и его запись есть в `chapter_likes`. Анонимные запросы получают `liked=False`
    но корректный `count`.
    """
    # Lazy-import (bot.py ↔ services/).
    from bot import DB_PATH

    chapter_key = request.query.get("chapter_key", "")
    user = get_auth_user(request)
    user_id = str(user.get("id", "")) if user else ""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM chapter_likes WHERE chapter_key = ?", (chapter_key,)) as c:
                count = (await c.fetchone())[0]
            liked = False
            if user_id:
                async with db.execute(
                    "SELECT 1 FROM chapter_likes WHERE chapter_key = ? AND user_id = ?",
                    (chapter_key, user_id),
                ) as c:
                    liked = bool(await c.fetchone())
        return aiohttp.web.json_response({"count": count, "liked": liked}, headers=CORS_HEADERS)
    except Exception as e:  # noqa: BLE001 — generic error, логируем через _api_error_response.
        return _api_error_response(e, context=request.path)


async def handle_likes_post(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST `/api/likes` с `{chapter_key}` → toggle like (201 не используется, всегда 200).

    Требует auth. Возвращает новое состояние `{count, liked}` после toggle.
    """
    # Lazy-import (bot.py ↔ services/).
    from bot import DB_PATH

    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))

        data = await request.json()
        chapter_key = data.get("chapter_key", "")
        if not chapter_key:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT 1 FROM chapter_likes WHERE chapter_key = ? AND user_id = ?",
                (chapter_key, user_id),
            ) as c:
                exists = await c.fetchone()
            if exists:
                await db.execute("DELETE FROM chapter_likes WHERE chapter_key = ? AND user_id = ?", (chapter_key, user_id))
                liked = False
            else:
                await db.execute("INSERT INTO chapter_likes (chapter_key, user_id) VALUES (?, ?)", (chapter_key, user_id))
                liked = True
            await db.commit()

            async with db.execute("SELECT COUNT(*) FROM chapter_likes WHERE chapter_key = ?", (chapter_key,)) as c:
                count = (await c.fetchone())[0]

        return aiohttp.web.json_response({"count": count, "liked": liked}, headers=CORS_HEADERS)
    except Exception as e:  # noqa: BLE001 — generic error, логируем через _api_error_response.
        return _api_error_response(e, context=request.path)
