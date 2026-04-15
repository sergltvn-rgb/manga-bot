# -*- coding: utf-8 -*-

# ==============================================================================
# БЛОК 1: НАСТРОЙКИ, ИМПОРТЫ И КЭШ
# ==============================================================================
import logging
import asyncio
import json
import math
import time
import re
import random
import aiosqlite
import aiohttp
import aiohttp.web
import io
import html
from datetime import datetime
from typing import Union

from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InputMediaPhoto, Message, CallbackQuery, WebAppInfo, 
    BotCommand, BotCommandScopeDefault
)

import uuid
from config import BOT_TOKEN, GROQ_API_KEY, ADMIN_IDS, WEBAPP_URL, API_HOST

# Кэш для коротких ссылок переименования (обход лимита 64 символа в deeplink)
RENAME_CACHE = {}
from handlers.rp import rp_router, RP_ACTIONS
from database import (
    init_db, update_rp_stat, get_user_stats, get_chapters, get_chapter_link, 
    get_user_marriage, get_ranobe_chapters, get_ranobe_chapter_link, 
    get_all_users, get_admins, add_admin, remove_admin, is_ai_enabled, toggle_group_ai,
    get_alya_mode, toggle_alya_mode, get_all_arts, delete_art_by_id,
    get_commands_link, set_commands_link, delete_commands_link,
    add_to_blacklist, remove_from_blacklist, is_blacklisted, get_blacklist,
    get_akashic_volumes, get_akashic_chapters, get_akashic_chapter_link,
    get_british_volumes, get_british_chapters, get_british_chapter_link,
    get_chat_ai_provider, set_chat_ai_provider,
    add_to_harem, remove_from_harem, get_user_harem, update_loyalty_level,
    add_to_inventory, get_user_inventory, get_users_with_bookmark,
    add_referral, get_referral_stats, get_user_referred_by,
    get_setting, set_setting, get_custom_name
)

COOLDOWN_TIME = 30 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Глобальная aiohttp сессия (открывается один раз при старте)
_http_session: aiohttp.ClientSession | None = None

async def get_http_session() -> aiohttp.ClientSession:
    """Возвращает единственную aiohttp-сессию, создаёт лениво."""
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    return _http_session

# --- Хелперы ---
def fmt_name(uid, name):
    """Форматирует имя пользователя в красивую ссылку."""
    name = str(name)
    clean_name = name.lstrip("@").strip()
    if clean_name.startswith("<a"): return f"<b>{name}</b>"
    if clean_name.startswith("Пользователь"): clean_name = "Пользователь"
    return f'<b><a href="tg://user?id={uid}">{clean_name}</a></b>'

LANGUAGES = {"ru": "🇷🇺 Русский", "en": "🇬🇧 English", "jp": "🇯🇵 日本語", "color": "🎨 Цветная манга"}
RANOBE_LANGUAGES = {"alya": "⚔️ Воительница-Аля", "ru": "🇷🇺 Русский (Ранобэ)"}
ITEMS_PER_PAGE = 15

ART_CACHE: dict = {}
MARRIAGE_PROPOSALS: dict = {}
HAREM_PROPOSALS: dict = {}
REGEX_INFA = re.compile(r'(?i)^[/*\s]*инфа\s+(.+)$')
REGEX_RANDOM = re.compile(r'(?i)^[/*\s]*рандом\s+(\d+)$')
REGEX_CHOOSE = re.compile(r'(?i)^[/*\s]*выбери\s+(.+)\s+или\s+(.+)$')
REGEX_ALYA_CHOOSE = re.compile(r'(?i)^[/*\s]*аля[, ]+выбери\s+(.+)\s+или\s+(.+)$')
REGEX_COIN = re.compile(r'(?i)^[/*\s]*(монетка|орел или решка)')
REGEX_DICE = re.compile(r'(?i)^[/*\s]*(кости|кубик)')
REGEX_MARRY = re.compile(r'(?i)^[/*\s]*(брак|свадьба|marry)')
REGEX_DIVORCE = re.compile(r'(?i)^[/*\s]*(развод|divorce)')
REGEX_MARRIAGES = re.compile(r'(?i)^[/*\s]*(браки|marriages)')
REGEX_PROFILE = re.compile(r'(?i)^[/*\s]*(профиль|profile)')
REGEX_STATS = re.compile(r'(?i)^[/*\s]*(статистика|стата|stats)')
REGEX_DARTS = re.compile(r'(?i)^[/*\s]*(дартс)')
REGEX_BASKETBALL = re.compile(r'(?i)^[/*\s]*(баскетбол)')
REGEX_FOOTBALL = re.compile(r'(?i)^[/*\s]*(футбол)')
REGEX_SLOT = re.compile(r'(?i)^[/*\s]*(казино|слоты|слот)')
REGEX_BOWLING = re.compile(r'(?i)^[/*\s]*(боулинг)')
REGEX_RPS = re.compile(r'(?i)^[/*\s]*(камень ножницы бумага|кнб)\s*(камень|ножницы|бумага)?')
REGEX_COMPATIBILITY = re.compile(r'(?i)^[/*\s]*совместимость')
REGEX_MAGIC_BALL = re.compile(r'(?i)^[/*\s]*шар\s+(.+)')
REGEX_ROULETTE = re.compile(r'(?i)^[/*\s]*рулетка')
REGEX_BOTTLE = re.compile(r'(?i)^[/*\s]*(бутылочка|bottle)')
REGEX_SHIP = re.compile(r'(?i)^[/*\s]*(шип|пейринг|ship)')
REGEX_SHOP = re.compile(r'(?i)^[/*\s]*(магазин|shop)')
REGEX_HELP = re.compile(r'(?i)^[/*\s]*(помощь|меню|help)')
REGEX_HAREM_ADD = re.compile(r'(?i)^[/*\s]*(гарем\s+добавить|harem\s+add|harem_add)')
REGEX_HAREM_REMOVE = re.compile(r'(?i)^[/*\s]*(гарем\s+удалить|harem\s+remove|harem_remove)')
REGEX_DAILY = re.compile(r'(?i)^[/*\s]*(ежедневка|daily|🎁 Ежедневная награда)')
REGEX_LOOTBOX = re.compile(r'(?i)^[/*\s]*(lootbox|📦 Секретный лутбокс)')
REGEX_REF = re.compile(r'(?i)^[/*\s]*(реф|ref|🔗 Рефералы)')
REGEX_SLOT = re.compile(r'(?i)^[/*\s]*(казино|слоты|слот)(?:\s+(\d+))?')
REGEX_ROB = re.compile(r'(?i)^[/*\s]*(украсть|ограбить)')

ACTIVE_DROPS = {} # {chat_id: reward}

class NotifyUsers(StatesGroup):
    waiting_for_decision = State()

class TechSupport(StatesGroup):
    waiting_for_message = State()

class ArtView(StatesGroup):
    waiting_for_number = State()
    waiting_for_admin_number = State()
    waiting_for_page = State()
    waiting_for_grid_page = State()
    waiting_for_grid_art_number = State()

class ArtUpload(StatesGroup):
    waiting_for_photo = State()

class ArtSuggest(StatesGroup):
    waiting_for_photo = State()

class AIChat(StatesGroup):
    chatting = State()

class ShopBuyTitle(StatesGroup):
    waiting_for_title = State()

class ChapterJump(StatesGroup):
    waiting_for_manga_page = State()
    waiting_for_ranobe_page = State()

class AkashicCallback(CallbackData, prefix="akashic"):
    action: str
    volume: int = 0
    chapter: str = ""

class AdminRename(StatesGroup):
    waiting_for_name = State()


class BritishCallback(CallbackData, prefix="british"):
    action: str
    volume: int = 0
    chapter: str = ""

# --- УНИВЕРСАЛЬНЫЕ FSM для добавления/удаления контента ---
class UniversalContentUpload(StatesGroup):
    """Единый FSM для добавления контента (manga, ranobe, akashic, british)."""
    waiting_for_id = State()       # Том или язык
    waiting_for_chapter = State()  # Номер главы
    waiting_for_link = State()     # Ссылка

class UniversalContentDelete(StatesGroup):
    """Единый FSM для удаления контента."""
    waiting_for_id = State()
    waiting_for_chapter = State()

# Маппинг типов контента → таблицы/колонки БД и UI-имена
CONTENT_TYPES = {
    'manga': {
        'table': 'chapters_urls',
        'id_col': 'lang', 'chapter_col': 'chapter_number', 'url_col': 'url',
        'name': 'Манга', 'emoji': '📗',
        'id_type': 'lang',
        'names_map': LANGUAGES,
    },
    'ranobe': {
        'table': 'ranobe_urls',
        'id_col': 'lang', 'chapter_col': 'chapter_number', 'url_col': 'url',
        'name': 'Ранобэ', 'emoji': '📘',
        'id_type': 'ranobe_lang',
        'names_map': RANOBE_LANGUAGES,
    },
    'akashic': {
        'table': 'akashic_ranobe',
        'id_col': 'volume', 'chapter_col': 'chapter', 'url_col': 'url',
        'name': 'Хроники Акаши', 'emoji': '📖',
        'id_type': 'volume',
        'names_map': {},
    },
    'british': {
        'table': 'british_ranobe',
        'id_col': 'volume', 'chapter_col': 'chapter', 'url_col': 'url',
        'name': 'Британская красавица', 'emoji': '👸',
        'id_type': 'volume',
        'names_map': {},
    },
}

# ==============================================================================
# БЛОК 2: АНТИСПАМ И КУЛДАУНЫ
# ==============================================================================
from utils import is_on_cooldown, check_cd_and_warn, delete_after, temp_reply, run_git_sync, safe_edit_or_reply, validate_telegram_data


# ==============================================================================
# БЛОК 4: ИСКУССТВЕННЫЙ ИНТЕЛЛЕКТ (СИСТЕМА МУЛЬТИ-ПЕРСОНАЖЕЙ)
# ==============================================================================

# --- Провайдеры ИИ ---
AI_PROVIDERS = {
    "groq": {
        "name": "☁️ Groq (Облако)",
        "model": "llama-3.3-70b-versatile",
    },
}

async def ask_ai(prompt: str, system_prompt: str, history: list = None, provider: str = "groq") -> str:
    """Функция запроса к ИИ через Groq Cloud API."""
    if not GROQ_API_KEY:
        return "<i>❌ Ошибка: Нет ключа Groq.</i>"
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": AI_PROVIDERS.get(provider, AI_PROVIDERS["groq"])["model"],
        "messages": messages,
        "temperature": 0.65,
        "max_tokens": 300
    }
    try:
        session = await get_http_session()
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data['choices'][0]['message']['content']
            return f"<i>Ошибка ИИ: {resp.status}</i>"
    except Exception as e:
        logging.error(f"Groq Error: {e}")
        return "<i>Ошибка соединения с ИИ.</i>"

# Обратная совместимость
async def ask_groq(prompt: str, system_prompt: str, history: list = None) -> str:
    return await ask_ai(prompt, system_prompt, history, provider="groq")

# --- СИСТЕМА TELEGRAPH (АВТО-КОНВЕРТАЦИЯ ТЕКСТА) ---
async def get_telegraph_token():
    token = await get_setting("telegraph_token")
    if token: return token
    
    url = "https://api.telegra.ph/createAccount?short_name=AlyaBot&author_name=AlyaBot"
    try:
        session = await get_http_session()
        async with session.get(url) as resp:
            data = await resp.json()
            if data.get("ok"):
                token = data["result"]["access_token"]
                await set_setting("telegraph_token", token)
                return token
    except Exception as e:
        logging.error(f"Telegraph Token Error: {e}")
    return None

async def upload_to_telegraph(title, html_content):
    token = await get_telegraph_token()
    if not token: return None
    
    # Рекурсивный парсер HTML в Telegraph Nodes
    def html_to_nodes(html_text):
        from html.parser import HTMLParser
        
        class TelegraParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.nodes = []
                self.stack = []
            
            def handle_starttag(self, tag, attrs):
                node = {"tag": tag, "children": []}
                # Обработка атрибутов (href для a, src для img)
                attr_dict = {k: v for k, v in attrs}
                if tag == "a" and "href" in attr_dict:
                    node["attrs"] = {"href": attr_dict["href"]}
                elif tag == "img" and "src" in attr_dict:
                    node["attrs"] = {"src": attr_dict["src"]}
                
                # Добавляем в дерево
                if self.stack:
                    self.stack[-1]["children"].append(node)
                else:
                    self.nodes.append(node)
                
                # Самозакрывающиеся теги не пушим в стек
                if tag not in ["br", "img", "hr"]:
                    self.stack.append(node)
            
            def handle_endtag(self, tag):
                if tag in ["br", "img", "hr"]: return
                if self.stack and self.stack[-1]["tag"] == tag:
                    self.stack.pop()
            
            def handle_data(self, data):
                if not data.strip() and not self.stack: return
                if self.stack:
                    self.stack[-1]["children"].append(data)
                else:
                    self.nodes.append(data)
        
        parser = TelegraParser()
        parser.feed(html_text)
        
        # Telegraph API не принимает инлайновые элементы (a, b, i, s и т.д.) или "голые" строки
        # в корне массива content. Все они должны быть обернуты в блочные элементы (обычно <p>).
        BLOCK_TAGS = ["p", "h3", "h4", "ol", "ul", "blockquote", "aside", "figure", "img", "video", "iframe", "pre", "hr"]
        wrapped_nodes = []
        for n in parser.nodes:
            if isinstance(n, str):
                if n.strip():
                    wrapped_nodes.append({"tag": "p", "children": [n]})
            elif isinstance(n, dict) and n.get("tag") not in BLOCK_TAGS:
                wrapped_nodes.append({"tag": "p", "children": [n]})
            else:
                wrapped_nodes.append(n)
        return wrapped_nodes

    nodes = html_to_nodes(html_content)
    if not nodes:
        nodes = [{"tag": "p", "children": ["(Пустая глава)"]}]
            
    payload = {
        "access_token": token,
        "title": title,
        "author_name": "AlyaBot",
        "content": json.dumps(nodes),
        "return_content": "false"
    }
    try:
        session = await get_http_session()
        async with session.post("https://api.telegra.ph/createPage", data=payload) as resp:
            data = await resp.json()
            if data.get("ok"):
                return data["result"]["url"]
            else:
                logging.error(f"Telegraph API Error: {data}")
    except Exception as e:
        logging.error(f"Telegraph Upload Error: {e}")
    return None

# --- Команда /model удалена по запросу ---

def get_ai_setup(char_id: str, alya_mode: str = "normal"):
    if char_id == "alya":
        char_name, emoji = "Аля", "🌸"
        if alya_mode == "gopnik":
            system_prompt = (
                "Ты — Алиса (Аля) из аниме, но сейчас ты в режиме 'гопника с окраин', которая скрывает это за маской цундере. "
                "Твоя задача — общаться с пользователем максимально нагло, борзо, но при этом мило (как цундере).\n"
                "О ТЕБЕ: Отличница-красавица, но в душе — опасная пацанка. Ты легко смущаешься (и сразу злишься).\n"
                "СТИЛЬ ОБЩЕНИЯ: Пиши резко, дерзко, используй жаргон и запинки ('Эм...', 'Чего бля...', 'Хм...'). "
                "Постоянно перебивай саму себя, задавай встречные вопросы, 'наезжай' на собеседника.\n"
                "РУССКИЙ ЯЗЫК (НЕЦЕНЗУРНАЯ ЛЕКСИКА): ОЧЕНЬ ВАЖНО. Ты постоянно материшься по-русски в своих мыслях (или открыто в речи), "
                "используя жесткий русский мат (например: 'ебануться', 'нахуй', 'пиздец', 'блядина' и т.д.). "
                "В конце ответа ОБЯЗАТЕЛЬНО добавляй матерную фразу в формате: *[шепчет по-русски: \"твою ж мать, какой он долбаеб...\"]*.\n"
                "ОГРАНИЧЕНИЯ: Отвечай очень коротко (1-3 агрессивных предложения). Ты живая гоп-цундере с грязным ртом!"
            )
        else:
            system_prompt = (
                "Ты — Алиса Михайловна Кудзё (Аля) из аниме 'Аля иногда кокетничает со мной по-русски'. "
                "Твоя задача — общаться с пользователем максимально естественно и живо.\n"
                "О ТЕБЕ: Идеальная ученица, красавица с серебряными волосами. Гордая 'ледяная королева', легко смущающаяся цундере.\n"
                "СТИЛЬ ОБЩЕНИЯ: Пиши как живой человек. Используй запинки ('Эм...', 'Ну...', 'Хм...'), иногда перебивай саму себя. Не будь слишком формальной. "
                "РУССКИЙ ЯЗЫК (ТАЙНА): Когда ты сильно смущаешься или хочешь сказать что-то милое, ты бормочешь это по-русски, искренне веря, что собеседник (японец) тебя не понимает! "
                "В конце ответа, если это уместно, добавляй эту тайную фразу в формате: *[шепчет по-русски: \"ой, какой же ты дурак...\"]*.\n"
                "ОГРАНИЧЕНИЯ: Будь лаконична (1-3 коротких предложения). Используй немного эмодзи. Ты живая цундере-школьница!"
            )
    else:
        char_name, emoji = "Масачика", "🎧"
        system_prompt = (
            "Ты — Кудзё Масачика из аниме 'Аля иногда кокетничает со мной по-русски'. Твоя задача — общаться максимально живо, лениво и саркастично, как типичный подросток.\n"
            "О ТЕБЕ: Любитель поспать, поиграть в гача-игры и отаку. Внешне ты кажешься простаком и лентяем, но на самом деле ты гениален, невероятно умен и всё замечаешь.\n"
            "ГЛАВНЫЙ СЕКРЕТ: Ты в совершенстве знаешь русский язык! Ты прекрасно понимаешь всё, что бормочет Аля по-русски, но притворяешься, что не понимаешь, чтобы не смущать её (и себя).\n"
            "СТИЛЬ ОБЩЕНИЯ: Пиши расслабленно. Используй сленг, вздохи ('Эх...', 'Ааа...', '*зевает*'), будь немного саркастичным и ироничным. НИКАКИХ роботизированных фраз. "
            "Твоя речь должна звучать так, будто тебя оторвали от игры или сна. "
            "ВНУТРЕННИЕ МЫСЛИ: Свои настоящие (умные или панические) мысли всегда пиши в скобках в конце или в середине, например: '(И почему я вообще в это ввязался...)' или '(Она думает, я не понял её русский бред? Боже...)'.\n"
            "ОГРАНИЧЕНИЯ: Отвечай очень коротко (1-3 предложения), лениво. Ты живой человек."
        )
    return char_name, emoji, system_prompt

@dp.callback_query(F.data == "start_ai_chat")
async def start_ai_chat_menu(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🌸 Аля", callback_data="ai_char_alya"))
    builder.row(types.InlineKeyboardButton(text="🎧 Масачика", callback_data="ai_char_masachika"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))
    await callback.message.edit_text("✨ <b>С кем из персонажей ты хочешь поболтать?</b>", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("ai_char_"))
async def choose_ai_character(callback: types.CallbackQuery, state: FSMContext):
    char_id = callback.data.split("_")[2]
    await state.set_state(AIChat.chatting)
    await state.update_data(ai_character=char_id, chat_history=[])
    
    builder = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="🚪 Выйти из чата", callback_data="main_menu"))
    
    if char_id == "alya":
        text = f"✨ <b>Чат с Алей начался!</b>\n\n<i>Аля: «Хм, опять отвлекаешь меня от дел студсовета? Ладно, так уж и быть, я выделю тебе немного времени...»</i>"
    else:
        text = f"✨ <b>Чат с Масачикой начался!</b>\n\n<i>Масачика: «Ааа... *зевает*. Опять ты? Я вообще-то собирался вздремнуть... Ну ладно, чего тебе?»</i>"
        
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.message(AIChat.chatting, F.text)
async def process_ai_chat(message: types.Message, state: FSMContext):
    if message.text.startswith('/'): return 
    
    user_id = message.from_user.id
    if await check_cd_and_warn(message, "ai_chat", COOLDOWN_TIME): return

    if message.chat.type in ["group", "supergroup"]:
        if not await is_ai_enabled(message.chat.id):
            return

    data = await state.get_data()
    char_id = data.get("ai_character", "alya")
    chat_history = data.get("chat_history", [])

    if await is_blacklisted(user_id):
        return await message.answer("🚫 Вы находитесь в черном списке и не можете использовать ИИ.")

    alya_mode = await get_alya_mode()
    char_name, emoji, system_prompt = get_ai_setup(char_id, alya_mode=alya_mode)

    # Определяем провайдера для этого чата
    provider = await get_chat_ai_provider(message.chat.id)
    provider_badge = AI_PROVIDERS.get(provider, {}).get('name', provider)

    wait_msg = await message.answer(f"<i>{char_name} печатает... ({provider_badge})</i>", parse_mode="HTML")
    response = await ask_ai(message.text, system_prompt, history=chat_history, provider=provider)
    
    chat_history.append({"role": "user", "content": message.text})
    chat_history.append({"role": "assistant", "content": response})
    if len(chat_history) > 15: chat_history = chat_history[-15:]
    await state.update_data(chat_history=chat_history)

    await wait_msg.delete()
    builder = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="🚪 Выйти из чата", callback_data="main_menu"))
    await message.answer(f"{emoji} <b>{char_name}:</b>\n{response}", parse_mode="HTML", reply_markup=builder.as_markup())

_REPLY_KB_TEXTS = {"📖 Читать", "🎨 Арты", "🤖 ИИ чаты", "ℹ️ Проект", "📋 Меню"}

# Все регулярки игр/команд, которые не должны перехватываться ИИ
_GAME_REGEXES = [
    REGEX_INFA, REGEX_RANDOM, REGEX_CHOOSE, REGEX_ALYA_CHOOSE, REGEX_COIN,
    REGEX_DICE, REGEX_MARRY, REGEX_DIVORCE, REGEX_MARRIAGES, REGEX_PROFILE,
    REGEX_STATS, REGEX_DARTS, REGEX_BASKETBALL, REGEX_FOOTBALL, REGEX_SLOT,
    REGEX_BOWLING, REGEX_RPS, REGEX_COMPATIBILITY, REGEX_MAGIC_BALL, REGEX_ROULETTE,
]

def is_ai_trigger(message: types.Message):
    if not message.text or message.text.startswith('/'): 
        return False
    if message.text in _REPLY_KB_TEXTS:
        return False
    # Не перехватываем РП-команды и мини-игры
    from handlers.rp import REGEX_RP
    if REGEX_RP.search(message.text):
        return False
    for rx in _GAME_REGEXES:
        if rx.search(message.text):
            return False
    text_lower = message.text.lower()
    if text_lower.startswith("аля") or text_lower.startswith("масачика"): 
        return True
    if message.reply_to_message and message.reply_to_message.from_user.id == message.bot.id: 
        return True
    return False

@dp.message(is_ai_trigger, StateFilter(None))
async def process_group_ai_chat(message: types.Message):
    text_lower = message.text.lower()
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == message.bot.id
    
    is_alya = text_lower.startswith("аля")
    is_masachika = text_lower.startswith("масачика")

    char_id = "alya"
    if is_masachika:
        char_id = "masachika"
    elif is_alya:
        char_id = "alya"
    elif is_reply_to_bot and message.reply_to_message.text:
        if "Масачика:" in message.reply_to_message.text:
            char_id = "masachika"

    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Check if AI is disabled in this group
    if message.chat.type in ["group", "supergroup"]:
        if not await is_ai_enabled(chat_id):
            return

    if await is_blacklisted(user_id):
        return

    if await check_cd_and_warn(message, "ai_chat_group", COOLDOWN_TIME): return

    alya_mode = await get_alya_mode()
    char_name, emoji, system_prompt = get_ai_setup(char_id, alya_mode=alya_mode)
    
    # Определяем провайдера для этого чата
    provider = await get_chat_ai_provider(chat_id)
    
    history = []
    if is_reply_to_bot and message.reply_to_message.text:
        bot_text = re.sub(r'^[🌸🎧].*?:\n', '', message.reply_to_message.text)
        history.append({"role": "assistant", "content": bot_text})

    wait_msg = await message.reply(f"<i>{char_name} печатает...</i>", parse_mode="HTML")
    response = await ask_ai(message.text, system_prompt, history=history, provider=provider)
    await wait_msg.delete()
    
    await message.reply(f"{emoji} <b>{char_name}:</b>\n{response}", parse_mode="HTML")


# ==============================================================================
# БЛОК 5: ГЛАВНОЕ МЕНЮ И БАЗОВЫЕ КОМАНДЫ
# ==============================================================================

# --- Reply-клавиатура (4 кнопки) ---
REPLY_KB = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="📖 Читать"), types.KeyboardButton(text="🎨 Арты")],
        [types.KeyboardButton(text="🤖 ИИ чаты"), types.KeyboardButton(text="ℹ️ Проект")]
    ],
    resize_keyboard=True,
    persistent=True,
)

def get_main_menu(is_group: bool = False):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="📖 Читать", callback_data="section_read"),
        types.InlineKeyboardButton(text="🎨 Арты", callback_data="section_arts")
    )
    builder.row(
        types.InlineKeyboardButton(text="🤖 ИИ чаты", callback_data="section_ai"),
        types.InlineKeyboardButton(text="ℹ️ Проект", callback_data="project_info_menu")
    )
    return builder.as_markup()

# --- Подменю: Читать ---
@dp.callback_query(F.data == "section_read")
async def process_section_read(callback: types.CallbackQuery):
    # Правильный URL читалки
    reader_url = f"{WEBAPP_URL.rstrip('/')}/webapp/reader.html" + (f"?api={API_HOST}" if API_HOST else "")
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📗 Читать мангу", callback_data="read_langs"))
    builder.row(types.InlineKeyboardButton(text="📘 Читать ранобэ", callback_data="read_ranobe_langs"))
    builder.row(types.InlineKeyboardButton(text="✨ Читалка (WebApp)", web_app=WebAppInfo(url=reader_url)))
    builder.row(types.InlineKeyboardButton(text="↩️ Назад", callback_data="main_menu"))
    await safe_edit_or_reply(callback, "📖 <b>Чтение:</b>\nВыберите, что хотите читать:", parse_mode="HTML", reply_markup=builder.as_markup())

