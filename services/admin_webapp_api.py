from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any

import aiohttp.web
import aiosqlite

import database
from database import get_admins, write_admin_audit_log
from services.auth import get_auth_user
from services.giveaways import (
    Giveaway,
    count_giveaway_entries,
    count_recent_giveaways,
    format_giveaway_end,
    format_giveaway_publish,
    get_required_channel_ids,
    list_active_giveaways,
    list_recent_giveaways,
)
from services.webapp_cors import CORS_HEADERS


STARTED_AT = time.time()


def _json(payload: dict[str, Any], *, status: int = 200) -> aiohttp.web.Response:
    return aiohttp.web.json_response(payload, status=status, headers=CORS_HEADERS)


async def _require_admin(request: aiohttp.web.Request) -> dict[str, Any] | aiohttp.web.Response:
    user = get_auth_user(request)
    if not user:
        return _json({"ok": False, "error": "unauthorized"}, status=401)
    try:
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError):
        return _json({"ok": False, "error": "unauthorized"}, status=401)
    if user_id not in await get_admins():
        return _json({"ok": False, "error": "forbidden"}, status=403)
    return user


def _page_params(request: aiohttp.web.Request, *, default_limit: int = 30) -> tuple[int, int]:
    try:
        limit = int(request.query.get("limit", default_limit))
        offset = int(request.query.get("offset", 0))
    except (TypeError, ValueError):
        return default_limit, 0
    return max(1, min(limit, 100)), max(0, offset)


async def _count(db: aiosqlite.Connection, query: str, params: tuple[Any, ...] = ()) -> int:
    try:
        async with db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return int(row[0] or 0) if row else 0
    except Exception:  # noqa: BLE001 - optional tables should not break summary widgets.
        return 0


async def _admin_summary_counts() -> dict[str, int]:
    async with aiosqlite.connect(database.DB_PATH) as db:
        chapters_total = sum(
            [
                await _count(db, "SELECT COUNT(*) FROM chapters_urls"),
                await _count(db, "SELECT COUNT(*) FROM ranobe_urls"),
                await _count(db, "SELECT COUNT(*) FROM akashic_ranobe"),
                await _count(db, "SELECT COUNT(*) FROM british_ranobe"),
            ]
        )
        return {
            "users_total": await _count(db, "SELECT COUNT(*) FROM users_stats"),
            "messages_total": await _count(db, "SELECT COALESCE(SUM(messages_count), 0) FROM users_stats"),
            "chapters_total": chapters_total,
            "manga_chapters": await _count(db, "SELECT COUNT(*) FROM chapters_urls"),
            "ranobe_chapters": await _count(db, "SELECT COUNT(*) FROM ranobe_urls"),
            "arts_visible": await _count(db, "SELECT COUNT(*) FROM arts WHERE COALESCE(is_hidden, 0) = 0"),
            "arts_hidden": await _count(db, "SELECT COUNT(*) FROM arts WHERE COALESCE(is_hidden, 0) = 1"),
            "suggestions_pending": await _count(db, "SELECT COUNT(*) FROM suggested_arts WHERE status = 'pending'"),
            "giveaways_active": await _count(db, "SELECT COUNT(*) FROM giveaways WHERE status IN ('active', 'scheduled', 'finishing')"),
            "comments_total": await _count(db, "SELECT COUNT(*) FROM chapter_comments"),
            "webapp_errors": await _count(
                db,
                """
                SELECT COUNT(*) FROM webapp_telemetry
                WHERE event_type IN ('client_runtime_error', 'client_unhandled_rejection', 'client_state_contract_violation')
                """,
            ),
        }


async def handle_admin_summary(request: aiohttp.web.Request) -> aiohttp.web.Response:
    user = await _require_admin(request)
    if isinstance(user, aiohttp.web.Response):
        return user
    return _json({"ok": True, "counts": await _admin_summary_counts()})


def _git_hash() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:  # noqa: BLE001 - git is best-effort in packaged deployments.
        return "unknown"
    value = (result.stdout or "").strip()
    return value if result.returncode == 0 and value else "unknown"


async def _database_ok() -> bool:
    try:
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT 1") as cursor:
                return (await cursor.fetchone()) is not None
    except Exception:  # noqa: BLE001 - health endpoint reports DB down instead of failing.
        return False


