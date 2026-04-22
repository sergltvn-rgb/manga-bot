"""WebApp API handlers для комментариев к главам.

4 endpoints:

- `handle_comments_get(request)` — GET `/api/comments?chapter_key=...` →
  список комментариев с лайками/дизлайками (JOIN на `comment_reactions`).
- `handle_comments_post(request)` — POST нового комментария (auth + rate-limit).
- `handle_comment_react_post(request)` — POST like/dislike на комментарий.
- `handle_comments_delete(request)` — DELETE свой комментарий (или админом)
  вместе со всеми ответами (`parent_id = ?`).
- `handle_comments_update(request)` — PUT `/api/comments/{id}` — редактировать
  свой комментарий (админ не редактирует от чужого имени).

Lazy-импорт `DB_PATH` и `get_admins` из bot.py.

Вынесено из `bot.py` как шаг Фазы 3 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import html
import logging

import aiohttp.web
import aiosqlite

from services.admin_audit import _api_error_response
from services.auth import get_auth_user
from services.rate_limit import _enforce_rate_limit
from services.validators import (
    MAX_CHAPTER_KEY_LENGTH,
    MAX_COMMENT_REPORT_TEXT_LENGTH,
    MAX_COMMENT_TEXT_LENGTH,
    MAX_REPORT_REASON_LENGTH,
)
from services.webapp_cors import CORS_HEADERS


async def handle_comments_get(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """GET `/api/comments?chapter_key=...` → список комментариев с реакциями.

    Анонимный запрос — просто получает комментарии с counters, но без
    `user_reaction` (null). Авторизованный — ещё и `user_reaction` заполняется.
    """
    from bot import DB_PATH

    chapter_key = request.query.get("chapter_key", "")
    user = get_auth_user(request)
    current_user_id = str(user.get("id", "")) if user else None

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            query = """
                SELECT
                    c.id, c.user_id, c.user_name, c.text, c.created_at, c.parent_id,
                    COUNT(CASE WHEN r.type = 'like' THEN 1 END) as likes,
                    COUNT(CASE WHEN r.type = 'dislike' THEN 1 END) as dislikes,
                    MAX(CASE WHEN r.user_id = ? THEN r.type ELSE NULL END) as user_reaction,
                    c.updated_at
                FROM chapter_comments c
                LEFT JOIN comment_reactions r ON c.id = r.comment_id
                WHERE c.chapter_key = ?
                GROUP BY c.id
                ORDER BY c.created_at ASC
            """
            async with db.execute(query, (current_user_id, chapter_key)) as cursor:
                rows = await cursor.fetchall()

        comments = [
            {
                "id": r[0],
                "user_id": r[1],
                "user_name": r[2],
                "text": r[3],
                "created_at": r[4],
                "parent_id": r[5],
                "likes": r[6],
                "dislikes": r[7],
                "user_reaction": r[8],
                "updated_at": r[9],
            }
            for r in rows
        ]
        return aiohttp.web.json_response({"comments": comments}, headers=CORS_HEADERS)
    except Exception as e:  # noqa: BLE001
        logging.error(f"Error in handle_comments_get: {e}")
        return _api_error_response(e, context=request.path)


async def handle_comment_react_post(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST `/api/comments/react` с `{comment_id, type}` — лайк/дизлайк комментария.

    `type` ∈ `{'like', 'dislike'}`. Повторный вызов с тем же type снимает реакцию
    (логика в `database.add_comment_reaction`).
    """
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        limited = await _enforce_rate_limit(request, "comments_react", user_id=user_id)
        if limited:
            return limited

        data = await request.json()
        comment_id = data.get("comment_id")
        reaction_type = str(data.get("type", "")).strip()  # 'like' or 'dislike'
        try:
            comment_id_int = int(comment_id)
        except Exception:  # noqa: BLE001
            return aiohttp.web.json_response({"error": "invalid comment_id"}, status=400, headers=CORS_HEADERS)

        if comment_id_int <= 0 or reaction_type not in ["like", "dislike"]:
            return aiohttp.web.json_response({"error": "invalid arguments"}, status=400, headers=CORS_HEADERS)

        from database import add_comment_reaction

        await add_comment_reaction(comment_id_int, user_id, reaction_type)

        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:  # noqa: BLE001
        return _api_error_response(e, context=request.path)