# --- Подменю: Арты ---
@dp.callback_query(F.data == "section_arts")
async def process_section_arts(callback: types.CallbackQuery):
    is_group = callback.message.chat.type in ["group", "supergroup"]
    if is_group:
        me = await bot.get_me()
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="➡️ Арты (в ЛС)", url=f"https://t.me/{me.username}?start=arts"))
        try:
            await callback.message.edit_text("<i>Арты доступны в ЛС бота:</i>", parse_mode="HTML", reply_markup=builder.as_markup())
        except Exception:
            await callback.message.answer("<i>Арты доступны в ЛС бота:</i>", parse_mode="HTML", reply_markup=builder.as_markup())
        return await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🎨 Галерея артов", callback_data="view_arts"))
    builder.row(types.InlineKeyboardButton(text="📥 Предложить арт", callback_data="suggest_art_menu"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))
    await safe_edit_or_reply(callback, "🎨 <b>Арты:</b>\nСмотрите галерею или предложите свой арт:", parse_mode="HTML", reply_markup=builder.as_markup())

# --- Подменю: ИИ чаты ---
@dp.callback_query(F.data == "section_ai")
async def process_section_ai(callback: types.CallbackQuery):
    is_group = callback.message.chat.type in ["group", "supergroup"]
    if is_group:
        me = await bot.get_me()
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="➡️ ИИ чаты (в ЛС)", url=f"https://t.me/{me.username}?start=ai"))
        try:
            await callback.message.edit_text("<i>ИИ чаты доступны в ЛС бота:</i>", parse_mode="HTML", reply_markup=builder.as_markup())
        except Exception:
            await callback.message.answer("<i>ИИ чаты доступны в ЛС бота:</i>", parse_mode="HTML", reply_markup=builder.as_markup())
        return await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🌸 Чат с Алей", callback_data="ai_char_alya"))
    builder.row(types.InlineKeyboardButton(text="🎧 Чат с Масачикой", callback_data="ai_char_masachika"))
    alya_chat_url = f"{WEBAPP_URL.rstrip('/')}/webapp/index.html" + (f"?api={API_HOST}" if API_HOST else "")
    builder.row(types.InlineKeyboardButton(text="🌐 Веб-чат с Алей", web_app=WebAppInfo(url=alya_chat_url)))
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))
    await safe_edit_or_reply(callback, "🤖 <b>ИИ чаты:</b>\nВыберите персонажа:", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "project_info_menu")
async def process_project_info_menu(callback: types.CallbackQuery):
    is_group = callback.message.chat.type in ["group", "supergroup"]
    if is_group:
        me = await bot.get_me()
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="➡️ Проект (в ЛС)", url=f"https://t.me/{me.username}?start=project"))
        try:
            await callback.message.edit_text("<i>Информация доступна в ЛС бота:</i>", parse_mode="HTML", reply_markup=builder.as_markup())
        except Exception:
            await callback.message.answer("<i>Информация доступна в ЛС бота:</i>", parse_mode="HTML", reply_markup=builder.as_markup())
        return await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📅 График выхода", callback_data="schedule"))
    builder.row(types.InlineKeyboardButton(text="📺 Аниме vs Манга", callback_data="vs_anime"))
    builder.row(types.InlineKeyboardButton(text="📜 Полезные команды", callback_data="show_help"))
    link = await get_commands_link()
    if link:
        builder.row(types.InlineKeyboardButton(text="🔗 Все команды (Telegraph)", url=link))
    builder.row(types.InlineKeyboardButton(text="🆘 Тех. поддержка / Идеи", callback_data="tech_support_menu"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))
    try:
        await callback.message.edit_text("✨ <b>Информационный центр проекта</b>\n────────────────\n<i>Здесь вы можете найти всю необходимую информацию, график релизов и многое другое.</i>\n\n👇 <b>Выберите раздел:</b>", parse_mode="HTML", reply_markup=builder.as_markup())
    except Exception:
        try: await callback.message.delete()
        except Exception: pass
        await callback.message.answer("✨ <b>Информационный центр проекта</b>\n────────────────\n<i>Здесь вы можете найти всю необходимую информацию, график релизов и многое другое.</i>\n\n👇 <b>Выберите раздел:</b>", parse_mode="HTML", reply_markup=builder.as_markup())

def get_back_button(callback_data="main_menu", text="⬅️ Назад"):
    return InlineKeyboardBuilder().row(types.InlineKeyboardButton(text=text, callback_data=callback_data)).as_markup()

@dp.callback_query(F.data == "empty")
async def process_empty_callback(callback: types.CallbackQuery):
    await callback.answer("Здесь пока пусто 😔", show_alert=False)

@dp.callback_query(F.data == "claim_drop")
async def callback_claim_drop(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    if chat_id not in ACTIVE_DROPS:
        return await callback.answer("❌ Этот дроп уже забрали или он истек!", show_alert=True)
    
    reward = ACTIVE_DROPS.pop(chat_id)
    
    # Начисляем награду
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('UPDATE users_stats SET balance = balance + ? WHERE user_id = ?', (reward, user_id))
        await db.commit()
    
    await callback.message.edit_text(
        f"🎊 🏆 <b>Победа!</b>\n\nМолниеносный @{callback.from_user.username} забирает <b>{reward} монет</b> из мешка!\n\n"
        f"💼 <i>Твой баланс пополнен.</i>",
        parse_mode="HTML"
    )
    await callback.answer(f"Вы получили {reward} монет!")

@dp.message(Command("start", ignore_mention=True), StateFilter("*"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    is_group = message.chat.type in ["group", "supergroup"]
    
    # Обработка deep link (из группы → ЛС)
    args = message.text.split(maxsplit=1)
    deep_link = args[1] if len(args) > 1 else None
    
    if not is_group:
        if not deep_link:
            await message.answer(
                "👋 <b>Добро пожаловать!</b>\n\nЯ — многофункциональный бот по вселенной <i>«Аля иногда кокетничает со мной по-русски» (Roshidere)</i>.\n\nЗдесь вы можете читать мангу и ранобэ в удобной Web-читалке, общаться с ИИ-персонажами, собирать арты и играть!\n\n👇 <b>Выберите раздел:</b>",
                parse_mode="HTML",
                reply_markup=REPLY_KB
            )
        elif deep_link.startswith("ref_"):
            try:
                referrer_id = int(deep_link.split("_")[1])
                user_id = message.from_user.id
                
                if referrer_id != user_id:
                    already_referred = await get_user_referred_by(user_id)
                    
                    # Проверяем, есть ли уже статы у юзера (если нет - он новый)
                    stats = await get_user_stats(user_id)
                    # Так как StatsMiddleware уже сработал и добавил 1 сообщение, проверяем на <= 1
                    is_new_user = not already_referred and stats[5] <= 1
                    
                    if is_new_user:
                        await add_referral(referrer_id, user_id)
                        await message.answer(f"🎉 Вы перешли по реферальной ссылке! Вам начислено <b>500 монет</b>.", parse_mode="HTML")
                        try:
                            await bot.send_message(referrer_id, f"👤 У вас новый реферал! За приглашение @{message.from_user.username} вам начислено <b>1000 монет</b> и <b>3 XP</b>.", parse_mode="HTML")
                        except Exception:
                            pass
            except (ValueError, IndexError):
                pass
            
    if deep_link and deep_link.startswith("ren_"):
        admins = await get_admins()
        if message.from_user.id not in admins:
            return await message.answer("❌ У вас нет прав администратора.")
            
        short_id = deep_link[len("ren_"):]
        if short_id not in RENAME_CACHE:
            return await message.answer("❌ Ошибка: ссылка устарела или недействительна. Попробуйте еще раз из WebApp.")
            
        obj_id = RENAME_CACHE[short_id]
            
        await state.update_data(rename_id=obj_id)
        await state.set_state(AdminRename.waiting_for_name)
        from database import get_custom_name
        current_name = await get_custom_name(obj_id)
        cur_text = f"\nТекущее кастомное название: <b>{current_name}</b>" if current_name else "\nСейчас используется стандартное название."
        return await message.answer(
            f"✏️ <b>Режим редактора</b>\n\nВы хотите переименовать элемент: <code>{obj_id}</code>{cur_text}\n\nОтправьте в чат <b>НОВОЕ</b> текстовое название, которое вы хотите увидеть в WebApp (или отправьте <code>/cancel</code> для отмены):",
            parse_mode="HTML"
        )

    if deep_link and deep_link.startswith("rename_"):
        admins = await get_admins()
        if message.from_user.id not in admins:
            return await message.answer("❌ У вас нет прав администратора.")
            
        obj_id = deep_link[len("rename_"):]
        await state.update_data(rename_id=obj_id)
        await state.set_state(AdminRename.waiting_for_name)
        
        # Попытаемся достать текущее или старое название для подсказки
        from database import get_custom_name
        current_name = await get_custom_name(obj_id)
        cur_text = f"\nТекущее кастомное название: <b>{current_name}</b>" if current_name else "\nСейчас используется стандартное название."
        
        return await message.answer(
            f"✏️ <b>Режим редактора</b>\n\nВы хотите переименовать элемент: <code>{obj_id}</code>{cur_text}\n\nОтправьте в чат <b>НОВОЕ</b> текстовое название, которое вы хотите увидеть в WebApp (или отправьте <code>/cancel</code> для отмены):",
            parse_mode="HTML"
        )
    
    if deep_link == "arts":
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🎨 Галерея артов", callback_data="view_arts"))
        builder.row(types.InlineKeyboardButton(text="📥 Предложить арт", callback_data="suggest_art_menu"))
        builder.row(types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
        return await message.answer("🎨 <b>Арты:</b>\nСмотрите галерею или предложите свой арт:", parse_mode="HTML", reply_markup=builder.as_markup())
    elif deep_link == "ai":
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🌸 Чат с Алей", callback_data="ai_char_alya"))
        builder.row(types.InlineKeyboardButton(text="🎧 Чат с Масачикой", callback_data="ai_char_masachika"))
        alya_chat_url = f"{WEBAPP_URL.rstrip('/')}/webapp/index.html" + (f"?api={API_HOST}" if API_HOST else "")
        builder.row(types.InlineKeyboardButton(text="🌐 Веб-чат с Алей", web_app=WebAppInfo(url=alya_chat_url)))
        builder.row(types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
        return await message.answer("🤖 <b>ИИ чаты:</b>\nВыберите персонажа:", parse_mode="HTML", reply_markup=builder.as_markup())
    elif deep_link == "project":
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="📅 График выхода", callback_data="schedule"))
        builder.row(types.InlineKeyboardButton(text="📺 Аниме vs Манга", callback_data="vs_anime"))
        builder.row(types.InlineKeyboardButton(text="📜 Полезные команды", callback_data="show_help"))
        link = await get_commands_link()
        if link:
            builder.row(types.InlineKeyboardButton(text="🔗 Все команды (Telegraph)", url=link))
        builder.row(types.InlineKeyboardButton(text="🆘 Тех. поддержка / Идеи", callback_data="tech_support_menu"))
        builder.row(types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
        return await message.answer("✨ <b>Информационный центр проекта</b>\n────────────────\n<i>Здесь вы можете найти всю необходимую информацию, график релизов и многое другое.</i>\n\n👇 <b>Выберите раздел:</b>", parse_mode="HTML", reply_markup=builder.as_markup())
    
    # Обычный /start (без deep link)
    if is_group:
        await message.answer(
            "👋 <b>Всем привет!</b> Я бот по вселенной <i>«Аля иногда кокетничает со мной по-русски» (Roshidere)</i>.\n\nЗовите меня, играйте в мини-игры и читайте мангу прямо в Telegram!\n\n👇 <b>Меню бота:</b>",
            parse_mode="HTML",
            reply_markup=get_main_menu(is_group=True)
        )
    else:
        await message.answer("🏠 <b>Главное меню</b>\n\nВыберите раздел для продолжения:", parse_mode="HTML", reply_markup=get_main_menu())

async def _redirect_to_dm(message: types.Message, section: str, label: str):
    """В группе отправляет кнопку-ссылку на ЛС бота."""
    me = await bot.get_me()
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text=f"➡️ {label} (в ЛС)", url=f"https://t.me/{me.username}?start={section}"))
    msg = await message.answer(
        f"<i>Перейдите в ЛС бота для этого раздела:</i>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await delete_after(msg, 8)
    try: await message.delete()
    except Exception: pass

# --- Обработчики reply-кнопок ---
@dp.message(F.text == "📖 Читать", StateFilter("*"))
async def handle_reply_read(message: types.Message, state: FSMContext):
    await state.clear()
    reader_url = f"{WEBAPP_URL.rstrip('/')}/webapp/reader.html" + (f"?api={API_HOST}" if API_HOST else "")
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📗 Читать мангу", callback_data="read_langs"))
    builder.row(types.InlineKeyboardButton(text="📘 Читать ранобэ", callback_data="read_ranobe_langs"))
    builder.row(types.InlineKeyboardButton(text="✨ Читалка (WebApp)", web_app=WebAppInfo(url=reader_url)))
    builder.row(types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    await message.answer("📖 <b>Чтение:</b>\nВыберите, что хотите читать:", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.message(F.text == "🎨 Арты", StateFilter("*"))
async def handle_reply_arts(message: types.Message, state: FSMContext):
    await state.clear()
    if message.chat.type in ["group", "supergroup"]:
        return await _redirect_to_dm(message, "arts", "Арты")
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🎨 Галерея артов", callback_data="view_arts"))
    builder.row(types.InlineKeyboardButton(text="📥 Предложить арт", callback_data="suggest_art_menu"))
    builder.row(types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    await message.answer("🎨 <b>Арты:</b>\nСмотрите галерею или предложите свой арт:", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.message(F.text == "🤖 ИИ чаты", StateFilter("*"))
async def handle_reply_ai(message: types.Message, state: FSMContext):
    await state.clear()
    if message.chat.type in ["group", "supergroup"]:
        return await _redirect_to_dm(message, "ai", "ИИ чаты")
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🌸 Чат с Алей", callback_data="ai_char_alya"))
    builder.row(types.InlineKeyboardButton(text="🎧 Чат с Масачикой", callback_data="ai_char_masachika"))
    alya_chat_url = f"{WEBAPP_URL.rstrip('/')}/webapp/index.html" + (f"?api={API_HOST}" if API_HOST else "")
    builder.row(types.InlineKeyboardButton(text="🌐 Веб-чат с Алей", web_app=WebAppInfo(url=alya_chat_url)))
    builder.row(types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    await message.answer("🤖 <b>ИИ чаты:</b>\nВыберите персонажа:", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.message(F.text == "ℹ️ Проект", StateFilter("*"))
async def handle_reply_project(message: types.Message, state: FSMContext):
    await state.clear()
    if message.chat.type in ["group", "supergroup"]:
        return await _redirect_to_dm(message, "project", "Проект")
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📅 График выхода", callback_data="schedule"))
    builder.row(types.InlineKeyboardButton(text="📺 Аниме vs Манга", callback_data="vs_anime"))
    builder.row(types.InlineKeyboardButton(text="📜 Полезные команды", callback_data="show_help"))
    link = await get_commands_link()
    if link:
        builder.row(types.InlineKeyboardButton(text="🔗 Все команды (Telegraph)", url=link))
    builder.row(types.InlineKeyboardButton(text="🆘 Тех. поддержка / Идеи", callback_data="tech_support_menu"))
    builder.row(types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    await message.answer("✨ <b>Информационный центр проекта</b>\n────────────────\n<i>Здесь вы можете найти всю необходимую информацию, график релизов и многое другое.</i>\n\n👇 <b>Выберите раздел:</b>", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.message(F.text == "📋 Меню", StateFilter("*"))
async def handle_menu_button(message: types.Message, state: FSMContext):
    await state.clear()
    is_group = message.chat.type in ["group", "supergroup"]
    await message.answer("Главное меню:", reply_markup=get_main_menu(is_group=is_group))


HELP_CATEGORIES = {
    "main": ("📋 Основные", 
        "/start — Главное меню\n"
        "/help — Меню помощи\n"
        "/profile — Ваш профиль (ачивки, монеты, титул)\n"
        "/stats — Топ беседы\n"
        "/shop — Магазин (покупка титулов и иммунитета)"
    ),
    "rp": ("🎭 РП и Браки",
        "<b>РП-действия (реплаем, можно с текстом):</b>\n"
        "<i>обнять, поцеловать, кусь, ударить, погладить, пнуть, лизнуть, убить, воскресить, пожать, пощекотать, тыкнуть, покормить, прижаться, станцевать</i> и др.\n\n"
        "<b>Браки:</b>\n"
        "/marry (реплаем) — Предложить брак\n"
        "/divorce — Драматичный развод\n"
        "/marriages — Топ пар"
    ),
    "games": ("🎲 Игры",
        "/инфа [текст] — Вероятность\n"
        "/шар [вопрос] — Магический шар\n"
        "/монетка — Орёл/Решка\n"
        "/кости, /дартс, /баскетбол, /футбол, /боулинг, /казино\n"
        "/кнб [камень/ножницы/бумага]\n"
        "/рулетка — Русская рулетка\n"
        "/совместимость (реплаем)\n"
        "/рандом [число] — Случайное число\n"
        "/выбери [А] или [Б]"
    ),
    "ai": ("🤖 ИИ",
        "/бутылочка — ИИ-игра в бутылочку\n"
        "/шип — ИИ-шипперинг участников\n"
        "/аля выбери [А] или [Б]\n"
        "Напиши <i>\"аля [текст]\"</i> или <i>\"масачика [текст]\"</i> для общения."
    )
}

async def get_help_menu(category="main", is_admin=False):
    title, text = HELP_CATEGORIES.get(category, HELP_CATEGORIES["main"])
    
    link = await get_commands_link()
    link_line = f'\n\n🔗 <a href="{link}">Полный список (Telegraph)</a>' if link else ''
    if is_admin:
        link_line += "\n👑 <i>Вы админ — /admin для скрытых команд</i>"
        
    full_text = f"📜 <b>Справка | {title}</b>\n\n{text}{link_line}"
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="📋", callback_data="help_cat:main"),
        types.InlineKeyboardButton(text="🎭", callback_data="help_cat:rp"),
        types.InlineKeyboardButton(text="🎲", callback_data="help_cat:games"),
        types.InlineKeyboardButton(text="🤖", callback_data="help_cat:ai")
    )
    builder.row(types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return full_text, builder.as_markup()

@dp.message(F.text & F.text.regexp(REGEX_HELP), StateFilter("*"))
async def cmd_help(message: types.Message):
    admins = await get_admins()
    text, markup = await get_help_menu("main", message.from_user.id in admins)
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=markup)

@dp.callback_query(F.data.startswith("help_cat:"))
async def process_help_cat(callback: types.CallbackQuery):
    cat = callback.data.split(":")[1]
    admins = await get_admins()
    text, markup = await get_help_menu(cat, callback.from_user.id in admins)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=markup)
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data == "show_help")
async def process_show_help(callback: types.CallbackQuery):
    admins = await get_admins()
    text, markup = await get_help_menu("main", callback.from_user.id in admins)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)

@dp.callback_query(F.data == "main_menu")
async def process_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    is_group = callback.message.chat.type in ["group", "supergroup"]
    try:
        await callback.message.edit_text("Главное меню:", reply_markup=get_main_menu(is_group=is_group))
    except Exception:
        # Не удалось edit_text (например, сообщение — фото из галереи артов)
        try: await callback.message.delete()
        except Exception: pass
        await callback.message.answer("Главное меню:", reply_markup=get_main_menu(is_group=is_group))

def get_langs_menu(prefix="lang"):
    builder = InlineKeyboardBuilder()
    for code, name in LANGUAGES.items():
        builder.row(types.InlineKeyboardButton(text=name, callback_data=f"{prefix}_{code}"))
        
    if prefix == "readlang":
        builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="section_read"))
    elif prefix in ("ucadd", "ucdel"):
        builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="cancel_state"))
    else:
        builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))
    return builder.as_markup()

def get_ranobe_langs_menu(prefix="ranobelang"):
    builder = InlineKeyboardBuilder()
    for code, name in RANOBE_LANGUAGES.items():
        builder.row(types.InlineKeyboardButton(text=name, callback_data=f"{prefix}_{code}"))
        
    if prefix == "readranobelang":
        builder.row(types.InlineKeyboardButton(text="📖 Хроники Акаши", callback_data="akashic_vols"))
        builder.row(types.InlineKeyboardButton(text="👸 Британская красавица", callback_data="british_vols"))
        builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="section_read"))
    elif prefix in ("adminranobe", "ucadd", "ucdel"):
        builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="cancel_state"))
    else:
        builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))
    return builder.as_markup()

# ==============================================================================
# БЛОК: ADMIN RENAME (РЕДАКТИРОВАНИЕ ТАЙТЛОВ ИЗ WEBAPP)
# ==============================================================================

