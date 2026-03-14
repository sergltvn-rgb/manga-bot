# -*- coding: utf-8 -*-
import re
from aiogram import Router, types, F
from typing import Union
import time
import asyncio
import aiohttp
from database import update_rp_stat, get_admins

rp_router = Router()

RP_ACTIONS = {
    # Существующие SFW
    "обнять": ("hugs", "🤗", "тепло обнял(а)"),
    "поцеловать": ("kisses", "😘", "нежно поцеловал(а)"),
    "кусь": ("bites", "🧛‍♀️", "сделал(а) кусь"),
    "ударить": ("slaps", "😠", "дал(а) пощечину"),
    "погладить": ("pats", "🥰", "ласково погладил(а) по голове"),
    "пнуть": ("slaps", "🥾", "сильно пнул(а)"),
    "лизнуть": ("kisses", "👅", "лизнул(а)"),
    "убить": ("slaps", "💀", "жестоко убил(а)"),
    "воскресить": ("hugs", "👼", "чудесно воскресил(а)"),
    "пожать": ("pats", "🤝", "пожал(а) руку"),
    "пощекотать": ("pats", "🪶", "пощекотал(а)"),
    "тыкнуть": ("pats", "👈", "тыкнул(а) пальцем в"),
    "покормить": ("hugs", "🍲", "покормил(а)"),
    "прижаться": ("hugs", "🫂", "крепко прижался(ась) к"),
    "посмеяться": ("hugs", "😂", "посмеялся(ась) над"),
    "поплакать": ("hugs", "😭", "поплакал(а) на плече у"),
    "смущаться": ("hugs", "😳", "засмущался(ась) из-за"),
    "пять": ("pats", "✋", "дал(а) пять"),
    "улыбнуться": ("hugs", "😊", "мило улыбнулся(ась)"),
    "станцевать": ("hugs", "💃", "станцевал(а) с"),
    # Новые 18+ (NSFW)
    "трахаться": ("kisses", "🔞", "жестко трахнул(а)"),
    "секс": ("kisses", "🔞", "занялся(ась) сексом с"),
    "минет": ("kisses", "🔞", "сделал(а) минет"),
    "отсосать": ("kisses", "🔞", "отсосал(а) у"),
    "спать вместе": ("hugs", "🛌", "лёг(ла) спать вместе с")
}

# Эндпоинты nekos.best для аниме-гифок
NEKOS_ENDPOINTS = {
    "обнять":    "hug",
    "поцеловать":"kiss",
    "кусь":      "bite",
    "ударить":   "slap",
    "погладить": "pat",
    "пнуть":     "kick",
    "лизнуть":   "lick",
    "убить":     "shoot",
    "воскресить":"wave",
    "пожать":    "handshake",
    "пощекотать":"tickle",
    "тыкнуть":   "poke",
    "покормить": "feed",
    "прижаться": "cuddle",
    "посмеяться":"laugh",
    "поплакать": "cry",
    "смущаться": "blush",
    "пять":      "highfive",
    "улыбнуться":"smile",
    "станцевать":"dance",
}

# Эндпоинты PurrBot (SFW / NSFW)
PURR_ENDPOINTS = {
    "трахаться": "nsfw/fuck",
    "секс": "nsfw/fuck",
    "минет": "nsfw/blowjob",
    "отсосать": "nsfw/blowjob",
    "спать вместе": "sfw/lay",
}

async def get_rp_gif(action: str) -> str | None:
    # 1. Сначала проверяем PurrBot (для 18+ и сна)
    if action in PURR_ENDPOINTS:
        endpoint = PURR_ENDPOINTS[action]
        url = f"https://api.purrbot.site/v2/img/{endpoint}/gif"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    data = await resp.json()
                    return data.get("link")
        except Exception:
            pass

    # 2. Потом Nekos.best (стандартные SFW)
    endpoint = NEKOS_ENDPOINTS.get(action)
    if not endpoint: return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://nekos.best/api/v2/{endpoint}", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                return data["results"][0]["url"]
    except Exception:
        return None

# Сортировка по длине в обратном порядке для предотвращения багов частичного маппинга (например "спать" vs "спать вместе")
keys_sorted = sorted(RP_ACTIONS.keys(), key=len, reverse=True)
REGEX_RP = re.compile(r'(?i)^[/*\s]*(' + '|'.join(keys_sorted) + r')')

# Временно дублируем функцию COOLDOWN из `bot.py` для корректной работы здесь (или выносим в отдельный `utils.py`)
# Для простоты, перенесем её сюда:
from utils import is_on_cooldown, check_cd_and_warn, delete_after, temp_reply

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
    await update_rp_stat(user1.id, stat_type)
    
    caption = f"{emoji} {user1.mention_html()} {text_act} {user2.mention_html()}"
    gif_url = await get_rp_gif(action_key)
    if gif_url:
        await message.answer_animation(animation=gif_url, caption=caption, parse_mode="HTML")
    else:
        await message.answer(caption, parse_mode="HTML")
