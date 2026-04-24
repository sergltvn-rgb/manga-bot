"""Public-site Telegram Login Widget auth endpoints."""

from __future__ import annotations

import aiohttp.web
import aiosqlite

from services.auth import (
    WEB_SESSION_COOKIE_NAME,
    WEB_SESSION_TTL_SECONDS,
    create_web_session,
    get_auth_user,
    revoke_web_session_token,
    validate_telegram_login_payload,
)
from services.webapp_cors import CORS_HEADERS


def _public_user(user: dict) -> dict:
    result = {"id": user.get("id")}
    for key in ("first_name", "last_name", "username", "photo_url"):
        value = user.get(key)
        if value not in (None, ""):
            result[key] = value
    return result


async def _is_admin(user: dict | None) -> bool:
    if not user:
        return False
    try:
        user_id = int(user.get("id", 0))
    except (TypeError, ValueError):
        return False
    from bot import get_admins

    return user_id in await get_admins()


def _set_session_cookie(response: aiohttp.web.Response, token: str) -> None:
    response.set_cookie(
        WEB_SESSION_COOKIE_NAME,
        token,
        max_age=WEB_SESSION_TTL_SECONDS,
        path="/",
        httponly=True,
        secure=True,
        samesite="Lax",
    )


async def handle_auth_telegram_login(request: aiohttp.web.Request) -> aiohttp.web.Response:
    from database import DB_PATH

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return aiohttp.web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)

    user = validate_telegram_login_payload(payload)
    if not user:
        return aiohttp.web.json_response({"error": "invalid telegram login"}, status=401, headers=CORS_HEADERS)

    async with aiosqlite.connect(DB_PATH) as db:
        token, expires_at = await create_web_session(db, user)

    response = aiohttp.web.json_response(
        {
            "ok": True,
            "authenticated": True,
            "user": _public_user(user),
            "is_admin": await _is_admin(user),
            "expires_at": expires_at,
        },
        headers=CORS_HEADERS,
    )
    _set_session_cookie(response, token)
    return response


async def handle_auth_me(request: aiohttp.web.Request) -> aiohttp.web.Response:
    user = get_auth_user(request)
    if not user:
        return aiohttp.web.json_response({"authenticated": False, "user": None, "is_admin": False}, headers=CORS_HEADERS)
    return aiohttp.web.json_response(
        {
            "authenticated": True,
            "user": _public_user(user),
            "is_admin": await _is_admin(user),
        },
        headers=CORS_HEADERS,
    )


async def handle_auth_logout(request: aiohttp.web.Request) -> aiohttp.web.Response:
    token = request.cookies.get(WEB_SESSION_COOKIE_NAME, "")
    revoke_web_session_token(token)
    response = aiohttp.web.json_response({"ok": True, "authenticated": False}, headers=CORS_HEADERS)
    response.del_cookie(WEB_SESSION_COOKIE_NAME, path="/")
    return response