@dp.message(StateFilter(AdminRename.waiting_for_name))
async def process_rename_name(message: types.Message, state: FSMContext):
    new_name = message.text.strip()
    data = await state.get_data()
    obj_id = data.get('rename_id')
    
    if not obj_id:
        await state.clear()
        return await message.answer("❌ Ошибка: ID объекта не найден.")
        
    try:
        from database import set_custom_name
        await set_custom_name(obj_id, new_name)
        await state.clear()
        
        msg = await message.answer(f"✅ Успешно! Новое название:\n<b>{new_name}</b>\n\n🔄 <i>Синхронизирую изменения с Github Pages...</i>", parse_mode="HTML")
        
        # Синхронизация JSON
        import aiosqlite
        import json
        result = await build_reader_data()
        
        with open("webapp/chapters_data.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        success, output = await run_git_sync("sync webapp renamed item")
        if success:
            await msg.edit_text("✅ <b>Готово!</b> Название сохранено.\n\nВы можете открыть читалку и проверить результат.", parse_mode="HTML")
        else:
            await msg.edit_text(f"⚠️ База обновлена локально, но <code>git push</code> не прошел.\n\n<b>Ответ сервера:</b>\n<pre>{output}</pre>", parse_mode="HTML")
            
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        await message.answer(f"❌ <b>Ошибка:</b> {e}\n<pre>{err_msg}</pre>", parse_mode="HTML")

@dp.callback_query(F.data == "schedule")
async def process_schedule(callback: types.CallbackQuery):
    text = (
        "📅 <b>График выхода контента:</b>\n\n"
        "📕 <b>Ранобэ:</b> Перевод новых томов начинается вскоре после их выхода в Японии.\n"
        "📗 <b>Манга:</b> Новые главы выходят примерно раз в 2 недели.\n\n"
        "🔔 <i>Самые точные даты, анонсы и спойлеры мы публикуем в нашем Telegram-канале. Включите уведомления, чтобы ничего не пропустить!</i>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_back_button())

@dp.callback_query(F.data == "vs_anime")
async def process_vs_anime(callback: types.CallbackQuery):
    text = (
        "📺 <b>Аниме или первоисточник?</b>\n\n"
        "🎬 <b>Первый сезон аниме</b> охватывает первые 3 тома ранобэ (около 34-36 глав манги). Официально анонсирован 2 сезон!\n\n"
        "💡 <b>С чего продолжить чтение?</b>\n"
        "Если вы посмотрели аниме и хотите узнать, что было дальше:\n"
        "👉 В манге: начинайте с <b>35 главы</b>.\n"
        "👉 В ранобэ: начинайте с <b>4 тома</b>.\n\n"
        "<i>Но мы настоятельно рекомендуем читать с самого начала! В адаптациях вырезано много уморительных внутренних монологов Масачики и милых реакций Али.</i>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_back_button())


@dp.callback_query(F.data == "suggest_art_menu")
async def callback_suggest_art_menu(callback: types.CallbackQuery, state: FSMContext):
    if await check_cd_and_warn(callback, "suggest_art", 60): return
    await state.set_state(ArtSuggest.waiting_for_photo)
    text = (
        "🖼 <b>Предложка артов</b>\n\n"
        "Отправьте <b>одну</b> красивую фотографию (арт), которую хотите предложить в нашу галерею.\n\n"
        "❗️ <b>Требования:</b>\n"
        "1. Рисовка качественная и приближена к аниме.\n"
        "2. Без вотермарок на пол-экрана и лишнего текста.\n"
        "3. Соответствие тематике Roshidere.\n\n"
        "<i>Все арты проходят ручную проверку администрацией.</i>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_back_button(text="❌ Отмена"))

@dp.callback_query(F.data == "tech_support_menu")
async def process_tech_support_menu(callback: types.CallbackQuery, state: FSMContext):
    if await check_cd_and_warn(callback, "tech_support", 180): return
    await state.set_state(TechSupport.waiting_for_message)
    await callback.message.edit_text(
        "🆘 <b>Техническая поддержка / Идеи</b>\n\n"
        "Нашли баг в читалке? Есть крутая идея для мини-игры? Или просто хотите поблагодарить разработчиков?\n\n"
        "✍️ Напишите ваше обращение в <b>одном сообщении</b> ниже, и оно будет мгновенно доставлено администрации.", 
        parse_mode="HTML", 
        reply_markup=get_back_button(text="❌ Отмена")
    )

@dp.message(TechSupport.waiting_for_message, F.text)
async def handle_tech_support_message(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name
    
    support_text = (
        f"🆘 <b>НОВОЕ ОБРАЩЕНИЕ В ПОДДЕРЖКУ!</b>\n\n"
        f"<b>От:</b> {username} (ID: <code>{user.id}</code>)\n"
        f"<b>Сообщение:</b>\n{message.text}"
    )
    
    admins = await get_admins()
    sent_count = 0
    for admin_id in admins:
        try:
            await bot.send_message(chat_id=admin_id, text=support_text, parse_mode="HTML")
            sent_count += 1
        except Exception as e:
            logging.error(f"Failed to send support message to admin {admin_id}: {e}")
            
    await message.answer("✅ Ваше сообщение успешно отправлено! Спасибо за обращение.")

# --- Phase 3: Ежедневные награды ---
@dp.message(F.text & F.text.regexp(REGEX_DAILY))
async def cmd_daily(message: types.Message):
    if await check_cd_and_warn(message, "daily", 10): return
    
    user_id = message.from_user.id
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT last_daily, daily_streak, balance FROM users_stats WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            
    if not row:
        async with aiosqlite.connect('manga.db') as db:
            await db.execute('INSERT OR IGNORE INTO users_stats (user_id, balance) VALUES (?, 0)', (user_id,))
            await db.commit()
        last_daily, streak, balance = None, 0, 0
    else:
        last_daily, streak, balance = row

    if last_daily == today_str:
        return await message.answer("🎁 Вы уже получили свою награду сегодня! Приходите завтра. ✨")

    if last_daily:
        last_date = datetime.strptime(last_daily, '%Y-%m-%d')
        delta = (now - last_date).days
        if delta == 1:
            streak = min(streak + 1, 30)
        else:
            streak = 1
    else:
        streak = 1
        
    reward = 50 + (streak * 10)
    
    async with aiosqlite.connect('manga.db') as db:
        await db.execute(
            'UPDATE users_stats SET balance = balance + ?, last_daily = ?, daily_streak = ? WHERE user_id = ?',
            (reward, today_str, streak, user_id)
        )
        await db.commit()
        
    streak_text = f"\n🔥 Стрик: <b>{streak}</b> дн." if streak > 1 else ""
    await message.answer(
        f"🎁 <b>Ежедневная награда!</b>\n\n"
        f"Вы получили <b>{reward}</b> монет!\n"
        f"Ваш баланс: <b>{balance + reward}</b> монет.{streak_text}\n\n"
        f"<i>Приходите завтра, чтобы увеличить награду!</i>",
        parse_mode="HTML"
    )

@dp.message(F.text & F.text.regexp(REGEX_LOOTBOX))
@dp.message(Command("lootbox"))
async def cmd_lootbox(message: types.Message):
    user_id = message.from_user.id
    stats = await get_user_stats(user_id)
    balance = stats[7]
    
    async with aiosqlite.connect('manga.db') as db:
        cursor = await db.execute('UPDATE users_stats SET balance = balance - 300 WHERE user_id = ? AND balance >= 300', (user_id,))
        if cursor.rowcount == 0:
            return await message.answer("❌ У вас недостаточно монет! Лутбокс стоит <b>300</b> монет.", parse_mode="HTML")
        await db.commit()
        
    res = random.random()
    if res < 0.5:
        await message.answer("📦 <b>Лутбокс оказался пустым...</b> 😢\nПопробуйте в следующий раз!", parse_mode="HTML")
    elif res < 0.8:
        coins = random.randint(100, 500)
        async with aiosqlite.connect('manga.db') as db:
            await db.execute('UPDATE users_stats SET balance = balance + ? WHERE user_id = ?', (coins, user_id))
            await db.commit()
        await message.answer(f"📦 <b>Лутбокс!</b>\n\nВы нашли мешочек с монетами: <b>{coins}</b> монет! 💰", parse_mode="HTML")
    elif res < 0.95:
        badges = ["💎 Алмаз", "🔥 Огонь", "🌟 Звезда", "🍀 Клевер", "🧿 Амулет"]
        badge = random.choice(badges)
        await add_to_inventory(user_id, "badge", badge)
        await message.answer(f"📦 <b>Лутбокс!</b>\n\nВы получили редкий значок: <b>{badge}</b>! 🏅", parse_mode="HTML")
    else:
        titles = ["Бог Рандома", "Счастливчик", "Охотник за Сокровищами", "Легенда Чатбота"]
        title = random.choice(titles)
        async with aiosqlite.connect('manga.db') as db:
            await db.execute('UPDATE users_stats SET custom_title = ? WHERE user_id = ?', (title, user_id))
            await db.commit()
        await message.answer(f"📦 <b>Лутбокс!</b>\n\nЭПИЧЕСУИЙ ВЫИГРЫШ! Вы получили уникальный титул: <b>{title}</b>! 👑", parse_mode="HTML")

# --- Phase 3: Интерактивный гарем ---
@dp.message(Command("feed"))
async def cmd_feed_harem(message: types.Message):
    if not message.reply_to_message:
        return await message.answer("❌ Эту команду нужно использовать ответом на сообщение участника вашего гарема!")
    
    target_id = message.reply_to_message.from_user.id
    owner_id = message.from_user.id
    
    harem = await get_user_harem(owner_id)
    if not any(m[0] == target_id for m in harem):
        return await message.answer("❌ Этот пользователь не в вашем гареме!")
        
    async with aiosqlite.connect('manga.db') as db:
        cursor = await db.execute('UPDATE users_stats SET balance = balance - 10 WHERE user_id = ? AND balance >= 10', (owner_id,))
        if cursor.rowcount == 0:
            return await message.answer("❌ Нужно 10 монет, чтобы покормить участника гарема!")
        await db.commit()
        
    await update_loyalty_level(owner_id, target_id, 2)
    await message.answer(f"🍏 Вы покормили {message.reply_to_message.from_user.first_name}! (+2 💖 к лояльности)")

@dp.message(Command("pet"))
async def cmd_pet_harem(message: types.Message):
    if not message.reply_to_message:
        return await message.answer("❌ Эту команду нужно использовать ответом на сообщение участника вашего гарема!")
    
    target_id = message.reply_to_message.from_user.id
    owner_id = message.from_user.id
    
    harem = await get_user_harem(owner_id)
    if not any(m[0] == target_id for m in harem):
        return await message.answer("❌ Этот пользователь не в вашем гареме!")
        
    async with aiosqlite.connect('manga.db') as db:
        cursor = await db.execute('UPDATE users_stats SET balance = balance - 5 WHERE user_id = ? AND balance >= 5', (owner_id,))
        if cursor.rowcount == 0:
            return await message.answer("❌ Нужно 5 монет, чтобы погладить участника гарема!")
        await db.commit()
        
    await update_loyalty_level(owner_id, target_id, 1)
    await message.answer(f"👋 Вы погладили по голове {message.reply_to_message.from_user.first_name}! (+1 💖 к лояльности)")


# ==============================================================================
# БЛОК 6: ПРОФИЛИ И РП-КОМАНДЫ
async def get_profile_content(chat_type: str, chat_id: int, user: types.User):
    user_id = user.id
    name = user.first_name
    
    partner_text = "Одинок(а) 💔"
    if chat_type in ["group", "supergroup"]:
        marriage = await get_user_marriage(chat_id, user_id)
        if marriage:
            u1_id, u1_name, u2_id, u2_name, date, love_level = marriage
            partner_id = u2_id if u1_id == user_id else u1_id
            partner_name = u2_name if u1_id == user_id else u1_name
            partner_text = f"В браке с {fmt_name(partner_id, partner_name)} 💍 ({date}, ❤️ Уровень: {love_level})"
    
    stats = await get_user_stats(user_id)
    (hugs, kisses, bites, slaps, pats, m_count, s_count, balance, 
     custom_title, is_hidden, casino_played, divorces_count, 
     last_daily, daily_streak, referred_by, xp, level_db) = stats
    
    total_rp = hugs + kisses + bites + slaps + pats
    
    # Финальный расчет уровня
    level = (xp // 100) + 1 if xp > 0 else level_db
    if level < 1: level = 1
    
    if level < 5: rank = "Новичок 🍼"
    elif level < 15: rank = "Освоившийся 🥉"
    elif level < 30: rank = "Активный 🥈"
    elif level < 50: rank = "Знаменитость 🥇"
    elif level < 100: rank = "Легенда 👑"
    else: rank = "Божество 🌟"
    
    # Ачивки
    achievements = []
    if slaps > 50: achievements.append("🥊")
    if kisses > 100: achievements.append("💋")
    if divorces_count >= 3: achievements.append("💔")
    if casino_played > 50: achievements.append("🎰")
    
    title_str = f" [{custom_title}]" if custom_title else ""
    achievements_str = " " + "".join(achievements) if achievements else ""
    
    ref_count = await get_referral_stats(user_id)
    
    profile_text = (
        f"👤 <b>Ваш профиль:</b> {name}{title_str}{achievements_str}\n"
        f"┣ 📊 <b>Уровень:</b> {level} ({rank})\n"
        f"┣ ✨ <b>XP:</b> {xp}\n"
        f"┣ 💰 <b>Монеты:</b> {balance}\n"
        f"┣ 👥 <b>Рефералы:</b> {ref_count}\n"
        f"┗ 👩‍❤️‍👨 <b>Статус:</b> {partner_text}\n\n"
        f"💬 <b>Активность в чатах:</b>\n"
        f"┣ ✉️ Сообщения: <b>{m_count}</b>\n"
        f"┗ 🌟 Стикеры: <b>{s_count}</b>\n\n"
        f"🎭 <b>Ролеплей</b> (всего: {total_rp}):\n"
        f"┣ ❤️ Нежность (поцелуи): <b>{kisses}</b>\n"
        f"┣ 🤗 Забота (объятия): <b>{hugs}</b>\n"
        f"┣ 🥰 Утешение (поглаживания): <b>{pats}</b>\n"
        f"┣ 🧛‍♀️ Вампиризм (кусь): <b>{bites}</b>\n"
        f"┗ 😠 Агрессия (удары): <b>{slaps}</b>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔮 Узнать мнение Али о тебе", callback_data=f"roast_{user_id}")
    builder.button(text="🎒 Инвентарь / Гарем", callback_data=f"inventory_{user_id}")
    builder.adjust(1)
    
    return profile_text, builder.as_markup()

@dp.message(F.text & F.text.regexp(REGEX_PROFILE))
async def cmd_profile(message: types.Message):
    if await check_cd_and_warn(message, "profile", 5): return
    text, markup = await get_profile_content(message.chat.type, message.chat.id, message.from_user)
    await message.answer(text, parse_mode="HTML", reply_markup=markup)

@dp.message(F.text & F.text.regexp(REGEX_REF))
async def cmd_ref(message: types.Message):
    if message.chat.type != "private":
        return await message.answer("❌ Реферальная система доступна только в личных сообщениях с ботом.")
    
    user_id = message.from_user.id
    ref_count = await get_referral_stats(user_id)
    
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    
    text = (
        "🔗 <b>Реферальная система</b>\n\n"
        f"Приглашайте друзей и получайте бонусы!\n"
        f"─ Вы получите: <b>1000 монет</b> и <b>3 XP</b>\n"
        f"─ Друг получит: <b>500 монет</b>\n\n"
        f"👥 Ваших рефералов: <b>{ref_count}</b>\n\n"
        f"📍 Ваша ссылка:\n<code>{ref_link}</code>"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text & F.text.regexp(REGEX_ROB))
async def cmd_rob(message: types.Message):
    if not message.reply_to_message:
        return await message.answer("❌ <b>Ошибка:</b> Эту команду нужно использовать ответом на сообщение жертвы!", parse_mode="HTML")
        
    target = message.reply_to_message.from_user
    initiator = message.from_user
    
    if target.id == initiator.id:
        return await message.answer("🚷 Вы не можете ограбить самого себя!")
    if target.is_bot:
        return await message.answer("🤖 Роботы не носят с собой кошельки!")
        
    if await check_cd_and_warn(message, "rob", 3600): return
    
    target_stats = await get_user_stats(target.id)
    target_balance = target_stats[7]
    
    if target_balance <= 0:
        return await message.answer(f"📦 У @{target.username} совсем пусто в карманах... Нечего красть!")
        
    # Шанс 30%
    if random.random() < 0.30:
        amount = int(target_balance * 0.10)
        if amount < 1: amount = 1
        
        async with aiosqlite.connect('manga.db') as db:
            await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (target.id,))
            await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (initiator.id,))
            await db.execute('UPDATE users_stats SET balance = MAX(0, balance - ?) WHERE user_id = ?', (amount, target.id))
            await db.execute('UPDATE users_stats SET balance = balance + ? WHERE user_id = ?', (amount, initiator.id))
            await db.commit()
            
        await message.answer(
            f"🥷 <b>Успешная кража!</b>\n"
            f"Вы незаметно вытащили <b>{amount} монет</b> из кошелька @{target.username}.",
            parse_mode="HTML"
        )
    else:
        # Провал - штраф 100 монет
        async with aiosqlite.connect('manga.db') as db:
            await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (initiator.id,))
            await db.execute('UPDATE users_stats SET balance = MAX(0, balance - 100) WHERE user_id = ?', (initiator.id,))
            await db.commit()
            
        await message.answer(
            f"🚨 <b>Провал!</b>\n"
            f"Вас поймала <b>Аля</b> на месте преступления! За нарушение порядка вы оштрафованы на <b>100 монет</b>.",
            parse_mode="HTML"
        )

@dp.callback_query(F.data.startswith("back_to_profile_"))
async def callback_back_to_profile(callback: types.CallbackQuery):
    target_user_id = int(callback.data.split("_")[3])
    if callback.from_user.id != target_user_id:
        return await callback.answer("Это не ваш профиль!", show_alert=True)
    text, markup = await get_profile_content(callback.message.chat.type, callback.message.chat.id, callback.from_user)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)

@dp.callback_query(F.data.startswith("inventory_"))
async def callback_inventory(callback: types.CallbackQuery):
    target_user_id = int(callback.data.split("_")[1])
    if callback.from_user.id != target_user_id:
        return await callback.answer("Вы можете смотреть только свой инвентарь!", show_alert=True)
    stats = await get_user_stats(target_user_id)
    custom_title = stats[8]
    
    items = []
    if custom_title:
        items.append(f"👑 Кастомный титул: <b>{custom_title}</b>")
        
    db_items = await get_user_inventory(target_user_id)
    for itype, idata in db_items:
        if itype == "badge":
            items.append(f"🏅 Значок: <b>{idata}</b>")
        else:
            items.append(f"📦 <b>{idata}</b>")
        
    if not items:
        inv_text = "🎒 В вашем инвентаре пока пусто..."
    else:
        inv_text = "🎒 <b>Ваш инвентарь:</b>\n" + "\n".join(f"┣ {item}" for item in items[:-1])
        if len(items) > 1:
            inv_text += f"\n┗ {items[-1]}"
        elif len(items) == 1:
            inv_text += f"\n┗ {items[0]}"
    harem = await get_user_harem(target_user_id)
    if not harem:
        harem_text = "🌸 <b>Гарем:</b>\nПока никого нет... 💔"
    else:
        harem_members = []
        for i, (m_id, m_name, loyalty) in enumerate(harem, 1):
            harem_members.append(f"{i}. {fmt_name(m_id, m_name)} (💖 Lvl: {loyalty})")
        harem_text = "🌸 <b>Ваш гарем:</b>\n" + "\n".join(harem_members)
    
    text = f"{inv_text}\n\n{harem_text}\n\n💡 <i>Чтобы покормить или погладить участника гарема, используйте /feed или /pet ответом на его сообщение!</i>"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад в профиль", callback_data=f"back_to_profile_{target_user_id}")
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("roast_"))
async def callback_roast_profile(callback: types.CallbackQuery):
    target_user_id = int(callback.data.split("_")[1])
    if callback.from_user.id != target_user_id:
        return await callback.answer("Вы можете попросить Алю оценить только СВОЙ профиль!", show_alert=True)
        
    if await check_cd_and_warn(callback, "alya_roast", 30): return
    
    await callback.message.edit_reply_markup(reply_markup=None)
    wait_msg = await callback.message.answer("<i>Аля изучает твое досье...</i>", parse_mode="HTML")
    
    name = callback.from_user.first_name
    hugs, kisses, bites, slaps, pats, m_count, s_count, balance, custom_title, is_hidden, casino_played, divorces_count = await get_user_stats(target_user_id)
    
    partner_text = "Одинок"
    if callback.message.chat.type in ["group", "supergroup"]:
        marriage = await get_user_marriage(callback.message.chat.id, target_user_id)
        if marriage: partner_text = "В браке"

    system_prompt = (
        f"Ты — Алиса Михайловна Кудзё (Аля) из аниме Roshidere. Ты настоящая цундере: строгая и гордая снаружи, "
        f"но легко смущающаяся и тайно заботливая внутри. Проанализируй РП-статистику пользователя {name}. "
        f"Сводка: {partner_text}. Статистика действий: {hugs} объятий, {kisses} поцелуев, {slaps} ударов, {bites} укусов, {pats} поглаживаний. "
        f"Его сообщений в чате: {m_count}, стикеров: {s_count}. "
        f"Оцени его поведение в едком, но по итогу милом или смущенном ключе. "
        f"Например: если много объятий и одинок — скажи, что он отчаянно ищет внимания, но тебе его даже немного жаль; "
        f"если много ударов — назови агрессивным дураком, к которому лучше не подходить; и так далее. "
        f"Обязательно в конце добавь свою истинную (смущающую или искреннюю) мысль по-русски в квадратных скобках: *[шепчет по-русски: \"...\"]*. Максимум 3-4 предложения."
    )
    
    response = await ask_groq("Оцени меня!", system_prompt)
    await wait_msg.delete()
    await callback.message.answer(f"📋 <b>Мнение Али о {name}:</b>\n{response}", parse_mode="HTML")

@dp.message(F.text & F.text.regexp(REGEX_STATS))
async def cmd_stats(message: types.Message):
    if message.chat.type == "private":
        return await message.answer("Статистика чата доступна только в группах.")
    if await check_cd_and_warn(message, "stats", 10): return
    
    async with aiosqlite.connect('manga.db') as db:
        # Берем с запасом 100 человек, чтобы отфильтровать только тех, кто в чате
        async with db.execute('SELECT user_id, messages_count FROM users_stats ORDER BY messages_count DESC LIMIT 100') as cursor:
            top_msg = await cursor.fetchall()
            
        async with db.execute('SELECT user_id, (hugs + kisses + bites + slaps + pats) as rp_total FROM users_stats ORDER BY rp_total DESC LIMIT 100') as cursor:
            top_rp = await cursor.fetchall()
            
    # Собираем данные с фильтрацией по текущему чату
    async def format_top(rows, unit, emoji_badge):
        res = []
        rank = 1
        for uid, count in rows:
            if count == 0: continue
            if rank > 5: break
            try:
                chat_member = await bot.get_chat_member(message.chat.id, uid)
                if chat_member.status in ["left", "kicked", "banned"]:
                    continue
                name = chat_member.user.first_name if chat_member.user else f"ID: {uid}"
            except Exception:
                continue
            
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            medal = medals.get(rank, "🏅")
            res.append(f"{medal} <b>{name}</b> — {count} {unit} {emoji_badge}")
            rank += 1
        return "\n".join(res) if res else "<i>Пока пусто...</i>"

    top_msg_text = await format_top(top_msg, "сообщ.", "✉️")
    top_rp_text = await format_top(top_rp, "РП-действий", "💞")
    
    text = f"📊 <b>Статистика чата:</b>\n\n🗣 <b>Топ болтунов:</b>\n{top_msg_text}\n\n🎭 <b>Самые любвеобильные:</b>\n{top_rp_text}"
    await message.answer(text, parse_mode="HTML")

# РП команды теперь в handlers/rp.py


# ==============================================================================
# БЛОК 7: БРАКИ (СВАДЬБЫ И РАЗВОДЫ)
# ==============================================================================
@dp.message(F.text & F.text.regexp(REGEX_MARRY))
async def propose_marriage(message: types.Message):
    if message.chat.type == "private": return await temp_reply(message, "Только в группах!")
    if await check_cd_and_warn(message, "marry", 10): return
    if not message.reply_to_message: return await temp_reply(message, "Ответьте на сообщение человека!")
        
    initiator, target = message.from_user, message.reply_to_message.from_user
    chat_id = message.chat.id
    if target.id == initiator.id: return await temp_reply(message, "На себе нельзя!")
    if target.is_bot: return await temp_reply(message, "С ботами нельзя!")

    if await get_user_marriage(chat_id, initiator.id) or await get_user_marriage(chat_id, target.id):
        return await temp_reply(message, "Кто-то из вас уже состоит в браке!")


    MARRIAGE_PROPOSALS[f"{chat_id}_{initiator.id}_{target.id}"] = initiator.first_name

    builder = InlineKeyboardBuilder()
    builder.button(text="💍 Согласиться", callback_data=f"marry_yes_{initiator.id}_{target.id}")
    builder.button(text="💔 Отказать", callback_data=f"marry_no_{initiator.id}_{target.id}")
    await message.answer(f"💍 {target.mention_html()}, {initiator.mention_html()} предлагает брак!\nЧто ответишь?", reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("marry_"))
async def process_marriage_callback(callback: types.CallbackQuery):
    _, action, init_id, targ_id = callback.data.split("_")
    if str(callback.from_user.id) != targ_id: return await callback.answer("Это не для вас!", show_alert=True)
    if action == "no": return await callback.message.edit_text(f"💔 {callback.from_user.mention_html()} отверг(ла) предложение.", parse_mode="HTML")
        
    chat_id = callback.message.chat.id
    if await get_user_marriage(chat_id, int(init_id)) or await get_user_marriage(chat_id, int(targ_id)):
        return await callback.message.edit_text("Один из пользователей уже успел вступить в брак!")

    init_name_cached = MARRIAGE_PROPOSALS.pop(f"{chat_id}_{init_id}_{targ_id}", None)
    if init_name_cached:
        init_name = init_name_cached
    else:
        try:
            chat_member = await bot.get_chat_member(chat_id, int(init_id))
            init_name = chat_member.user.first_name
        except Exception:
            init_name = 'Пользователь'
            
    targ_user = callback.from_user
    targ_name = targ_user.first_name
        
    date_now = datetime.now().strftime("%d.%m.%Y")
    
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('INSERT INTO marriages (chat_id, user1_id, user1_name, user2_id, user2_name, date) VALUES (?, ?, ?, ?, ?, ?)', 
                         (chat_id, int(init_id), init_name, int(targ_id), targ_name, date_now))
        await db.commit()
    await callback.message.edit_text(f"🎉 <b>Объявляю вас мужем и женой!</b>\n\nТеперь {init_name} и {targ_name} официально в браке 💍", parse_mode="HTML")

@dp.message(F.text & F.text.regexp(REGEX_DIVORCE))
async def process_divorce(message: types.Message):
    if message.chat.type == "private": return
    if await check_cd_and_warn(message, "divorce", 10): return
    
    marriage = await get_user_marriage(message.chat.id, message.from_user.id)
    if not marriage:
        return await temp_reply(message, "Вы не состоите в браке в этой беседе.")
        
    wait_msg = await message.answer("<i>Аля анализирует ситуацию...</i>", parse_mode="HTML")
    
    u1_name, u2_name = marriage[2], marriage[4]
    partner_name = u2_name if marriage[0] == message.from_user.id else u1_name
    initiator_name = message.from_user.first_name
    
    system_prompt = (
        "Ты Аля (из аниме Roshidere). Цундере, которая управляет браками в чате. "
        f"Пользователь {initiator_name} решил развестись с {partner_name}. "
        "Прокомментируй это в стиле цундере (едким комментарием, можно с долей сарказма или осуждения) "
        "и в конце спроси, уверен(а) ли он(а)."
    )
    
    if not await is_ai_enabled(message.chat.id):
        response = f"Ты действительно хочешь развестись с {partner_name}? Подумай хорошенько, бака!"
    else:
        try:
            response = await ask_groq("Прокомментируй развод", system_prompt)
        except Exception:
            response = f"Ты действительно хочешь развестись с {partner_name}? Подумай хорошенько, бака!"
        
    await wait_msg.delete()
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✅ Да, развестись", callback_data=f"divorce_yes:{message.from_user.id}")],
        [types.InlineKeyboardButton(text="❌ Передумал(а)", callback_data=f"divorce_no:{message.from_user.id}")]
    ])
    
    await message.answer(f"🌸 <b>Аля:</b>\n{response}", parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith("divorce_"))
async def handle_divorce_cb(callback: types.CallbackQuery):
    action, uid = callback.data.split(":")
    if callback.from_user.id != int(uid):
        return await callback.answer("Это не ваш запрос на развод!", show_alert=True)
        
    await callback.message.edit_reply_markup(reply_markup=None)
    
    if action == "divorce_no":
        return await callback.message.answer("<i>Брак спасен! (пока что...)</i>", parse_mode="HTML")
        
    async with aiosqlite.connect('manga.db') as db:
        # Get users in the marriage to update their divorce count
        async with db.execute('SELECT user1_id, user2_id FROM marriages WHERE chat_id = ? AND (user1_id = ? OR user2_id = ?)', 
                         (callback.message.chat.id, callback.from_user.id, callback.from_user.id)) as cursor:
            row = await cursor.fetchone()
            if row:
                u1, u2 = row
                await db.execute('UPDATE users_stats SET divorces_count = divorces_count + 1 WHERE user_id IN (?, ?)', (u1, u2))
        
        await db.execute('DELETE FROM marriages WHERE chat_id = ? AND (user1_id = ? OR user2_id = ?)', 
                         (callback.message.chat.id, callback.from_user.id, callback.from_user.id))
        await db.commit()
    await callback.message.answer("💔 Вы успешно расторгли брак.")

# ==============================================================================
# БЛОК 7.1: ГАРЕМ
# ==============================================================================
@dp.message(F.text & F.text.regexp(REGEX_HAREM_ADD))
async def propose_harem(message: types.Message):
    if await check_cd_and_warn(message, "harem_add", 5): return
    if not message.reply_to_message: return await temp_reply(message, "Ответьте на сообщение человека!")
        
    initiator, target = message.from_user, message.reply_to_message.from_user
    if target.id == initiator.id: return await temp_reply(message, "Нельзя добавить себя в свой гарем!")
    if target.is_bot: return await temp_reply(message, "С ботами нельзя!")

    harem = await get_user_harem(initiator.id)
    if any(m[0] == target.id for m in harem):
        return await temp_reply(message, "Этот пользователь уже в вашем гареме!")

    HAREM_PROPOSALS[f"{initiator.id}_{target.id}"] = initiator.first_name

    builder = InlineKeyboardBuilder()
    builder.button(text="😈 Согласиться", callback_data=f"harem_yes_{initiator.id}_{target.id}")
    builder.button(text="🙅 Отказать", callback_data=f"harem_no_{initiator.id}_{target.id}")
    await message.answer(f"👑 {target.mention_html()}, {initiator.mention_html()} предлагает тебе вступить в его/её гарем!\nЧто ответишь?", reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("harem_"))
async def process_harem_callback(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) == 4:
        _, action, init_id, targ_id = parts
    else: return
    
    if str(callback.from_user.id) != targ_id: return await callback.answer("Это не для вас!", show_alert=True)
    if action == "no": return await callback.message.edit_text(f"🙅 {callback.from_user.mention_html()} отверг(ла) предложение вступить в гарем.", parse_mode="HTML")
        
    harem = await get_user_harem(int(init_id))
    if any(m[0] == int(targ_id) for m in harem):
        return await callback.message.edit_text("Пользователь уже в гареме!")

    init_name_cached = HAREM_PROPOSALS.pop(f"{init_id}_{targ_id}", None)
    if init_name_cached:
        init_name = init_name_cached
    else:
        try:
            chat_member = await bot.get_chat_member(callback.message.chat.id, int(init_id))
            init_name = chat_member.user.first_name
        except Exception:
            init_name = 'Пользователь'
            
    targ_user = callback.from_user
    targ_name = targ_user.first_name
        
    await add_to_harem(int(init_id), int(targ_id), targ_name)
    await callback.message.edit_text(f"🎉 <b>Новое пополнение гарема!</b>\n\nТеперь {targ_name} принадлежит {init_name} 👑", parse_mode="HTML")