async def _recent_webapp_errors(limit: int = 5) -> list[dict[str, str]]:
    async with aiosqlite.connect(database.DB_PATH) as db:
        async with db.execute(
            """
            SELECT event_type, message, source_module, created_at
            FROM webapp_telemetry
            WHERE event_type IN ('client_runtime_error', 'client_unhandled_rejection', 'client_state_contract_violation')
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        {
            "event_type": str(row[0]),
            "message": str(row[1] or ""),
            "source_module": str(row[2] or ""),
            "created_at": str(row[3] or ""),
        }
        for row in rows
    ]


async def handle_admin_health(request: aiohttp.web.Request) -> aiohttp.web.Response:
    user = await _require_admin(request)
    if isinstance(user, aiohttp.web.Response):
        return user

    bot_username = ""
    try:
        bot = request.app.get("bot")
        if bot:
            me = await bot.get_me()
            bot_username = str(getattr(me, "username", "") or "")
    except Exception:  # noqa: BLE001 - bot profile is optional health metadata.
        bot_username = ""

    health = {
        "database": {"ok": await _database_ok()},
        "git": {"hash": _git_hash()},
        "bot": {"username": bot_username},
        "uptime_seconds": int(max(0, time.time() - STARTED_AT)),
        "providers": {
            "gemma": {"configured": bool(os.getenv("GEMMA_URL", "").strip())},
            "groq": {"configured": bool(os.getenv("GROQ_API_KEY", "").strip())},
        },
        "recent_errors": await _recent_webapp_errors(),
    }
    return _json({"ok": True, "health": health})


async def handle_admin_audit(request: aiohttp.web.Request) -> aiohttp.web.Response:
    user = await _require_admin(request)
    if isinstance(user, aiohttp.web.Response):
        return user
    limit, offset = _page_params(request)
    async with aiosqlite.connect(database.DB_PATH) as db:
        total = await _count(db, "SELECT COUNT(*) FROM admin_audit_log")
        async with db.execute(
            """
            SELECT id, action, actor_user_id, target, payload_json, result, error, created_at
            FROM admin_audit_log
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
    items = [
        {
            "id": int(row[0]),
            "action": str(row[1]),
            "actor_user_id": str(row[2]),
            "target": str(row[3] or ""),
            "payload": _parse_payload(row[4]),
            "result": str(row[5]),
            "error": str(row[6] or ""),
            "created_at": str(row[7] or ""),
        }
        for row in rows
    ]
    return _json({"ok": True, "total": total, "limit": limit, "offset": offset, "items": items})


async def _giveaway_payload(item: Giveaway) -> dict[str, Any]:
    required_channels = await get_required_channel_ids(item.id)
    return {
        "id": item.id,
        "status": item.status,
        "channel_id": item.channel_id,
        "message_id": item.message_id,
        "prize": item.prize,
        "post_text": item.post_text,
        "winners_count": item.winners_count,
        "participants": await count_giveaway_entries(item.id),
        "ends_at": format_giveaway_end(item.ends_at_utc),
        "publish_at": format_giveaway_publish(item.publish_at_utc),
        "media_type": item.media_type or "",
        "required_channels": required_channels,
        "required_channels_count": len(required_channels),
        "replacements_count": item.replacements_count,
    }


async def handle_admin_giveaways(request: aiohttp.web.Request) -> aiohttp.web.Response:
    user = await _require_admin(request)
    if isinstance(user, aiohttp.web.Response):
        return user

    limit, offset = _page_params(request, default_limit=8)
    active_items = await list_active_giveaways()
    recent_items = await list_recent_giveaways(limit=limit, offset=offset)
    return _json(
        {
            "ok": True,
            "active": [await _giveaway_payload(item) for item in active_items],
            "recent": [await _giveaway_payload(item) for item in recent_items],
            "total": await count_recent_giveaways(),
            "limit": limit,
            "offset": offset,
        }
    )


def _parse_payload(raw: Any) -> Any:
    try:
        return json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}


async def _run_webapp_sync() -> dict[str, str]:
    import bot
    from services.reader_cache import invalidate_reader_cache
    from utils import run_git_sync, spawn_bg

    invalidate_reader_cache("admin_webapp_sync")
    result, _, _ = await bot.get_cached_reader_data(force_refresh=True)
    with open("webapp/chapters_data.json", "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    spawn_bg(run_git_sync("admin webapp sync"), name="run_git_sync:admin_webapp")
    return {"status": "queued", "message": "sync started"}


async def handle_admin_sync(request: aiohttp.web.Request) -> aiohttp.web.Response:
    user = await _require_admin(request)
    if isinstance(user, aiohttp.web.Response):
        return user
    try:
        result = await _run_webapp_sync()
        status_text = str(result.get("status", "queued"))
        await write_admin_audit_log(
            action="webapp_sync",
            actor_user_id=str(user.get("id", "")),
            target="webapp",
            payload_json=json.dumps({"source": "admin_webapp"}, ensure_ascii=False),
            result=status_text,
        )
        return _json({"ok": True, "status": status_text, "message": str(result.get("message", "sync started"))})
    except Exception as exc:  # noqa: BLE001 - sync failure must be reported and audited.
        await write_admin_audit_log(
            action="webapp_sync",
            actor_user_id=str(user.get("id", "")),
            target="webapp",
            payload_json=json.dumps({"source": "admin_webapp"}, ensure_ascii=False),
            result="error",
            error=str(exc)[:250],
        )
        return _json({"ok": False, "error": "sync_failed"}, status=500)
