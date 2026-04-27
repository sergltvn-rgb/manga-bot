from __future__ import annotations

import aiohttp
import aiohttp.web

from config import BOT_TOKEN
from database import get_admins
from services import arts
from services.auth import get_auth_user
from services.webapp_cors import CORS_HEADERS


def _json(payload: dict, *, status: int = 200) -> aiohttp.web.Response:
    return aiohttp.web.json_response(payload, status=status, headers=CORS_HEADERS)


def _auth_user(request: aiohttp.web.Request) -> dict | None:
    return get_auth_user(request)


async def _is_admin_user(user: dict | None) -> bool:
    if not user:
        return False
    try:
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError):
        return False
    return user_id in await get_admins()


async def _require_user(request: aiohttp.web.Request) -> dict | aiohttp.web.Response:
    user = _auth_user(request)
    if not user:
        return _json({"ok": False, "error": "unauthorized"}, status=401)
    return user


async def _require_admin(request: aiohttp.web.Request) -> dict | aiohttp.web.Response:
    user = await _require_user(request)
    if isinstance(user, aiohttp.web.Response):
        return user
    if not await _is_admin_user(user):
        return _json({"ok": False, "error": "forbidden"}, status=403)
    return user


def _page_params(request: aiohttp.web.Request, *, default_limit: int) -> tuple[int, int]:
    try:
        limit = int(request.query.get("limit", default_limit))
        offset = int(request.query.get("offset", 0))
    except (TypeError, ValueError):
        return default_limit, 0
    return max(1, min(limit, 60)), max(0, offset)


async def handle_arts_list(request: aiohttp.web.Request) -> aiohttp.web.Response:
    user = await _require_user(request)
    if isinstance(user, aiohttp.web.Response):
        return user
    is_admin = await _is_admin_user(user)
    limit, offset = _page_params(request, default_limit=arts.ART_PAGE_SIZE)
    view = request.query.get("view", "all")
    payload = await arts.get_arts_webapp_payload(
        user_id=int(user["id"]),
        is_admin=is_admin,
        limit=limit,
        offset=offset,
        only_hidden=view == "hidden",
    )
    return _json(payload)


async def handle_art_suggestions_list(request: aiohttp.web.Request) -> aiohttp.web.Response:
    user = await _require_admin(request)
    if isinstance(user, aiohttp.web.Response):
        return user
    limit, offset = _page_params(request, default_limit=arts.SUGGESTION_PAGE_SIZE)
    return _json(await arts.get_suggestions_webapp_payload(limit=limit, offset=offset))


async def handle_art_suggestion_approve(request: aiohttp.web.Request) -> aiohttp.web.Response:
    user = await _require_admin(request)
    if isinstance(user, aiohttp.web.Response):
        return user
    try:
        suggestion_id = int(request.match_info["id"])
    except (KeyError, TypeError, ValueError):
        return _json({"ok": False, "error": "bad_request"}, status=400)
    item = await arts.approve_suggested_art(suggestion_id, reviewed_by=int(user["id"]))
    if not item:
        return _json({"ok": False, "error": "not_found"}, status=404)
    return _json({"ok": True, "art_id": item.id})


async def handle_art_suggestion_reject(request: aiohttp.web.Request) -> aiohttp.web.Response:
    user = await _require_admin(request)
    if isinstance(user, aiohttp.web.Response):
        return user
    try:
        suggestion_id = int(request.match_info["id"])
    except (KeyError, TypeError, ValueError):
        return _json({"ok": False, "error": "bad_request"}, status=400)
    reason = ""
    if request.can_read_body:
        try:
            payload = await request.json()
            reason = str(payload.get("reason", "")).strip()
        except Exception:  # noqa: BLE001
            reason = ""
    if not await arts.reject_suggested_art(suggestion_id, reviewed_by=int(user["id"]), reason=reason):
        return _json({"ok": False, "error": "not_found"}, status=404)
    return _json({"ok": True})


async def handle_art_delete(request: aiohttp.web.Request) -> aiohttp.web.Response:
    user = await _require_admin(request)
    if isinstance(user, aiohttp.web.Response):
        return user
    try:
        art_id = int(request.match_info["id"])
    except (KeyError, TypeError, ValueError):
        return _json({"ok": False, "error": "bad_request"}, status=400)
    if not await arts.delete_art(art_id, actor_id=int(user["id"])):
        return _json({"ok": False, "error": "not_found"}, status=404)
    return _json({"ok": True})


async def handle_art_hide(request: aiohttp.web.Request) -> aiohttp.web.Response:
    user = await _require_admin(request)
    if isinstance(user, aiohttp.web.Response):
        return user
    try:
        art_id = int(request.match_info["id"])
    except (KeyError, TypeError, ValueError):
        return _json({"ok": False, "error": "bad_request"}, status=400)
    if not await arts.hide_art(art_id, actor_id=int(user["id"])):
        return _json({"ok": False, "error": "not_found"}, status=404)
    return _json({"ok": True})


async def handle_art_unhide(request: aiohttp.web.Request) -> aiohttp.web.Response:
    user = await _require_admin(request)
    if isinstance(user, aiohttp.web.Response):
        return user
    try:
        art_id = int(request.match_info["id"])
    except (KeyError, TypeError, ValueError):
        return _json({"ok": False, "error": "bad_request"}, status=400)
    if not await arts.unhide_art(art_id, actor_id=int(user["id"])):
        return _json({"ok": False, "error": "not_found"}, status=404)
    return _json({"ok": True})


async def _fetch_telegram_file(request: aiohttp.web.Request, file_id: str) -> aiohttp.web.Response:
    bot = request.app["bot"]
    file = await bot.get_file(file_id)
    file_path = getattr(file, "file_path", "")
    if not file_path:
        return aiohttp.web.Response(status=404, headers=CORS_HEADERS)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                return aiohttp.web.Response(status=404, headers=CORS_HEADERS)
            body = await response.read()
            content_type = response.headers.get("Content-Type", "image/jpeg")
    return aiohttp.web.Response(body=body, content_type=content_type, headers=CORS_HEADERS)


async def handle_art_media(request: aiohttp.web.Request) -> aiohttp.web.Response:
    try:
        art_id = int(request.match_info["id"])
    except (KeyError, TypeError, ValueError):
        return aiohttp.web.Response(status=400, headers=CORS_HEADERS)
    item = await arts.get_art(art_id)
    if not item:
        return aiohttp.web.Response(status=404, headers=CORS_HEADERS)
    if item.is_hidden and not await _is_admin_user(_auth_user(request)):
        return aiohttp.web.Response(status=403, headers=CORS_HEADERS)
    return await _fetch_telegram_file(request, item.file_id)


async def handle_art_suggestion_media(request: aiohttp.web.Request) -> aiohttp.web.Response:
    user = await _require_admin(request)
    if isinstance(user, aiohttp.web.Response):
        return user
    try:
        suggestion_id = int(request.match_info["id"])
    except (KeyError, TypeError, ValueError):
        return aiohttp.web.Response(status=400, headers=CORS_HEADERS)
    item = await arts.get_suggestion(suggestion_id)
    if not item:
        return aiohttp.web.Response(status=404, headers=CORS_HEADERS)
    return await _fetch_telegram_file(request, item.file_id)