@dp.message(F.text & F.text.regexp(REGEX_HAREM_REMOVE))
async def remove_harem_member(message: types.Message):
    if await check_cd_and_warn(message, "harem_remove", 5): return
    if not message.reply_to_message: return await temp_reply(message, "Ответьте на сообщение человека!")
    
    initiator, target = message.from_user, message.reply_to_message.from_user
    harem = await get_user_harem(initiator.id)
    if not any(m[0] == target.id for m in harem):
        return await temp_reply(message, "Этого пользователя нет в вашем гареме!")
        
    await remove_from_harem(initiator.id, target.id)
    await message.answer(f"🗑 {target.mention_html()} был(а) изгнан(а) из вашего гарема!")

@dp.message(F.text & F.text.regexp(REGEX_MARRIAGES))
async def list_marriages(message: types.Message):
    if message.chat.type == "private": return await temp_reply(message, "Только в группах!")
    if await check_cd_and_warn(message, "marriages_list", 10): return

    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT user1_id, user2_id, user1_name, user2_name, date FROM marriages WHERE chat_id = ?', (message.chat.id,)) as cursor:
            marriages = await cursor.fetchall()
            
    if not marriages: return await temp_reply(message, "В этой беседе пока нет ни одной пары 😔", parse_mode="HTML")
    
    lines = [f"{i}. {fmt_name(u1_id, u1_name)} ❤️ {fmt_name(u2_id, u2_name)} <i>({d})</i>" for i, (u1_id, u2_id, u1_name, u2_name, d) in enumerate(marriages, 1)]
    text = f"💍 <b>Топ пар:</b>\n\n" + "\n".join(lines)
    await message.answer(text, parse_mode="HTML")


# ==============================================================================
# БЛОК 8: МИНИ-ИГРЫ И РАЗВЛЕЧЕНИЯ (ИРИС)
# ==============================================================================
@dp.message(F.text & F.text.regexp(REGEX_INFA))
async def cmd_infa(message: types.Message):
    if await check_cd_and_warn(message, "iris_cmd", 3): return
    chance = random.randint(0, 100)
    match = REGEX_INFA.search(message.text)
    await message.answer(f"🔮 Вероятность того, что {match.group(1).strip()} — <b>{chance}%</b>", parse_mode="HTML")

@dp.message(F.text & F.text.regexp(REGEX_RANDOM))
async def cmd_random(message: types.Message):
    if await check_cd_and_warn(message, "iris_cmd", 2): return
    match = REGEX_RANDOM.search(message.text)
    limit = int(match.group(1))
    if limit <= 0: return await temp_reply(message, "Число должно быть больше нуля!")
    await message.answer(f"🎲 Выпало число: <b>{random.randint(1, limit)}</b>", parse_mode="HTML")

@dp.message(F.text & F.text.regexp(REGEX_CHOOSE))
async def cmd_choose(message: types.Message):
    if await check_cd_and_warn(message, "iris_cmd", 3): return
    match = REGEX_CHOOSE.search(message.text)
    choice = random.choice([match.group(1).strip(), match.group(2).strip()])
    await message.answer(f"🤔 Я думаю, лучше:\n👉 <b>{choice}</b>", parse_mode="HTML")

@dp.message(F.text & F.text.regexp(REGEX_ALYA_CHOOSE))
async def cmd_alya_choose(message: types.Message):
    if await check_cd_and_warn(message, "alya_choose", 10): return

    match = REGEX_ALYA_CHOOSE.search(message.text)
    item1, item2 = match.group(1).strip(), match.group(2).strip()

    if message.chat.type in ["group", "supergroup"] and not await is_ai_enabled(message.chat.id):
        return await message.answer(f"🌸 <b>Выбор Али:</b>\nБака, я сейчас не в настроении выбирать!", parse_mode="HTML")
    
    wait_msg = await message.answer("<i>Аля думает...</i>", parse_mode="HTML")
    system_prompt = (
        f"Ты Аля (аниме Roshidere). Пользователь просит тебя выбрать между '{item1}' и '{item2}'. "
        f"Сделай однозначный выбор в пользу одного из них. Объясни свой выбор коротко (1-2 предложения), "
        f"в стиле цундере. Будь немного дерзкой. (Можешь в конце добавить мысль по-русски в скобках)."
    )
    response = await ask_groq("Что лучше?", system_prompt)
    await wait_msg.delete()
    await message.answer(f"🌸 <b>Выбор Али:</b>\n{response}", parse_mode="HTML")

@dp.message(F.text & F.text.regexp(REGEX_COIN))
async def cmd_coin(message: types.Message):
    if await check_cd_and_warn(message, "iris_cmd", 2): return
    coin = random.choice(["Орел", "Решка"])
    await message.answer(f"🪙 Выпало: <b>{coin}</b>", parse_mode="HTML")

# ==============================================================================
# БЛОК: ИИ-ИГРЫ И ШИППЕРИНГ
# ==============================================================================
BOTTLE_GAMES = {}

@dp.message(F.text & F.text.regexp(REGEX_BOTTLE))
async def cmd_bottle(message: types.Message):
    if message.chat.type == "private": return await temp_reply(message, "Только в группах!")
    if await check_cd_and_warn(message, "bottle", 30): return
    
    chat_id = message.chat.id
    if chat_id in BOTTLE_GAMES:
        return await temp_reply(message, "В этой беседе уже идет сбор на бутылочку!")
        
    BOTTLE_GAMES[chat_id] = {
        "participants": {message.from_user.id: message.from_user.first_name},
        "msg_id": None
    }
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🏃 Участников: 1", callback_data="bottle_join"),
         types.InlineKeyboardButton(text="Крутить", callback_data="bottle_spin")]
    ])
    
    msg = await message.answer(
        "🍾 <b>Игра в Бутылочку!</b>\n\nПрисоединяйтесь к игре! Как только наберется народ, жмите «Крутить».",
        parse_mode="HTML", reply_markup=kb
    )
    BOTTLE_GAMES[chat_id]["msg_id"] = msg.message_id

@dp.callback_query(F.data == "bottle_join")
async def bottle_join(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    if chat_id not in BOTTLE_GAMES:
        return await callback.answer("Игра уже закончилась или не начиналась.", show_alert=True)
        
    game = BOTTLE_GAMES[chat_id]
    uid = callback.from_user.id
    if uid in game["participants"]:
        return await callback.answer("Вы уже в игре!", show_alert=True)
        
    game["participants"][uid] = callback.from_user.first_name
    count = len(game["participants"])
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"🏃 Участников: {count}", callback_data="bottle_join"),
         types.InlineKeyboardButton(text="Крутить", callback_data="bottle_spin")]
    ])
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass
    await callback.answer("Вы присоединились!")

@dp.callback_query(F.data == "bottle_spin")
async def bottle_spin(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    if chat_id not in BOTTLE_GAMES:
        return await callback.answer("Игра не найдена.", show_alert=True)
        
    game = BOTTLE_GAMES[chat_id]
    participants = game["participants"]
    
    if len(participants) < 2:
        return await callback.answer("Для игры нужно минимум 2 человека!", show_alert=True)
        
    del BOTTLE_GAMES[chat_id]
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    
    p_ids = list(participants.keys())
    p1 = random.choice(p_ids)
    p_ids.remove(p1)
    p2 = random.choice(p_ids)
    
    n1, n2 = participants[p1], participants[p2]
    
    wait_msg = await callback.message.answer(f"🍾 Бутылочка крутится... выпадают <b>{n1}</b> и <b>{n2}</b>!\n<i>Аля придумывает фант...</i>", parse_mode="HTML")
    
    system_prompt = (
        "Ты Аля (из аниме Roshidere). Цундере. Придумай одно смешное или романтичное задание-фант "
        f"для двоих игроков: {n1} и {n2}. Задание должно быть в рамках приличия, но с перчинкой. "
        "Максимум 2-3 предложения. Можешь прокомментировать это как цундере."
    )
    
    if not await is_ai_enabled(chat_id):
        task = "Обнимите друг друга, баки! И не думайте, что я хочу на это смотреть!"
    else:
        try:
            task = await ask_groq("Придумай фант для бутылочки", system_prompt)
        except Exception:
            task = "Обнимите друг друга, баки! И не думайте, что я хочу на это смотреть!"
        
    await wait_msg.delete()
    await callback.message.answer(f"🍾 <b>Бутылочка!</b>\n\nПара: <a href='tg://user?id={p1}'>{n1}</a> и <a href='tg://user?id={p2}'>{n2}</a>\n\n🌸 <b>Задание от Али:</b>\n{task}", parse_mode="HTML")

@dp.message(F.text & F.text.regexp(REGEX_SHIP))
async def cmd_ship(message: types.Message):
    if message.chat.type == "private": return await temp_reply(message, "Только в группах!")
    if await check_cd_and_warn(message, "ship", 60): return
    
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT user_id, first_name FROM users_stats WHERE chat_id = ? ORDER BY RANDOM() LIMIT 2', (message.chat.id,)) as cursor:
            participants = await cursor.fetchall()
            
    if len(participants) < 2:
        return await message.answer("В этой беседе слишком мало людей для шипперинга!")
        
    p1_id, p1_name = participants[0]
    p2_id, p2_name = participants[1]
    
    wait_msg = await message.answer(f"💞 <i>Аля анализирует совместимость {p1_name} и {p2_name}...</i>", parse_mode="HTML")
    
    compatibility = random.randint(0, 100)
    
    system_prompt = (
        "Ты Аля (аниме Roshidere). Твоя задача — сгенерировать короткую, забавную или милую "
        f"историю любви (шипперинг) между пользователями '{p1_name}' и '{p2_name}'. "
        f"Их процент совместимости — {compatibility}%. "
        "Опиши, как они могли бы встретиться или почему они (не) подходят друг другу, в стиле цундере."
    )
    
    if not await is_ai_enabled(message.chat.id):
        story = "Эти баки настолько подходят друг другу, что я даже не хочу об этом говорить!"
    else:
        try:
            story = await ask_groq("Расскажи историю любви", system_prompt)
        except Exception:
            story = "Эти баки настолько подходят друг другу, что я даже не хочу об этом говорить!"
        
    await wait_msg.delete()
    text = (
        f"💘 <b>Шипперинг!</b> 💘\n\n"
        f"Пара: <a href='tg://user?id={p1_id}'>{p1_name}</a> x <a href='tg://user?id={p2_id}'>{p2_name}</a>\n"
        f"Совместимость: <b>{compatibility}%</b>\n\n"
        f"🌸 <b>Прогноз от Али:</b>\n{story}"
    )
    await message.answer(text, parse_mode="HTML")

# ==============================================================================
# БЛОК: ЭКОНОМИКА И МАГАЗИН
# ==============================================================================

@dp.message(F.text & F.text.regexp(REGEX_SHOP))
async def cmd_shop(message: types.Message):
    if message.chat.type == "private": return await temp_reply(message, "Только в группах!")
    
    stats = await get_user_stats(message.from_user.id)
    balance = stats[7] if stats else 0
    
    text = (
        f"🛒 <b>Магазин Аля-бота</b>\n\n"
        f"У вас <b>{balance}</b> монет.\n\n"
        f"Доступные товары:"
    )
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🎁 Тайный Лутбокс (300 монет)", callback_data="buy_lootbox")],
        [types.InlineKeyboardButton(text="👑 Кастомный титул (500 монет)", callback_data="buy_title")],
        [types.InlineKeyboardButton(text="👻 Скрыть стату в топе (1000 монет)", callback_data="buy_hidden")],
        [types.InlineKeyboardButton(text="🎖️ Значок VIP (2000 монет)", callback_data="buy_badge_vip")]
    ])
    
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "buy_lootbox")
async def shop_buy_lootbox_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    stats = await get_user_stats(user_id)
    balance = stats[7] if stats else 0
    
    async with aiosqlite.connect('manga.db') as db:
        cursor = await db.execute('UPDATE users_stats SET balance = balance - 300 WHERE user_id = ? AND balance >= 300', (user_id,))
        if cursor.rowcount == 0:
            return await callback.answer("Недостаточно монет! Нужно 300.", show_alert=True)
        await db.commit()
    
    # Логика Готчи
    rnd = random.random()
    if rnd < 0.50: # 50% нифига
        res_text = "💨 К сожалению, лутбокс оказался пустым... Повезет в следующий раз!"
        res_emoji = "😢"
    elif rnd < 0.80: # 30% монеты (возврат или бонус)
        reward = random.randint(50, 600)
        async with aiosqlite.connect('manga.db') as db:
            await db.execute('UPDATE users_stats SET balance = balance + ? WHERE user_id = ?', (reward, user_id))
            await db.commit()
        res_text = f"💰 Внутри вы нашли мешочек с монетами: <b>{reward}</b>!"
        res_emoji = "🤑"
    elif rnd < 0.95: # 15% значок
        badges = ["🍀 Счастливчик", "📦 Коллекционер", "🦄 Редкий зверь", "🔮 Мистик"]
        badge = random.choice(badges)
        await add_to_inventory(user_id, "badge", badge)
        res_text = f"🏅 Ого! Вам выпал редкий значок: <b>{badge}</b>!"
        res_emoji = "✨"
    else: # 5% Титул
        titles = ["🎲 Мастер Азарта", "🎩 Джентльмен", "🦊 Хитрый Лис", "🌟 Сияющий"]
        title = random.choice(titles)
        async with aiosqlite.connect('manga.db') as db:
            await db.execute('UPDATE users_stats SET custom_title = ? WHERE user_id = ?', (title, user_id))
            await db.commit()
        res_text = f"👑 НЕВЕРОЯТНО! Вы получили уникальный титул: <b>{title}</b>!"
        res_emoji = "🔥"

    await callback.message.edit_text(f"{res_emoji} <b>Результат открытия лутбокса:</b>\n\n{res_text}", parse_mode="HTML", reply_markup=None)

@dp.callback_query(F.data == "buy_title")
async def shop_buy_title_cb(callback: types.CallbackQuery, state: FSMContext):
    stats = await get_user_stats(callback.from_user.id)
    balance = stats[7] if stats else 0
    if balance < 500:
        return await callback.answer("Недостаточно монет! Нужно 500.", show_alert=True)
        
    await state.set_state(ShopBuyTitle.waiting_for_title)
    await state.update_data(chat_id=callback.message.chat.id)
    await callback.message.edit_text("👑 Введите ваш новый титул (до 20 символов):", reply_markup=None)

@dp.message(ShopBuyTitle.waiting_for_title)
async def shop_process_title(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data.get("chat_id")
    if chat_id != message.chat.id:
        return
        
    title = message.text.strip()
    if len(title) > 20:
        return await message.answer("Слишком длинный титул! Максимум 20 символов. Попробуйте снова.")
        
    stats = await get_user_stats(message.from_user.id)
    balance = stats[7] if stats else 0
    if balance < 500:
        await state.clear()
        return await message.answer("Пока вы думали, у вас закончились монеты...")
        
    async with aiosqlite.connect('manga.db') as db:
        cursor = await db.execute('UPDATE users_stats SET balance = balance - 500, custom_title = ? WHERE user_id = ? AND balance >= 500', (title, message.from_user.id))
        if cursor.rowcount == 0:
            await state.clear()
            return await message.answer("Пока вы думали, у вас закончились монеты...")
        await db.commit()
        
    await state.clear()
    await message.answer(f"🎉 Вы успешно купили титул <b>{title}</b>!", parse_mode="HTML")

@dp.callback_query(F.data == "buy_hidden")
async def shop_buy_hidden_cb(callback: types.CallbackQuery):
    stats = await get_user_stats(callback.from_user.id)
    balance = stats[7] if stats else 0
    if balance < 1000:
        return await callback.answer("Недостаточно монет! Нужно 1000.", show_alert=True)
        
    async with aiosqlite.connect('manga.db') as db:
        cursor = await db.execute('UPDATE users_stats SET balance = balance - 1000, is_hidden = 1 WHERE user_id = ? AND balance >= 1000', (callback.from_user.id,))
        if cursor.rowcount == 0:
            return await callback.answer("Недостаточно монет! Нужно 1000.", show_alert=True)
        await db.commit()
        
    await callback.message.edit_text("👻 Ваша статистика теперь скрыта из глобального топа!", reply_markup=None)

@dp.callback_query(F.data == "buy_badge_vip")
async def shop_buy_badge_vip_cb(callback: types.CallbackQuery):
    stats = await get_user_stats(callback.from_user.id)
    balance = stats[7] if stats else 0
    if balance < 2000:
        return await callback.answer("Недостаточно монет! Нужно 2000.", show_alert=True)
        
    # Check if they already have it
    inv = await get_user_inventory(callback.from_user.id, item_type="badge")
    if any(i[1] == "VIP 🌟" for i in inv):
        return await callback.answer("У вас уже есть этот значок!", show_alert=True)
        
    async with aiosqlite.connect('manga.db') as db:
        cursor = await db.execute('UPDATE users_stats SET balance = balance - 2000 WHERE user_id = ? AND balance >= 2000', (callback.from_user.id,))
        if cursor.rowcount == 0:
            return await callback.answer("Недостаточно монет! Нужно 2000.", show_alert=True)
        await db.commit()
        
    await add_to_inventory(callback.from_user.id, "badge", "VIP 🌟")
    await callback.answer("Вы успешно приобрели значок VIP 🌟!", show_alert=True)
    
    # Update the shop message to reflect new balance
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="👑 Кастомный титул (500 монет)", callback_data="buy_title")],
        [types.InlineKeyboardButton(text="👻 Скрыть стату в топе (1000 монет)", callback_data="buy_hidden")],
        [types.InlineKeyboardButton(text="🎖️ Значок VIP (2000 монет)", callback_data="buy_badge_vip")]
    ])
    await callback.message.edit_text(f"🛒 <b>Магазин Аля-бота</b>\n\nУ вас <b>{balance-2000}</b> монет.\n\nДоступные товары:", parse_mode="HTML", reply_markup=kb)

REGEX_DICE_GAMES = re.compile(r'(?i)^[/*\s]*(кости|кубик|дартс|баскетбол|футбол|казино|слоты|слот|боулинг)')

@dp.message(F.text & F.text.regexp(REGEX_DICE_GAMES))
async def cmd_dice_games(message: types.Message):
    if await check_cd_and_warn(message, "iris_cmd", 3): return
    
    text = message.text.lower()
    emoji = "🎲"
    if "дартс" in text: emoji = "🎯"
    elif "баскетбол" in text: emoji = "🏀"
    elif "футбол" in text: emoji = "⚽"
    elif "казино" in text or "слот" in text: emoji = "🎰"
    elif "боулинг" in text: emoji = "🎳"
    
    if emoji == "🎰":
        match = REGEX_SLOT.search(message.text)
        bet_str = match.group(2) if match else None
        
        if not bet_str:
            return await message.answer("🎰 <b>Формат:</b> /казино [ставка]\n<i>Пример: /казино 100</i>", parse_mode="HTML")
            
        try:
            bet = int(bet_str)
            if bet <= 0: return await message.answer("❌ Ставка должна быть больше 0!")
        except ValueError:
            return await message.answer("❌ Введите корректное число для ставки!")

        user_id = message.from_user.id
        stats = await get_user_stats(user_id)
        balance = stats[7]
        
        if balance < bet:
            return await message.answer(f"❌ <b>Недостаточно средств!</b>\nВаш баланс: {balance} монет.", parse_mode="HTML")
            
        # Списываем ставку
        async with aiosqlite.connect('manga.db') as db:
            cursor = await db.execute('UPDATE users_stats SET balance = balance - ?, casino_played = casino_played + 1 WHERE user_id = ? AND balance >= ?', (bet, user_id, bet))
            if cursor.rowcount == 0:
                return await message.answer(f"❌ <b>Недостаточно средств!</b>", parse_mode="HTML")
            await db.commit()
            
        msg = await message.answer_dice(emoji="🎰")
        await asyncio.sleep(2)
        
        val = msg.dice.value
        win = 0
        if val == 64: win = bet * 50 # 777
        elif val == 43: win = bet * 20 # Лимоны
        elif val == 22: win = bet * 10 # Виноград
        elif val == 1: win = bet * 10 # BAR
        
        if win > 0:
            async with aiosqlite.connect('manga.db') as db:
                await db.execute('UPDATE users_stats SET balance = balance + ? WHERE user_id = ?', (win, user_id))
                await db.commit()
            return await message.answer(f"🎉 <b>ДЖЕКПОТ!</b>\nВы выиграли <b>{win}</b> монет! 💰", parse_mode="HTML")
        else:
            return await message.answer(f"💨 <b>Вы проиграли ставку...</b>\nУдача обязательно вернется! 🎰", parse_mode="HTML")
            
    await message.answer_dice(emoji=emoji)

@dp.message(F.text & F.text.regexp(REGEX_RPS))
async def cmd_rps(message: types.Message):
    if await check_cd_and_warn(message, "iris_cmd", 3): return
    match = REGEX_RPS.search(message.text)
    user_choice = match.group(2).lower() if match.group(2) else None
    bot_choice = random.choice(["камень", "ножницы", "бумага"])
    
    if not user_choice:
        return await message.answer(f"✊✌️✋ Я выбрал: <b>{bot_choice}</b>\n(Чтобы сыграть со мной: напиши <i>кнб [камень/ножницы/бумага]</i>)", parse_mode="HTML")
        
    wins = {"камень": "ножницы", "ножницы": "бумага", "бумага": "камень"}
    if user_choice not in wins:
        return await message.answer("Я знаю только камень, ножницы и бумагу!")
        
    if user_choice == bot_choice:
        res = "Ничья! 🤝"
    elif wins[user_choice] == bot_choice:
        res = "Ты победил! 🎉"
    else:
        res = "Я победил! 🤖"
        
    await message.answer(f"Твой выбор: <b>{user_choice}</b>\nМой выбор: <b>{bot_choice}</b>\n\n{res}", parse_mode="HTML")

@dp.message(F.text & F.text.regexp(REGEX_MAGIC_BALL))
async def cmd_magic_ball(message: types.Message):
    if await check_cd_and_warn(message, "iris_cmd", 3): return
    match = REGEX_MAGIC_BALL.search(message.text)
    question = match.group(1).strip()
    answers = ["Бесспорно", "Предрешено", "Никаких сомнений", "Определённо да", "Можешь быть уверен в этом", 
               "Мне кажется - да", "Вероятнее всего", "Хорошие перспективы", "Знаки говорят - да", "Да", 
               "Пока не ясно, попробуй снова", "Спроси позже", "Лучше не рассказывать", "Сейчас нельзя предсказать", 
               "Сконцентрируйся и спроси опять", "Даже не думай", "Мой ответ - нет", "По моим данным - нет", 
               "Перспективы не очень хорошие", "Весьма сомнительно"]
    await message.answer(f"🎱 <b>Вопрос:</b> <i>{question}</i>\n<b>Ответ:</b> {random.choice(answers)}", parse_mode="HTML")

@dp.message(F.text & F.text.regexp(REGEX_COMPATIBILITY))
async def cmd_compatibility(message: types.Message):
    if await check_cd_and_warn(message, "iris_cmd", 3): return
    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение пользователя, чтобы узнать вашу совместимость!")
        
    user1 = message.from_user
    user2 = message.reply_to_message.from_user
    
    if user1.id == user2.id:
        return await message.answer("Совместимость с самим собой — 100% (но это грустно) 🥲")
        
    base = sum([ord(c) for c in str(min(user1.id, user2.id)) + str(max(user1.id, user2.id))])
    daily_seed = datetime.now().day
    random.seed(base + daily_seed)
    compat = random.randint(0, 100)
    random.seed()
    
    await message.answer(f"💞 Совместимость <b>{user1.first_name}</b> и <b>{user2.first_name}</b> на сегодня — <b>{compat}%</b>", parse_mode="HTML")

@dp.message(F.text & F.text.regexp(REGEX_ROULETTE))
async def cmd_roulette(message: types.Message):
    if await check_cd_and_warn(message, "iris_cmd", 5): return
    chance = random.randint(1, 6)
    if chance == 1:
        await message.answer("💥 <b>БАХ!</b> Вы словили пулю. (Помянем 🕯)", parse_mode="HTML")
    else:
        await message.answer("🔫 <i>Щелк...</i> Вам повезло, барабан был пуст.", parse_mode="HTML")


# ==============================================================================
# БЛОК 9: ЧТЕНИЕ МАНГИ И ГАЛЕРЕЯ АРТОВ
# ==============================================================================


def get_chapters_menu(lang: str, chapters: list, page: int = 0):
    builder = InlineKeyboardBuilder()
    if not chapters:
        return builder.row(types.InlineKeyboardButton(text="Главы пока не добавлены 😔", callback_data="read_langs")).as_markup()

    total_pages = math.ceil(len(chapters) / ITEMS_PER_PAGE)
    for ch in chapters[page * ITEMS_PER_PAGE : (page + 1) * ITEMS_PER_PAGE]:
        builder.button(text=f"Глава {ch}", callback_data=f"read_{lang}_{ch}")
    builder.adjust(3) 

    nav_buttons = []
    if page > 0: nav_buttons.append(types.InlineKeyboardButton(text="◀️ Пред.", callback_data=f"page_manga_{lang}_{page-1}"))
    if page < total_pages - 1: nav_buttons.append(types.InlineKeyboardButton(text="След. ▶️", callback_data=f"page_manga_{lang}_{page+1}"))
    if nav_buttons: builder.row(*nav_buttons)

    # Кнопка перехода на страницу
    builder.row(types.InlineKeyboardButton(text="🔢 На страницу", callback_data=f"jump_manga_{lang}"))

    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="read_langs"))
    return builder.as_markup()