async def handle_comments_post(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST нового комментария (или ответа через `parent_id`)."""
    from bot import DB_PATH

    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        limited = await _enforce_rate_limit(request, "comments_post", user_id=user_id)
        if limited:
            return limited
        user_name = str(user.get("first_name", "Аноним"))[:80]

        data = await request.json()
        chapter_key = str(data.get("chapter_key", "")).strip()
        text = str(data.get("text", "")).strip()
        parent_id = data.get("parent_id", None)
        if not chapter_key or not text:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)
        if len(chapter_key) > MAX_CHAPTER_KEY_LENGTH:
            return aiohttp.web.json_response({"error": "invalid chapter_key"}, status=400, headers=CORS_HEADERS)
        if len(text) > MAX_COMMENT_TEXT_LENGTH:
            return aiohttp.web.json_response({"error": "too long"}, status=400, headers=CORS_HEADERS)
        if parent_id not in (None, "", 0):
            try:
                parent_id = int(parent_id)
                if parent_id <= 0:
                    raise ValueError("invalid parent_id")
            except Exception:  # noqa: BLE001
                return aiohttp.web.json_response({"error": "invalid parent_id"}, status=400, headers=CORS_HEADERS)
        else:
            parent_id = None

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO chapter_comments (chapter_key, user_id, user_name, text, parent_id) VALUES (?, ?, ?, ?, ?)",
                (chapter_key, user_id, user_name, text, parent_id),
            )
            await db.commit()

        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:  # noqa: BLE001
        return _api_error_response(e, context=request.path)


async def handle_comments_delete(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """DELETE свой комментарий или админом. Каскадно удаляет все ответы (`parent_id = ?`)."""
    from bot import DB_PATH, get_admins

    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))

        data = await request.json()
        comment_id = data.get("comment_id", 0)

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT user_id FROM chapter_comments WHERE id = ?", (comment_id,)) as c:
                row = await c.fetchone()
            if not row:
                return aiohttp.web.json_response({"error": "not found"}, status=404, headers=CORS_HEADERS)
            if str(row[0]) != str(user_id):
                # Проверяем, админ ли.
                admins = await get_admins()
                try:
                    if int(user_id) not in admins:
                        return aiohttp.web.json_response({"error": "forbidden"}, status=403, headers=CORS_HEADERS)
                except (ValueError, TypeError):
                    return aiohttp.web.json_response({"error": "forbidden"}, status=403, headers=CORS_HEADERS)

            await db.execute("DELETE FROM chapter_comments WHERE id = ? OR parent_id = ?", (comment_id, comment_id))
            await db.commit()

        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:  # noqa: BLE001
        return _api_error_response(e, context=request.path)


async def handle_comments_update(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """PUT `/api/comments/{id}` — редактирование комментария автором.

    Админ НЕ может редактировать от имени другого — только автор. Для удаления
    админ может использовать `handle_comments_delete`.
    """
    from bot import DB_PATH

    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        limited = await _enforce_rate_limit(request, "comments_update", user_id=user_id)
        if limited:
            return limited

        try:
            comment_id = int(request.match_info.get("id", "0"))
        except (TypeError, ValueError):
            return aiohttp.web.json_response({"error": "invalid comment id"}, status=400, headers=CORS_HEADERS)
        if comment_id <= 0:
            return aiohttp.web.json_response({"error": "invalid comment id"}, status=400, headers=CORS_HEADERS)

        data = await request.json()
        new_text = str(data.get("text", "")).strip()
        if not new_text:
            return aiohttp.web.json_response({"error": "text required"}, status=400, headers=CORS_HEADERS)
        if len(new_text) > MAX_COMMENT_TEXT_LENGTH:
            return aiohttp.web.json_response({"error": "too long"}, status=400, headers=CORS_HEADERS)

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT user_id FROM chapter_comments WHERE id = ?", (comment_id,)) as c:
                row = await c.fetchone()
            if not row:
                return aiohttp.web.json_response({"error": "not found"}, status=404, headers=CORS_HEADERS)
            if str(row[0]) != str(user_id):
                return aiohttp.web.json_response({"error": "forbidden"}, status=403, headers=CORS_HEADERS)

            await db.execute("UPDATE chapter_comments SET text = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_text, comment_id))
            await db.commit()

            async with db.execute("SELECT id, text, updated_at FROM chapter_comments WHERE id = ?", (comment_id,)) as c:
                updated_row = await c.fetchone()

        if not updated_row:
            return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)

        return aiohttp.web.json_response(
            {
                "ok": True,
                "comment": {
                    "id": updated_row[0],
                    "text": updated_row[1],
                    "updated_at": updated_row[2],
                },
            },
            headers=CORS_HEADERS,
        )
    except Exception as e:  # noqa: BLE001
        logging.exception("handle_comments_update failed")
        return _api_error_response(e, context=request.path)


async def handle_comments_report(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST `/api/comments/report` — жалоба на комментарий.

    Не пишет в БД — только уведомляет админов в Telegram с причиной и текстом
    репортуемого комментария. Защита от спама — через rate-limit.
    """
    from bot import bot, get_admins

    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        limited = await _enforce_rate_limit(request, "comments_report", user_id=user_id)
        if limited:
            return limited
        user_name = user.get("first_name", "Аноним")

        data = await request.json()
        comment_id = data.get("comment_id")
        reason = str(data.get("reason", "")).strip()
        comment_text = str(data.get("comment_text", "")).strip()
        try:
            comment_id_int = int(comment_id)
        except Exception:  # noqa: BLE001
            return aiohttp.web.json_response({"error": "invalid comment_id"}, status=400, headers=CORS_HEADERS)

        if comment_id_int <= 0 or not reason:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)
        if len(reason) > MAX_REPORT_REASON_LENGTH:
            return aiohttp.web.json_response({"error": "reason too long"}, status=400, headers=CORS_HEADERS)
        if len(comment_text) > MAX_COMMENT_REPORT_TEXT_LENGTH:
            return aiohttp.web.json_response({"error": "comment_text too long"}, status=400, headers=CORS_HEADERS)

        admins = await get_admins()
        report_text = (
            f"🚫 <b>Жалоба на комментарий!</b>\n"
            f"От: {html.escape(user_name)} (ID: <code>{user_id}</code>)\n"
            f"ID комментария: <code>{comment_id_int}</code>\n"
            f"Причина: {html.escape(reason)}\n\n"
            f"<b>Текст комментария:</b>\n<i>{html.escape(comment_text)}</i>"
        )
        for admin_id in admins:
            try:
                await bot.send_message(admin_id, report_text, parse_mode="HTML")
            except Exception as e:  # noqa: BLE001 — aiogram-ошибка не должна фейлить HTTP-ответ.
                logging.debug(f"comments_report: failed to notify admin {admin_id}: {e}")

        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:  # noqa: BLE001
        return _api_error_response(e, context=request.path)
