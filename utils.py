# -*- coding: utf-8 -*-
import asyncio
import time
from typing import Union
from aiogram import types
from database import get_admins
import hmac
import hashlib
from urllib.parse import parse_qsl

# Кэш кулдаунов: key -> (timestamp, cooldown_duration)
COOLDOWNS: dict = {}

# Кэш админов: обновляется раз в 60 секунд
_ADMINS_CACHE: set = set()
_ADMINS_CACHE_TS: float = 0.0
_ADMINS_CACHE_TTL: float = 60.0

# Счётчик вызовов для периодической очистки COOLDOWNS
_call_counter: list = [0]  # список для мутабельности без global
_CLEANUP_EVERY: int = 50  # раз в 50 вызовов

async def _get_admins_cached() -> set:
    """Возвращает список админов с TTL-кэшем, чтобы не ходить в БД на каждый запрос."""
    global _ADMINS_CACHE, _ADMINS_CACHE_TS
    now = time.monotonic()
    if now - _ADMINS_CACHE_TS > _ADMINS_CACHE_TTL:
        _ADMINS_CACHE = set(await get_admins())
        _ADMINS_CACHE_TS = now
    return _ADMINS_CACHE

def invalidate_admins_cache():
    """Сбросить кэш админов (вызывать после add_admin / remove_admin)."""
    global _ADMINS_CACHE_TS
    _ADMINS_CACHE_TS = 0.0

async def is_on_cooldown(user_id: int, action: str = "global", custom_cooldown: int = 30) -> int:
    global _call_counter

    if user_id in await _get_admins_cached():
        return 0

    now = time.time()

    # Детерминированная периодическая очистка устаревших записей
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
            msg = await event.answer(f"⏳ <b>Подожди!</b> Это действие остывает. Осталось {cd} сек.", parse_mode="HTML")
            asyncio.create_task(delete_after(msg, 3))
        return True
    return False

async def delete_after(message: types.Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except:
        pass

async def temp_reply(message: types.Message, text: str, delay: int = 5, **kwargs):
    msg = await message.answer(text, **kwargs)
    asyncio.create_task(delete_after(msg, delay))

def validate_telegram_data(init_data: str, bot_token: str) -> dict | None:
    """Validate data received from Telegram Web App via HMAC-SHA256.
    Returns the parsed data dict if valid, else None."""
    try:
        if not init_data:
            return None
        parsed_data = dict(parse_qsl(init_data, keep_blank_values=True))
        if 'hash' not in parsed_data:
            return None
            
        hash_value = parsed_data.pop('hash')
        
        # Sort keys
        sorted_keys = sorted(parsed_data.keys())
        data_check_string = '\n'.join(f"{k}={parsed_data[k]}" for k in sorted_keys)
        
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if calculated_hash == hash_value:
            # Reattach hash for completeness (optional)
            parsed_data['hash'] = hash_value
            return parsed_data
        return None
    except Exception as e:
        import logging
        logging.error(f"Telegram data validation error: {e}")
        return None


async def run_git_sync(commit_message: str = "sync webapp db") -> tuple[bool, str]:
    """Асинхронная git-синхронизация: config → add → commit → push.
    Не блокирует Event Loop (использует asyncio.create_subprocess_shell).
    Возвращает (success: bool, output: str)."""
    commands = [
        "git config user.name 'MangaBot' && git config user.email 'bot@manga.local'",
        "git add webapp/chapters_data.json",
        f'git commit -m "{commit_message}"',
    ]
    for cmd in commands:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    # Push — именно его результат важен
    proc = await asyncio.create_subprocess_shell(
        "git push",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    output = (stderr.decode(errors="replace").strip()
              or stdout.decode(errors="replace").strip())
    return proc.returncode == 0, output


async def safe_edit_or_reply(
    target: Union[types.Message, types.CallbackQuery],
    text: str,
    **kwargs,
) -> types.Message:
    """Безопасно редактирует сообщение. Если edit_text падает
    (удалено, не изменилось и т.п.) — отправляет новое сообщение."""
    msg = target.message if isinstance(target, types.CallbackQuery) else target
    try:
        return await msg.edit_text(text, **kwargs)
    except Exception:
        try: await msg.delete()
        except Exception: pass
        return await msg.answer(text, **kwargs)