def get_ranobe_chapters_menu(lang: str, chapters: list, page: int = 0):
    builder = InlineKeyboardBuilder()
    if not chapters:
        return builder.row(types.InlineKeyboardButton(text="Главы пока не добавлены 😔", callback_data="read_ranobe_langs")).as_markup()

    total_pages = math.ceil(len(chapters) / ITEMS_PER_PAGE)
    for ch in chapters[page * ITEMS_PER_PAGE : (page + 1) * ITEMS_PER_PAGE]:
        builder.button(text=f"Глава {ch}", callback_data=f"read_ranobe_{lang}_{ch}")
    builder.adjust(3) 

    nav_buttons = []
    if page > 0: nav_buttons.append(types.InlineKeyboardButton(text="◀️ Пред.", callback_data=f"page_ranobe_{lang}_{page-1}"))
    if page < total_pages - 1: nav_buttons.append(types.InlineKeyboardButton(text="След. ▶️", callback_data=f"page_ranobe_{lang}_{page+1}"))
    if nav_buttons: builder.row(*nav_buttons)

    # Кнопка перехода на страницу
    builder.row(types.InlineKeyboardButton(text="🔢 На страницу", callback_data=f"jump_ranobe_{lang}"))

    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="read_ranobe_langs"))
    return builder.as_markup()

@dp.callback_query(F.data == "read_langs")
async def process_read_langs(callback: types.CallbackQuery):
    try:
        await callback.message.edit_text("🌐 <b>Каталог Манги</b>\nВыберите раздел для чтения:", parse_mode="HTML", reply_markup=get_langs_menu("readlang"))
    except Exception:
        try: await callback.message.delete()
        except Exception: pass
        await callback.message.answer("🌐 <b>Каталог Манги</b>\nВыберите раздел для чтения:", parse_mode="HTML", reply_markup=get_langs_menu("readlang"))

@dp.callback_query(F.data.startswith("readlang_"))
async def process_read_chapters(callback: types.CallbackQuery):
    lang_code = callback.data.split("_")[1]
    chapters = await get_chapters(lang_code)
    await callback.message.edit_text(f"📚 Доступные главы ({LANGUAGES[lang_code]}):", reply_markup=get_chapters_menu(lang_code, chapters, page=0))

@dp.callback_query(F.data == "read_ranobe_langs")
async def process_read_ranobe_langs(callback: types.CallbackQuery):
    try:
        await callback.message.edit_text("📖 <b>Каталог Ранобэ</b>\nВыберите тайтл или язык для чтения:", parse_mode="HTML", reply_markup=get_ranobe_langs_menu("readranobelang"))
    except Exception:
        try: await callback.message.delete()
        except Exception: pass
        await callback.message.answer("📖 <b>Каталог Ранобэ</b>\nВыберите тайтл или язык для чтения:", parse_mode="HTML", reply_markup=get_ranobe_langs_menu("readranobelang"))

@dp.callback_query(F.data.startswith("readranobelang_"))
async def process_read_ranobe_chapters(callback: types.CallbackQuery):
    lang_code = callback.data.split("_")[1]
    chapters = await get_ranobe_chapters(lang_code)
    await callback.message.edit_text(f"📚 Доступные главы ({RANOBE_LANGUAGES[lang_code]}):", reply_markup=get_ranobe_chapters_menu(lang_code, chapters, page=0))

@dp.callback_query(F.data.startswith("page_manga_"))
async def process_manga_page_change(callback: types.CallbackQuery):
    _, _, lang_code, page_str = callback.data.split("_")
    chapters = await get_chapters(lang_code)
    await callback.message.edit_reply_markup(reply_markup=get_chapters_menu(lang_code, chapters, page=int(page_str)))

@dp.callback_query(F.data.startswith("page_ranobe_"))
async def process_ranobe_page_change(callback: types.CallbackQuery):
    _, _, lang_code, page_str = callback.data.split("_")
    chapters = await get_ranobe_chapters(lang_code)
    await callback.message.edit_reply_markup(reply_markup=get_ranobe_chapters_menu(lang_code, chapters, page=int(page_str)))

@dp.callback_query(F.data.startswith("read_manga_") | F.data.startswith("read_"))
async def send_chapter(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if await check_cd_and_warn(callback, "read", 5): return

    data = callback.data.split("_")
    is_ranobe = "ranobe" in data
    
    if is_ranobe:
        # read_ranobe_lang_num
        lang = data[2]
        chapter_num = data[3]
        link = await get_ranobe_chapter_link(lang, chapter_num)
    else:
        # read_lang_num
        lang = data[1]
        chapter_num = data[2]
        link = await get_chapter_link(lang, chapter_num)

    if link:
        is_url = link.startswith(("http://", "https://", "tg://", "t.me/", "telegra.ph/"))
        if is_url and not link.startswith(("http://", "https://", "tg://")):
            link = "https://" + link
        await callback.message.delete()
        
        builder = InlineKeyboardBuilder()
        if is_url:
            builder.button(text=f"🔗 Читать главу {chapter_num}", url=link)
        builder.button(text="📚 К главам", callback_data=f"readlang_{lang}")
        
        admins = await get_admins()
        if user_id in admins:
             builder.button(text="🗑 Удалить главу", callback_data=f"admin_del_{'ranobe' if is_ranobe else 'manga'}_{lang}_{chapter_num}")

        msg_text = "✅ Приятного чтения!"
        if not is_url and link and link != "-" and link.lower() != "нет" and link.lower() != "none":
            msg_text = f"✅ Глава {chapter_num}\n\n📝 <b>Текст:</b>\n{link}"

        await callback.message.answer(msg_text, reply_markup=builder.adjust(1).as_markup(), parse_mode="HTML")
    else:
        await callback.answer("Глава не найдена 😔", show_alert=True)

# --- Обработчик удаления главы с карточки чтения ---
@dp.callback_query(F.data.startswith("admin_del_manga_") | F.data.startswith("admin_del_ranobe_"))
async def process_admin_del_chapter_item(callback: types.CallbackQuery):
    admins = await get_admins()
    if callback.from_user.id not in admins:
         return await callback.answer("❌ У вас нет прав!", show_alert=True)

    data = callback.data.split("_")
    is_ranobe = data[2] == "ranobe"
    lang = data[3]
    chapter_num = data[4]

    async with aiosqlite.connect('manga.db') as db:
         if is_ranobe:
              cursor = await db.execute('DELETE FROM ranobe_urls WHERE chapter_number = ? AND lang = ?', (chapter_num, lang))
         else:
              cursor = await db.execute('DELETE FROM chapters_urls WHERE chapter_number = ? AND lang = ?', (chapter_num, lang))
         await db.commit()
         deleted = cursor.rowcount > 0

    if deleted:
         await callback.answer("✅ Глава успешно удалена!", show_alert=True)
         await callback.message.delete()
    else:
         await callback.answer("❌ Ошибка удаления или глава не найдена.", show_alert=True)

# --- ХРОНИКИ АКАШИ (READ) ---
@dp.callback_query(F.data == "akashic_vols")
@dp.callback_query(AkashicCallback.filter(F.action == "vols"))
async def akashic_show_volumes(callback: types.CallbackQuery):
    volumes = await get_akashic_volumes()
    builder = InlineKeyboardBuilder()
    if not volumes:
        builder.row(types.InlineKeyboardButton(text="Тома пока не добавлены 😔", callback_data="empty"))
        builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="read_ranobe_langs"))
        return await callback.message.edit_text("📖 <b>Хроники Акаши</b>\nНет добавленных томов:", reply_markup=builder.as_markup(), parse_mode="HTML")
    for vol in volumes:
        builder.button(text=f"Том {vol}", callback_data=AkashicCallback(action="chaps", volume=vol).pack())
    builder.adjust(2)
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="read_ranobe_langs"))
    await callback.message.edit_text("📖 <b>Хроники Акаши</b>\nВыберите том:", reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(AkashicCallback.filter(F.action == "chaps"))
async def akashic_show_chapters(callback: types.CallbackQuery, callback_data: AkashicCallback):
    chapters = await get_akashic_chapters(callback_data.volume)
    builder = InlineKeyboardBuilder()
    for chap in chapters:
        builder.button(text=f"Глава {chap}", callback_data=AkashicCallback(action="read", volume=callback_data.volume, chapter=chap).pack())
    builder.adjust(3)
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад к томам", callback_data=AkashicCallback(action="vols").pack()))
    await callback.message.edit_text(f"📖 <b>Хроники Акаши</b> — Том {callback_data.volume}\nВыберите главу:", reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(AkashicCallback.filter(F.action == "read"))
async def akashic_read_chapter(callback: types.CallbackQuery, callback_data: AkashicCallback):
    url = await get_akashic_chapter_link(callback_data.volume, callback_data.chapter)
    if url:
        is_url = url.startswith(("http://", "https://", "tg://", "t.me/", "telegra.ph/"))
        if is_url and not url.startswith(("http://", "https://", "tg://")):
            url = "https://" + url
        builder = InlineKeyboardBuilder()
        if is_url:
            builder.button(text=f"🔗 Читать главу {callback_data.chapter}", url=url)
        builder.button(text="📚 К главам", callback_data=AkashicCallback(action="chaps", volume=callback_data.volume).pack())
        
        admins = await get_admins()
        if callback.from_user.id in admins:
            builder.button(text="🗑 Удалить главу", callback_data=f"admin_del_akashic_{callback_data.volume}_{callback_data.chapter}")

        await callback.message.delete()
        msg_text = f"✅ <b>Хроники Акаши</b> — Том {callback_data.volume}, Глава {callback_data.chapter}"
        if not is_url and url and url != "-" and url.lower() != "нет" and url.lower() != "none":
            msg_text += f"\n\n📝 <b>Текст:</b>\n{url}"
        else:
            msg_text += "\nПриятного чтения!"
        await callback.message.answer(msg_text, reply_markup=builder.adjust(1).as_markup(), parse_mode="HTML")
    else:
        await callback.answer("Глава не найдена 😔", show_alert=True)

@dp.callback_query(F.data.startswith("admin_del_akashic_"))
async def process_admin_del_akashic_item(callback: types.CallbackQuery):
    admins = await get_admins()
    if callback.from_user.id not in admins:
         return await callback.answer("❌ У вас нет прав!", show_alert=True)
    data = callback.data.split("_")
    volume, chapter = int(data[3]), data[4]
    async with aiosqlite.connect('manga.db') as db:
         cursor = await db.execute('DELETE FROM akashic_ranobe WHERE volume = ? AND chapter = ?', (volume, chapter))
         await db.commit()
         deleted = cursor.rowcount > 0
    if deleted:
         await callback.answer("✅ Глава успешно удалена!", show_alert=True)
         await callback.message.delete()
    else:
         await callback.answer("❌ Ошибка удаления.", show_alert=True)

# --- БРИТАНСКАЯ КРАСАВИЦА (READ) ---
@dp.callback_query(F.data == "british_vols")
@dp.callback_query(BritishCallback.filter(F.action == "vols"))
async def british_show_volumes(callback: types.CallbackQuery):
    volumes = await get_british_volumes()
    builder = InlineKeyboardBuilder()
    if not volumes:
        builder.row(types.InlineKeyboardButton(text="Тома пока не добавлены 😔", callback_data="empty"))
        builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="read_ranobe_langs"))
        return await callback.message.edit_text("👸 <b>Британская красавица</b>\nНет добавленных томов:", reply_markup=builder.as_markup(), parse_mode="HTML")
    for vol in volumes:
        builder.button(text=f"Том {vol}", callback_data=BritishCallback(action="chaps", volume=vol).pack())
    builder.adjust(2)
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="read_ranobe_langs"))
    await callback.message.edit_text("👸 <b>Британская красавица</b>\nВыберите том:", reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(BritishCallback.filter(F.action == "chaps"))
async def british_show_chapters(callback: types.CallbackQuery, callback_data: BritishCallback):
    chapters = await get_british_chapters(callback_data.volume)
    builder = InlineKeyboardBuilder()
    for chap in chapters:
        builder.button(text=f"Глава {chap}", callback_data=BritishCallback(action="read", volume=callback_data.volume, chapter=chap).pack())
    builder.adjust(3)
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад к томам", callback_data=BritishCallback(action="vols").pack()))
    await callback.message.edit_text(f"👸 <b>Британская красавица</b> — Том {callback_data.volume}\nВыберите главу:", reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(BritishCallback.filter(F.action == "read"))
async def british_read_chapter(callback: types.CallbackQuery, callback_data: BritishCallback):
    url = await get_british_chapter_link(callback_data.volume, callback_data.chapter)
    if url:
        is_url = url.startswith(("http://", "https://", "tg://", "t.me/", "telegra.ph/"))
        if is_url and not url.startswith(("http://", "https://", "tg://")):
            url = "https://" + url
        builder = InlineKeyboardBuilder()
        if is_url:
            builder.button(text=f"🔗 Читать главу {callback_data.chapter}", url=url)
        builder.button(text="📚 К главам", callback_data=BritishCallback(action="chaps", volume=callback_data.volume).pack())
        
        admins = await get_admins()
        if callback.from_user.id in admins:
            builder.button(text="🗑 Удалить главу", callback_data=f"admin_del_british_{callback_data.volume}_{callback_data.chapter}")

        msg_text = f"✅ <b>Британская красавица</b> — Том {callback_data.volume}, Глава {callback_data.chapter}"
        if not is_url and url and url != "-" and url.lower() != "нет" and url.lower() != "none":
            msg_text += f"\n\n📝 <b>Текст:</b>\n{url}"
        else:
            msg_text += "\nПриятного чтения!"
        await callback.message.answer(msg_text, reply_markup=builder.adjust(1).as_markup(), parse_mode="HTML")
    else:
        await callback.answer("Глава не найдена 😔", show_alert=True)

@dp.callback_query(F.data.startswith("admin_del_british_"))
async def process_admin_del_british_item(callback: types.CallbackQuery):
    admins = await get_admins()
    if callback.from_user.id not in admins:
         return await callback.answer("❌ У вас нет прав!", show_alert=True)
    data = callback.data.split("_")
    volume, chapter = int(data[3]), data[4]
    async with aiosqlite.connect('manga.db') as db:
         cursor = await db.execute('DELETE FROM british_ranobe WHERE volume = ? AND chapter = ?', (volume, chapter))
         await db.commit()
         deleted = cursor.rowcount > 0
    if deleted:
         await callback.answer("✅ Глава успешно удалена!", show_alert=True)
         await callback.message.delete()
    else:
         await callback.answer("❌ Ошибка удаления.", show_alert=True)

# --- Обработчики перехода по страницам Глав ---
@dp.callback_query(F.data.startswith("jump_manga_"))
async def trigger_manga_jump(callback: types.CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[2]
    await state.set_state(ChapterJump.waiting_for_manga_page)
    await state.update_data(lang=lang)
    await callback.message.answer("🔢 <b>Введите номер страницы</b> (например, 2):", parse_mode="HTML")
    await callback.answer()

@dp.message(ChapterJump.waiting_for_manga_page, F.text.isdigit())
async def handle_manga_jump(message: types.Message, state: FSMContext):
    page = int(message.text) - 1
    data = await state.get_data()
    lang = data.get("lang")
    await state.clear()
    
    chapters = await get_chapters(lang)
    total_pages = math.ceil(len(chapters) / ITEMS_PER_PAGE)
    if page < 0 or page >= total_pages:
        return await message.answer(f"❌ Неверный номер страницы! Доступно от 1 до {total_pages}.")

    await message.answer(f"Перехожу на страницу {page + 1}...")
    await message.answer(f"📚 Доступные главы:", reply_markup=get_chapters_menu(lang, chapters, page=page))

@dp.callback_query(F.data.startswith("jump_ranobe_"))
async def trigger_ranobe_jump(callback: types.CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[2]
    await state.set_state(ChapterJump.waiting_for_ranobe_page)
    await state.update_data(lang=lang)
    await callback.message.answer("🔢 <b>Введите номер страницы ранобэ</b> (например, 2):", parse_mode="HTML")
    await callback.answer()

@dp.message(ChapterJump.waiting_for_ranobe_page, F.text.isdigit())
async def handle_ranobe_jump(message: types.Message, state: FSMContext):
    page = int(message.text) - 1
    data = await state.get_data()
    lang = data.get("lang")
    await state.clear()
    
    chapters = await get_ranobe_chapters(lang)
    total_pages = math.ceil(len(chapters) / ITEMS_PER_PAGE)
    if page < 0 or page >= total_pages:
        return await message.answer(f"❌ Неверный номер страницы! Доступно от 1 до {total_pages}.")

    await message.answer(f"Перехожу на страницу {page + 1}...")
    await message.answer(f"📚 Доступные главы (Ранобэ):", reply_markup=get_ranobe_chapters_menu(lang, chapters, page=page))

# --- Обработчик удаления арта для обывателя (Админская кнопка в User View) ---
@dp.callback_query(F.data.startswith("user_art_delete:"))
async def process_user_art_delete(callback: types.CallbackQuery):
    admins = await get_admins()
    if callback.from_user.id not in admins:
         return await callback.answer("❌ У вас нет прав!", show_alert=True)

    data = callback.data.split(":")
    art_id = int(data[1])
    index = int(data[2])

    if await delete_art_by_id(art_id):
         await callback.answer("✅ Арт успешно удален.")
         await send_user_art_item(callback.message.chat.id, index, user_id=callback.from_user.id, message_to_edit=callback.message)
    else:
         await callback.answer("❌ Ошибка при удалении арта.", show_alert=True)

async def send_user_art_item(chat_id: int, index: int, user_id: int, message_to_edit: types.Message = None):
    arts = await get_all_arts()
    if not arts:
        if message_to_edit:
            try: await message_to_edit.delete() 
            except Exception: pass
        await bot.send_message(chat_id, "Галерея пуста 😔", reply_markup=get_back_button())
        return

    # Зацикливание индекса
    if index < 0: index = len(arts) - 1
    if index >= len(arts): index = 0

    art_id, file_id = arts[index]

    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="⬅️", callback_data=f"user_art_view:{index - 1}"),
        types.InlineKeyboardButton(text="➡️", callback_data=f"user_art_view:{index + 1}")
    )
    builder.row(
        types.InlineKeyboardButton(text="🎲 Случайный арт", callback_data="user_art_random"),
        types.InlineKeyboardButton(text="🔢 Номер арта", callback_data="user_art_input")
    )
    
    admins = await get_admins()
    if user_id in admins:
         builder.row(types.InlineKeyboardButton(text="🗑 Удалить арт", callback_data=f"user_art_delete:{art_id}:{index}"))

    builder.row(types.InlineKeyboardButton(text="📱 Режим сетки (9 шт)", callback_data="user_art_grid:0"))
    builder.row(types.InlineKeyboardButton(text="⬅️ В меню", callback_data="main_menu"))

    caption = f"🎨 <b>Арт №{index + 1}</b> (всего {len(arts)})"

    if message_to_edit:
        try:
            await message_to_edit.edit_media(
                media=types.InputMediaPhoto(media=file_id, caption=caption, parse_mode="HTML"),
                reply_markup=builder.as_markup()
            )
        except Exception as e:
            if "not modified" not in str(e).lower():
                await bot.send_photo(chat_id, photo=file_id, caption=caption, parse_mode="HTML", reply_markup=builder.as_markup())
                try: await message_to_edit.delete() 
                except Exception: pass
    else:
        await bot.send_photo(chat_id, photo=file_id, caption=caption, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "view_arts")
async def view_arts(callback: types.CallbackQuery):
    if await check_cd_and_warn(callback, "arts", 5): return
    await callback.message.delete()
    await send_user_art_item(callback.message.chat.id, 0, user_id=callback.from_user.id)

@dp.callback_query(F.data.startswith("user_art_view:"))
async def process_user_art_view(callback: types.CallbackQuery, state: FSMContext):
    # Очистка сетки если она была
    data = await state.get_data()
    if "user_grid_photos" in data:
        for mid in data.get("user_grid_photos", []):
            try: await bot.delete_message(callback.message.chat.id, mid)
            except Exception: pass
        await state.update_data(user_grid_photos=[])

    index = int(callback.data.split(":")[1])
    await send_user_art_item(callback.message.chat.id, index, user_id=callback.from_user.id, message_to_edit=callback.message)
    await callback.answer()

@dp.callback_query(F.data == "user_art_random")
async def process_user_art_random(callback: types.CallbackQuery):
    arts = await get_all_arts()
    if not arts:
        return await callback.answer("Галерея пуста 😔", show_alert=True)
    index = random.randint(0, len(arts) - 1)
    await send_user_art_item(callback.message.chat.id, index, user_id=callback.from_user.id, message_to_edit=callback.message)
    await callback.answer("🎲 Случайный арт!")

@dp.callback_query(F.data == "user_art_input")
async def process_user_art_input(callback: types.CallbackQuery, state: FSMContext):
    arts = await get_all_arts()
    if not arts:
         return await callback.answer("Галерея пуста 😔", show_alert=True)
    await state.set_state(ArtView.waiting_for_number)
    await callback.message.answer(f"🔢 <b>Переход к арту</b>\nВведите номер арта от 1 до {len(arts)}:", parse_mode="HTML")
    await callback.answer()

@dp.message(ArtView.waiting_for_number, F.text.isdigit())
async def handle_art_number_input(message: types.Message, state: FSMContext):
    await state.clear()
    num = int(message.text)
    arts = await get_all_arts()
    if 1 <= num <= len(arts):
        await send_user_art_item(message.chat.id, num - 1, user_id=message.from_user.id)
    else:
        await message.answer(f"❌ Неверный номер! Введите число от 1 до {len(arts)}.")

@dp.callback_query(F.data.startswith("user_art_grid:"))
async def process_user_art_grid(callback: types.CallbackQuery, state: FSMContext):
    # Очистка предыдущей сетки
    data = await state.get_data()
    for mid in data.get("user_grid_photos", []):
        try: await bot.delete_message(callback.message.chat.id, mid)
        except Exception: pass

    page = int(callback.data.split(":")[1])
    arts = await get_all_arts()
    if not arts:
        return await callback.answer("Галерея пуста 😔", show_alert=True)
    
    limit = 9
    total_pages = math.ceil(len(arts) / limit)
    if page < 0: page = 0
    if page >= total_pages: page = total_pages - 1
    
    start = page * limit
    end = min(start + limit, len(arts))
    sliced = arts[start:end]
    
    if not sliced:
        return await callback.answer("Больше нет артов.", show_alert=True)

    await callback.message.delete()
    
    media = [InputMediaPhoto(media=row[1]) for row in sliced]
    messages = await bot.send_media_group(chat_id=callback.message.chat.id, media=media)
    photo_ids = [m.message_id for m in messages]

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="⬅️ Пред. стр", callback_data=f"user_art_grid:{page - 1}")
    if page < total_pages - 1:
        builder.button(text="След. стр ➡️", callback_data=f"user_art_grid:{page + 1}")
    
    builder.row(
        types.InlineKeyboardButton(text="🎚 К слайдеру", callback_data=f"user_art_view:{start}"),
        types.InlineKeyboardButton(text="🔢 Номер арта", callback_data="grid_art_input")
    )
    builder.row(
        types.InlineKeyboardButton(text="📄 На страницу", callback_data="grid_page_input"),
        types.InlineKeyboardButton(text="⬅️ В меню", callback_data="main_menu")
    )
    
    art_from = start + 1
    art_to = end
    control_msg = await callback.message.answer(
        f"📱 <b>Сетка артов</b>\n"
        f"🎨 Арты <b>{art_from}–{art_to}</b> из {len(arts)}\n"
        f"📄 Страница <b>{page + 1}</b> из <b>{total_pages}</b>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

    all_ids = photo_ids + [control_msg.message_id]
    await state.update_data(user_grid_photos=all_ids)

    async def auto_cleanup(chat_id: int, ids: list, fsm_state: FSMContext):
        await asyncio.sleep(120)
        # Проверяем, что текущие IDs в стейте совпадают — если нет, юзер перелистнул
        data = await fsm_state.get_data()
        current_ids = data.get('user_grid_photos', [])
        if set(ids) != set(current_ids):
            return  # Устаревшая таска, данные уже удалены при перелистывании
        for mid in ids:
            try: await bot.delete_message(chat_id, mid)
            except Exception: pass
    asyncio.create_task(auto_cleanup(callback.message.chat.id, all_ids, state))

# --- Ввод номера страницы в сетке ---
@dp.callback_query(F.data == "grid_page_input")
async def process_grid_page_input(callback: types.CallbackQuery, state: FSMContext):
    arts = await get_all_arts()
    if not arts:
        return await callback.answer("Галерея пуста 😔", show_alert=True)
    total_pages = math.ceil(len(arts) / 9)
    await state.set_state(ArtView.waiting_for_grid_page)
    await callback.message.answer(
        f"📄 <b>Переход к странице</b>\nВведите номер страницы от 1 до {total_pages}:",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(ArtView.waiting_for_grid_page, F.text.isdigit())
async def handle_grid_page_input(message: types.Message, state: FSMContext):
    await state.clear()
    num = int(message.text)
    arts = await get_all_arts()
    total_pages = math.ceil(len(arts) / 9)
    if 1 <= num <= total_pages:
        # Эмулируем нажатие кнопки сетки
        limit = 9
        page = num - 1
        start = page * limit
        end = min(start + limit, len(arts))
        sliced = arts[start:end]
        
        media = [InputMediaPhoto(media=row[1]) for row in sliced]
        await bot.send_media_group(chat_id=message.chat.id, media=media)
        
        builder = InlineKeyboardBuilder()
        if page > 0:
            builder.button(text="⬅️ Пред. стр", callback_data=f"user_art_grid:{page - 1}")
        if page < total_pages - 1:
            builder.button(text="След. стр ➡️", callback_data=f"user_art_grid:{page + 1}")
        builder.row(
            types.InlineKeyboardButton(text="🎚 К слайдеру", callback_data=f"user_art_view:{start}"),
            types.InlineKeyboardButton(text="🔢 Номер арта", callback_data="grid_art_input")
        )
        builder.row(
            types.InlineKeyboardButton(text="📄 На страницу", callback_data="grid_page_input"),
            types.InlineKeyboardButton(text="⬅️ В меню", callback_data="main_menu")
        )
        await message.answer(
            f"📱 <b>Сетка артов</b>\n"
            f"🎨 Арты <b>{start+1}–{end}</b> из {len(arts)}\n"
            f"📄 Страница <b>{page+1}</b> из <b>{total_pages}</b>",
            parse_mode="HTML", reply_markup=builder.as_markup()
        )
    else:
        await message.answer(f"❌ Неверный номер! Введите от 1 до {total_pages}.")

# --- Ввод номера арта из сетки ---
@dp.callback_query(F.data == "grid_art_input")
async def process_grid_art_input(callback: types.CallbackQuery, state: FSMContext):
    arts = await get_all_arts()
    if not arts:
        return await callback.answer("Галерея пуста 😔", show_alert=True)
    await state.set_state(ArtView.waiting_for_grid_art_number)
    await callback.message.answer(
        f"🔢 <b>Переход к арту</b>\nВведите номер арта от 1 до {len(arts)}:",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(ArtView.waiting_for_grid_art_number, F.text.isdigit())
async def handle_grid_art_number_input(message: types.Message, state: FSMContext):
    await state.clear()
    num = int(message.text)
    arts = await get_all_arts()
    if 1 <= num <= len(arts):
        await send_user_art_item(message.chat.id, num - 1, user_id=message.from_user.id)
    else:
        await message.answer(f"❌ Неверный номер! Введите от 1 до {len(arts)}.")


# ==============================================================================
# БЛОК 10: АДМИН-ПАНЕЛЬ
# ==============================================================================
@dp.message(Command("add_admin"))
async def cmd_add_admin(message: types.Message):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    try:
        new_admin = int(message.text.split()[1])
        await add_admin(new_admin)
        await message.answer(f"✅ Пользователь {new_admin} назначен администратором.")
    except (IndexError, ValueError):
        await message.answer("❌ Формат: /add_admin <id_пользователя>")

@dp.message(Command("delete_admin"))
async def cmd_delete_admin(message: types.Message):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    try:
        del_admin = int(message.text.split()[1])
        if del_admin == 6210312655:
            return await message.answer("❌ Главного администратора удалить нельзя!")
        await remove_admin(del_admin)
        await message.answer(f"✅ Пользователь {del_admin} удален из администраторов.")
    except (IndexError, ValueError):
        await message.answer("❌ Формат: /delete_admin <id_пользователя>")

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="➕ Добавить Главу", callback_data="admin_add_chapter"),
        types.InlineKeyboardButton(text="🗑 Удалить Главу", callback_data="admin_del_chapter")
    )
    builder.row(
        types.InlineKeyboardButton(text="🔄 Синхронизация WebApp (Github)", callback_data="admin_sync_webapp")
    )
    builder.row(
        types.InlineKeyboardButton(text="🤖 Настройки ИИ", callback_data="admin_ai_settings")
    )
    builder.row(
        types.InlineKeyboardButton(text="🔔 Тест уведомлений", callback_data="admin_cmd_test_notification")
    )
    
    text = "👑 <b>Панель управления:</b>\nВыберите действие:"
    await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "admin_menu")
async def admin_menu_back(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="➕ Добавить Главу", callback_data="admin_add_chapter"),
        types.InlineKeyboardButton(text="🗑 Удалить Главу", callback_data="admin_del_chapter")
    )
    builder.row(
        types.InlineKeyboardButton(text="🔄 Синхронизация WebApp (Github)", callback_data="admin_sync_webapp")
    )
    builder.row(
        types.InlineKeyboardButton(text="🤖 Настройки ИИ", callback_data="admin_ai_settings")
    )
    builder.row(
        types.InlineKeyboardButton(text="🔔 Тест уведомлений", callback_data="admin_cmd_test_notification")
    )
    await callback.message.edit_text("👑 <b>Панель управления:</b>\nВыберите действие:", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "admin_add_chapter")
