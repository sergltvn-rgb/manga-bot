# -*- coding: utf-8 -*-
import asyncio
import time
from typing import Union
from aiogram import types
from database import get_admins

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
