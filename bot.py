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
from datetime import datetime
from typing import Union

from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command, StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InputMediaPhoto, Message, CallbackQuery, WebAppInfo, 
    BotCommand, BotCommandScopeDefault
)

from config import BOT_TOKEN, GROQ_API_KEY, ADMIN_IDS, WEBAPP_URL
from handlers.rp import rp_router, RP_ACTIONS
from database import (
    init_db, update_rp_stat, get_user_stats, get_chapters, get_chapter_link, 
    get_user_marriage, get_ranobe_chapters, get_ranobe_chapter_link, 
    get_all_users, get_admins, add_admin, remove_admin, is_ai_enabled, toggle_group_ai,
    get_alya_mode, toggle_alya_mode, get_all_arts, delete_art_by_id,
    get_commands_link, set_commands_link, delete_commands_link,
    add_to_blacklist, remove_from_blacklist, is_blacklisted
)

COOLDOWN_TIME = 30 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

LANGUAGES = {"ru": "🇷🇺 Русский", "en": "🇬🇧 English", "jp": "🇯🇵 日本語", "color": "🎨 Цветная манга"}
RANOBE_LANGUAGES = {"alya": "⚔️ Воительница-Аля", "ru": "🇷🇺 Русский (Ранобэ)"}
ITEMS_PER_PAGE = 15

ART_CACHE: dict = {}
MARRIAGE_PROPOSALS: dict = {}
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

class ChapterUpload(StatesGroup):
    waiting_for_language = State()
    waiting_for_chapter_number = State()
    waiting_for_link = State()

class ChapterDelete(StatesGroup):
    waiting_for_language = State()
    waiting_for_chapter_number = State()

class RanobeUpload(StatesGroup):
    waiting_for_language = State()
    waiting_for_chapter_number = State()
    waiting_for_link = State()

class RanobeDelete(StatesGroup):
    waiting_for_language = State()
    waiting_for_chapter_number = State()

class NotifyUsers(StatesGroup):
    waiting_for_decision = State()

class TechSupport(StatesGroup):
    waiting_for_message = State()

class ArtView(StatesGroup):
    waiting_for_number = State()
    waiting_for_admin_number = State()

class ArtUpload(StatesGroup):
    waiting_for_photo = State()

class ArtSuggest(StatesGroup):
    waiting_for_photo = State()

class AIChat(StatesGroup):
    chatting = State()


# ==============================================================================
# БЛОК 2: АНТИСПАМ И КУЛДАУНЫ
# ==============================================================================
from utils import is_on_cooldown, check_cd_and_warn, delete_after, temp_reply


# ==============================================================================
# БЛОК 4: ИСКУССТВЕННЫЙ ИНТЕЛЛЕКТ (СИСТЕМА МУЛЬТИ-ПЕРСОНАЖЕЙ)
# ==============================================================================
async def ask_groq(prompt: str, system_prompt: str, history: list = None) -> str:
    if not GROQ_API_KEY: return "<i>❌ Ошибка: Нет ключа Groq.</i>"
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "temperature": 0.65, 
        "max_tokens": 300    
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['choices'][0]['message']['content']
                return f"<i>Ошибка ИИ: {resp.status}</i>"
    except Exception as e:
        logging.error(f"Groq Error: {e}")
        return "<i>Ошибка соединения с ИИ.</i>"

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

    data = await state.get_data()
    char_id = data.get("ai_character", "alya")
    chat_history = data.get("chat_history", [])

    if await is_blacklisted(user_id):
        return await message.answer("🚫 Вы находитесь в черном списке и не можете использовать ИИ.")

    alya_mode = await get_alya_mode()
    char_name, emoji, system_prompt = get_ai_setup(char_id, alya_mode=alya_mode)

    wait_msg = await message.answer(f"<i>{char_name} печатает...</i>", parse_mode="HTML")
    response = await ask_groq(message.text, system_prompt, history=chat_history)
    
    chat_history.append({"role": "user", "content": message.text})
    chat_history.append({"role": "assistant", "content": response})
    if len(chat_history) > 15: chat_history = chat_history[-15:]
    await state.update_data(chat_history=chat_history)

    await wait_msg.delete()
    builder = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="🚪 Выйти из чата", callback_data="main_menu"))
    await message.answer(f"{emoji} <b>{char_name}:</b>\n{response}", parse_mode="HTML", reply_markup=builder.as_markup())