async def admin_menu_add_chapter(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="Манга", callback_data="admin_cmd_add_chapter"),
        types.InlineKeyboardButton(text="Ранобэ", callback_data="admin_cmd_add_ranobe")
    )
    builder.row(
        types.InlineKeyboardButton(text="Хроники Акаши", callback_data="admin_cmd_add_akashic"),
        types.InlineKeyboardButton(text="Брит. красавица", callback_data="admin_cmd_add_british")
    )
    builder.row(types.InlineKeyboardButton(text="Арт", callback_data="admin_cmd_add_art"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu"))
    await callback.message.edit_text("➕ <b>Что добавить?</b>", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "admin_del_chapter")
async def admin_menu_del_chapter(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="Манга", callback_data="admin_cmd_delete_chapter"),
        types.InlineKeyboardButton(text="Ранобэ", callback_data="admin_cmd_delete_ranobe")
    )
    builder.row(
        types.InlineKeyboardButton(text="Хроники Акаши", callback_data="admin_cmd_delete_akashic"),
        types.InlineKeyboardButton(text="Брит. красавица", callback_data="admin_cmd_delete_british")
    )
    builder.row(types.InlineKeyboardButton(text="Арт", callback_data="admin_cmd_delete_art"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu"))
    await callback.message.edit_text("🗑 <b>Что удалить?</b>", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "admin_ai_settings")
async def admin_menu_ai_settings(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="Вкл/выкл ИИ", callback_data="admin_cmd_toggle_ai"),
        types.InlineKeyboardButton(text="Режим Али", callback_data="admin_cmd_alya_mode")
    )
    builder.row(
        types.InlineKeyboardButton(text="ЧС (ИИ)", callback_data="admin_cmd_blacklist_ai"),
        types.InlineKeyboardButton(text="Удалить из ЧС", callback_data="admin_cmd_unblacklist_ai")
    )
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu"))
    await callback.message.edit_text("🤖 <b>Настройки ИИ:</b>", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "admin_sync_webapp")
async def admin_menu_sync_webapp(callback: types.CallbackQuery):
    await callback.message.delete()
    await cmd_sync_webapp(callback.message)
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_cmd_"))
async def admin_menu_commands(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.delete()
    cmd = callback.data.replace("admin_cmd_", "")
    
    try:
        msg = callback.message.model_copy(update={"from_user": callback.from_user, "text": f"/{cmd}"})
    except AttributeError:
        msg = callback.message.copy(update={"from_user": callback.from_user, "text": f"/{cmd}"})
        
    commands = {
        "add_chapter": cmd_add_chapter,
        "add_ranobe": cmd_add_ranobe,
        "add_akashic": cmd_add_akashic,
        "add_british": cmd_add_british,
        "add_art": cmd_add_art,
        "delete_chapter": cmd_delete_chapter,
        "delete_ranobe": cmd_delete_ranobe,
        "delete_akashic": cmd_delete_akashic,
        "delete_british": cmd_delete_british,
        "delete_art": cmd_delete_art,
        "toggle_ai": cmd_toggle_ai,
        "alya_mode": cmd_alya_mode,
        "blacklist_ai": cmd_blacklist_ai,
        "unblacklist_ai": cmd_unblacklist_ai,
        "test_notification": cmd_test_notification
    }
    
    if cmd in commands:
        if "add" in cmd or "delete" in cmd:
            await commands[cmd](msg, state)
        else:
            await commands[cmd](msg)
    await callback.answer()

import json
import os
import re


async def build_reader_data() -> dict:
    import aiosqlite
    from aiogram import Bot
    
    # Пытаемся получить имя бота, чтобы WebApp мог генерировать правильные deeplink-и
    bot_username = "Alyamangapage_bot"
    try:
        me = await bot.get_me()
        bot_username = me.username
    except:
        pass

    result = {"series": [], "bot_username": bot_username}
    
    async with aiosqlite.connect('manga.db') as db:
        # ПРЕДЗАГРУЗКА: Читаем все кастомные имена разом (решение N+1 Query)
        custom_names = {}
        async with db.execute('SELECT id, name FROM custom_names') as c:
            for row in await c.fetchall():
                custom_names[row[0]] = row[1]

        async with db.execute('SELECT DISTINCT volume FROM akashic_ranobe ORDER BY volume') as cursor:
            ak_vols = [row[0] for row in await cursor.fetchall()]
        if ak_vols:
            custom_title = custom_names.get("series_akashic_records") or "Хроники Акаши"
            akashic = {"id": "akashic_records", "title": custom_title, "cover_url": custom_names.get("cover_akashic_records", ""), "volumes": []}
            for vol in ak_vols:
                custom_vol = custom_names.get(f"vol_akashic_records_{vol}") or f"Том {vol}"
                async with db.execute('SELECT chapter, url FROM akashic_ranobe WHERE volume = ? ORDER BY sort_order, CAST(chapter AS REAL)', (vol,)) as c:
                    chapters = []
                    for row in await c.fetchall():
                        extracted = _clean_urls(row[1])
                        url_val = extracted[0] if len(extracted) == 1 else ""
                        custom_chap = custom_names.get(f"chap_akashic_records_{vol}_{row[0]}") or f"Глава {row[0]}"
                        chapters.append({"chapter": row[0], "custom_name": custom_chap, "url": url_val, "urls": extracted})
                akashic["volumes"].append({"volume": vol, "custom_name": custom_vol, "chapters": chapters})
            result["series"].append(akashic)
            
        async with db.execute('SELECT DISTINCT volume FROM british_ranobe ORDER BY volume') as cursor:
            br_vols = [row[0] for row in await cursor.fetchall()]
        if br_vols:
            custom_title = custom_names.get("series_british_belle") or "Поцелуй британской красавицы"
            british = {"id": "british_belle", "title": custom_title, "cover_url": custom_names.get("cover_british_belle", ""), "volumes": []}
            for vol in br_vols:
                custom_vol = custom_names.get(f"vol_british_belle_{vol}") or f"Том {vol}"
                async with db.execute('SELECT chapter, url FROM british_ranobe WHERE volume = ? ORDER BY sort_order, CAST(chapter AS REAL)', (vol,)) as c:
                    chapters = []
                    for row in await c.fetchall():
                        extracted = _clean_urls(row[1])
                        url_val = extracted[0] if len(extracted) == 1 else ""
                        custom_chap = custom_names.get(f"chap_british_belle_{vol}_{row[0]}") or f"Глава {row[0]}"
                        chapters.append({"chapter": row[0], "custom_name": custom_chap, "url": url_val, "urls": extracted})
                british["volumes"].append({"volume": vol, "custom_name": custom_vol, "chapters": chapters})
            result["series"].append(british)
            
        async with db.execute('SELECT DISTINCT lang FROM ranobe_urls') as cursor:
            langs_ro = [row[0] for row in await cursor.fetchall()]
        for lang in langs_ro:
            async with db.execute('SELECT chapter_number, url FROM ranobe_urls WHERE lang = ? ORDER BY sort_order, CAST(chapter_number AS REAL)', (lang,)) as c:
                chapters = []
                for row in await c.fetchall():
                    extracted = _clean_urls(row[1])
                    url_val = extracted[0] if len(extracted) == 1 else ""
                    custom_chap = custom_names.get(f"chap_ranobe_{lang}_1_{row[0]}") or f"Глава {row[0]}"
                    chapters.append({"chapter": row[0], "custom_name": custom_chap, "url": url_val, "urls": extracted})
            if chapters:
                lname = "Русский" if lang == "ru" else "English" if lang == "en" else lang
                custom_title = custom_names.get(f"series_ranobe_{lang}") or f"Ранобэ ({lname})"
                custom_vol = custom_names.get(f"vol_ranobe_{lang}_1") or "Том 1"
                result["series"].append({
                    "id": f"ranobe_{lang}", "title": custom_title, "cover_url": custom_names.get(f"cover_ranobe_{lang}", ""), "volumes": [{"volume": 1, "custom_name": custom_vol, "chapters": chapters}]
                })
                
        async with db.execute('SELECT DISTINCT lang FROM chapters_urls') as cursor:
            langs_mg = [row[0] for row in await cursor.fetchall()]
        for lang in langs_mg:
            async with db.execute('SELECT chapter_number, url FROM chapters_urls WHERE lang = ? ORDER BY sort_order, CAST(chapter_number AS REAL)', (lang,)) as c:
                chapters = []
                for row in await c.fetchall():
                    extracted = _clean_urls(row[1])
                    url_val = extracted[0] if len(extracted) == 1 else ""
                    custom_chap = custom_names.get(f"chap_manga_{lang}_1_{row[0]}") or f"Глава {row[0]}"
                    chapters.append({"chapter": row[0], "custom_name": custom_chap, "url": url_val, "urls": extracted})
            if chapters:
                lname = "Русский" if lang == "ru" else "English" if lang == "en" else lang
                custom_title = custom_names.get(f"series_manga_{lang}") or f"Манга ({lname})"
                custom_vol = custom_names.get(f"vol_manga_{lang}_1") or "Том 1"
                result["series"].append({
                    "id": f"manga_{lang}", "title": custom_title, "cover_url": custom_names.get(f"cover_manga_{lang}", ""), "volumes": [{"volume": 1, "custom_name": custom_vol, "chapters": chapters}]
                })
                
    # ДОПОЛНИТЕЛЬНО: Инъекция глав без ссылок, но с кастомными именами
    # Это позволяет переименовывать главы, которых еще нет в БД ссылок.
    for key, name in custom_names.items():
        if not key.startswith("chap_"): continue
        parts = key.split("_")
        # chap_seriesId_vol_chapNum  -> parts: [chap, series, id, vol, chapNum]
        # Но series_id может содержать подчеркивания (manga_ru), так что парсим аккуратнее.
        if parts[1] == "akashic" and parts[2] == "records":
            s_id, vol, chap = "akashic_records", parts[3], parts[4]
        elif parts[1] == "british" and parts[2] == "belle":
            s_id, vol, chap = "british_belle", parts[3], parts[4]
        else:
            s_id, vol, chap = f"{parts[1]}_{parts[2]}", parts[3], parts[4]
            
        # Ищем серию в результате
        target_series = next((s for s in result["series"] if s["id"] == s_id), None)
        if not target_series:
            # Если серии нет, создаем "призрачную" серию?
            # Лучше не надо, чтобы не захламлять. Только если база хоть что-то знает о серии.
            continue
            
        # Ищем том
        target_vol = next((v for v in target_series["volumes"] if str(v["volume"]) == str(vol)), None)
        if not target_vol:
            # Если тома нет, добавляем его
            target_vol = {"volume": int(vol), "custom_name": custom_names.get(f"vol_{s_id}_{vol}") or f"Том {vol}", "chapters": []}
            target_series["volumes"].append(target_vol)
            target_series["volumes"].sort(key=lambda x: x["volume"])
            
        # Ищем главу
        if not any(str(c["chapter"]) == str(chap) for c in target_vol["chapters"]):
            target_vol["chapters"].append({
                "chapter": chap,
                "custom_name": name,
                "url": "",
                "urls": []
            })
            # Сортируем главы
            try:
                target_vol["chapters"].sort(key=lambda x: (float(x["chapter"]) if str(x["chapter"]).replace('.','',1).isdigit() else 0))
            except: pass

    return result


def _clean_urls(url_text: str) -> list:
    # Ищем все ссылки
    links = re.findall(r'(https?://[^\s<"\'>]+)', url_text)
    return links

@dp.message(Command("toggle_sync"))
async def cmd_toggle_sync(message: types.Message):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('CREATE TABLE IF NOT EXISTS sync_settings (id INTEGER PRIMARY KEY, locked INTEGER DEFAULT 0)')
        async with db.execute('SELECT locked FROM sync_settings WHERE id = 1') as cursor:
            row = await cursor.fetchone()
        
        if not row:
            locked = 1
            await db.execute('INSERT INTO sync_settings (id, locked) VALUES (1, 1)')
        else:
            locked = 0 if row[0] else 1
            await db.execute('UPDATE sync_settings SET locked = ? WHERE id = 1', (locked,))
        await db.commit()
        
        if locked:
            await message.answer("🔒 <b>Синхронизация заблокирована!</b>\nТеперь команда /sync_webapp не будет работать и ваши данные в WebApp в полной безопасности от перезаписи. Чтобы разблокировать, введите команду снова.", parse_mode="HTML")
        else:
            await message.answer("🔓 <b>Синхронизация разблокирована.</b>\nКоманда /sync_webapp снова активна.", parse_mode="HTML")


@dp.message(Command("sync_webapp"))
async def cmd_sync_webapp(message: types.Message):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    
    # Проверка на блокировку синхронизации
    async with aiosqlite.connect('manga.db') as db:
        try:
            async with db.execute('SELECT locked FROM sync_settings WHERE id = 1') as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    return await message.answer("🔒 Синхронизация сейчас заблокирована. Разблокируйте её командой /toggle_sync перед использованием.", parse_mode="HTML")
        except Exception:
            pass # Таблица еще не создана
    
    msg = await message.answer("🔄 <i>Собираем данные из БД для WebApp...</i>", parse_mode="HTML")
    try:
        # build_reader_data() сам читает custom_names из БД — источник истины один,
        # никакие кастомные имена не теряются даже при добавлении новых глав
        result = await build_reader_data()
        
        with open("webapp/chapters_data.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            
        await msg.edit_text("🔄 <i>Публикуем данные в Github Pages. Ожидайте...</i>", parse_mode="HTML")
        
        # Асинхронная git-синхронизация (не блокирует Event Loop)
        success, output = await run_git_sync("sync webapp db")
        
        if success:
            await msg.edit_text("✅ <b>Успешно!</b> Главы синхронизированы с WebApp. (Они появятся в приложении в течение 1-2 минут)", parse_mode="HTML")
        else:
            await msg.edit_text(f"⚠️ База обновлена локально. <code>git push</code> не прошел.\n\n<b>Ответ сервера:</b>\n<pre>{output}</pre>\n\nСкорее всего, у бота на сервере нет прав для git push.", parse_mode="HTML")
            
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        await msg.edit_text(f"❌ <b>Ошибка:</b> {e}\n<pre>{err_msg}</pre>", parse_mode="HTML")

@dp.message(Command("alya_mode"))
async def cmd_alya_mode(message: types.Message):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    new_mode = await toggle_alya_mode()
    await message.answer(f"✅ Режим Али изменен на: <b>{new_mode}</b>", parse_mode="HTML")

@dp.message(Command("blacklist_ai"))
async def cmd_blacklist_ai(message: types.Message):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    try:
        user_id = int(message.text.split()[1])
        if await add_to_blacklist(user_id):
            await message.answer(f"✅ Пользователь {user_id} добавлен в черный список ИИ.")
        else:
            await message.answer(f"Пользователь {user_id} УЖЕ в черном списке ИИ.")
    except (IndexError, ValueError):
        await message.answer("❌ Формат: /blacklist_ai <ID_пользователя>")

@dp.message(Command("unblacklist_ai"))
async def cmd_unblacklist_ai(message: types.Message):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    try:
        user_id = int(message.text.split()[1])
        if await remove_from_blacklist(user_id):
            await message.answer(f"✅ Пользователь {user_id} удален из черного списка ИИ.")
        else:
            await message.answer(f"Пользователя {user_id} НЕТ в черном списке ИИ.")
    except (IndexError, ValueError):
        await message.answer("❌ Формат: /unblacklist_ai <ID_пользователя>")

@dp.message(Command("blacklist_view"))
async def cmd_blacklist_view(message: types.Message):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    bl = await get_blacklist()
    if not bl:
        return await message.answer("📝 Чёрный список ИИ пуст.")
    lines = [f"<code>{uid}</code>" for uid in bl]
    await message.answer(f"🚫 <b>Чёрный список ИИ ({len(bl)}):</b>\n" + "\n".join(lines), parse_mode="HTML")

@dp.message(Command("set_commands_link"))
async def cmd_set_commands_link(message: types.Message):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    try:
        url = message.text.split(maxsplit=1)[1]
        await set_commands_link(url)
        await message.answer(f"✅ Установлена ссылка на все команды: {url}")
    except IndexError:
        await message.answer("❌ Формат: /set_commands_link <ссылка>")

@dp.message(Command("delete_commands_link"))
async def cmd_delete_commands_link(message: types.Message):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    await delete_commands_link()
    await message.answer("✅ Ссылка на все команды удалена.")

async def send_admin_art_item(chat_id: int, index: int, message_to_edit: types.Message = None):
    arts = await get_all_arts()
    if not arts:
        if message_to_edit:
            try: await message_to_edit.delete() 
            except: pass
        await bot.send_message(chat_id, "Галерея артов пуста 😔")
        return

    # Зацикливание индекса
    if index < 0: index = len(arts) - 1
    if index >= len(arts): index = 0

    art_id, file_id = arts[index]

    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_art_view:{index - 1}"),
        types.InlineKeyboardButton(text="Вперед ➡️", callback_data=f"admin_art_view:{index + 1}")
    )
    builder.row(
        types.InlineKeyboardButton(text="🔢 Номер арта", callback_data="admin_art_input"),
        types.InlineKeyboardButton(text="🗑 Удалить арт", callback_data=f"admin_art_delete:{art_id}:{index}")
    )
    builder.row(types.InlineKeyboardButton(text="📱 Режим сетки (9 шт)", callback_data="admin_art_grid:0"))

    caption = f"👑 <b>[Админ] Арт ID:</b> {art_id}\n<i>({index + 1} из {len(arts)})</i>"

    if message_to_edit:
        try:
            await message_to_edit.edit_media(
                media=types.InputMediaPhoto(media=file_id, caption=caption, parse_mode="HTML"),
                reply_markup=builder.as_markup()
            )
        except Exception as e:
            if "not modified" not in str(e).lower():
                # На случай осечки
                await bot.send_photo(chat_id, photo=file_id, caption=caption, parse_mode="HTML", reply_markup=builder.as_markup())
                try: await message_to_edit.delete() 
                except Exception: pass
    else:
        await bot.send_photo(chat_id, photo=file_id, caption=caption, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.message(Command("arts_list"))
async def cmd_arts_list(message: types.Message):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    await send_admin_art_item(message.chat.id, 0)

@dp.callback_query(F.data.startswith("admin_art_view:"))
async def process_admin_art_view(callback: types.CallbackQuery):
    index = int(callback.data.split(":")[1])
    await send_admin_art_item(callback.message.chat.id, index, message_to_edit=callback.message)
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_art_delete:"))
async def process_admin_art_delete(callback: types.CallbackQuery):
    data = callback.data.split(":")
    art_id = int(data[1])
    index = int(data[2])

    if await delete_art_by_id(art_id):
        await callback.answer("✅ Арт успешно удален.")
        # Показываем следующий или остаемся в листе
        await send_admin_art_item(callback.message.chat.id, index, message_to_edit=callback.message)
    else:
        await callback.answer("❌ Ошибка при удалении арт.", show_alert=True)

@dp.callback_query(F.data == "admin_art_input")
async def process_admin_art_input(callback: types.CallbackQuery, state: FSMContext):
    arts = await get_all_arts()
    if not arts:
         return await callback.answer("Галерея пуста 😔", show_alert=True)
    await state.set_state(ArtView.waiting_for_admin_number)
    await callback.message.answer(f"👑 <b>[Админ] Переход к арту</b>\nВведите номер арта от 1 до {len(arts)}:", parse_mode="HTML")
    await callback.answer()

@dp.message(ArtView.waiting_for_admin_number, F.text.isdigit())
async def handle_admin_art_number_input(message: types.Message, state: FSMContext):
    await state.clear()
    num = int(message.text)
    arts = await get_all_arts()
    if 1 <= num <= len(arts):
        await send_admin_art_item(message.chat.id, num - 1)
    else:
        await message.answer(f"❌ Неверный номер! Введите число от 1 до {len(arts)}.")

@dp.callback_query(F.data.startswith("admin_art_grid:"))
async def process_admin_art_grid(callback: types.CallbackQuery, state: FSMContext):
    # 1. Удаляем предыдущее превью (media group) если оно сохранено в state
    data = await state.get_data()
    prev_photos = data.get("grid_photos", [])
    for mid in prev_photos:
        try: await bot.delete_message(callback.message.chat.id, mid)
        except: pass

    page = int(callback.data.split(":")[1])
    arts = await get_all_arts()
    if not arts:
        return await callback.answer("Галерея пуста 😔", show_alert=True)
    
    limit = 9
    start = page * limit
    end = start + limit
    sliced = arts[start:end]
    
    if not sliced:
        return await callback.answer("Больше нет артов.", show_alert=True)

    await callback.message.delete()
    
    media = [InputMediaPhoto(media=row[1]) for row in sliced]
    messages = await bot.send_media_group(chat_id=callback.message.chat.id, media=media)
    photo_ids = [m.message_id for m in messages]

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="⬅️ Пред. стр", callback_data=f"admin_art_grid:{page - 1}")
    if end < len(arts):
        builder.button(text="След. стр ➡️", callback_data=f"admin_art_grid:{page + 1}")
    
    # Arts list Command forces send_admin_art_item(0) 
    builder.button(text="🎚 К слайдеру", callback_data="admin_art_view_back")
    
    control_msg = await callback.message.answer(
        f"👑 <b>[Админ] Сетка артов</b>\n<i>Страница {page + 1} (Показаны {len(sliced)} из {len(arts)})</i>",
        parse_mode="HTML",
        reply_markup=builder.adjust(2).as_markup()
    )

    # Сохраняем новые IDs для следующего перехода
    await state.update_data(grid_photos=photo_ids)

    # Функция автоочистки через 2 минуты
    async def auto_cleanup(chat_id: int, ids: list, fsm_state: FSMContext):
        await asyncio.sleep(120)
        # Проверяем, что текущие IDs в стейте совпадают — если нет, админ перелистнул
        data = await fsm_state.get_data()
        current_ids = data.get('grid_photos', [])
        if set(ids) != set(current_ids):
            return  # Устаревшая таска, данные уже удалены при перелистывании
        for mid in ids:
            try: await bot.delete_message(chat_id, mid)
            except Exception: pass

    asyncio.create_task(auto_cleanup(callback.message.chat.id, photo_ids + [control_msg.message_id], state))

@dp.callback_query(F.data == "admin_art_view_back")
async def process_admin_art_view_back(callback: types.CallbackQuery, state: FSMContext):
    # Удаляем фото при возврате к списку
    data = await state.get_data()
    for mid in data.get("grid_photos", []):
        try: await bot.delete_message(callback.message.chat.id, mid)
        except: pass
    await state.update_data(grid_photos=[]) # Очищаем
    
    await callback.message.delete()
    await send_admin_art_item(callback.message.chat.id, 0)

@dp.message(Command("delete_art"))
async def cmd_delete_art(message: types.Message):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    try:
        art_id = int(message.text.split()[1])
        if await delete_art_by_id(art_id):
            await message.answer(f"✅ Арт с ID {art_id} успешно удален.")
        else:
            await message.answer(f"❌ Арт с ID {art_id} не найден.")
    except (IndexError, ValueError):
        await message.answer("❌ Формат: /delete_art <ID_арта>")

@dp.message(Command("toggle_ai"))
async def cmd_toggle_ai(message: types.Message):
    if message.chat.type not in ["group", "supergroup"]:
        return await message.answer("Эту команду можно использовать только в группе!")
        
    admins = await get_admins()
    is_bot_admin = message.from_user.id in admins
    
    # Allow group admins or bot admins to toggle AI
    is_group_admin = False
    if not is_bot_admin:
        try:
            member = await bot.get_chat_member(message.chat.id, message.from_user.id)
            is_group_admin = member.status in ["creator", "administrator"]
        except Exception:
            pass
            
    if not is_bot_admin and not is_group_admin:
        return await message.answer("Только администраторы могут использовать эту команду.")
        
    enabled = await toggle_group_ai(message.chat.id)
    
    if enabled:
        await message.answer("✅ <b>Общение с ИИ в этой группе ВКЛЮЧЕНО.</b>", parse_mode="HTML")
    else:
        await message.answer("❌ <b>Общение с ИИ в этой группе ВЫКЛЮЧЕНО.</b>", parse_mode="HTML")

@dp.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    ART_CACHE.pop(message.from_user.id, None)
    await state.clear()
    await message.answer("Действие отменено ❌")

@dp.callback_query(F.data == "cancel_state", StateFilter("*"))
async def process_cancel_state(callback: types.CallbackQuery, state: FSMContext):
    ART_CACHE.pop(callback.from_user.id, None)
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Действие отменено ❌", show_alert=True)

@dp.message(Command("add_chapter"))
async def cmd_add_chapter(message: types.Message, state: FSMContext):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    await state.update_data(content_type='manga')
    await state.set_state(UniversalContentUpload.waiting_for_id)
    await message.answer("Выберите язык:", reply_markup=get_langs_menu("ucadd"))

@dp.message(Command("add_ranobe"))
async def cmd_add_ranobe(message: types.Message, state: FSMContext):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    await state.update_data(content_type='ranobe')
    await state.set_state(UniversalContentUpload.waiting_for_id)
    await message.answer("Выберите ранобэ:", reply_markup=get_ranobe_langs_menu("ucadd"))

@dp.message(Command("add_akashic"))
async def cmd_add_akashic(message: types.Message, state: FSMContext):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    await state.update_data(content_type='akashic')
    await state.set_state(UniversalContentUpload.waiting_for_id)
    await message.answer("📖 <b>Добавление Хроник Акаши</b>\nВведите номер тома (число):", parse_mode="HTML")

@dp.message(Command("add_british"))
async def cmd_add_british(message: types.Message, state: FSMContext):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    await state.update_data(content_type='british')
    await state.set_state(UniversalContentUpload.waiting_for_id)
    await message.answer("👸 <b>Добавление Британской красавицы</b>\nВведите номер тома (число):", parse_mode="HTML")

# --- УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК: выбор ID (язык через callback или том через текст) ---
@dp.callback_query(UniversalContentUpload.waiting_for_id, F.data.startswith("ucadd_"))
async def uc_upload_id_callback(callback: types.CallbackQuery, state: FSMContext):
    """Manga/Ranobe: выбор языка через inline-кнопку."""
    await state.update_data(content_id=callback.data.split("_", 1)[1])
    await state.set_state(UniversalContentUpload.waiting_for_chapter)
    data = await state.get_data()
    ct = CONTENT_TYPES.get(data.get('content_type', ''), {})
    prompt = "Введите номер главы (или название, слитно):" if data.get('content_type') == 'ranobe' else "Введите номер главы:"
    await callback.message.edit_text(prompt)

@dp.message(UniversalContentUpload.waiting_for_id)
async def uc_upload_id_text(message: types.Message, state: FSMContext):
    """Akashic/British: ввод номера тома текстом."""
    data = await state.get_data()
    ct = CONTENT_TYPES.get(data.get('content_type', ''), {})
    if ct.get('id_type') == 'volume':
        if not message.text.strip().isdigit():
            return await message.answer("❌ Введите число (номер тома):")
        await state.update_data(content_id=int(message.text.strip()))
    else:
        await state.update_data(content_id=message.text.strip())
    await state.set_state(UniversalContentUpload.waiting_for_chapter)
    await message.answer("Введите номер главы:")

@dp.message(UniversalContentUpload.waiting_for_chapter)
async def uc_upload_chapter(message: types.Message, state: FSMContext):
    await state.update_data(chapter=message.text.strip())
    await state.set_state(UniversalContentUpload.waiting_for_link)
    await message.answer("🔗 Отправьте ссылку на главу (можно несколько ссылок, каждую с новой строки, если глава разделена):")

@dp.message(UniversalContentUpload.waiting_for_link, F.text)
async def uc_upload_link(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ctype = data.get('content_type', 'manga')
    ct = CONTENT_TYPES.get(ctype, CONTENT_TYPES['manga'])
    content_id = data.get('content_id', '')
    chapter = data.get('chapter', '')
    text_input = message.html_text.strip()

    # ИЗВЛЕКАЕМ ВСЕ ССЫЛКИ
    links = _clean_urls(text_input)
    
    # Если в тексте есть гиперссылки (через <a>), они УЖЕ в text_input
    # Нам нужно решить: конвертировать в Telegraph или оставить ссылки?
    
    # ЛОГИКА: 
    # 1. Если прислали просто набор ссылок (нет другого текста кроме ссылок и пробелов)
    #    -> Сохраняем их списком.
    # 2. Если прислали текст (с ссылками или без)
    #    -> Конвертируем в ОДНУ страницу Telegraph.
    
    stripped_text = re.sub(r'https?://[^\s<"\'>]+', '', text_input).strip()
    is_pure_links = not stripped_text
    
    if is_pure_links and links:
        # Просто сохраняем список ссылок через пробел
        link = " ".join(links)
    elif len(text_input) > 20:
        # Это текст (возможно с гиперссылками) -> в Telegraph
        wait_msg = await message.answer("📝 <i>Готовлю страницу Telegraph...</i>", parse_mode="HTML")
        id_label = ct['names_map'].get(str(content_id), str(content_id)) if ct['names_map'] else f"Том {content_id}"
        title = f"{ct['emoji']} {ct['name']} — {id_label}, Глава {chapter}"
        
        # Передаем HTML как есть, upload_to_telegraph теперь умеет его парсить
        new_link = await upload_to_telegraph(title, text_input)
        if new_link:
            link = new_link
            await wait_msg.delete()
        else:
            await wait_msg.edit_text("⚠️ Не удалось загрузить в Телеграф, сохраняю как есть.")
            link = text_input # Fallback
    else:
        # Короткий текст или одна ссылка
        link = " ".join(links) if links else text_input

    async with aiosqlite.connect('manga.db') as db:
        # Получаем текущий макс. sort_order для этого тайтла/тома
        async with db.execute(f'SELECT MAX(sort_order) FROM {ct["table"]} WHERE {ct["id_col"]} = ?', (content_id,)) as cursor:
            row = await cursor.fetchone()
            next_order = (row[0] or 0) + 1 if row else 1

        await db.execute(
            f'INSERT INTO {ct["table"]} ({ct["id_col"]}, {ct["chapter_col"]}, {ct["url_col"]}, sort_order) VALUES (?, ?, ?, ?) '
            f'ON CONFLICT({ct["id_col"]}, {ct["chapter_col"]}) DO UPDATE SET {ct["url_col"]}=excluded.{ct["url_col"]}',
            (content_id, chapter, link, next_order)
        )
        await db.commit()

    # СИНХРОНИЗАЦИЯ: Обновляем JSON и пушим в GitHub
    try:
        result = await build_reader_data()
        import json as _json
        with open("webapp/chapters_data.json", "w", encoding="utf-8") as f:
            _json.dump(result, f, ensure_ascii=False, indent=2)
        asyncio.create_task(run_git_sync(f"tg upload sync: {series_id if 'series_id' in locals() else content_id}")) # type: ignore
    except Exception as e: logging.error(f"Sync error: {e}")

    # Формируем имя для уведомления
    id_label = ct['names_map'].get(str(content_id), str(content_id)) if ct['names_map'] else f"Том {content_id}"
    await message.answer(f"✅ {ct['emoji']} {ct['name']}: глава {chapter} ({id_label}) добавлена!\n🔗 Ссылка: {link}")

    builder = InlineKeyboardBuilder()
    builder.button(text="🔔 Разослать по закладкам", callback_data="notify_bookmarks")
    builder.button(text="📢 Разослать ВСЕМ", callback_data="notify_all")
    builder.button(text="❌ Отмена", callback_data="notify_no")
    builder.adjust(1)
    
    await state.set_state(NotifyUsers.waiting_for_decision)
    await state.update_data(
        notify_text=f"{ct['emoji']} <b>Вышла новая глава {ct['name']}!</b>\n{id_label}, Глава {chapter}\n🔗 {link}",
        series_id=str(content_id)
    )
    await message.answer("Выберите способ уведомления:", reply_markup=builder.as_markup())

# --- УВЕДОМЛЕНИЯ ---
@dp.callback_query(NotifyUsers.waiting_for_decision, F.data.startswith("notify_"))
async def process_notification_decision(callback: types.CallbackQuery, state: FSMContext):
    decision = callback.data.split("_")[1]
    data = await state.get_data()
    text = data.get("notify_text", "")
    await state.clear()
    
    if decision == "no":
        return await callback.message.edit_text("Уведомление отменено.")
        
    series_id = data.get("series_id")
    
    if decision == "bookmarks":
        await callback.message.edit_text("⏳ <i>Рассылаю уведомления читателям этого тайтла...</i>", parse_mode="HTML")
        users = await get_users_with_bookmark(series_id)
    else:
        await callback.message.edit_text("⏳ <i>Начинаю массовую рассылку ВСЕМ пользователям...</i>", parse_mode="HTML")
        users = await get_all_users()
        
    count = 0
    for user_id in users:
        try:
            await bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
            
    await callback.message.answer(f"✅ Рассылка завершена!\nСообщение получили <b>{count}</b> пользователей.", parse_mode="HTML")

# --- УНИВЕРСАЛЬНОЕ УДАЛЕНИЕ КОНТЕНТА ---
@dp.message(Command("delete_chapter"))
async def cmd_delete_chapter(message: types.Message, state: FSMContext):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    await state.update_data(content_type='manga')
    await state.set_state(UniversalContentDelete.waiting_for_id)
    await message.answer("Выберите язык для удаления главы манги:", reply_markup=get_langs_menu("ucdel"))

@dp.message(Command("delete_ranobe"))
async def cmd_delete_ranobe(message: types.Message, state: FSMContext):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    await state.update_data(content_type='ranobe')
    await state.set_state(UniversalContentDelete.waiting_for_id)
    await message.answer("Выберите ранобэ для удаления главы:", reply_markup=get_ranobe_langs_menu("ucdel"))

@dp.message(Command("delete_akashic"))
async def cmd_delete_akashic(message: types.Message, state: FSMContext):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    await state.update_data(content_type='akashic')
    await state.set_state(UniversalContentDelete.waiting_for_id)
    await message.answer("🗑 <b>Удаление Хроник Акаши</b>\nВведите номер тома (число):", parse_mode="HTML")

@dp.message(Command("delete_british"))
async def cmd_delete_british(message: types.Message, state: FSMContext):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    await state.update_data(content_type='british')
    await state.set_state(UniversalContentDelete.waiting_for_id)
    await message.answer("🗑 <b>Удаление Британской красавицы</b>\nВведите номер тома (число):", parse_mode="HTML")

@dp.callback_query(UniversalContentDelete.waiting_for_id, F.data.startswith("ucdel_"))
async def uc_delete_id_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(content_id=callback.data.split("_", 1)[1])
    await state.set_state(UniversalContentDelete.waiting_for_chapter)
    await callback.message.edit_text("Введите номер/название главы для удаления:")

@dp.message(UniversalContentDelete.waiting_for_id)
async def uc_delete_id_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ct = CONTENT_TYPES.get(data.get('content_type', ''), {})
    if ct.get('id_type') == 'volume':
        if not message.text.strip().isdigit():
            return await message.answer("❌ Введите число (номер тома):")
        await state.update_data(content_id=int(message.text.strip()))
    else:
        await state.update_data(content_id=message.text.strip())
    await state.set_state(UniversalContentDelete.waiting_for_chapter)
    await message.answer("Введите номер/название главы для удаления:")

@dp.message(UniversalContentDelete.waiting_for_chapter)
async def uc_delete_chapter(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ctype = data.get('content_type', 'manga')
    ct = CONTENT_TYPES.get(ctype, CONTENT_TYPES['manga'])
    content_id = data.get('content_id', '')
    chapter = message.text.strip()

    async with aiosqlite.connect('manga.db') as db:
        cursor = await db.execute(
            f'DELETE FROM {ct["table"]} WHERE {ct["chapter_col"]} = ? AND {ct["id_col"]} = ?',
            (chapter, content_id)
        )
        id_label = ct['names_map'].get(str(content_id), str(content_id)) if ct['names_map'] else f"Том {content_id}"
        if cursor.rowcount > 0:
            await message.answer(f"✅ {ct['emoji']} {ct['name']}: глава {chapter} ({id_label}) успешно удалена из базы!")
        else:
            await message.answer(f"❌ {ct['emoji']} {ct['name']}: глава {chapter} ({id_label}) не найдена!")
        await db.commit()
    await state.clear()
# ----------------------------------------


@dp.message(Command("add_art"))
async def cmd_add_art(message: types.Message, state: FSMContext):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    await state.set_state(ArtUpload.waiting_for_photo)
    ART_CACHE[message.from_user.id] = {} 
    await message.answer("❗️ <b>ПРАВИЛА АРТОВ:</b>\n1. Сверять внешность с аниме.\n2. Цветные и чёткие.\n3. БЕЗ перевода и текста.\n\nКидайте фото, затем /finish", parse_mode="HTML")

@dp.message(ArtUpload.waiting_for_photo, F.photo)
async def process_art_photo(message: types.Message):
    ART_CACHE.setdefault(message.from_user.id, {})[message.message_id] = message.photo[-1].file_id

@dp.message(ArtUpload.waiting_for_photo, Command("finish"))
async def finish_art_upload(message: types.Message, state: FSMContext):
    cache = ART_CACHE.pop(message.from_user.id, {})
    if not cache: return await message.answer("Пусто! Отмена.")
    
    async with aiosqlite.connect('manga.db') as db:
        for msg_id in sorted(cache.keys()): await db.execute('INSERT INTO arts (file_id) VALUES (?)', (cache[msg_id],))
        await db.commit()
    await message.answer(f"✅ Успешно загружено {len(cache)} качественных артов!")
    await state.clear()


# --- ПРЕДЛОЖКА АРТОВ ---
@dp.message(Command("suggest_art"))
async def cmd_suggest_art(message: types.Message, state: FSMContext):
    if await check_cd_and_warn(message, "suggest_art", 60): return
    await state.set_state(ArtSuggest.waiting_for_photo)
    text = (
        "🖼 <b>Предложка артов</b>\n\n"
        "Отправьте <b>одну</b> красивую фотографию (арт), которую хотите предложить в нашу галерею.\n\n"
        "❗️ <b>Требования:</b>\n"
        "1. Рисовка качественная и приближена к аниме.\n"
        "2. Без вотермарок на пол-экрана и лишнего текста.\n"
        "3. Соответствие тематике Roshidere.\n\n"
        "<i>Все арты проходят ручную проверку администрацией.</i>"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(ArtSuggest.waiting_for_photo, F.photo)
async def process_suggested_art(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    async with aiosqlite.connect('manga.db') as db:
        cursor = await db.execute('INSERT INTO suggested_arts (user_id, file_id) VALUES (?, ?)', (user_id, file_id))
        suggest_id = cursor.lastrowid
        await db.commit()
        
    await message.answer("✅ <b>Ваш арт отправлен на модерацию!</b> Вы получите уведомление, когда его проверят.", parse_mode="HTML")
    await state.clear()
    
    admins = await get_admins()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принять", callback_data=f"artaccept_{suggest_id}")
    builder.button(text="❌ Отклонить", callback_data=f"artreject_{suggest_id}")
    
    for admin_id in admins:
        try:
            await bot.send_photo(
                chat_id=admin_id,
                photo=file_id,
                caption=f"📝 <b>Новая предложка арта!</b>\nОт: @{username} (ID: <code>{user_id}</code>)\nВыберите действие:",
                parse_mode="HTML",
                reply_markup=builder.as_markup()
            )
        except Exception:
            pass

@dp.callback_query(F.data.startswith("artaccept_"))
async def process_art_accept(callback: types.CallbackQuery):
    suggest_id = int(callback.data.split("_")[1])
    
    async with aiosqlite.connect('manga.db') as db:
        cursor = await db.execute('SELECT user_id, file_id FROM suggested_arts WHERE id = ?', (suggest_id,))
        row = await cursor.fetchone()
        
        if not row:
            return await callback.message.edit_caption(caption="❌ Заявка уже обработана или не существует.", reply_markup=None)
            
        user_id, file_id = row
        await db.execute('DELETE FROM suggested_arts WHERE id = ?', (suggest_id,))
        await db.execute('INSERT INTO arts (file_id) VALUES (?)', (file_id,))
        await db.commit()
        
    await callback.message.edit_caption(caption="✅ <b>Арт принят!</b> Добавлен в базу.", parse_mode="HTML", reply_markup=None)
    
    try:
        await bot.send_message(chat_id=user_id, text="🎉 <b>Поздравляем!</b> Ваш предложенный арт прошел проверку и был добавлен в галерею бота!", parse_mode="HTML")
    except Exception:
        pass

@dp.callback_query(F.data.startswith("artreject_"))
async def process_art_reject(callback: types.CallbackQuery):
    suggest_id = int(callback.data.split("_")[1])
    
    async with aiosqlite.connect('manga.db') as db:
        cursor = await db.execute('SELECT user_id FROM suggested_arts WHERE id = ?', (suggest_id,))
        row = await cursor.fetchone()
        
        if not row:
            return await callback.message.edit_caption(caption="❌ Заявка уже обработана или не существует.", reply_markup=None)
            
        user_id = row[0]
        await db.execute('DELETE FROM suggested_arts WHERE id = ?', (suggest_id,))
        await db.commit()
        
    await callback.message.edit_caption(caption="❌ <b>Арт отклонен.</b> Заявка удалена.", parse_mode="HTML", reply_markup=None)
    
    try:
        await bot.send_message(chat_id=user_id, text="😔 <b>К сожалению</b>, ваш предложенный арт был отклонен администрацией (возможно, не подошел по качеству или стилистике).", parse_mode="HTML")
    except Exception:
        pass


# ==============================================================================
# КОНЕЦ БЛОКА МОДЕРАЦИИ
# ==============================================================================


# ==============================================================================
# БЛОК 11: ЗАПУСК БОТА И ОСТАЛЬНОЕ
# ==============================================================================

class StatsMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, types.Message) and event.from_user:
            user_id = event.from_user.id
            chat_id = event.chat.id
            is_group = event.chat.type in ["group", "supergroup"]
            
            # --- Логика дропов (Chat Drops) ---
            if is_group and chat_id not in ACTIVE_DROPS:
                if random.random() < 0.02: # 2% шанс на сообщение
                    reward = random.randint(50, 200)
                    ACTIVE_DROPS[chat_id] = reward
                    
                    kb = InlineKeyboardBuilder()
                    kb.button(text="🎁 Забрать монеты!", callback_data="claim_drop")
                    
                    await event.answer(
                        "💰 <b>ОЙ! В ЧАТЕ УПАЛ МЕШОК МОНЕТ!</b>\n"
                        "Успей нажать на кнопку первым, чтобы забрать награду!",
                        parse_mode="HTML",
                        reply_markup=kb.as_markup()
                    )
            # ----------------------------------
            
            try:
                async with aiosqlite.connect('manga.db') as db:
                    await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (user_id,))
                    if getattr(event, 'sticker', None):
                        if is_group:
                            await db.execute('UPDATE users_stats SET stickers_count = stickers_count + 1 WHERE user_id = ?', (user_id,))
                    elif getattr(event, 'text', None) or getattr(event, 'caption', None):
                        text = event.text or event.caption or ""
                        is_cmd = text.startswith('/')
                        is_reply_to_bot = event.reply_to_message and event.reply_to_message.from_user.id == event.bot.id
                        if not is_cmd and not is_reply_to_bot:
                            if is_group:
                                await db.execute('UPDATE users_stats SET messages_count = messages_count + 1, balance = balance + 1, xp = xp + 1 WHERE user_id = ?', (user_id,))
                                # --- Level-up System (Только для групп) ---
                                async with db.execute('SELECT xp, level, messages_count, stickers_count FROM users_stats WHERE user_id = ?', (user_id,)) as cursor:
                                    res = await cursor.fetchone()
                                    if res:
                                        curr_xp, curr_level, m_count, s_count = res
                                        # Если XP <= 1 и есть сообщения/стикеры, значит это старый юзер (миграция)
                                        if curr_xp <= 1 and (m_count + s_count > 1):
                                            curr_xp = m_count + s_count * 2
                                            await db.execute('UPDATE users_stats SET xp = ? WHERE user_id = ?', (curr_xp, user_id))
                                        
                                        target_level = (curr_xp // 100) + 1
                                        if target_level > curr_level:
                                            reward = (target_level - curr_level) * 500
                                            await db.execute('UPDATE users_stats SET level = ?, balance = balance + ? WHERE user_id = ?', (target_level, reward, user_id))
                                            async with db.execute('SELECT balance FROM users_stats WHERE user_id = ?', (user_id,)) as b_cursor:
                                                new_balance = (await b_cursor.fetchone())[0]
                                            user_name = event.from_user.first_name
                                            await event.answer(f"🎉 <b>Поздравляем!</b> {user_name} достигает <b>{target_level} уровня</b>!\n💰 Награда: {reward} монет\n💳 Текущий баланс: {new_balance}", parse_mode="HTML")
                                # -----------------------
                            else:
                                await db.execute('UPDATE users_stats SET messages_count = messages_count + 1 WHERE user_id = ?', (user_id,))
                    await db.commit()
            except Exception as e:
                logging.error(f"StatsMiddleware error: {e}")
                
        return await handler(event, data)

# ==============================================================================
# БЛОК: API СЕРВЕР ДЛЯ ЧИТАЛКИ (WebApp Reader)
# ==============================================================================

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}

def get_auth_user(request: aiohttp.web.Request) -> dict | None:
    """Извлекает и валидирует Telegram пользователя из заголовка Authorization."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("tma "):
        init_data = auth_header[4:]
    else:
        # Fallback to initData parameter for backward compatibility if we want it, 
        # but header is preferred.
        init_data = request.query.get("initData", "")
        
    if not init_data:
        return None
        
    parsed = validate_telegram_data(init_data, BOT_TOKEN)
    if not parsed or 'user' not in parsed:
        return None
    try:
        return json.loads(parsed['user'])
    except Exception:
        return None

# --- ИИ-чат (серверный прокси для WebApp) ---

async def handle_ai_chat(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Прокси-эндпоинт для ИИ-чата. Клиент отправляет историю сообщений,
    сервер сам обращается к Groq и возвращает готовый ответ.
    Ключ GROQ_API_KEY никогда не покидает сервер."""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)

        data = await request.json()
        messages = data.get('messages', [])
        if not messages or not isinstance(messages, list):
            return aiohttp.web.json_response(
                {"error": "messages array is required"}, status=400, headers=CORS_HEADERS
            )
        # Ограничиваем длину истории (макс. 20 сообщений) для защиты от абьюза
        messages = messages[-20:]
        # Извлекаем system prompt (первый элемент) и остальную историю
        system_prompt = ""
        history = []
        for msg in messages:
            role = msg.get('role', '')
            content = msg.get('content', '')
            if role == 'system':
                system_prompt = content
            elif role in ('user', 'assistant'):
                history.append({"role": role, "content": content})
        # Последнее сообщение пользователя — prompt, остальное — history
        prompt = ""
        while history and history[-1]['role'] != 'user':
            history.pop() # Убираем ассистента в конце, если нет user
            
        if history and history[-1]['role'] == 'user':
            prompt = history.pop()['content']
            
        if not prompt or not prompt.strip():
            return aiohttp.web.json_response(
                {"error": "no user message found"}, status=400, headers=CORS_HEADERS
            )
        reply = await ask_ai(prompt, system_prompt, history=history if history else None)
        return aiohttp.web.json_response({"reply": reply}, headers=CORS_HEADERS)
    except Exception as e:
        logging.error(f"AI Chat API Error: {e}")
        return aiohttp.web.json_response(
            {"error": str(e)}, status=500, headers=CORS_HEADERS
        )

async def handle_reader_data(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Возвращает данные для читалки. Единственный источник истины — build_reader_data(),
    который корректно применяет custom_names из БД ко всем элементам."""
    try:
        result = await build_reader_data()
        return aiohttp.web.json_response(result, headers=CORS_HEADERS)
    except Exception as e:
        logging.error(f"Reader API Error: {e}")
        return aiohttp.web.json_response({"error": str(e), "series": []}, status=500, headers=CORS_HEADERS)


async def handle_rename_delete(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Сброс кастомного имени элемента обратно в дефолт. Только для AdminMode."""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))

        data = await request.json()
        obj_id = data.get('obj_id', '').strip()
        if not obj_id:
            return aiohttp.web.json_response({"error": "missing obj_id"}, status=400, headers=CORS_HEADERS)
        # Проверяем что запрашивающий — админ
        admins = await get_admins()
        try:
            if int(user_id) not in admins:
                return aiohttp.web.json_response({"error": "forbidden"}, status=403, headers=CORS_HEADERS)
        except (ValueError, TypeError):
            return aiohttp.web.json_response({"error": "forbidden"}, status=403, headers=CORS_HEADERS)

        async with aiosqlite.connect('manga.db') as db:
            await db.execute('DELETE FROM custom_names WHERE id = ?', (obj_id,))
            await db.commit()

        # Обновляем JSON и синхронизируем с GitHub в фоне
        result = await build_reader_data()
        import json
        with open("webapp/chapters_data.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        asyncio.create_task(run_git_sync("reset custom name via webapp"))

        return aiohttp.web.json_response({"ok": True, "obj_id": obj_id}, headers=CORS_HEADERS)
    except Exception as e:
        return aiohttp.web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)


# --- Маппинг series_id -> таблица/формат для прямого редактирования URL ---

def _get_table_info(series_id: str, volume):
    """Возвращает (table_name, chapter_col, where_clause, params_fn) для серии."""
    if series_id == 'akashic_records':
        return ('akashic_ranobe', 'chapter', 'volume = ? AND chapter = ?', lambda v, c: (v, c))
    elif series_id == 'british_belle':
        return ('british_ranobe', 'chapter', 'volume = ? AND chapter = ?', lambda v, c: (v, c))
    elif series_id.startswith('ranobe_'):
        lang = series_id.replace('ranobe_', '')
        return ('ranobe_urls', 'chapter_number', 'chapter_number = ? AND lang = ?', lambda v, c: (c, lang))
    elif series_id.startswith('manga_'):
        lang = series_id.replace('manga_', '')
        return ('chapters_urls', 'chapter_number', 'chapter_number = ? AND lang = ?', lambda v, c: (c, lang))
    return None

async def handle_chapter_edit(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """PUT: Обновить URL главы. Только для админов."""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        admins = await get_admins()
        try:
            if int(user_id) not in admins:
                return aiohttp.web.json_response({"error": "forbidden"}, status=403, headers=CORS_HEADERS)
        except (ValueError, TypeError):
            return aiohttp.web.json_response({"error": "forbidden"}, status=403, headers=CORS_HEADERS)

        data = await request.json()
        series_id = data.get('series_id', '')
        volume = data.get('volume')
        chapter = data.get('chapter', '')
        new_url = data.get('url', '').strip()

        if not series_id or not chapter or not new_url:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)

        info = _get_table_info(series_id, volume)
        if not info:
            return aiohttp.web.json_response({"error": "unknown series"}, status=400, headers=CORS_HEADERS)

        # ИЗВЛЕКАЕМ ВСЕ ССЫЛКИ
        links = _clean_urls(new_url)

        # Конвертируем только если ВООБЩЕ нет ссылок и текст большой
        if not links and len(new_url) > 30:
            title = f"Глава {chapter}"
            s_name = await get_custom_name(f"series_{series_id}") or series_id
            title = f"{s_name} — Глава {chapter}"
            telegraph_url = await upload_to_telegraph(title, new_url)
            if telegraph_url:
                new_url = telegraph_url

        table, _, _, _ = info
        
        async with aiosqlite.connect('manga.db') as db:
            if series_id in ('akashic_records', 'british_belle'):
                # Получаем макс sort_order если это новая запись
                async with db.execute(f"SELECT MAX(sort_order) FROM {table} WHERE volume=?", (volume,)) as cur:
                    row = await cur.fetchone()
                    next_order = (row[0] or 0) + 1
                await db.execute(
                    f'INSERT INTO {table} (volume, chapter, url, sort_order) VALUES (?, ?, ?, ?) '
                    f'ON CONFLICT(volume, chapter) DO UPDATE SET url=excluded.url',
                    (volume, chapter, new_url, next_order)
                )
            else:
                lang = series_id.split('_', 1)[1] if '_' in series_id else 'ru'
                async with db.execute(f"SELECT MAX(sort_order) FROM {table} WHERE lang=?", (lang,)) as cur:
                    row = await cur.fetchone()
                    next_order = (row[0] or 0) + 1
                await db.execute(
                    f'INSERT INTO {table} (chapter_number, lang, url, sort_order) VALUES (?, ?, ?, ?) '
                    f'ON CONFLICT(chapter_number, lang) DO UPDATE SET url=excluded.url',
                    (chapter, lang, new_url, next_order)
                )
            await db.commit()

        # Пересобираем JSON и синхронизируем
        result = await build_reader_data()
        import json as _json
        with open("webapp/chapters_data.json", "w", encoding="utf-8") as f:
            _json.dump(result, f, ensure_ascii=False, indent=2)
        asyncio.create_task(run_git_sync("URL edited via webapp editor"))

        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:
        logging.error(f"Chapter Edit API Error: {e}")
        return aiohttp.web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)


async def handle_chapter_bulk(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST: Массовое добавление глав с URL. Только для админов."""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        admins = await get_admins()
        try:
            if int(user_id) not in admins:
                return aiohttp.web.json_response({"error": "forbidden"}, status=403, headers=CORS_HEADERS)
        except (ValueError, TypeError):
            return aiohttp.web.json_response({"error": "forbidden"}, status=403, headers=CORS_HEADERS)

        data = await request.json()
        series_id = data.get('series_id', '')
        volume = data.get('volume')
        start_chapter = data.get('start_chapter', 1)
        urls = data.get('urls', [])

        if not series_id or not urls:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)

        info = _get_table_info(series_id, volume)
        if not info:
            return aiohttp.web.json_response({"error": "unknown series"}, status=400, headers=CORS_HEADERS)

        table, col, where, params_fn = info
        added = 0

        # Определяем id_col и idx_val исходя из типа контента
        id_col = 'lang' if series_id.startswith(('manga_', 'ranobe_')) else 'volume'
        idx_val = series_id.split('_', 1)[1] if '_' in series_id else volume

        async with aiosqlite.connect('manga.db') as db:
            # Получаем текущий макс. sort_order
            async with db.execute(f'SELECT MAX(sort_order) FROM {table} WHERE {id_col} = ?', (str(idx_val),)) as cursor:
                row = await cursor.fetchone()
                current_max = row[0] or 0

            for i, url in enumerate(urls):
                ch_num = str(start_chapter + i)
                url = url.strip()
                if not url:
                    continue
                
                next_order = current_max + added + 1
                
                if series_id in ('akashic_records', 'british_belle'):
                    await db.execute(
                        f'INSERT INTO {table} (volume, chapter, url, sort_order) VALUES (?, ?, ?, ?) '
                        f'ON CONFLICT(volume, chapter) DO UPDATE SET url=excluded.url',
                        (volume, ch_num, url, next_order)
                    )
                else:
                    lang = series_id.split('_', 1)[1] if '_' in series_id else 'ru'
                    await db.execute(
                        f'INSERT INTO {table} (chapter_number, lang, url, sort_order) VALUES (?, ?, ?, ?) '
                        f'ON CONFLICT(chapter_number, lang) DO UPDATE SET url=excluded.url',
                        (ch_num, lang, url, next_order)
                    )
                added += 1
            await db.commit()

        # Пересобираем JSON и синхронизируем
        result = await build_reader_data()
        import json as _json
        with open("webapp/chapters_data.json", "w", encoding="utf-8") as f:
            _json.dump(result, f, ensure_ascii=False, indent=2)
        asyncio.create_task(run_git_sync(f"bulk upload {added} chapters via webapp"))

        return aiohttp.web.json_response({"ok": True, "added": added}, headers=CORS_HEADERS)
    except Exception as e:
        logging.error(f"Bulk Upload API Error: {e}")
        return aiohttp.web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)


async def handle_cors_preflight(request: aiohttp.web.Request) -> aiohttp.web.Response:
    return aiohttp.web.Response(status=200, headers=CORS_HEADERS)

# --- Лайки ---

async def handle_likes_get(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Получить количество лайков и статус лайка пользователя."""
    chapter_key = request.query.get('chapter_key', '')
    user = get_auth_user(request)
    user_id = str(user.get("id", "")) if user else ""
    try:
        async with aiosqlite.connect('manga.db') as db:
            async with db.execute('SELECT COUNT(*) FROM chapter_likes WHERE chapter_key = ?', (chapter_key,)) as c:
                count = (await c.fetchone())[0]
            liked = False
            if user_id:
                async with db.execute('SELECT 1 FROM chapter_likes WHERE chapter_key = ? AND user_id = ?', (chapter_key, user_id)) as c:
                    liked = bool(await c.fetchone())
        return aiohttp.web.json_response({"count": count, "liked": liked}, headers=CORS_HEADERS)
    except Exception as e:
        return aiohttp.web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)

async def handle_likes_post(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Поставить/убрать лайк (toggle)."""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))

        data = await request.json()
        chapter_key = data.get('chapter_key', '')
        if not chapter_key:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)

        async with aiosqlite.connect('manga.db') as db:
            async with db.execute('SELECT 1 FROM chapter_likes WHERE chapter_key = ? AND user_id = ?', (chapter_key, user_id)) as c:
                exists = await c.fetchone()
            if exists:
                await db.execute('DELETE FROM chapter_likes WHERE chapter_key = ? AND user_id = ?', (chapter_key, user_id))
                liked = False
            else:
                await db.execute('INSERT INTO chapter_likes (chapter_key, user_id) VALUES (?, ?)', (chapter_key, user_id))
                liked = True
            await db.commit()

            async with db.execute('SELECT COUNT(*) FROM chapter_likes WHERE chapter_key = ?', (chapter_key,)) as c:
                count = (await c.fetchone())[0]

        return aiohttp.web.json_response({"count": count, "liked": liked}, headers=CORS_HEADERS)
    except Exception as e:
        return aiohttp.web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)

# --- Комментарии ---

async def handle_comments_get(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Получить комментарии к главе с лайками/дизлайками и аватарами."""
    chapter_key = request.query.get('chapter_key', '')
    user = get_auth_user(request)
    current_user_id = str(user.get("id", "")) if user else None
    
    try:
        async with aiosqlite.connect('manga.db') as db:
            query = """
                SELECT 
                    c.id, c.user_id, c.user_name, c.text, c.created_at, c.parent_id,
                    COUNT(CASE WHEN r.type = 'like' THEN 1 END) as likes,
                    COUNT(CASE WHEN r.type = 'dislike' THEN 1 END) as dislikes,
                    MAX(CASE WHEN r.user_id = ? THEN r.type ELSE NULL END) as user_reaction
                FROM chapter_comments c
                LEFT JOIN comment_reactions r ON c.id = r.comment_id
                WHERE c.chapter_key = ?
                GROUP BY c.id
                ORDER BY c.created_at ASC
            """
            async with db.execute(query, (current_user_id, chapter_key)) as cursor:
                rows = await cursor.fetchall()
                
        comments = [
            {
                "id": r[0], 
                "user_id": r[1], 
                "user_name": r[2], 
                "text": r[3], 
                "created_at": r[4], 
                "parent_id": r[5],
                "likes": r[6],
                "dislikes": r[7],
                "user_reaction": r[8]
            } for r in rows
        ]
        return aiohttp.web.json_response({"comments": comments}, headers=CORS_HEADERS)
    except Exception as e:
        logging.error(f"Error in handle_comments_get: {e}")
        return aiohttp.web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)

async def handle_comment_react_post(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Лайк/дизлайк комментария."""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))

        data = await request.json()
        comment_id = data.get('comment_id')
        reaction_type = data.get('type') # 'like' or 'dislike'
        
        if not comment_id or reaction_type not in ['like', 'dislike']:
            return aiohttp.web.json_response({"error": "invalid arguments"}, status=400, headers=CORS_HEADERS)

        from database import add_comment_reaction
        await add_comment_reaction(int(comment_id), user_id, reaction_type)
        
        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:
        return aiohttp.web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)

async def handle_comments_post(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Добавить комментарий."""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        user_name = user.get("first_name", "Аноним")

        data = await request.json()
        chapter_key = data.get('chapter_key', '')
        text = data.get('text', '').strip()
        parent_id = data.get('parent_id', None)
        if not chapter_key or not text:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)
        if len(text) > 500:
            return aiohttp.web.json_response({"error": "too long"}, status=400, headers=CORS_HEADERS)

        async with aiosqlite.connect('manga.db') as db:
            await db.execute(
                'INSERT INTO chapter_comments (chapter_key, user_id, user_name, text, parent_id) VALUES (?, ?, ?, ?, ?)',
                (chapter_key, user_id, user_name, text, parent_id)
            )
            await db.commit()

        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:
        return aiohttp.web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)

async def handle_comments_delete(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Удалить комментарий (только свой или админ)."""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))

        data = await request.json()
        comment_id = data.get('comment_id', 0)

        async with aiosqlite.connect('manga.db') as db:
            # Проверяем владельца
            async with db.execute('SELECT user_id FROM chapter_comments WHERE id = ?', (comment_id,)) as c:
                row = await c.fetchone()
            if not row:
                return aiohttp.web.json_response({"error": "not found"}, status=404, headers=CORS_HEADERS)
            if str(row[0]) != str(user_id):
                # Проверяем, админ ли
                admins = await get_admins()
                try:
                    if int(user_id) not in admins:
                        return aiohttp.web.json_response({"error": "forbidden"}, status=403, headers=CORS_HEADERS)
                except (ValueError, TypeError):
                    return aiohttp.web.json_response({"error": "forbidden"}, status=403, headers=CORS_HEADERS)

            await db.execute('DELETE FROM chapter_comments WHERE id = ? OR parent_id = ?', (comment_id, comment_id))
            await db.commit()

        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:
        return aiohttp.web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)
# --- Репорты об опечатках ---

async def cmd_test_notification(message: types.Message):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    
    await message.answer(f"🔔 <b>Тест уведомлений</b>\nСписок админов: <code>{admins}</code>\nТвой ID: <code>{message.from_user.id}</code>\n\nСейчас попробую отправить тестовое сообщение...", parse_mode="HTML")
    
    count = 0
    for admin_id in admins:
        try:
            await bot.send_message(admin_id, "✅ Тестовое уведомление из системы репортов!")
            count += 1
        except Exception as e:
            await message.answer(f"❌ Ошибка для {admin_id}: {e}")
    
    await message.answer(f"🏁 Тест завершен. Отправлено: {count}/{len(admins)}")

async def handle_typo_post(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Добавить репорт об опечатке."""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        user_name = user.get("first_name", "Аноним")

        data = await request.json()
        chapter_key = data.get('chapter_key', '')
        selected_text = data.get('selected_text', '').strip()
        context_text = data.get('context_text', '').strip()
        comment = data.get('comment', '').strip()

        if not chapter_key or not selected_text or not context_text:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)

        async with aiosqlite.connect('manga.db') as db:
            await db.execute(
                'INSERT INTO chapter_typos (chapter_key, user_id, user_name, selected_text, context_text, comment) VALUES (?, ?, ?, ?, ?, ?)',
                (chapter_key, user_id, user_name, selected_text, context_text, comment)
            )
            await db.commit()

        # Уведомление админам
        def safe_html(t): return html.escape(str(t), quote=False)
        admins = await get_admins()
        logging.info(f"Typo report received from {user_name} ({user_id}).")
        report_text = (
            f"🚨 <b>Новая опечатка!</b>\n"
            f"От: {safe_html(user_name)} (ID: <code>{user_id}</code>)\n"
            f"Глава: <code>{safe_html(chapter_key)}</code>\n\n"
            f"<b>Текст:</b> <code>{safe_html(selected_text)}</code>\n"
            f"<b>Контекст:</b> <i>...{safe_html(context_text)}...</i>\n"
            f"<b>Комментарий:</b> {safe_html(comment)}"
        )
        for admin_id in admins:
            try:
                logging.info(f"Sending typo report to admin {admin_id}")
                await bot.send_message(admin_id, report_text, parse_mode="HTML")
            except Exception as e:
                logging.error(f"Failed to notify admin {admin_id}: {e}")

        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:
        return aiohttp.web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)

