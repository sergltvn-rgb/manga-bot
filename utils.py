# -*- coding: utf-8 -*-
import asyncio
import time
import random
from typing import Union
from aiogram import types
from database import get_admins

COOLDOWNS: dict = {}

async def is_on_cooldown(user_id: int, action: str = "global", custom_cooldown: int = 30) -> int:
    admins = await get_admins()
    if user_id in admins: return 0
    now = time.time()
    
    # Simple cleanup
    if random.random() < 0.05: 
        expired_keys = [k for k, v in COOLDOWNS.items() if now - v > 60]
        for k in expired_keys: COOLDOWNS.pop(k, None)

    key = f"{user_id}_{action}"
    if key in COOLDOWNS:
        elapsed = now - COOLDOWNS[key]
        if elapsed < custom_cooldown:
            return int(custom_cooldown - elapsed)
    COOLDOWNS[key] = now
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
    try: await message.delete()
    except: pass

async def temp_reply(message: types.Message, text: str, delay: int = 5, **kwargs):
    msg = await message.answer(text, **kwargs)
    asyncio.create_task(delete_after(msg, delay))