def is_ai_trigger(message: types.Message):
    if not message.text or message.text.startswith('/'): 
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
    
    history = []
    if is_reply_to_bot and message.reply_to_message.text:
        bot_text = re.sub(r'^[🌸🎧].*?:\n', '', message.reply_to_message.text)
        history.append({"role": "assistant", "content": bot_text})

    wait_msg = await message.reply(f"<i>{char_name} печатает...</i>", parse_mode="HTML")
    response = await ask_groq(message.text, system_prompt, history=history)
    await wait_msg.delete()
    
    await message.reply(f"{emoji} <b>{char_name}:</b>\n{response}", parse_mode="HTML")


# ==============================================================================
# БЛОК 5: ГЛАВНОЕ МЕНЮ И БАЗОВЫЕ КОМАНДЫ
# ==============================================================================
def get_main_menu(is_group: bool = False):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="📖 Читать мангу", callback_data="read_langs"),
        types.InlineKeyboardButton(text="📚 Читать ранобэ", callback_data="read_ranobe_langs")
    )
    builder.row(
        types.InlineKeyboardButton(text="🎨 Цветные арты", callback_data="view_arts"),
        types.InlineKeyboardButton(text="📥 Предложить арт", callback_data="suggest_art_menu")
    )
    builder.row(types.InlineKeyboardButton(text="🌸 Чат с Алей", callback_data="ai_char_alya"))
    builder.row(types.InlineKeyboardButton(text="🎧 Чат с Масачикой", callback_data="ai_char_masachika"))
    builder.row(types.InlineKeyboardButton(text="ℹ️ Информация о проекте", callback_data="project_info_menu"))
    builder.row(types.InlineKeyboardButton(text="🆘 Тех. поддержка / Идеи", callback_data="tech_support_menu"))
    if not is_group:
        builder.row(types.InlineKeyboardButton(text="🌐 Веб-чат с Алей", web_app=WebAppInfo(url=WEBAPP_URL)))
    return builder.as_markup()

@dp.callback_query(F.data == "project_info_menu")
async def process_project_info_menu(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📅 График выхода", callback_data="schedule"))
    builder.row(types.InlineKeyboardButton(text="📺 Аниме vs Манга", callback_data="vs_anime"))
    
    # 2 buttons for commands
    builder.row(types.InlineKeyboardButton(text="📜 Полезные команды", callback_data="show_help"))
    link = await get_commands_link()
    if link:
        builder.row(types.InlineKeyboardButton(text="🔗 Все команды (Telegraph)", url=link))
        
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))
    await callback.message.edit_text("ℹ️ <b>Информация о проекте:</b>\n\nВыберите интересующий вас раздел ниже:", parse_mode="HTML", reply_markup=builder.as_markup())

def get_back_button(callback_data="main_menu", text="⬅️ Назад"):
    return InlineKeyboardBuilder().row(types.InlineKeyboardButton(text=text, callback_data=callback_data)).as_markup()