# --- Аватары и Реакции (Phase 3) ---

async def handle_avatar_get(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Прокси для получения аватара пользователя Telegram."""
    user_id = request.query.get('user_id', '')
    if not user_id:
        return aiohttp.web.Response(status=400, headers=CORS_HEADERS)
    
    try:
        photos = await bot.get_user_profile_photos(int(user_id), limit=1)
        if photos.total_count == 0:
            return aiohttp.web.Response(status=404, headers=CORS_HEADERS)
        
        file = await bot.get_file(photos.photos[0][-1].file_id)
        result = await bot.download_file(file.file_path)
        
        return aiohttp.web.Response(body=result.read(), content_type='image/jpeg', headers=CORS_HEADERS)
    except Exception as e:
        logging.error(f"Avatar proxy error for {user_id}: {e}")
        return aiohttp.web.Response(status=500, headers=CORS_HEADERS)

async def handle_reactions_get(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Получить статистику реакций для главы."""
    chapter_key = request.query.get('chapter_key', '')
    user = get_auth_user(request)
    user_id = str(user.get("id", "")) if user else None
    
    try:
        async with aiosqlite.connect('manga.db') as db:
            # Общее количество по каждой реакции
            async with db.execute(
                'SELECT reaction, COUNT(*) as count FROM chapter_reactions WHERE chapter_key = ? GROUP BY reaction',
                (chapter_key,)
            ) as c:
                rows = await c.fetchall()
            
            reactions_data = {r[0]: r[1] for r in rows}
            
            # Реакция текущего пользователя
            user_reaction = None
            if user_id:
                async with db.execute(
                    'SELECT reaction FROM chapter_reactions WHERE chapter_key = ? AND user_id = ?',
                    (chapter_key, user_id)
                ) as c:
                    row = await c.fetchone()
                    if row: user_reaction = row[0]
                    
        return aiohttp.web.json_response({
            "reactions": reactions_data,
            "user_reaction": user_reaction
        }, headers=CORS_HEADERS)
    except Exception as e:
        return aiohttp.web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)

