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
COOLDOWNS: dict[str, tuple[float, int]] = {}

# Admin cache with TTL to reduce DB reads
_ADMINS_CACHE: set[int] = set()
_ADMINS_CACHE_TS: float = 0.0
_ADMINS_CACHE_TTL: float = 60.0

# Periodic cleanup counters for COOLDOWNS
_call_counter: list[int] = [0]
_CLEANUP_EVERY: int = 50

# Track pending delete tasks to avoid duplicate scheduling for same message
_PENDING_DELETES: set[tuple[int, int]] = set()

# Serialize git syncs to avoid concurrent commit/push races
_GIT_SYNC_LOCK = asyncio.Lock()

# ---------------------------------------------------------------------------
# TTL presets for auto-delete (seconds). Use in reply_and_forget / temp_reply.
# ---------------------------------------------------------------------------
TTL_ERROR = 5            # Errors, cooldown-warnings, validation fails
TTL_GAME = 180           # Games, RP, small-random results (3 min)
TTL_HEAVY_GAME = 300     # Bottles, roulette, ship, lootbox (5 min)
TTL_MENU = 600           # Menus, FSM dialog prompts (10 min)

# ---------------------------------------------------------------------------
# Background tasks registry: prevent `asyncio.create_task(...)` from being
# garbage-collected prematurely (common aiogram pitfall).
# ---------------------------------------------------------------------------
_BG_TASKS: set[asyncio.Task] = set()


def spawn_bg(coro, *, name: str | None = None) -> asyncio.Task:
    """Create an `asyncio.Task` and keep a strong ref until it completes.

    Use this everywhere instead of raw `asyncio.create_task(...)` when the
    returned task is not awaited, to avoid GC-related cancellations.
    """
    task = asyncio.create_task(coro, name=name)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task


def _build_user_cd_key(user_id: int, action: str) -> str:
    return f"u:{user_id}:{action}"


def _build_chat_cd_key(chat_id: int, action: str) -> str:
    return f"c:{chat_id}:{action}"


async def _get_admins_cached() -> set[int]:
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


def _cleanup_expired_cooldowns(now: float):
    global _call_counter
    _call_counter[0] += 1
    if _call_counter[0] < _CLEANUP_EVERY:
        return

    _call_counter[0] = 0
    expired = [k for k, (ts, cd) in COOLDOWNS.items() if now - ts > cd]
    for key in expired:
        COOLDOWNS.pop(key, None)


def _check_key_cooldown(key: str, now: float, cooldown: int, touch: bool = True) -> int:
    if cooldown <= 0:
        return 0

    state = COOLDOWNS.get(key)
    if state:
        ts, cd = state
        elapsed = now - ts
        if elapsed < cd:
            return int(cd - elapsed)

    if touch:
        COOLDOWNS[key] = (now, cooldown)
    return 0


async def is_on_cooldown(
    user_id: int,
    action: str = "global",
    custom_cooldown: int = 30,
    ignore_admin_bypass: bool = False,
    touch: bool = True,
) -> int:
    if not ignore_admin_bypass and user_id in await _get_admins_cached():
        return 0

    now = time.time()
    _cleanup_expired_cooldowns(now)
    return _check_key_cooldown(
        _build_user_cd_key(user_id, action),
        now,
        custom_cooldown,
        touch=touch,
    )


async def is_on_scoped_cooldown(
    user_id: int,
    action: str,
    user_cooldown: int = 0,
    chat_id: int | None = None,
    chat_cooldown: int = 0,
    ignore_admin_bypass: bool = False,
    touch: bool = True,
) -> int:
    if not ignore_admin_bypass and user_id in await _get_admins_cached():
        return 0

    now = time.time()
    _cleanup_expired_cooldowns(now)

    user_remaining = _check_key_cooldown(
        _build_user_cd_key(user_id, action),
        now,
        user_cooldown,
        touch=touch,
    )

    chat_remaining = 0
    if chat_id is not None and chat_cooldown > 0:
        chat_remaining = _check_key_cooldown(
            _build_chat_cd_key(chat_id, action),
            now,
            chat_cooldown,
            touch=touch,
        )

    return max(user_remaining, chat_remaining)


def set_cooldown(user_id: int, action: str, custom_cooldown: int) -> None:
    """Force-set cooldown for a user action."""
    COOLDOWNS[_build_user_cd_key(user_id, action)] = (time.time(), custom_cooldown)