@dp.message(Command("start", ignore_mention=True), StateFilter("*"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    if message.chat.type == "private":
        reply_kb = types.ReplyKeyboardMarkup(
            keyboard=[[types.KeyboardButton(text="📋 Меню")]],
            resize_keyboard=True,
            persistent=True,
        )
        await message.answer(
            "👋 <b>Привет!</b> Я бот по манге <i>«Аля иногда кокетничает со мной по-русски»</i>.\n\nВыбирай раздел ниже:",
            parse_mode="HTML",
            reply_markup=reply_kb
        )
        await message.answer("Главное меню:", reply_markup=get_main_menu())
    else:
        await message.answer(
            "👋 <b>Привет!</b> Я бот по манге <i>«Аля иногда кокетничает со мной по-русски»</i>.\n\nВыбирай раздел ниже:",
            parse_mode="HTML",
            reply_markup=get_main_menu(is_group=True)
        )

@dp.message(F.text == "📋 Меню", StateFilter("*"))
async def handle_menu_button(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню:", reply_markup=get_main_menu())


async def get_help_text(user_id: int) -> str:
    text = (
        "📜 <b>Самые полезные команды:</b>\n\n"
        "🔹 /start — Открыть главное меню\n"
        "🔹 /profile — Твой профиль (ролеплей)\n"
        "🔹 /stats — Твоя статистика чата\n"
        "🔹 /marry (реплаем) — Вступить в брак\n"
        "🔹 /divorce — Расторгнуть брак\n"
        "🔹 /marriages — Показать топ пар\n\n"
        "🎲 <b>Рекомендуемые развлечения:</b>\n"
        "🔸 <i>/аля выбери [А] или [Б]</i> — Умный ИИ-выбор!\n"
        "🔸 <i>/инфа [текст]</i> — Вероятность события\n"
        "🔸 <i>/шар [вопрос]</i> — Магический шар (да/нет)\n"
        "🔸 <i>/монетка</i> — Орел или Решка\n\n"
        "<i>Подсказка: полный список команд и описание РП действий смотрите по кнопке «Все команды» (Telegraph).</i>"
    )
    
    admins = await get_admins()
    if user_id in admins:
        text += "\n\n(Вы администратор! Введите /admin чтобы увидеть скрытые команды)"
    return text

@dp.message(Command("help"), StateFilter("*"))
async def cmd_help(message: types.Message):
    await message.answer(await get_help_text(message.from_user.id), parse_mode="HTML")

@dp.callback_query(F.data == "show_help")
async def process_show_help(callback: types.CallbackQuery):
    await callback.message.edit_text(await get_help_text(callback.from_user.id), parse_mode="HTML", reply_markup=get_back_button())

@dp.callback_query(F.data == "main_menu")
async def process_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    is_group = callback.message.chat.type in ["group", "supergroup"]
    await callback.message.edit_text("Главное меню:", reply_markup=get_main_menu(is_group=is_group))

def get_langs_menu(prefix="lang"):
    builder = InlineKeyboardBuilder()
    for code, name in LANGUAGES.items():
        builder.row(types.InlineKeyboardButton(text=name, callback_data=f"{prefix}_{code}"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu" if prefix == "lang" else "admin_menu"))
    return builder.as_markup()

def get_ranobe_langs_menu(prefix="ranobelang"):
    builder = InlineKeyboardBuilder()
    for code, name in RANOBE_LANGUAGES.items():
        builder.row(types.InlineKeyboardButton(text=name, callback_data=f"{prefix}_{code}"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu" if prefix == "ranobelang" else "admin_menu"))
    return builder.as_markup()

@dp.callback_query(F.data == "schedule")
async def process_schedule(callback: types.CallbackQuery):
    await callback.message.edit_text("<b>📅 График:</b> Новые главы выходят раз в 2 недели по субботам в 18:00 МСК.", parse_mode="HTML", reply_markup=get_back_button())

@dp.callback_query(F.data == "vs_anime")
async def process_vs_anime(callback: types.CallbackQuery):
    await callback.message.edit_text("<b>📺 Аниме vs Манга:</b>\nМанга подробнее раскрывает монологи и шутки. Читай мангу примерно с 35 главы после 1 сезона аниме!", parse_mode="HTML", reply_markup=get_back_button())

@dp.callback_query(F.data == "suggest_art_menu")
async def callback_suggest_art_menu(callback: types.CallbackQuery, state: FSMContext):
    if await check_cd_and_warn(callback, "suggest_art", 60): return
    await state.set_state(ArtSuggest.waiting_for_photo)
    await callback.message.edit_text("🖼 <b>Предложка артов</b>\nОтправьте <b>одну</b> фотографию (арт), которую хотите предложить. Она будет проверена администрацией.\n\n❗️ Требования:\n1. Рисовка приближена к аниме.\n2. Хорошее качество.\n3. Без лишнего текста.", parse_mode="HTML", reply_markup=get_back_button(text="❌ Отмена"))

@dp.callback_query(F.data == "tech_support_menu")
async def process_tech_support_menu(callback: types.CallbackQuery, state: FSMContext):
    if await check_cd_and_warn(callback, "tech_support", 180): return
    await state.set_state(TechSupport.waiting_for_message)
    await callback.message.edit_text(
        "🆘 <b>Техническая поддержка / Предложения</b>\n"
        "Опишите вашу проблему, баг или идею в <b>одном сообщении</b>.\n"
        "Оно будет отправлено всем администраторам бота.", 
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


# ==============================================================================
# БЛОК 6: ПРОФИЛИ И РП-КОМАНДЫ
# ==============================================================================
@dp.message(F.text & F.text.regexp(REGEX_PROFILE))
async def cmd_profile(message: types.Message):
    if await check_cd_and_warn(message, "profile", 5): return
    user_id = message.from_user.id
    name = message.from_user.first_name
    
    partner_text = "Одинок(а) 💔"
    if message.chat.type in ["group", "supergroup"]:
        marriage = await get_user_marriage(message.chat.id, user_id)
        if marriage:
            u1_id, u1_name, u2_id, u2_name, date = marriage
            partner_name = u2_name if u1_name == name else u1_name
            partner_text = f"В браке с <b>{partner_name}</b> 💍 ({date})"
    
    hugs, kisses, bites, slaps, pats, m_count, s_count = await get_user_stats(user_id)
    
    profile_text = (
        f"👤 <b>Профиль пользователя {name}</b>\n\n"
        f"👩‍❤️‍👨 <b>Статус в чате:</b> {partner_text}\n\n"
        f"📊 <b>Твоя активность (РП):</b>\n"
        f"❤️ Нежность (поцеловал/лизнул): {kisses}\n"
        f"🤗 Забота (обнял/воскресил): {hugs}\n"
        f"🥰 Утешение (погладил/пожал руку): {pats}\n"
        f"🧛‍♀️ Вампиризм (кусь): {bites}\n"
        f"😠 Агрессия (ударил/пнул/убил): {slaps}\n"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔮 Узнать мнение Али о тебе", callback_data=f"roast_{user_id}")
    await message.answer(profile_text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("roast_"))
async def callback_roast_profile(callback: types.CallbackQuery):
    target_user_id = int(callback.data.split("_")[1])
    if callback.from_user.id != target_user_id:
        return await callback.answer("Вы можете попросить Алю оценить только СВОЙ профиль!", show_alert=True)
        
    if await check_cd_and_warn(callback, "alya_roast", 30): return
    
    await callback.message.edit_reply_markup(reply_markup=None)
    wait_msg = await callback.message.answer("<i>Аля изучает твое досье...</i>", parse_mode="HTML")
    
    name = callback.from_user.first_name
    hugs, kisses, bites, slaps, pats, m_count, s_count = await get_user_stats(target_user_id)
    
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
    if await check_cd_and_warn(message, "stats", 5): return
    user_id = message.from_user.id
    name = message.from_user.first_name
    
    hugs, kisses, bites, slaps, pats, m_count, s_count = await get_user_stats(user_id)
    
    stats_text = (
        f"📊 <b>Полная статистика {name}</b>\n\n"
        f"✉️ <b>Всего сообщений:</b> {m_count}\n"
        f"🌟 <b>Отправлено стикеров:</b> {s_count}\n\n"
        f"🎭 <b>РП Активность:</b>\n"
        f"Спокойствие (обнял, погладил и т.д.): {hugs + pats} раз\n"
        f"Агрессия (ударил, пнул и т.д.): {slaps + bites} раз\n"
        f"Любовь (поцеловал): {kisses} раз\n"
    )
    await message.answer(stats_text, parse_mode="HTML")

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


    MARRIAGE_PROPOSALS[f"{chat_id}_{initiator.id}_{target.id}"] = f"@{initiator.username}" if initiator.username else initiator.first_name

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
            init_name = f"@{chat_member.user.username}" if chat_member.user.username else chat_member.user.first_name
        except Exception:
            init_name = f'<a href="tg://user?id={init_id}">Пользователь</a>'
            
    targ_user = callback.from_user
    targ_name = f"@{targ_user.username}" if targ_user.username else targ_user.first_name
        
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
    
    if not await get_user_marriage(message.chat.id, message.from_user.id):
        return await temp_reply(message, "Вы не состоите в браке в этой беседе.")
        
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('DELETE FROM marriages WHERE chat_id = ? AND (user1_id = ? OR user2_id = ?)', (message.chat.id, message.from_user.id, message.from_user.id))
        await db.commit()
    await message.answer("💔 Вы успешно расторгли брак.")

@dp.message(F.text & F.text.regexp(REGEX_MARRIAGES))
async def list_marriages(message: types.Message):
    if message.chat.type == "private": return await temp_reply(message, "Только в группах!")
    if await check_cd_and_warn(message, "marriages_list", 10): return

    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT user1_id, user2_id, user1_name, user2_name, date FROM marriages WHERE chat_id = ?', (message.chat.id,)) as cursor:
            marriages = await cursor.fetchall()
            
    if not marriages: return await temp_reply(message, "В этой беседе пока нет ни одной пары 😔", parse_mode="HTML")
    
    # helper for safe name display
    def fmt_name(uid, name):
        name = str(name)
        if name.startswith("Пользователь "): return f'<a href="tg://user?id={uid}">Пользователь</a>'
        if name.startswith("@") or name.startswith("<a"): return f"<b>{name}</b>"
        return f'<b><a href="tg://user?id={uid}">{name}</a></b>'

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
def get_langs_menu(prefix: str):
    builder = InlineKeyboardBuilder()
    for code, name in LANGUAGES.items(): builder.button(text=name, callback_data=f"{prefix}_{code}")
    builder.adjust(1)
    if prefix.startswith("read"): builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))
    return builder.as_markup()

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

    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="read_ranobe_langs"))
    return builder.as_markup()

@dp.callback_query(F.data == "read_langs")
async def process_read_langs(callback: types.CallbackQuery):
    await callback.message.edit_text("🌐 Выберите язык для чтения:", reply_markup=get_langs_menu("readlang"))

@dp.callback_query(F.data.startswith("readlang_"))
async def process_read_chapters(callback: types.CallbackQuery):
    lang_code = callback.data.split("_")[1]
    chapters = await get_chapters(lang_code)
    await callback.message.edit_text(f"📚 Доступные главы ({LANGUAGES[lang_code]}):", reply_markup=get_chapters_menu(lang_code, chapters, page=0))

@dp.callback_query(F.data == "read_ranobe_langs")
async def process_read_ranobe_langs(callback: types.CallbackQuery):
    await callback.message.edit_text("📖 Выберите ранобэ для чтения:", reply_markup=get_ranobe_langs_menu("readranobelang"))

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

    _, lang, chapter_num = callback.data.split("_")
    link = await get_chapter_link(lang, chapter_num)

    if link:
        await callback.message.delete() 
        status_msg = await callback.message.answer(f"⏳ Загружаю информацию о главе {chapter_num}...")
        
        # Soft cooldown for AI recap to prevent UI blocking
        if not await is_on_cooldown(user_id, "ai_recap", 20):
            sys_prompt = "Ты фанат манги Roshidere. Коротко (2-3 предложения) опиши сюжет в районе этой главы."
            recap = await ask_groq(f"Напомни сюжет без спойлеров к главе {chapter_num}", sys_prompt)
            await status_msg.edit_text(f"✨ <b>Рекап сюжета:</b>\n<i>{recap}</i>", parse_mode="HTML")
        else:
            await status_msg.edit_text(f"⏳ <b>Глава найдена!</b>\n<i>(Рекап временно недоступен, Алиса отдыхает).</i>", parse_mode="HTML")
            
        builder = InlineKeyboardBuilder()
        builder.button(text=f"🔗 Читать главу {chapter_num}", url=link)
        builder.button(text="📚 К главам", callback_data=f"readlang_{lang}")
        await callback.message.answer("✅ Приятного чтения!", reply_markup=builder.adjust(1).as_markup())
    else:
        await callback.answer("Глава не найдена 😔", show_alert=True)

import random

async def send_user_art_item(chat_id: int, index: int, message_to_edit: types.Message = None):
    arts = await get_all_arts()
    if not arts:
        if message_to_edit:
            try: await message_to_edit.delete() 
            except: pass
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
    builder.row(types.InlineKeyboardButton(text="📱 Режим сетки (9 шт)", callback_data="user_art_grid:0"))
    builder.row(types.InlineKeyboardButton(text="⬅️ В меню", callback_data="main_menu"))

    caption = f"🎨 <b>Арт из галереи</b>\n<i>({index + 1} из {len(arts)})</i>"

    if message_to_edit:
        try:
            await message_to_edit.edit_media(
                media=types.InputMediaPhoto(media=file_id, caption=caption, parse_mode="HTML"),
                reply_markup=builder.as_markup()
            )
        except Exception:
            await bot.send_photo(chat_id, photo=file_id, caption=caption, parse_mode="HTML", reply_markup=builder.as_markup())
            try: await message_to_edit.delete() 
            except: pass
    else:
        await bot.send_photo(chat_id, photo=file_id, caption=caption, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "view_arts")
async def view_arts(callback: types.CallbackQuery):
    if await check_cd_and_warn(callback, "arts", 5): return
    await callback.message.delete()
    await send_user_art_item(callback.message.chat.id, 0)

@dp.callback_query(F.data.startswith("user_art_view:"))
async def process_user_art_view(callback: types.CallbackQuery):
    index = int(callback.data.split(":")[1])
    await send_user_art_item(callback.message.chat.id, index, message_to_edit=callback.message)
    await callback.answer()

@dp.callback_query(F.data == "user_art_random")
async def process_user_art_random(callback: types.CallbackQuery):
    arts = await get_all_arts()
    if not arts:
        return await callback.answer("Галерея пуста 😔", show_alert=True)
    index = random.randint(0, len(arts) - 1)
    await send_user_art_item(callback.message.chat.id, index, message_to_edit=callback.message)
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
        await send_user_art_item(message.chat.id, num - 1)
    else:
        await message.answer(f"❌ Неверный номер! Введите число от 1 до {len(arts)}.")

@dp.callback_query(F.data.startswith("user_art_grid:"))
async def process_user_art_grid(callback: types.CallbackQuery):
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
    await bot.send_media_group(chat_id=callback.message.chat.id, media=media)

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="⬅️ Пред. стр", callback_data=f"user_art_grid:{page - 1}")
    if end < len(arts):
        builder.button(text="След. стр ➡️", callback_data=f"user_art_grid:{page + 1}")
    
    builder.button(text="🎚 К слайдеру", callback_data="view_arts")
    builder.button(text="⬅️ В меню", callback_data="main_menu")
    
    await callback.message.answer(
        f"📱 <b>Сетка артов</b>\n<i>Страница {page + 1} (Показаны {len(sliced)} из {len(arts)})</i>",
        parse_mode="HTML",
        reply_markup=builder.adjust(2).as_markup()
    )


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
    text = (
        "👑 <b>Админка</b>\n"
        "/add_chapter | /delete_chapter - Главы манги\n"
        "/add_ranobe | /delete_ranobe - Главы ранобэ\n"
        "/add_art | /arts_list | /delete_art - Арты\n"
        "/add_admin | /delete_admin - Админы\n"
        "/blacklist_ai | /unblacklist_ai - ЧС для ИИ\n"
        "/toggle_ai - Вкл/выкл ИИ (в текущей группе)\n"
        "/alya_mode - Переключить режим Али (нормальный/гопник)\n"
        "/set_commands_link | /delete_commands_link - Telegraph ссылка на список команд\n"
        "/cancel - Отмена"
    )
    await message.answer(text, parse_mode="HTML")

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
        except Exception:
            # На случай осечки
            await bot.send_photo(chat_id, photo=file_id, caption=caption, parse_mode="HTML", reply_markup=builder.as_markup())
            try: await message_to_edit.delete() 
            except: pass
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
async def process_admin_art_grid(callback: types.CallbackQuery):
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
    await bot.send_media_group(chat_id=callback.message.chat.id, media=media)

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="⬅️ Пред. стр", callback_data=f"admin_art_grid:{page - 1}")
    if end < len(arts):
        builder.button(text="След. стр ➡️", callback_data=f"admin_art_grid:{page + 1}")
    
    # Arts list Command forces send_admin_art_item(0) 
    builder.button(text="🎚 К слайдеру", callback_data="admin_art_view_back")
    
    await callback.message.answer(
        f"👑 <b>[Админ] Сетка артов</b>\n<i>Страница {page + 1} (Показаны {len(sliced)} из {len(arts)})</i>",
        parse_mode="HTML",
        reply_markup=builder.adjust(2).as_markup()
    )

@dp.callback_query(F.data == "admin_art_view_back")
async def process_admin_art_view_back(callback: types.CallbackQuery):
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
        except:
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

@dp.message(Command("add_chapter"))
async def cmd_add_chapter(message: types.Message, state: FSMContext):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    await state.set_state(ChapterUpload.waiting_for_language)
    await message.answer("Выберите язык:", reply_markup=get_langs_menu("adminlang"))

@dp.callback_query(ChapterUpload.waiting_for_language, F.data.startswith("adminlang_"))
async def admin_process_language(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(lang=callback.data.split("_")[1])
    await state.set_state(ChapterUpload.waiting_for_chapter_number)
    await callback.message.edit_text("Введите номер главы:")

@dp.message(ChapterUpload.waiting_for_chapter_number)
async def admin_process_chapter_number(message: types.Message, state: FSMContext):
    await state.update_data(chapter_number=message.text.strip())
    await state.set_state(ChapterUpload.waiting_for_link)
    await message.answer("🔗 Отправьте ссылку на главу:")

@dp.message(ChapterUpload.waiting_for_link, F.text)
async def admin_process_link(message: types.Message, state: FSMContext):
    data = await state.get_data()
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('INSERT OR REPLACE INTO chapters_urls (chapter_number, lang, url) VALUES (?, ?, ?)', (data['chapter_number'], data['lang'], message.text.strip()))
        await db.commit()
    
    await message.answer(f"✅ Глава манги {data['chapter_number']} добавлена!\n🔗 Ссылка: {message.text.strip()}")
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, разослать", callback_data="notify_yes")
    builder.button(text="Нет", callback_data="notify_no")
    await state.set_state(NotifyUsers.waiting_for_decision)
    await state.update_data(notify_text=f"📚 <b>Вышла новая глава манги:</b> {data['chapter_number']} ({LANGUAGES.get(data['lang'], data['lang'])})\n🔗 {message.text.strip()}")
    await message.answer("Отправить уведомление всем пользователям?", reply_markup=builder.as_markup())

# --- РАНОБЭ ДОБАВЛЕНИЕ ---
@dp.message(Command("add_ranobe"))
async def cmd_add_ranobe(message: types.Message, state: FSMContext):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    await state.set_state(RanobeUpload.waiting_for_language)
    await message.answer("Выберите ранобэ:", reply_markup=get_ranobe_langs_menu("adminranobe"))

@dp.callback_query(RanobeUpload.waiting_for_language, F.data.startswith("adminranobe_"))
async def admin_process_ranobe_language(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(lang=callback.data.split("_")[1])
    await state.set_state(RanobeUpload.waiting_for_chapter_number)
    await callback.message.edit_text("Введите номер главы (или название, слитно):")

@dp.message(RanobeUpload.waiting_for_chapter_number)
async def admin_process_ranobe_chapter_number(message: types.Message, state: FSMContext):
    await state.update_data(chapter_number=message.text.strip())
    await state.set_state(RanobeUpload.waiting_for_link)
    await message.answer("🔗 Отправьте ссылку на главу ранобэ:")

@dp.message(RanobeUpload.waiting_for_link, F.text)
async def admin_process_ranobe_link(message: types.Message, state: FSMContext):
    data = await state.get_data()
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('INSERT OR REPLACE INTO ranobe_urls (chapter_number, lang, url) VALUES (?, ?, ?)', (data['chapter_number'], data['lang'], message.text.strip()))
        await db.commit()
    
    await message.answer(f"✅ Глава ранобэ {data['chapter_number']} добавлена!\n🔗 Ссылка: {message.text.strip()}")
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, разослать", callback_data="notify_yes")
    builder.button(text="Нет", callback_data="notify_no")
    await state.set_state(NotifyUsers.waiting_for_decision)
    await state.update_data(notify_text=f"📚 <b>Вышла новая глава ранобэ:</b> {data['chapter_number']} ({RANOBE_LANGUAGES.get(data['lang'], data['lang'])})\n🔗 {message.text.strip()}")
    await message.answer("Отправить уведомление всем пользователям?", reply_markup=builder.as_markup())

# --- УВЕДОМЛЕНИЯ ---
@dp.callback_query(NotifyUsers.waiting_for_decision, F.data.startswith("notify_"))
async def process_notification_decision(callback: types.CallbackQuery, state: FSMContext):
    decision = callback.data.split("_")[1]
    data = await state.get_data()
    text = data.get("notify_text", "")
    await state.clear()
    
    if decision == "no":
        return await callback.message.edit_text("Уведомление отменено.")
        
    await callback.message.edit_text("⏳ <i>Начинаю массовую рассылку...</i>", parse_mode="HTML")
    
    users = await get_all_users()
    count = 0
    for user_id in users:
        try:
            await bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
            
    await callback.message.answer(f"✅ Рассылка завершена!\nСообщение получили <b>{count}</b> из <b>{len(users)}</b> пользователей.", parse_mode="HTML")

# --- ДОБАВЛЕНА ФУНКЦИЯ УДАЛЕНИЯ ГЛАВ ---
@dp.message(Command("delete_chapter"))
async def cmd_delete_chapter(message: types.Message, state: FSMContext):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    await state.set_state(ChapterDelete.waiting_for_language)
    await message.answer("Выберите язык для удаления главы манги:", reply_markup=get_langs_menu("dellang"))

@dp.callback_query(ChapterDelete.waiting_for_language, F.data.startswith("dellang_"))
async def admin_process_del_language(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(lang=callback.data.split("_")[1])
    await state.set_state(ChapterDelete.waiting_for_chapter_number)
    await callback.message.edit_text("Введите номер главы для удаления:")

@dp.message(ChapterDelete.waiting_for_chapter_number)
async def admin_process_del_chapter_number(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang")
    chapter_number = message.text.strip()
    
    async with aiosqlite.connect('manga.db') as db:
        cursor = await db.execute('DELETE FROM chapters_urls WHERE chapter_number = ? AND lang = ?', (chapter_number, lang))
        if cursor.rowcount > 0:
            await message.answer(f"✅ Глава манги {chapter_number} ({LANGUAGES.get(lang, lang)}) успешно удалена из базы!")
        else:
            await message.answer(f"❌ Глава манги {chapter_number} ({LANGUAGES.get(lang, lang)}) не найдена!")
        await db.commit()
    await state.clear()

# --- ДОБАВЛЕНА ФУНКЦИЯ УДАЛЕНИЯ РАНОБЭ ---
@dp.message(Command("delete_ranobe"))
async def cmd_delete_ranobe(message: types.Message, state: FSMContext):
    admins = await get_admins()
    if message.from_user.id not in admins: return
    await state.set_state(RanobeDelete.waiting_for_language)
    await message.answer("Выберите ранобэ для удаления главы:", reply_markup=get_ranobe_langs_menu("delranobelang"))

@dp.callback_query(RanobeDelete.waiting_for_language, F.data.startswith("delranobelang_"))
async def admin_process_del_ranobe_language(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(lang=callback.data.split("_")[1])
    await state.set_state(RanobeDelete.waiting_for_chapter_number)
    await callback.message.edit_text("Введите номер/название главы для удаления:")

@dp.message(RanobeDelete.waiting_for_chapter_number)
async def admin_process_del_ranobe_chapter_number(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang")
    chapter_number = message.text.strip()
    
    async with aiosqlite.connect('manga.db') as db:
        cursor = await db.execute('DELETE FROM ranobe_urls WHERE chapter_number = ? AND lang = ?', (chapter_number, lang))
        if cursor.rowcount > 0:
            await message.answer(f"✅ Глава ранобэ {chapter_number} ({RANOBE_LANGUAGES.get(lang, lang)}) успешно удалена из базы!")
        else:
            await message.answer(f"❌ Глава ранобэ {chapter_number} ({RANOBE_LANGUAGES.get(lang, lang)}) не найдена!")
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
    await message.answer("🖼 <b>Предложка артов</b>\nОтправьте <b>одну</b> фотографию (арт), которую хотите предложить. Она будет проверена администрацией.\n\n❗️ Требования:\n1. Рисовка приближена к аниме.\n2. Хорошее качество.\n3. Без лишнего текста.", parse_mode="HTML")

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
            is_sticker = 1 if getattr(event, 'sticker', None) else 0
            
            async with aiosqlite.connect('manga.db') as db:
                await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (user_id,))
                if is_sticker:
                    await db.execute('UPDATE users_stats SET stickers_count = stickers_count + 1 WHERE user_id = ?', (user_id,))
                elif getattr(event, 'text', None) or getattr(event, 'caption', None):
                    await db.execute('UPDATE users_stats SET messages_count = messages_count + 1 WHERE user_id = ?', (user_id,))
                await db.commit()
                
        return await handler(event, data)

async def main():
    dp.include_router(rp_router)
    
    await init_db()
    
    dp.message.middleware(StatsMiddleware())
    
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
    # ================================
    
    logging.info("Бот запущен. База данных готова.")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: logging.info("Бот остановлен.")