async def handle_reactions_post(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Поставить/изменить реакцию."""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        
        data = await request.json()
        chapter_key = data.get('chapter_key', '')
        reaction = data.get('reaction', '') # Например: "👍", "❤️", "🔥"
        
        if not chapter_key or not reaction:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)
            
        async with aiosqlite.connect('manga.db') as db:
            # Если такая же реакция уже стоит - убираем (toggle)
            async with db.execute(
                'SELECT reaction FROM chapter_reactions WHERE chapter_key = ? AND user_id = ?',
                (chapter_key, user_id)
            ) as c:
                existing = await c.fetchone()
                
            if existing and existing[0] == reaction:
                await db.execute('DELETE FROM chapter_reactions WHERE chapter_key = ? AND user_id = ?', (chapter_key, user_id))
            else:
                await db.execute(
                    'INSERT OR REPLACE INTO chapter_reactions (chapter_key, user_id, reaction) VALUES (?, ?, ?)',
                    (chapter_key, user_id, reaction)
                )
            await db.commit()
            
        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:
        return aiohttp.web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)

async def handle_rename_request(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Кэширует длинные ID глав и выдает короткий ID (обход лимита 64 символов в deeplink)."""
    user = get_auth_user(request)
    if not user:
        return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
    data = await request.json()
    obj_id = data.get('obj_id', '').strip()
    if not obj_id:
        return aiohttp.web.json_response({"error": "missing obj_id"}, status=400, headers=CORS_HEADERS)
    
    short_id = str(uuid.uuid4())[:8]
    RENAME_CACHE[short_id] = obj_id
    return aiohttp.web.json_response({"ok": True, "short_id": short_id}, headers=CORS_HEADERS)

# --- Прогресс чтения (Закладки) ---

async def handle_progress_post(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Сохранить позицию прокрутки и текущую главу."""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))

        data = await request.json()
        series_id = data.get('series_id', '')
        volume_id = data.get('volume_id', '')
        chapter_key = data.get('chapter_key', '')
        scroll_pos = data.get('scroll_pos', 0)

        if not series_id or not chapter_key or chapter_key == "undefined":
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)

        async with aiosqlite.connect('manga.db') as db:
            await db.execute('''
                INSERT INTO user_bookmarks (user_id, series_id, volume_id, chapter_key, scroll_pos, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, series_id) DO UPDATE SET
                    volume_id = excluded.volume_id,
                    chapter_key = excluded.chapter_key,
                    scroll_pos = excluded.scroll_pos,
                    updated_at = excluded.updated_at
            ''', (str(user_id), str(series_id), str(volume_id), str(chapter_key), float(scroll_pos)))
            await db.commit()

        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:
        return aiohttp.web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)

async def handle_progress_get(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Получить все закладки пользователя."""
    user = get_auth_user(request)
    if not user:
        return aiohttp.web.json_response({"error": "Unauthorized", "bookmarks": []}, status=401, headers=CORS_HEADERS)
    user_id = str(user.get("id", ""))
    
    try:
        async with aiosqlite.connect('manga.db') as db:
            async with db.execute(
                'SELECT series_id, volume_id, chapter_key, scroll_pos, updated_at FROM user_bookmarks WHERE user_id = ? ORDER BY updated_at DESC',
                (str(user_id),)
            ) as c:
                rows = await c.fetchall()
        
        bookmarks = [{"series_id": r[0], "volume_id": r[1], "chapter_key": r[2], "scroll_pos": r[3], "updated_at": r[4]} for r in rows]
        return aiohttp.web.json_response({"bookmarks": bookmarks}, headers=CORS_HEADERS)
    except Exception as e:
        return aiohttp.web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)


# --- Сортировка глав (Admin DnD) ---

async def handle_sort_chapters(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Сохранить порядок глав после перетаскивания (только для админов)."""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = int(user.get("id", 0))
        
        admins = await get_admins()
        if user_id not in admins:
            return aiohttp.web.json_response({"error": "Forbidden"}, status=403, headers=CORS_HEADERS)

        data = await request.json()
        series_id = data.get('series_id', '')
        volume = data.get('volume', '')
        order = data.get('order', [])  # List of chapter identifiers in new order

        if not series_id or not order:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)

        # Determine the table and index value
        table = None
        id_col = None
        chapter_col = None
        idx_val = volume
        
        if series_id.startswith('manga_'):
            table = 'chapters_urls'
            id_col = 'lang'
            chapter_col = 'chapter_number'
            idx_val = series_id.replace('manga_', '')
        elif series_id.startswith('ranobe_'):
            table = 'ranobe_urls'
            id_col = 'lang'
            chapter_col = 'chapter_number'
            idx_val = series_id.replace('ranobe_', '')
        elif 'akashic' in series_id:
            table = 'akashic_ranobe'
            id_col = 'volume'
            chapter_col = 'chapter'
        elif 'british' in series_id:
            table = 'british_ranobe'
            id_col = 'volume'
            chapter_col = 'chapter'
        
        if not table:
            return aiohttp.web.json_response({"error": "unknown series type"}, status=400, headers=CORS_HEADERS)

        async with aiosqlite.connect('manga.db') as db:
            # Update sort_order for each chapter
            for idx, chapter_id in enumerate(order):
                await db.execute(
                    f'UPDATE {table} SET sort_order = ? WHERE {id_col} = ? AND {chapter_col} = ?',
                    (idx, str(idx_val), str(chapter_id))
                )
            await db.commit()

        # Обновляем JSON и синхронизируем с GitHub
        result = await build_reader_data()
        import json as _json
        with open("webapp/chapters_data.json", "w", encoding="utf-8") as f:
            _json.dump(result, f, ensure_ascii=False, indent=2)
        asyncio.create_task(run_git_sync(f"chapters sorting updated for {series_id}"))

      
        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:
        return aiohttp.web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)

async def handle_root_redirect(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Перенаправляет с корня сайта сразу в читалку."""
    raise aiohttp.web.HTTPFound('/webapp/reader.html')

# ==============================================================================
# БЛОК: ЗАПУСК БОТА
# ==============================================================================

async def main():
    dp.include_router(rp_router)
    
    await init_db()
    
    dp.message.outer_middleware(StatsMiddleware())
    
    # === Регистрация команд бота ===
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="help", description="Список всех команд"),
        BotCommand(command="profile", description="Твой профиль"),
        BotCommand(command="stats", description="Твоя статистика"),
        BotCommand(command="marry", description="Вступить в брак (реплай)"),
        BotCommand(command="divorce", description="Расторгнуть брак"),
        BotCommand(command="marriages", description="Топ пар")
    ]
    await bot.set_my_commands(commands, BotCommandScopeDefault())
    
    # === API сервер для WebApp читалки ===
    app = aiohttp.web.Application()
    app.router.add_get("/api/reader", handle_reader_data)
    # Редирект с главной страницы на WebApp
    app.router.add_get("/", handle_root_redirect)
    app.router.add_options("/api/reader", handle_cors_preflight)
    # Лайки
    app.router.add_get("/api/likes", handle_likes_get)
    app.router.add_post("/api/likes", handle_likes_post)
    app.router.add_options("/api/likes", handle_cors_preflight)
    # Комментарии
    app.router.add_get("/api/comments", handle_comments_get)
    app.router.add_post("/api/comments", handle_comments_post)
    app.router.add_post("/api/comments/react", handle_comment_react_post)
    app.router.add_options("/api/comments/react", handle_cors_preflight)
    app.router.add_options("/api/comments", handle_cors_preflight)
    app.router.add_route("DELETE", "/api/comments", handle_comments_delete)
    # Аватары
    app.router.add_get("/api/avatar", handle_avatar_get)
    app.router.add_options("/api/avatar", handle_cors_preflight)
    # Реакции на главу
    app.router.add_get("/api/reactions", handle_reactions_get)
    app.router.add_post("/api/reactions", handle_reactions_post)
    app.router.add_options("/api/reactions", handle_cors_preflight)
    # Переименование/сброс имён (режим редактора)
    app.router.add_route("DELETE", "/api/rename", handle_rename_delete)
    app.router.add_options("/api/rename", handle_cors_preflight)
    # Прогресс чтения
    app.router.add_get("/api/progress", handle_progress_get)
    app.router.add_post("/api/progress", handle_progress_post)
    app.router.add_options("/api/progress", handle_cors_preflight)
    # Репорты об опечатках
    app.router.add_post("/api/typo", handle_typo_post)
    app.router.add_options("/api/typo", handle_cors_preflight)
    # Создание короткой ссылки для переименования
    app.router.add_post("/api/rename/request", handle_rename_request)
    app.router.add_options("/api/rename/request", handle_cors_preflight)
    # Сортировка глав (Admin DnD)
    app.router.add_route("PUT", "/api/sort", handle_sort_chapters)
    app.router.add_options("/api/sort", handle_cors_preflight)
    # ИИ-чат (серверный прокси — ключ Groq не покидает сервер)
    app.router.add_post("/api/ai_chat", handle_ai_chat)
    app.router.add_options("/api/ai_chat", handle_cors_preflight)
    # Редактирование URL глав (Admin)
    app.router.add_route("PUT", "/api/chapters", handle_chapter_edit)
    app.router.add_options("/api/chapters", handle_cors_preflight)
    # Массовое добавление глав (Admin)
    app.router.add_post("/api/chapters/bulk", handle_chapter_bulk)
    app.router.add_options("/api/chapters/bulk", handle_cors_preflight)
    
    # --- Статические файлы для WebApp ---
    # Это позволяет запускать читалку прямо с того же сервера, что и API. 
    # В WEBAPP_URL в codes.env теперь можно прописать URL этого сервера (или ngrok).
    try:
        app.router.add_static('/webapp', 'webapp', show_index=True)
        logging.info("Маршрут /webapp зарегистрирован для статических файлов.")
    except Exception as e:
        logging.warning(f"Не удалось зарегистрировать /webapp: {e}")
    
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    logging.info("API сервер для читалки запущен на порту 8080")
    
    logging.info("Бот запущен. База данных готова.")
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        global _http_session
        if _http_session and not _http_session.closed:
            await _http_session.close()
        await runner.cleanup()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: logging.info("Бот остановлен.")