async def check_cd_and_warn(
    event: Union[types.Message, types.CallbackQuery],
    action: str,
    custom_cd: int = 30,
    ignore_admin_bypass: bool = False,
    *,
    user_cd: int | None = None,
    chat_cd: int | None = None,
    silent_in_groups: bool = False,
    delete_source_on_cd: bool = False,
    response_mode: str = "ephemeral",
) -> bool:
    if isinstance(event, types.CallbackQuery):
        chat = event.message.chat if event.message else None
    else:
        chat = event.chat

    is_group_chat = bool(chat and chat.type in ["group", "supergroup"])
    chat_id = chat.id if chat else None

    if user_cd is not None or chat_cd is not None:
        cd = await is_on_scoped_cooldown(
            user_id=event.from_user.id,
            action=action,
            user_cooldown=user_cd or 0,
            chat_id=chat_id,
            chat_cooldown=chat_cd or 0,
            ignore_admin_bypass=ignore_admin_bypass,
        )
    else:
        cd = await is_on_cooldown(
            event.from_user.id,
            action,
            custom_cd,
            ignore_admin_bypass=ignore_admin_bypass,
        )

    if not cd:
        return False

    if delete_source_on_cd and is_group_chat and isinstance(event, types.Message):
        try:
            await event.delete()
        except Exception:
            pass

    if isinstance(event, types.CallbackQuery):
        if response_mode == "silent" and silent_in_groups and is_group_chat:
            await event.answer()
            return True
        await event.answer(
            f"⏳ Подожди {cd} сек.",
            show_alert=(response_mode == "alert"),
        )
        return True

    if response_mode == "silent" and silent_in_groups and is_group_chat:
        return True

    msg = await event.answer(
        f"⏳ <b>Подожди!</b> Это действие остывает. Осталось {cd} сек.",
        parse_mode="HTML",
    )
    if response_mode == "ephemeral":
        schedule_delete_once(msg, 3)
    return True


def schedule_delete_once(message: types.Message, delay: int):
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    message_id = getattr(message, "message_id", None)
    if chat_id is None or message_id is None:
        spawn_bg(delete_after(message, delay), name="delete_after:nochat")
        return

    key = (chat_id, message_id)
    if key in _PENDING_DELETES:
        return
    _PENDING_DELETES.add(key)

    async def _runner():
        try:
            await delete_after(message, delay)
        finally:
            _PENDING_DELETES.discard(key)

    spawn_bg(_runner(), name=f"delete_after:{chat_id}:{message_id}")


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
    schedule_delete_once(msg, delay)
    return msg


async def reply_and_forget(
    message: types.Message,
    text: str,
    *,
    ttl: int = TTL_GAME,
    delete_source: bool = False,
    **kwargs,
) -> types.Message | None:
    """Send a reply and schedule both it and (optionally) the source command
    for auto-delete after ``ttl`` seconds.

    - `ttl`: one of TTL_ERROR / TTL_GAME / TTL_HEAVY_GAME / TTL_MENU, or custom.
    - `delete_source=True`: also schedule deletion of the original user command
      (only effective in groups; in DMs the bot cannot clean user messages).
    - Safe to call with optional extra aiogram `answer()` kwargs.
    """
    try:
        msg = await message.answer(text, **kwargs)
    except Exception as e:
        logging.debug(f"reply_and_forget: answer failed: {e}")
        return None
    if ttl and ttl > 0:
        schedule_delete_once(msg, ttl)
    is_group = getattr(getattr(message, "chat", None), "type", None) in ("group", "supergroup")
    if delete_source and is_group:
        schedule_delete_once(message, ttl)
    return msg


async def cb_warn(
    callback: types.CallbackQuery,
    text: str,
    *,
    alert: bool = False,
) -> None:
    """Warn user via callback answer popup, without polluting the chat.
    Use for cooldown/permission denials on inline buttons.
    """
    try:
        await callback.answer(text, show_alert=alert)
    except Exception as e:
        logging.debug(f"cb_warn: callback.answer failed: {e}")


async def maybe_ephemeral_reply(
    target: Union[types.Message, types.CallbackQuery],
    text: str,
    delay: int = 3,
    **kwargs,
):
    if isinstance(target, types.CallbackQuery):
        await target.answer(text, show_alert=False)
        return None

    msg = await target.answer(text, **kwargs)
    schedule_delete_once(msg, delay)
    return msg


async def send_or_edit_quiet(
    target: Union[types.Message, types.CallbackQuery],
    text: str,
    **kwargs,
) -> types.Message:
    if isinstance(target, types.CallbackQuery):
        return await safe_edit_or_reply(target, text, **kwargs)
    return await target.answer(text, **kwargs)


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


def parse_duration(text: str) -> int | None:
    """Parse duration like '30s', '5m', '2h', '7d' into seconds. Returns None on invalid.

    Supported suffixes: s(seconds), m(minutes), h(hours), d(days).
    Plain number = minutes for convenience: '15' → 15 minutes.
    """
    if not text:
        return None
    text = text.strip().lower()
    if not text:
        return None
    # pure number → minutes
    if text.isdigit():
        return int(text) * 60
    suffix = text[-1]
    try:
        value = int(text[:-1])
    except ValueError:
        return None
    if value <= 0:
        return None
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if suffix not in multipliers:
        return None
    return value * multipliers[suffix]


def humanize_duration(seconds: int) -> str:
    """Render seconds as '5м', '2ч 30м', '1д 4ч' for user-facing messages."""
    if seconds <= 0:
        return "0с"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if minutes:
        parts.append(f"{minutes}м")
    if secs and not parts:
        parts.append(f"{secs}с")
    return " ".join(parts) or f"{seconds}с"


async def is_moderator(
    bot,
    chat_id: int,
    user_id: int,
) -> bool:
    """True if user is creator/administrator in this chat, OR a global bot admin."""
    # Global bot admins bypass chat admin requirement.
    if user_id in await _get_admins_cached():
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("creator", "administrator")
    except Exception:
        return False


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
