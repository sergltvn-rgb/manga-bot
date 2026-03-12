# -*- coding: utf-8 -*-
import re
from aiogram import Router, types, F
from typing import Union
import time
import asyncio
from database import update_rp_stat, get_admins

rp_router = Router()

RP_ACTIONS = {
    "обнять": ("hugs", "🤗", "тепло обнял(а)"),
    "поцеловать": ("kisses", "😘", "нежно поцеловал(а)"),
    "кусь": ("bites", "🧛‍♀️", "сделал(а) кусь"),
    "ударить": ("slaps", "😠", "дал(а) пощечину"),
    "погладить": ("pats", "🥰", "ласково погладил(а) по голове"),
    "пнуть": ("slaps", "🥾", "сильно пнул(а)"),
    "лизнуть": ("kisses", "👅", "лизнул(а)"),
    "убить": ("slaps", "💀", "жестоко убил(а)"),
    "воскресить": ("hugs", "👼", "чудесно воскресил(а)"),
    "пожать": ("pats", "🤝", "пожал(а) руку")
}

RP_GIFS = {
    "обнять":    "https://media.tenor.com/6RqRlNxzWOsAAAAC/hug-anime.gif",
    "поцеловать":"https://media.tenor.com/C7EKFXvMViIAAAAC/kiss-anime.gif",
    "кусь":      "https://media.tenor.com/bPKGbEDIgUcAAAAC/anime-bite.gif",
    "ударить":   "https://media.tenor.com/F5kDa6JNFsEAAAAC/anime-slap.gif",
    "погладить": "https://media.tenor.com/xtcBj-PaScYAAAAC/anime-pat.gif",
    "пнуть":     "https://media.tenor.com/3JNaZs43FSIAAAAC/kick-anime.gif",
    "лизнуть":   "https://media.tenor.com/JdGT-HMy3AUAAAAC/lick-anime.gif",
    "убить":     "https://media.tenor.com/bfFaOjOy_-4AAAAC/kill-anime.gif",
    "воскресить":"https://media.tenor.com/Zx4aXE26nz8AAAAC/anime-healing.gif",
    "пожать":    "https://media.tenor.com/Yf_DxbKo4XIAAAAC/handshake-anime.gif",
}

REGEX_RP = re.compile(r'(?i)^[/*\s]*(' + '|'.join(list(RP_ACTIONS.keys())) + r')')

# Временно дублируем функцию COOLDOWN из `bot.py` для корректной работы здесь (или выносим в отдельный `utils.py`)
# Для простоты, перенесем её сюда:
COOLDOWNS = {}
async def delete_after(message: types.Message, delay: int):
    await asyncio.sleep(delay)
    try: await message.delete()
    except: pass

async def temp_reply(message: types.Message, text: str, delay: int = 5, **kwargs):
    msg = await message.answer(text, **kwargs)
    asyncio.create_task(delete_after(msg, delay))


async def is_on_cooldown(user_id: int, action: str = "global", custom_cooldown: int = 30) -> int:
    admins = await get_admins()
    if user_id in admins: return 0
    now = time.time()
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

@rp_router.message(F.text & F.text.regexp(REGEX_RP))
async def rp_commands(message: types.Message):
    if not message.reply_to_message:
        return await temp_reply(message, "ℹ️ Ответьте на сообщение другого пользователя!")
        
    match = REGEX_RP.search(message.text)
    if not match: return
    action_key = match.group(1).lower()
            
    user1, user2 = message.from_user, message.reply_to_message.from_user
    if user1.id == user2.id: return await temp_reply(message, "Ты не можешь применить это на себе!")
    if user2.is_bot: return await temp_reply(message, "Боты ничего не почувствуют 🤖")

    if await check_cd_and_warn(message, "rp_commands", 3): return

    stat_type, emoji, text_act = RP_ACTIONS[action_key]
    gif_url = RP_GIFS.get(action_key)
    await update_rp_stat(user1.id, stat_type)
    
    caption = f"{emoji} {user1.mention_html()} {text_act} {user2.mention_html()}"
    if gif_url:
        await message.answer_animation(animation=gif_url, caption=caption, parse_mode="HTML")
    else:
        await message.answer(caption, parse_mode="HTML")
