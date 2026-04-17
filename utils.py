# -*- coding: utf-8 -*-
import asyncio
import hashlib
import hmac
import logging
import time
from typing import Union
from urllib.parse import parse_qsl

from aiogram import types

from database import get_admins


# Cache for cooldowns: key -> (timestamp, cooldown_duration)
COOLDOWNS: dict = {}

# Admin cache with TTL to reduce DB reads
_ADMINS_CACHE: set = set()
_ADMINS_CACHE_TS: float = 0.0
_ADMINS_CACHE_TTL: float = 60.0

# Periodic cleanup counters for COOLDOWNS
_call_counter: list = [0]
_CLEANUP_EVERY: int = 50

# Serialize git syncs to avoid concurrent commit/push races
_GIT_SYNC_LOCK = asyncio.Lock()


async def _get_admins_cached() -> set:
    """Return admins list using a short TTL cache."""
    global _ADMINS_CACHE, _ADMINS_CACHE_TS
    now = time.monotonic()
    if now - _ADMINS_CACHE_TS > _ADMINS_CACHE_TTL:
        _ADMINS_CACHE = set(await get_admins())
        _ADMINS_CACHE_TS = now
    return _ADMINS_CACHE


def invalidate_admins_cache():
    """Reset admin cache (call after add_admin/remove_admin)."""
    global _ADMINS_CACHE_TS
    _ADMINS_CACHE_TS = 0.0


async def is_on_cooldown(user_id: int, action: str = "global", custom_cooldown: int = 30) -> int:
    global _call_counter

    if user_id in await _get_admins_cached():
        return 0

    now = time.time()

    _call_counter[0] += 1
    if _call_counter[0] >= _CLEANUP_EVERY:
        _call_counter[0] = 0
        expired = [k for k, (ts, cd) in COOLDOWNS.items() if now - ts > cd]
        for k in expired:
            COOLDOWNS.pop(k, None)

    key = f"{user_id}_{action}"
    if key in COOLDOWNS:
        ts, cd = COOLDOWNS[key]
        elapsed = now - ts
        if elapsed < cd:
            return int(cd - elapsed)

    COOLDOWNS[key] = (now, custom_cooldown)
    return 0


async def check_cd_and_warn(event: Union[types.Message, types.CallbackQuery], action: str, custom_cd: int = 30) -> bool:
    cd = await is_on_cooldown(event.from_user.id, action, custom_cd)
    if cd:
        if isinstance(event, types.CallbackQuery):
            await event.answer(f"⏳ Остынь! Подожди {cd} сек.", show_alert=True)
        else:
            msg = await event.answer(
                f"⏳ <b>Подожди!</b> Это действие остывает. Осталось {cd} сек.",
                parse_mode="HTML",
            )
            asyncio.create_task(delete_after(msg, 3))
        return True
    return False


async def delete_after(message: types.Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception as e:
        logging.debug(
            f"delete_after: failed to delete message {getattr(message, 'message_id', '?')}: {e}"
        )


async def temp_reply(message: types.Message, text: str, delay: int = 5, **kwargs):
    msg = await message.answer(text, **kwargs)
    asyncio.create_task(delete_after(msg, delay))


def validate_telegram_data(init_data: str, bot_token: str) -> dict | None:
    """Validate Telegram WebApp init data using HMAC-SHA256."""
    try:
        if not init_data:
            return None

        parsed_data = dict(parse_qsl(init_data, keep_blank_values=True))
        if "hash" not in parsed_data:
            return None

        hash_value = parsed_data.pop("hash")
        sorted_keys = sorted(parsed_data.keys())
        data_check_string = "\n".join(f"{k}={parsed_data[k]}" for k in sorted_keys)

        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if calculated_hash == hash_value:
            parsed_data["hash"] = hash_value
            return parsed_data
        return None
    except Exception as e:
        logging.error(f"Telegram data validation error: {e}")
        return None


async def run_git_sync(commit_message: str = "sync webapp db") -> tuple[bool, str]:
    """Async git sync: config -> add -> commit (if needed) -> push.
    Uses a lock to avoid concurrent git race conditions."""

    async def run_cmd(*args: str) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = "\n".join(
            part
            for part in (
                stdout.decode(errors="replace").strip(),
                stderr.decode(errors="replace").strip(),
            )
            if part
        )
        return proc.returncode, output

    async with _GIT_SYNC_LOCK:
        rc, out = await run_cmd("git", "config", "user.name", "MangaBot")
        if rc != 0:
            return False, out

        rc, out = await run_cmd("git", "config", "user.email", "bot@manga.local")
        if rc != 0:
            return False, out

        rc, out = await run_cmd("git", "add", "webapp/chapters_data.json")
        if rc != 0:
            return False, out

        # 0 = no staged changes, 1 = staged changes exist, >1 = error
        rc, diff_out = await run_cmd("git", "diff", "--cached", "--quiet", "--", "webapp/chapters_data.json")
        if rc == 0:
            return True, "No changes in webapp/chapters_data.json"
        if rc != 1:
            return False, diff_out

        rc, commit_out = await run_cmd("git", "commit", "-m", commit_message)
        if rc != 0:
            return False, commit_out

        rc, push_out = await run_cmd("git", "push")
        output = "\n".join(part for part in (commit_out, push_out) if part)
        return rc == 0, output


async def safe_edit_or_reply(
    target: Union[types.Message, types.CallbackQuery],
    text: str,
    **kwargs,
) -> types.Message:
    """Safely edit a message; fallback to delete+send when edit fails."""
    msg = target.message if isinstance(target, types.CallbackQuery) else target
    try:
        return await msg.edit_text(text, **kwargs)
    except Exception as e:
        logging.debug(f"safe_edit_or_reply: edit_text failed, trying delete+answer: {e}")
        try:
            await msg.delete()
        except Exception as del_e:
            logging.debug(f"safe_edit_or_reply: delete failed, sending answer anyway: {del_e}")
        return await msg.answer(text, **kwargs)
