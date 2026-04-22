# -*- coding: utf-8 -*-
import html
import re
import logging
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Union
import time
import asyncio
import aiohttp
from database import update_rp_stat, get_admins, get_user_profile_by_username

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
    "спать вместе": ("hugs", "🛌", "лёг(ла) спать вместе с"),
    # Новые 18+ (NSFW) - ТОЛЬКО ДЛЯ АДМИНОВ
    "трахаться": ("kisses", "🔞", "жестко трахнул(а)"),
    "трахнуть": ("kisses", "🔞", "трахнул(а)"),
    "секс": ("kisses", "🔞", "занялся(ась) сексом с"),
    "минет": ("kisses", "🔞", "сделал(а) минет"),
    "отсосать": ("kisses", "🔞", "отсосал(а) у"),
    "сосать": ("kisses", "🔞", "отсосал(а) у"),
    "соблазнить": ("kisses", "🔞", "соблазнил(а)"),
    "заняться любовью": ("kisses", "🔞", "страстно занялся(ась) любовью с"),
    "жестко взять": ("kisses", "🔞", "жестко взял(а)"),
    "поласкать": ("kisses", "🔞", "нежно поласкал(а)"),
    "глубокий минет": ("kisses", "🔞", "сделал(а) глубокий минет"),
    "сделать приятно": ("kisses", "🔞", "сделал(а) приятно")
}

RP_18PLUS = [
    "трахаться", "трахнуть", "секс", "минет", "отсосать", "сосать",
    "соблазнить", "заняться любовью", "жестко взять", "поласкать",
    "глубокий минет", "сделать приятно",
]

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
    "трахнуть": "nsfw/fuck",
    "секс": "nsfw/fuck",
    "соблазнить": "nsfw/fuck",
    "заняться любовью": "nsfw/fuck",
    "жестко взять": "nsfw/fuck",
    "минет": "nsfw/blowjob",
    "отсосать": "nsfw/blowjob",
    "сосать": "nsfw/blowjob",
    "поласкать": "nsfw/blowjob",
    "глубокий минет": "nsfw/blowjob",
    "сделать приятно": "nsfw/blowjob",
    "спать вместе": "sfw/lay",
}

async def get_rp_gif(action: str) -> str | None:
    # Переиспользуем глобальную сессию из bot.py
    from bot import get_http_session
    session = await get_http_session()
    
    # 1. Сначала проверяем PurrBot (для 18+ и сна)
    if action in PURR_ENDPOINTS:
        endpoint = PURR_ENDPOINTS[action]
        url = f"https://api.purrbot.site/v2/img/{endpoint}/gif"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                return data.get("link")
        except Exception:
            pass

    # 2. Потом Nekos.best (стандартные SFW)
    endpoint = NEKOS_ENDPOINTS.get(action)
    if not endpoint: return None
    try:
        async with session.get(f"https://nekos.best/api/v2/{endpoint}", timeout=aiohttp.ClientTimeout(total=5)) as resp:
            data = await resp.json()
            return data["results"][0]["url"]
    except Exception:
        return None

# Сортировка по длине в обратном порядке для предотвращения багов частичного маппинга (например "спать" vs "спать вместе")
keys_sorted = sorted(RP_ACTIONS.keys(), key=len, reverse=True)
REGEX_RP = re.compile(r'(?i)^[/*\s]*(' + '|'.join(keys_sorted) + r')(?:\s+(.+))?$')

from utils import is_on_cooldown, check_cd_and_warn, delete_after, temp_reply, reply_and_forget, TTL_GAME, TTL_ERROR
MAX_GROUP_TARGETS = 5


