from __future__ import annotations

import aiohttp.web

from services.auth import get_auth_user
from services.giveaways import get_giveaway_webapp_status, join_giveaway_from_webapp, record_giveaway_participant_event
from services.webapp_cors import CORS_HEADERS


async def handle_giveaway_status(request: aiohttp.web.Request) -> aiohttp.web.Response:
    user = get_auth_user(request)
    if not user:
        return aiohttp.web.json_response({"ok": False, "error": "unauthorized"}, status=401, headers=CORS_HEADERS)

    try:
        giveaway_id = int(request.query.get("giveaway_id") or request.query.get("id") or "0")
        user_id = int(user["id"])
    except (TypeError, ValueError, KeyError):
        return aiohttp.web.json_response({"ok": False, "error": "bad_request"}, status=400, headers=CORS_HEADERS)

    if giveaway_id <= 0:
        return aiohttp.web.json_response({"ok": False, "error": "bad_request"}, status=400, headers=CORS_HEADERS)

    bot = request.app["bot"]
    await record_giveaway_participant_event(
        giveaway_id,
        user_id,
        "webapp_open",
        referral_source=request.query.get("ref") or request.query.get("source") or "",
        username=user.get("username"),
        first_name=user.get("first_name"),
        language_code=user.get("language_code"),
        is_premium=user.get("is_premium"),
    )
    payload = await get_giveaway_webapp_status(bot, giveaway_id, user_id)
    status = 404 if payload.get("status") == "not_found" else 200
    return aiohttp.web.json_response(payload, status=status, headers=CORS_HEADERS)


async def handle_giveaway_join(request: aiohttp.web.Request) -> aiohttp.web.Response:
    user = get_auth_user(request)
    if not user:
        return aiohttp.web.json_response({"ok": False, "error": "unauthorized"}, status=401, headers=CORS_HEADERS)

    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        data = {}
    try:
        giveaway_id = int(data.get("giveaway_id") or request.query.get("giveaway_id") or request.query.get("id") or "0")
    except (TypeError, ValueError):
        return aiohttp.web.json_response({"ok": False, "error": "bad_request"}, status=400, headers=CORS_HEADERS)

    if giveaway_id <= 0:
        return aiohttp.web.json_response({"ok": False, "error": "bad_request"}, status=400, headers=CORS_HEADERS)

    bot = request.app["bot"]
    captcha_answer = data.get("captcha_answer")
    payload = await join_giveaway_from_webapp(
        bot,
        giveaway_id,
        user,
        captcha_answer=str(captcha_answer) if captcha_answer is not None else None,
        refresh_markup=True,
    )
    status = 404 if payload.get("status") == "not_found" else 200
    return aiohttp.web.json_response(payload, status=status, headers=CORS_HEADERS)