def build_rp_gif_keyboard(owner_id: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🙈 Скрыть GIF", callback_data=f"rp_hide_gif:{owner_id}")
    return builder.as_markup()


async def extract_mentioned_targets(message: types.Message) -> list[tuple[int, bool, str]]:
    """Resolve @mentions and text_mention entities to unique target tuples: (id, is_bot, mention_html)."""
    if not message.text or not message.entities:
        return []

    targets: dict[int, tuple[bool, str]] = {}
    mention_usernames: list[str] = []
    for ent in message.entities:
        if ent.type == "text_mention" and ent.user:
            user = ent.user
            targets[user.id] = (bool(user.is_bot), user.mention_html())
        elif ent.type == "mention":
            username = message.text[ent.offset:ent.offset + ent.length]
            if username:
                mention_usernames.append(username.lower())

    for username in dict.fromkeys(mention_usernames):
        profile = await get_user_profile_by_username(username)
        if not profile:
            continue
        uid, uname, fname = profile
        is_bot = False
        name = fname or uname or str(uid)
        mention_html = f'<a href="tg://user?id={uid}">{html.escape(name, quote=False)}</a>'
        targets[uid] = (is_bot, mention_html)

    return [(uid, is_bot, mention_html) for uid, (is_bot, mention_html) in targets.items()]


async def can_manage_rp_hide(callback: types.CallbackQuery, owner_id: int) -> bool:
    uid = callback.from_user.id
    if uid == owner_id:
        return True

    admins = await get_admins()
    if uid in admins:
        return True

    if callback.message and callback.message.chat.type in ["group", "supergroup"]:
        try:
            member = await callback.bot.get_chat_member(callback.message.chat.id, uid)
            if member.status in ["creator", "administrator"]:
                return True
        except Exception:
            pass
    return False


@rp_router.callback_query(F.data.startswith("rp_hide_gif:"))
async def rp_hide_gif_callback(callback: types.CallbackQuery):
    try:
        owner_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return await callback.answer("Некорректная кнопка.", show_alert=True)

    if not await can_manage_rp_hide(callback, owner_id):
        return await callback.answer("Только автор команды или админ может скрыть GIF.", show_alert=True)

    msg = callback.message
    # InaccessibleMessage (сообщение старше 48ч) не имеет полей animation/caption.
    if not isinstance(msg, types.Message):
        return await callback.answer("Сообщение слишком старое, скрыть не получится.", show_alert=True)
    if not getattr(msg, "animation", None):
        return await callback.answer("Здесь нет GIF для скрытия.", show_alert=True)
    if msg.animation.has_spoiler:
        return await callback.answer("GIF уже скрыта 🙈")

    caption_text = msg.caption or ""
    try:
        # 1) Preferred path: hide current media in-place (keeps message position).
        await msg.edit_media(
            media=types.InputMediaAnimation(
                media=msg.animation.file_id,
                caption=caption_text,
                has_spoiler=True,
            ),
            reply_markup=None,
        )
        return await callback.answer("GIF скрыта.")
    except Exception as e:
        # 2) Fallback: resend as spoiler and delete old message.
        logging.warning(f"rp_hide_gif: edit_media failed, fallback to resend. err={e}")

    try:
        sent = await callback.bot.send_animation(
            chat_id=msg.chat.id,
            animation=msg.animation.file_id,
            caption=caption_text,
            has_spoiler=True,
        )
        try:
            await msg.delete()
        except Exception as de:
            logging.warning(f"rp_hide_gif: old message delete failed after resend. err={de}")
        return await callback.answer("GIF скрыта.")
    except Exception as e2:
        logging.warning(f"rp_hide_gif: resend spoiler failed, fallback to text. err={e2}")

    try:
        # 3) Last-resort fallback: remove GIF and keep only text.
        await msg.delete()
    except Exception as de2:
        logging.warning(f"rp_hide_gif: delete for text fallback failed. err={de2}")
        return await callback.answer("Не получилось скрыть GIF. Попробуйте позже.", show_alert=True)

    try:
        text_msg = "🙈 GIF скрыта."
        if caption_text:
            text_msg += f"\n\n{caption_text}"
        await callback.bot.send_message(chat_id=msg.chat.id, text=text_msg)
        await callback.answer("GIF скрыта (текстовый режим).")
    except Exception as e3:
        logging.warning(f"rp_hide_gif: text fallback send failed. err={e3}")
        await callback.answer("Не получилось скрыть GIF. Попробуйте позже.", show_alert=True)

@rp_router.message(F.text & F.text.regexp(REGEX_RP))
async def rp_commands(message: types.Message):
    match = REGEX_RP.search(message.text)
    if not match: return
    action_key = match.group(1).lower()
    custom_text = match.group(2) if len(match.groups()) > 1 else None
            
    # Проверка на 18+ ограничение (Только для админов)
    if action_key in RP_18PLUS:
        admins = await get_admins()
        if message.from_user.id not in admins:
            return await temp_reply(message, "🔞 18+ действия доступны только администраторам бота!", delay=5)

    if await check_cd_and_warn(message, "rp_commands", 3): return

    user1 = message.from_user
    targets: list[tuple[int, bool, str]] = []
    if message.reply_to_message:
        user2 = message.reply_to_message.from_user
        targets = [(user2.id, bool(user2.is_bot), user2.mention_html())]
    else:
        targets = await extract_mentioned_targets(message)
        if not targets:
            return await temp_reply(
                message,
                f"ℹ️ Ответьте на сообщение пользователя или укажите до {MAX_GROUP_TARGETS} @username."
            )

    unique_targets: list[tuple[int, bool, str]] = []
    seen_ids: set[int] = set()
    for uid, is_bot, mention_html in targets:
        if uid in seen_ids:
            continue
        seen_ids.add(uid)
        if uid == user1.id:
            continue
        if is_bot:
            continue
        unique_targets.append((uid, is_bot, mention_html))

    if not unique_targets:
        return await temp_reply(message, "Нужны реальные цели: не вы сами и не боты 🤖")
    if len(unique_targets) > MAX_GROUP_TARGETS:
        return await temp_reply(message, f"Слишком много целей. Максимум: {MAX_GROUP_TARGETS}.")

    stat_type, emoji, text_act = RP_ACTIONS[action_key]
    for _ in unique_targets:
        await update_rp_stat(user1.id, stat_type)
    
    if len(unique_targets) == 1:
        caption = f"{emoji} {user1.mention_html()} {text_act} {unique_targets[0][2]}"
    else:
        targets_list = "\n".join(f"• {mention_html}" for _, _, mention_html in unique_targets)
        caption = (
            f"{emoji} {user1.mention_html()} применил(а) действие "
            f"«{html.escape(action_key, quote=False)}» к группе:\n{targets_list}"
        )

    if custom_text:
        cleaned_custom = re.sub(r'@\w+', '', custom_text).strip()
        if cleaned_custom:
            caption += f"\n💬 <i>«{html.escape(cleaned_custom, quote=False)}»</i>"
        
    gif_url = await get_rp_gif(action_key)
    if gif_url:
        await message.answer_animation(
            animation=gif_url,
            caption=caption,
            parse_mode="HTML",
            has_spoiler=(action_key in RP_18PLUS),
            reply_markup=build_rp_gif_keyboard(user1.id),
        )
    else:
        # Text fallback когда не смогли получить GIF — автоудаляем через TTL_GAME.
        await reply_and_forget(message, caption, ttl=TTL_GAME, parse_mode="HTML")
