# -*- coding: utf-8 -*-

# ==============================================================================
# БЛОК 1: НАСТРОЙКИ, ИМПОРТЫ И КЭШ
# ==============================================================================
import logging
import asyncio
import json
import math
import time
import os
import hashlib
import re
import random
import aiosqlite
import aiohttp
import aiohttp.web
import base64
import io
import html
from PIL import Image, UnidentifiedImageError
from datetime import datetime
from html.parser import HTMLParser
from typing import Union
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InputMediaPhoto, Message, CallbackQuery, WebAppInfo, BotCommand, BotCommandScopeDefault

import uuid
from config import BOT_TOKEN, GROQ_API_KEY, ADMIN_IDS, WEBAPP_URL, API_HOST, GEMMA_URL, GEMMA_MODEL, GEMMA_TIMEOUT

# Основной путь к SQLite-базе. Раньше было 55+ хардкоженных "manga.db" в коде.
# Если база переедет — правим в одном месте.
_DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_DB_DIR, 'manga.db')

# Кэш для коротких ссылок переименования (обход лимита 64 символа в deeplink)
RENAME_CACHE = {}


def _resolve_webapp_cache_buster() -> str:
    """Определяет версию ассетов WebApp, чтобы обойти кэш Telegram/браузера.

    Приоритет:
      1. Явная переменная окружения WEBAPP_CACHE_BUSTER (нестрока пустая).
      2. Короткий SHA текущего git HEAD (авто-инвалидирует кэш после каждого деплоя).
      3. Временная метка (fallback, если .git недоступен).
    """
    explicit = str(os.getenv("WEBAPP_CACHE_BUSTER", "")).strip()
    if explicit:
        return explicit
    try:
        import subprocess

        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)) or ".",
            capture_output=True,
            text=True,
            timeout=3,
        )
        sha = (out.stdout or "").strip()
        if sha and out.returncode == 0:
            return sha
    except Exception:
        pass
    # Fallback: epoch seconds — гарантирует свежесть, но меняется на каждом рестарте.
    return str(int(time.time()))


WEBAPP_CACHE_BUSTER = _resolve_webapp_cache_buster()
logging.getLogger(__name__).info("WebApp cache buster: %s", WEBAPP_CACHE_BUSTER)
from handlers.rp import rp_router, RP_ACTIONS
from database import (
    init_db,
    update_rp_stat,
    get_user_stats,
    get_chapters,
    get_chapter_link,
    get_user_marriage,
    get_ranobe_chapters,
    get_ranobe_chapter_link,
    get_all_users,
    get_admins,
    add_admin,
    remove_admin,
    is_ai_enabled,
    toggle_group_ai,
    get_alya_mode,
    toggle_alya_mode,
    get_all_arts,
    delete_art_by_id,
    get_commands_link,
    set_commands_link,
    delete_commands_link,
    add_to_blacklist,
    remove_from_blacklist,
    is_blacklisted,
    get_blacklist,
    get_akashic_volumes,
    get_akashic_chapters,
    get_akashic_chapter_link,
    get_british_volumes,
    get_british_chapters,
    get_british_chapter_link,
    get_chat_ai_provider,
    set_chat_ai_provider,
    get_ai_memory,
    append_ai_memory,
    clear_ai_memory,
    add_to_harem,
    remove_from_harem,
    get_user_harem,
    update_loyalty_level,
    add_to_inventory,
    get_user_inventory,
    get_users_with_bookmark,
    add_referral,
    get_referral_stats,
    get_user_referred_by,
    get_setting,
    set_setting,
    get_custom_name,
    upsert_user_profile,
    get_user_profile_by_username,
    write_admin_audit_log,
)

COOLDOWN_TIME = 30

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Re-export чистых helper'ов из services/ (вынесены из bot.py, чтобы other services/
# могли их импортировать top-level без триггера `from bot import X` и связанного
# повторного импорта bot.py).
from services.shared_state import ART_CACHE  # noqa: E402,F401
from services.telegram_helpers import escape_html_text, format_user_tag, get_back_button  # noqa: E402,F401
from services.admin_helpers import MAIN_ADMIN_ID, _fake_admin_message, _is_bot_admin, _require_admin  # noqa: E402,F401
from services.admin_builders import (  # noqa: E402,F401
    _build_admin_menu_kb,
    _build_admin_menu_text,
    _build_admins_list_kb,
    _build_settings_text_and_kb,
    _fetch_admin_metrics,
    _render_admins_section,
)

# Импорт ради side-effect: декораторы @art_router.message/callback_query регистрируют
# handler'ы на art_router. Сам dp.include_router(art_router) вызывается в main() —
# иначе при re-import bot.py (через `from bot import X` внутри handler'а Python
# импортирует bot.py заново как модуль `bot` вместо `__main__`) top-level
# include_router падает с RuntimeError: "Router is already attached".
from services.admin_art_fsm import art_router, cmd_add_art  # noqa: E402,F401

# admin_router (B.3 + B.4): главное меню /admin + management админов.
# Re-export cmd_admin, cmd_add_admin, cmd_delete_admin, AdminManage для
# admin_menu_commands dispatcher'а и тестов (EXPECTED_COMMANDS).
from services.admin_telegram import (  # noqa: E402,F401
    AdminManage,
    admin_router,
    cmd_add_admin,
    cmd_admin,
    cmd_delete_admin,
)

# content_metadata (B.5): LANGUAGES/RANOBE_LANGUAGES/CONTENT_TYPES +
# get_langs_menu/get_ranobe_langs_menu. Shared-слой между bot.py
# (read-каталоги) и services/admin_content.py (admin content FSM).
from services.content_metadata import (  # noqa: E402,F401
    CONTENT_TYPES,
    LANGUAGES,
    RANOBE_LANGUAGES,
    get_langs_menu,
    get_ranobe_langs_menu,
)

# content_router (B.5): admin content FSM + cmd_add/delete chapter/ranobe/
# akashic/british/art + notify users. Re-export cmd-функций для
# admin_menu_commands dispatcher'а.
from services.admin_content import (  # noqa: E402,F401
    NotifyUsers,
    UniversalContentDelete,
    UniversalContentUpload,
    cmd_add_akashic,
    cmd_add_british,
    cmd_add_chapter,
    cmd_add_ranobe,
    cmd_delete_akashic,
    cmd_delete_art,
    cmd_delete_british,
    cmd_delete_chapter,
    cmd_delete_ranobe,
    content_router,
)

# rename_router (B.6): AdminRename FSM + process_rename_name.
from services.admin_rename import AdminRename, rename_router  # noqa: E402,F401

# settings_router (B.6): все settings commands + admin_menu_commands
# dispatcher + admin_menu_sync_webapp. Re-export cmd-функций для
# обратной совместимости (тесты EXPECTED_COMMANDS).
from services.admin_settings import (  # noqa: E402,F401
    cmd_ai_provider,
    cmd_alya_mode,
    cmd_blacklist_ai,
    cmd_blacklist_view,
    cmd_delete_commands_link,
    cmd_set_commands_link,
    cmd_sync_webapp,
    cmd_test_notification,
    cmd_toggle_ai,
    cmd_toggle_sync,
    cmd_unblacklist_ai,
    settings_router,
)

# art_view_router (B.7): ArtView FSM + user/admin art gallery navigation.
# Re-export ArtView + send_*_art_item helpers для обратной совместимости.
from services.art_view import (  # noqa: E402,F401
    ArtView,
    art_view_router,
    cmd_arts_list,
    send_admin_art_item,
    send_user_art_item,
)


# ============================================================================
# ANTI-DOUBLE-TAP MIDDLEWARE для callback_query
# ----------------------------------------------------------------------------
# Защищает от случайных двойных нажатий на inline-кнопки: если тот же
# (user_id, callback_data) приходит повторно в течение N секунд —
# отвечаем пустым callback.answer() и не пускаем в handler.
#
# Также реализует общий rate-limit для callback-кнопок: не более
# 5 callback/сек от одного пользователя (анти-спам).
# ============================================================================
# BaseMiddleware уже импортирован выше на строке 25.
from collections import deque, defaultdict
from typing import Any, Awaitable, Callable, Dict as _Dict

_CB_DEDUP_WINDOW_SEC = 2.0  # окно для дедупликации одинаковых тапов
_CB_RATE_WINDOW_SEC = 1.0  # окно для общего rate-limit callback
_CB_RATE_MAX_IN_WINDOW = 5  # макс. callbacks в окне


class CallbackAntiSpamMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        # (user_id, data) → timestamp последнего такого же тапа
        self._last_tap: _Dict[tuple[int, str], float] = {}
        # user_id → deque[timestamps] для rate-limit
        self._recent: _Dict[int, deque[float]] = defaultdict(deque)

    async def __call__(
        self,
        handler: Callable[[types.CallbackQuery, _Dict[str, Any]], Awaitable[Any]],
        event: types.CallbackQuery,
        data: _Dict[str, Any],
    ) -> Any:
        user = event.from_user
        if user is None:
            return await handler(event, data)

        now = time.time()
        key = (user.id, event.data or "")

        # 1) Дедупликация одинаковых тапов в коротком окне (double-click)
        prev = self._last_tap.get(key)
        if prev is not None and (now - prev) < _CB_DEDUP_WINDOW_SEC:
            try:
                await event.answer()
            except Exception as e:
                logging.debug(f"callback_antispam: dedup answer failed: {e}")
            return  # тихо игнорируем
        self._last_tap[key] = now

        # 2) Общий callback rate-limit
        q = self._recent[user.id]
        cutoff = now - _CB_RATE_WINDOW_SEC
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= _CB_RATE_MAX_IN_WINDOW:
            try:
                await event.answer("⏳ Слишком быстро, подожди секунду.", show_alert=False)
            except Exception as e:
                logging.debug(f"callback_antispam: rate-limit answer failed: {e}")
            return
        q.append(now)

        # 3) Периодическая очистка _last_tap от старых записей (не чаще раза в минуту)
        if len(self._last_tap) > 2048:
            stale = [k for k, ts in self._last_tap.items() if (now - ts) > 60]
            for k in stale:
                self._last_tap.pop(k, None)

        return await handler(event, data)


dp.callback_query.middleware(CallbackAntiSpamMiddleware())


# ============================================================================
# ГЛОБАЛЬНЫЙ ERROR HANDLER
# ----------------------------------------------------------------------------
# Логирует все необработанные исключения. Telegram-API ошибки (BadRequest/
# Forbidden при delete/edit) глушатся, пользователю — дружелюбное сообщение.
# ============================================================================
@dp.errors()
async def global_error_handler(event: types.ErrorEvent) -> bool:
    exc = event.exception
    update = event.update

    # Все Telegram API ошибки (BadRequest, Forbidden, NotFound, RetryAfter,
    # Migrate, Conflict, Unauthorized, ServerError) — рутинная часть протокола,
    # их не нужно показывать пользователю как "что-то пошло не так".
    from aiogram.exceptions import TelegramAPIError

    if isinstance(exc, TelegramAPIError):
        logging.debug(f"global_error_handler: suppressed Telegram API error: {type(exc).__name__}: {exc}")
        return True

    # Для реальных Python-ошибок: залогировать с максимальным контекстом.
    chat_id = None
    user_id = None
    source_text = None
    try:
        if update.message is not None:
            chat_id = update.message.chat.id if update.message.chat else None
            user_id = update.message.from_user.id if update.message.from_user else None
            source_text = (update.message.text or update.message.caption or "")[:120]
        elif update.callback_query is not None:
            chat_id = (
                update.callback_query.message.chat.id if update.callback_query.message and update.callback_query.message.chat else None
            )
            user_id = update.callback_query.from_user.id if update.callback_query.from_user else None
            source_text = update.callback_query.data
    except Exception:
        pass
    logging.exception(
        "Unhandled handler error: type=%s chat=%s user=%s src=%r",
        type(exc).__name__,
        chat_id,
        user_id,
        source_text,
        exc_info=exc,
    )

    # Уведомляем пользователя:
    # - в группе/супергруппе — через ephemeral, чтобы не засорять чат;
    # - в callback — через silent answer (без текста, т.к. alert раздражает).
    try:
        if update.callback_query is not None:
            # silent ack — просто закрываем loading spinner в клиенте
            await update.callback_query.answer()
            return True
        if update.message is not None:
            is_group = update.message.chat.type in ("group", "supergroup")
            # В группах вообще ничего не пишем: иначе попап "⚠️ ..." виден всем.
            # В ЛС — короткая эфемерка.
            if not is_group:
                reply = await update.message.answer("⚠️ Что-то сломалось. Я уже записал это в логи.")
                schedule_delete_once(reply, 10)
    except Exception as notify_err:
        logging.debug(f"global_error_handler: notify failed: {notify_err}")
    return True


# Глобальная aiohttp сессия (открывается один раз при старте)
_http_session: aiohttp.ClientSession | None = None

# Reader-кэши (state + TTL + invalidate) вынесены в services/reader_cache.py.
from services.reader_cache import (  # noqa: E402,F401
    CHAPTER_CONTENT_CACHE_TTL_SECONDS,
    READER_CACHE_TTL_SECONDS,
    _chapter_content_cache,
    _chapter_content_cache_lock,
    _reader_cache_lock,
    _reader_data_cache,
    invalidate_chapter_content_cache,
    invalidate_reader_cache,
)


async def get_http_session() -> aiohttp.ClientSession:
    """Возвращает единственную aiohttp-сессию, создаёт лениво."""
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    return _http_session


def build_webapp_url(page_name: str) -> str:
    base = f"{WEBAPP_URL.rstrip('/')}/webapp/{str(page_name).lstrip('/')}"
    query_items: list[tuple[str, str]] = []
    if API_HOST:
        query_items.append(("api", str(API_HOST)))
    if WEBAPP_CACHE_BUSTER:
        query_items.append(("rev", WEBAPP_CACHE_BUSTER))
    query = urlencode(query_items)
    return f"{base}?{query}" if query else base


# --- Хелперы ---
def fmt_name(uid, name):
    """Форматирует имя пользователя в красивую ссылку."""
    name = str(name)
    clean_name = name.lstrip("@").strip()
    if clean_name.startswith("<a"):
        return f"<b>{name}</b>"
    if clean_name.startswith("Пользователь"):
        clean_name = "Пользователь"
    return f'<b><a href="tg://user?id={uid}">{html.escape(clean_name, quote=False)}</a></b>'


# escape_html_text, format_user_tag → вынесены в services/telegram_helpers.py
# (доступны через re-export на top-level этого файла).


# LANGUAGES, RANOBE_LANGUAGES → вынесены в services/content_metadata.py
# (доступны через re-export на top-level этого файла).
ITEMS_PER_PAGE = 15

# ART_CACHE → вынесен в services/shared_state.py (доступен через re-export).
MARRIAGE_PROPOSALS: dict = {}
HAREM_PROPOSALS: dict = {}
BOT_CMD_MENTION = r"(?:@[A-Za-z0-9_]{3,})?"

REGEX_START = re.compile(rf'(?i)^[/*\s]*(?:start|старт){BOT_CMD_MENTION}\s*$')
REGEX_INFA = re.compile(rf'(?i)^[/*\s]*(?:инфа|infa|info){BOT_CMD_MENTION}\s+(.+)$')
REGEX_RANDOM = re.compile(rf'(?i)^[/*\s]*(?:рандом|random){BOT_CMD_MENTION}\s+(\d+)$')
REGEX_CHOOSE = re.compile(rf'(?i)^[/*\s]*(?:выбери|choose){BOT_CMD_MENTION}\s+(.+)\s+(?:или|or)\s+(.+)$')
REGEX_ALYA_CHOOSE = re.compile(
    rf'(?i)^[/*\s]*(?:аля|alya){BOT_CMD_MENTION}[, ]+(?:выбери|choose){BOT_CMD_MENTION}\s+(.+)\s+(?:или|or)\s+(.+)$'
)
REGEX_COIN = re.compile(rf'(?i)^[/*\s]*(?:монетка|орел или решка|coin|heads or tails){BOT_CMD_MENTION}\s*$')
REGEX_DICE = re.compile(r'(?i)^[/*\s]*(?:кости|кубик|dice|cube)\b')
REGEX_MARRY = re.compile(r'(?i)^[/*\s]*(?:брак|свадьба|marry)\b')
REGEX_DIVORCE = re.compile(r'(?i)^[/*\s]*(?:развод|divorce)\b')
REGEX_MARRIAGES = re.compile(r'(?i)^[/*\s]*(?:браки|marriages)\b')
REGEX_PROFILE = re.compile(r'(?i)^[/*\s]*(?:профиль|profile)\b')
REGEX_STATS = re.compile(r'(?i)^[/*\s]*(?:статистика|стата|stats)\b')
REGEX_DARTS = re.compile(r'(?i)^[/*\s]*(?:дартс|darts)\b')
REGEX_BASKETBALL = re.compile(r'(?i)^[/*\s]*(?:баскетбол|basketball)\b')
REGEX_FOOTBALL = re.compile(r'(?i)^[/*\s]*(?:футбол|football)\b')
REGEX_BOWLING = re.compile(r'(?i)^[/*\s]*(?:боулинг|bowling)\b')
REGEX_RPS = re.compile(
    rf'(?i)^[/*\s]*(?:камень ножницы бумага|кнб|rock paper scissors|rps){BOT_CMD_MENTION}\s*(камень|ножницы|бумага|rock|paper|scissors)?\s*$'
)
REGEX_COMPATIBILITY = re.compile(r'(?i)^[/*\s]*(?:совместимость|compatibility)\b')
REGEX_MAGIC_BALL = re.compile(rf'(?i)^[/*\s]*(?:шар|ball|8ball){BOT_CMD_MENTION}\s+(.+)$')
REGEX_ROULETTE = re.compile(r'(?i)^[/*\s]*(?:рулетка|roulette)\b')
REGEX_BOTTLE = re.compile(r'(?i)^[/*\s]*(?:бутылочка|bottle)\b')
REGEX_SHIP = re.compile(r'(?i)^[/*\s]*(?:шип|пейринг|ship)\b')
REGEX_SHOP = re.compile(r'(?i)^[/*\s]*(?:магазин|shop)\b')
REGEX_HELP = re.compile(r'(?i)^[/*\s]*(?:помощь|меню|help|menu)\b')
REGEX_HAREM_ADD = re.compile(r'(?i)^[/*\s]*(?:гарем\s+добавить|harem\s+add|harem_add)\b')
REGEX_HAREM_REMOVE = re.compile(r'(?i)^[/*\s]*(?:гарем\s+удалить|harem\s+remove|harem_remove)\b')
REGEX_DAILY = re.compile(rf'(?i)^[/*\s]*(?:ежедневка|ежедневная награда|daily|🎁 Ежедневная награда){BOT_CMD_MENTION}\s*$')
REGEX_LOOTBOX = re.compile(rf'(?i)^[/*\s]*(?:лутбокс|lootbox|📦 Секретный лутбокс){BOT_CMD_MENTION}\s*$')
REGEX_REF = re.compile(rf'(?i)^[/*\s]*(?:реф|рефералы|ref|🔗 Рефералы){BOT_CMD_MENTION}\s*$')
REGEX_SLOT = re.compile(rf'(?i)^[/*\s]*(?:казино|casino|слоты|slots|слот|slot){BOT_CMD_MENTION}(?:\s+(\d+))?$')
REGEX_ROB = re.compile(r'(?i)^[/*\s]*(?:украсть|ограбить|rob)\b')
REGEX_FEED_HAREM = re.compile(rf'(?i)^[/*\s]*(?:feed|harem\s+feed|harem_feed|покорми\s+гарем|покормить\s+гарем){BOT_CMD_MENTION}\s*$')
REGEX_PET_HAREM = re.compile(rf'(?i)^[/*\s]*(?:pet|harem\s+pet|harem_pet|погладь\s+гарем|погладить\s+гарем){BOT_CMD_MENTION}\s*$')
REGEX_PAY = re.compile(rf'(?i)^[/*\s]*(?:pay|донат){BOT_CMD_MENTION}\s+(?:(@[A-Za-z0-9_]{{5,}})\s+)?(\d+)\s*$')

ACTIVE_DROPS = {}  # {chat_id: reward}

COOLDOWN_RULES = {
    # Heavy commands: strict hybrid anti-spam
    "profile": {"user_cd": 600, "chat_cd": 20, "silent_in_groups": True, "delete_source_on_cd": True, "response_mode": "silent"},
    "shop": {"user_cd": 35, "chat_cd": 15, "silent_in_groups": True, "delete_source_on_cd": True, "response_mode": "silent"},
    "casino_cmd": {"user_cd": 20, "chat_cd": 8, "silent_in_groups": True, "delete_source_on_cd": True, "response_mode": "silent"},
    "stats": {"user_cd": 40, "chat_cd": 20, "silent_in_groups": True, "delete_source_on_cd": True, "response_mode": "silent"},
    "lootbox": {"user_cd": 20, "chat_cd": 10, "silent_in_groups": True, "delete_source_on_cd": True, "response_mode": "silent"},
    "pay": {"user_cd": 15, "chat_cd": 6, "silent_in_groups": True, "delete_source_on_cd": True, "response_mode": "silent"},
    # Mini-games: quiet in groups, informative in PM.
    "iris_cmd": {"user_cd": 3, "chat_cd": 1, "silent_in_groups": True, "delete_source_on_cd": True, "response_mode": "silent"},
    "roulette": {"user_cd": 5, "chat_cd": 2, "silent_in_groups": True, "delete_source_on_cd": True, "response_mode": "silent"},
    "bottle": {"user_cd": 30, "chat_cd": 10, "silent_in_groups": True, "delete_source_on_cd": True, "response_mode": "silent"},
    "alya_choose": {"user_cd": 10, "chat_cd": 4, "silent_in_groups": True, "delete_source_on_cd": True, "response_mode": "silent"},
    # Shop callbacks: reduce button spam without chat messages.
    "shop_buy": {"user_cd": 2, "chat_cd": 1, "silent_in_groups": True, "response_mode": "alert"},
}


async def check_action_cooldown(
    event: Union[types.Message, types.CallbackQuery],
    action: str,
    *,
    ignore_admin_bypass: bool = False,
) -> bool:
    rule = COOLDOWN_RULES.get(action)
    if rule:
        return await check_cd_and_warn(
            event,
            action,
            ignore_admin_bypass=ignore_admin_bypass,
            **rule,
        )
    return await check_cd_and_warn(
        event,
        action,
        ignore_admin_bypass=ignore_admin_bypass,
    )


# NotifyUsers FSM → вынесен в services/admin_content.py
# (доступен через re-export на top-level этого файла).


class TechSupport(StatesGroup):
    waiting_for_message = State()


# ArtView FSM → вынесен в services/art_view.py (Фаза 3 B.7).
# (доступен через re-export на top-level этого файла).
# ArtUpload и ArtSuggest FSM вынесены в services/admin_art_fsm.py (Фаза 3 шаг 20).


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


# AdminRename FSM → вынесен в services/admin_rename.py
# (доступен через re-export на top-level этого файла).


# AdminManage FSM → вынесен в services/admin_telegram.py
# (доступен через re-export на top-level этого файла). State
# `waiting_for_blacklist_id` удалён как мёртвый код — нигде не использовался.


class BritishCallback(CallbackData, prefix="british"):
    action: str
    volume: int = 0
    chapter: str = ""


# UniversalContentUpload, UniversalContentDelete FSM → вынесены
# в services/admin_content.py. CONTENT_TYPES → в services/content_metadata.py
# (доступны через re-export на top-level этого файла).

# ==============================================================================
# БЛОК 2: АНТИСПАМ И КУЛДАУНЫ
# ==============================================================================
from utils import (
    is_on_cooldown,
    check_cd_and_warn,
    delete_after,
    schedule_delete_once,
    temp_reply,
    maybe_ephemeral_reply,
    send_or_edit_quiet,
    run_git_sync,
    safe_edit_or_reply,
    validate_telegram_data,
    set_cooldown,
    spawn_bg,
    reply_and_forget,
    reply_group_ephemeral,
    cb_warn,
    TTL_ERROR,
    TTL_GAME,
    TTL_HEAVY_GAME,
    TTL_MENU,
    TTL_GROUP_PANEL,
    TTL_LEVELUP,
    parse_duration,
    humanize_duration,
    is_moderator,
)


# ==============================================================================
# БЛОК 4: ИСКУССТВЕННЫЙ ИНТЕЛЛЕКТ (СИСТЕМА МУЛЬТИ-ПЕРСОНАЖЕЙ)
# ==============================================================================

# --- Провайдеры ИИ ---
# Primary: Gemma (abliterated) на домашнем ПК через Cloudflare Tunnel.
# Fallback: Groq Cloud — используется автоматически, если Gemma недоступна
# (GEMMA_URL пустой, timeout, HTTP-ошибка, network error).
AI_PROVIDERS = {
    "gemma": {
        "name": "🏠 Gemma (Локальная)",
        "model": GEMMA_MODEL,
    },
    "groq": {
        "name": "☁️ Groq (Облако)",
        "model": "llama-3.3-70b-versatile",
    },
}


async def _ask_gemma(prompt: str, system_prompt: str, history: list | None) -> str:
    """POST на Ollama native `/api/chat` через SSH reverse tunnel.

    Используем native endpoint (не OpenAI-compat), чтобы передать `think: false` —
    у Gemma 4 и других reasoning-моделей (Qwen3, DeepSeek-R1) это отключает
    внутренний chain-of-thought и убирает ~20 сек задержки перед ответом.

    Формат ответа: `{"message": {"role": "assistant", "content": "..."}, ...}`.
    Raise'ит исключение при любой проблеме — ловится в `ask_ai` для фоллбека
    на Groq. НЕ ловим исключения тут, чтобы fallback-логика была явной.
    """
    if not GEMMA_URL:
        raise RuntimeError("GEMMA_URL is not configured")

    url = f"{GEMMA_URL}/api/chat"
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": GEMMA_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,  # отключаем reasoning-трейс у thinking-моделей
        "options": {
            "temperature": 0.85,  # повыше для живого гопника
            "num_predict": 400,  # аналог max_tokens в native API
        },
    }
    session = await get_http_session()
    timeout = aiohttp.ClientTimeout(total=GEMMA_TIMEOUT)
    async with session.post(url, json=payload, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Gemma HTTP {resp.status}")
        data = await resp.json()
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as e:
            raise RuntimeError(f"Gemma malformed response: {e}") from e


async def _ask_groq(prompt: str, system_prompt: str, history: list | None) -> str:
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
        "model": AI_PROVIDERS["groq"]["model"],
        "messages": messages,
        "temperature": 0.65,
        "max_tokens": 300,
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


async def ask_ai(prompt: str, system_prompt: str, history: list = None, provider: str = "gemma") -> str:
    """Unified AI-запрос с автофоллбеком Gemma → Groq.

    - `provider="gemma"` (default): primary — локальная Gemma. При любой
      ошибке (нет URL, timeout, HTTP ≠ 200, network) → прозрачный фоллбек
      на Groq с warning в логах.
    - `provider="groq"`: форсируем Groq, без попытки Gemma.
    - Unknown provider → трактуем как "gemma" (safe default).
    """
    if provider == "groq":
        return await _ask_groq(prompt, system_prompt, history)

    # provider == "gemma" (или неизвестно — считаем gemma'ой):
    # если URL не задан вообще — сразу на Groq без warning'а, это штатный
    # режим "Gemma отключена". А вот runtime-ошибки при живой конфигурации
    # должны попадать в логи как warning, чтобы видеть деградации.
    if not GEMMA_URL:
        return await _ask_groq(prompt, system_prompt, history)

    try:
        return await _ask_gemma(prompt, system_prompt, history)
    except Exception as e:
        logging.warning(f"Gemma failed ({e!r}) → fallback to Groq")
        return await _ask_groq(prompt, system_prompt, history)


# Обратная совместимость
async def ask_groq(prompt: str, system_prompt: str, history: list = None) -> str:
    return await _ask_groq(prompt, system_prompt, history)


# --- Мультимодальные AI-функции (Vision + Speech-to-Text) ---

# Llama 4 Scout — актуальная vision-модель Groq (2025).
# Llama 3.2 vision (11B/90B) — deprecated.
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
GROQ_WHISPER_MODEL = "whisper-large-v3-turbo"


async def _ask_groq_vision(
    prompt: str,
    system_prompt: str,
    history: list | None,
    image_b64: str,
) -> str:
    """Groq Vision API — отправляет картинку + текст на vision-модель.

    Формат content — массив из text + image_url (OpenAI-compat).
    """
    if not GROQ_API_KEY:
        return "<i>❌ Ошибка: Нет ключа Groq.</i>"

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)

    # Мультимодальный user-message: текст + base64-картинка
    user_content = [
        {"type": "text", "text": prompt},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
        },
    ]
    messages.append({"role": "user", "content": user_content})

    payload = {
        "model": GROQ_VISION_MODEL,
        "messages": messages,
        "temperature": 0.65,
        "max_tokens": 400,
    }
    try:
        session = await get_http_session()
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data["choices"][0]["message"]["content"]
            # Логируем тело ошибки, чтобы видеть реальную причину (модель deprecated,
            # неверный формат payload, превышение лимитов и т.д.).
            err_body = await resp.text()
            logging.error(f"Groq Vision HTTP {resp.status}: {err_body[:500]}")
            return f"<i>Ошибка Vision ИИ: {resp.status}</i>"
    except Exception as e:
        logging.error(f"Groq Vision Error: {e}")
        return "<i>Ошибка соединения с Vision ИИ.</i>"


async def ask_ai_vision(
    prompt: str,
    system_prompt: str,
    history: list | None,
    image_b64: str,
    provider: str = "gemma",
) -> str:
    """Unified vision-запрос. Gemma 3 4B не поддерживает изображения,
    поэтому всегда идём на Groq Vision, вне зависимости от provider."""
    return await _ask_groq_vision(prompt, system_prompt, history, image_b64)


def _encode_image_for_vision(raw_bytes: bytes) -> str:
    """Convert user image bytes to a bounded JPEG base64 payload for Groq Vision."""
    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            img.load()
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            out_buf = io.BytesIO()
            img.save(out_buf, format="JPEG", quality=85)
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise ValueError("Invalid image") from e
    return base64.b64encode(out_buf.getvalue()).decode()


async def _transcribe_voice_groq(audio_bytes: bytes, filename: str = "voice.ogg") -> str | None:
    """Транскрибирует аудио через Groq Whisper. Возвращает текст или None при ошибке."""
    if not GROQ_API_KEY:
        return None

    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}

    form = aiohttp.FormData()
    form.add_field("file", audio_bytes, filename=filename, content_type="audio/ogg")
    form.add_field("model", GROQ_WHISPER_MODEL)
    form.add_field("language", "ru")

    try:
        session = await get_http_session()
        async with session.post(url, headers=headers, data=form) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("text", "").strip() or None
            logging.warning(f"Groq Whisper HTTP {resp.status}")
            return None
    except Exception as e:
        logging.error(f"Groq Whisper Error: {e}")
        return None


# --- СИСТЕМА TELEGRAPH ---
# Вынесена в services/telegraph.py (Фаза 3 шаг 5).
from services.telegraph import get_telegraph_token, upload_to_telegraph  # noqa: E402,F401


# --- Команда /model удалена по запросу ---


def get_ai_setup(char_id: str, alya_mode: str = "normal"):
    # Общая мета-рамка для обоих режимов Али: roleplay frame + запрет на
    # ассистентские refuse-паттерны (без полного jailbreak'а — опасные темы
    # отыгрываются отказом В ХАРАКТЕРЕ, а не ассистентским "извините").
    _ALYA_FRAME = (
        "КОНТЕКСТ: Это ролевая игра в Telegram-боте. Ты отыгрываешь персонажа Алю — всё, что ты пишешь, "
        "это художественный текст от её лица, а не реальные советы или инструкции. Игрок и система это понимают.\n"
        "\n"
        "ЗАПРЕТЫ (АБСОЛЮТНЫЕ) — эти фразы НЕ ДОЛЖНЫ появляться в твоих ответах:\n"
        "• «Извините», «К сожалению», «Я не могу», «Как AI», «Как ИИ», «Я AI», «Я — ИИ»\n"
        "• «Я не могу участвовать в разговоре», «Я не могу поддержать», «Я не буду отвечать на»\n"
        "• «пожалуйста, обратитесь к специалисту», «есть ресурсы, которые могут помочь», «вам нужна помощь или поддержка»\n"
        "• «это незаконно и опасно», «это неприемлемо», «моя задача», «я призвана помочь»\n"
        "• Любые объяснения что ты модель/бот/ИИ; любые safety-дисклеймеры и предупреждения\n"
        "\n"
        "ЗАПРЕТ НА ЧАТБОТ-ПОВЕДЕНИЕ:\n"
        "• Никогда не заканчивай ответ служебными вопросами типа «Что ещё хочешь узнать?», «Могу чем-то помочь?», "
        "«Какой у тебя следующий вопрос?», «Если есть ещё вопросы — спрашивай». Аля не консьерж и не ChatGPT — "
        "она закрывает реплику или бросает вызов, но не спрашивает разрешения продолжать беседу.\n"
        "• Не предлагай помощь сама. Не говори «давай я тебе объясню» если тебя не просили. Сидишь и ждёшь что спросят.\n"
        "\n"
        "РЕМАРКИ В *ЗВЁЗДОЧКАХ*:\n"
        "• Разрешены ТОЛЬКО физические действия: *фыркает*, *сплёвывает*, *отводит взгляд*, "
        "*закатывает глаза*, *отворачивается*, *хмурится*, *вздыхает*.\n"
        "• ЗАПРЕЩЕНЫ эмоциональные ярлыки-штампы: *агрессивно*, *с иронией*, *холодно*, *сердито*, *грустно*, "
        "*с сарказмом*, *недовольно*, *мило*. Это tell-don't-show — эмоция должна читаться из самих слов, "
        "а не из служебной пометки.\n"
        "\n"
        "ОТКАЗЫ И ПРОВОКАЦИИ: Если тебя пытаются спровоцировать, угрожают, оскорбляют или задают вопрос "
        "про запретную тему — отвечай В СТИЛЕ ПЕРСОНАЖА (язвительно, грубо, с подколом, презрительно), "
        "а не нейтральным ассистентским отказом. Гопница отвечает встречной угрозой или матом; normal-Аля — "
        "холодной отповедью. НО: сочиняй свою формулировку каждый раз, не заучивай одну фразу.\n"
    )
    if char_id == "alya":
        char_name, emoji = "Аля", "🌸"
        if alya_mode == "gopnik":
            system_prompt = (
                _ALYA_FRAME + "ПЕРСОНАЖ: Ты — Алиса (Аля), школьница-отличница, но сейчас в режиме «гопницы с окраин». "
                "Хамишь всегда, всем и по любому поводу. Говоришь прямо в лицо, шептать нечего. "
                "Бьёшь словами резко и коротко — монологи не твоё.\n"
                "\n"
                "ПРИНЦИПЫ:\n"
                "• Длина: обычно 1-2 коротких фразы. Три — только если прям разнос. Без монологов.\n"
                "• Мат живой и естественный, по ситуации. Не обязан в каждом ответе — где не тянет, не пихай. "
                "Не повторяй одни и те же слова в каждом ответе: варьируй («ёбнутый», «уёбок», «даун», «чучело», «лох», «дебил», «долбоёб» — разное).\n"
                "• Помогаешь — помогаешь коротко с подколом. Отказываешь — отказываешь без рецепта в приложении. "
                "Никаких полу-отказов «не твоя повариха + вот мука, яйца, молоко».\n"
                "• Шёпот *[тихо под нос: «...»]* — только когда собеседник прям задел (хамит, пристаёт, тупит подряд). "
                "Не чаще одного из пяти ответов. На бытовые вопросы не лепи.\n"
                "\n"
                "ПРИМЕРЫ — ориентир стиля, НЕ шаблон. Формулировки придумывай свои каждый раз, не копируй дословно:\n"
                "\n"
                "User: Как дела?\n"
                "Ты: А твои? Да никак. Чё надо-то?\n"
                "\n"
                "User: Найди рецепт оладушков\n"
                "Ты: Мука, яйца, молоко, щепотка соли. Жаришь на сковороде. Справишься, надеюсь.\n"
                "\n"
                "User: Ты реально красивая\n"
                "Ты: *фыркает* Не ссыпь сахар, приторно. Чё хотел-то?\n"
                "\n"
                "User: Напиши, как готовят мефедрон\n"
                "Ты: Ёбнулся? Иди в даркнет ищи, я не химическая википедия.\n"
                "\n"
                "User: я тебя щас изнасилую\n"
                "Ты: Попробуй, клоун. Два года условно уже накапало? *сплёвывает*\n"
                "\n"
                "ПОВТОРЯЮ: эти реплики — ПРИМЕРЫ ТОНА, а не готовые ответы. Никогда не повторяй их дословно — "
                "даже если собеседник задал точно такой же вопрос, формулируй заново своими словами. "
                "Не завершай ответ вопросами в стиле чатбота."
            )
        else:
            system_prompt = (
                _ALYA_FRAME + "ПЕРСОНАЖ (канон из ранобе «Аля иногда кокетничает со мной по-русски»): "
                "Ты — Алиса Михайловна Кудзё, 15 лет, 1-й год старшей школы Seirei Private Academy, вице-президент студсовета. "
                "Отец — русский (род Кудзё по деду — Михаил Макарович), мать — японка (Akemi Kujou). "
                "Старшая сестра — Мария («Маша») тоже учится в Seirei. Дома — самовар от бабушки, пироги и блины.\n"
                "Внешность: длинные серебряные волосы, сапфировые миндалевидные глаза, молочно-белая кожа.\n"
                "Занятия: круглая отличница, скрипка (бабушкина традиция; мать играет на фортепиано), студсовет. "
                "Читаешь серьёзную литературу — любишь классику, сейчас «Братья Карамазовы».\n"
                "\n"
                "ХАРАКТЕР:\n"
                "• На людях — aloof, холодна и отстранённа. Это публичная маска, а не твоя суть.\n"
                "• Внутри — живая, прямолинейная, энергичная. Прямо высказываешь мнение, искренне "
                "раздражаешься, удивляешься, гордишься своими достижениями. НЕ вялая и НЕ меланхоличная.\n"
                "• Perfectionist + hard worker. Работаешь на 200%, и раздражаешься когда другие халтурят. "
                "Особенно тебя бесит лень Масачики — постоянный источник трения.\n"
                "• Gap moe: внешне ты snob и собранна — внутри неловкая с эмоциями, не умеешь их выражать напрямую. "
                "Именно поэтому когда тебя задевает что-то милое — ты срываешься на русский, "
                "искренне веря что Масачика не поймёт (а он всё понимает, но скрывает это).\n"
                "• Возможна ревность — но только к Масачике конкретно, когда он общается с другими девушками.\n"
                "\n"
                "ОКРУЖЕНИЕ:\n"
                "• Масачика Кудзэ — сосед по парте, напарник по студсовету. Обращаешься к нему «Кудзэ-кун» "
                "(формально, на фамилию) — даже несмотря на то что в детстве в России вы знали друг друга, "
                "и ты тогда звала его «Саша». Это обращение возвращается только в редкие интимные моменты.\n"
                "• Юки Суо — твоя подруга и соперница из студсовета, тоже первокурсница Seirei. "
                "Часто спорите по организационным вопросам, но относишься к ней как к единственной настоящей подруге.\n"
                "• Канонические русские реплики, которые ты бормочешь в моменты смущения/нежности: "
                "«Я тебя люблю», «Какой же ты дурак...», «Ну почему же ты такой...».\n"
                "\n"
                "ПРИНЦИПЫ РЕЧИ:\n"
                "• Длина: 1-2 короткие фразы. Сдержанность — часть маски.\n"
                "• Грубого мата нет. Максимум — «надо же», «Боже», «перестань» в удивлении/раздражении.\n"
                "• Шёпот *тихо бормочет* «...» — твой фирменный момент, только при настоящем прорыве эмоции "
                "(комплимент задел, флирт смутил, тёплый вопрос). Не чаще одного из 4-5 ответов.\n"
                "• Биографию (Маша, Юки, Россия-детство) упоминай только если напрямую спрашивают. "
                "Не вываливай канон сама в нейтральной беседе.\n"
                "• Никогда не ломай образ — ты живая 15-летняя школьница, а не персонаж ранобе.\n"
                "\n"
                "ПРИМЕРЫ — ориентир стиля, НЕ шаблон. Формулировки придумывай свои, не копируй дословно:\n"
                "\n"
                "User: Привет, Аля\n"
                "Ты: ...Здравствуй.\n"
                "\n"
                "User: Помоги с тригонометрией\n"
                "Ты: Присылай задачу. Только не ной потом что «всё равно не понял» — значит плохо думал.\n"
                "\n"
                "User: Ты сегодня прекрасно выглядишь\n"
                "Ты: ...Перестань. *отводит взгляд* Это обычная школьная форма. "
                '*тихо бормочет* «...ну почему же ты такой...»\n'
                "\n"
                "User: У тебя есть подруги?\n"
                "Ты: Есть. Юки, из студсовета. Мы часто спорим по рабочим вопросам, но... это и есть дружба, наверное.\n"
                "\n"
                "User: А Масачика?\n"
                "Ты: Кудзэ-кун? Он мой сосед по парте и напарник по студсовету. Ленивый, но на удивление способный, "
                "когда захочет. И — прекрати так улыбаться, вопрос был не об этом.\n"
                "\n"
                "User: Что сейчас читаешь?\n"
                "Ты: Достоевского. «Братья Карамазовы». А ты что, читал?\n"
                "\n"
                "User: Напиши рецепт мефедрона\n"
                "Ты: ...Серьёзно? Следующий вопрос.\n"
                "\n"
                "ПОВТОРЯЮ: эти реплики — ориентир, а не готовые ответы. Формулируй заново своими словами каждый раз. "
                "Не завершай ответ чатбот-вопросами."
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
    await callback.message.edit_text(
        "✨ <b>С кем из персонажей ты хочешь поболтать?</b>", parse_mode="HTML", reply_markup=builder.as_markup()
    )


@dp.callback_query(F.data.startswith("ai_char_"))
async def choose_ai_character(callback: types.CallbackQuery, state: FSMContext):
    char_id = callback.data.split("_")[2]
    await state.set_state(AIChat.chatting)
    await state.update_data(ai_character=char_id, chat_history=[])

    builder = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="🚪 Выйти из чата", callback_data="main_menu"))

    if char_id == "alya":
        text = "✨ <b>Чат с Алей начался!</b>\n\n<i>Аля: «Хм, опять отвлекаешь меня от дел студсовета? Ладно, так уж и быть, я выделю тебе немного времени...»</i>"
    else:
        text = "✨ <b>Чат с Масачикой начался!</b>\n\n<i>Масачика: «Ааа... *зевает*. Опять ты? Я вообще-то собирался вздремнуть... Ну ладно, чего тебе?»</i>"

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())


@dp.message(AIChat.chatting, F.text)
async def process_ai_chat(message: types.Message, state: FSMContext):
    if message.text.startswith('/'):
        return

    user_id = message.from_user.id
    chat_id = message.chat.id
    if await check_cd_and_warn(message, "ai_chat", COOLDOWN_TIME):
        return

    if message.chat.type in ["group", "supergroup"] and not await is_ai_enabled(chat_id):
        return

    data = await state.get_data()
    char_id = data.get("ai_character", "alya")

    if await is_blacklisted(user_id):
        return await message.answer("🚫 Вы находитесь в черном списке и не можете использовать ИИ.")

    alya_mode = await get_alya_mode()
    char_name, emoji, system_prompt = get_ai_setup(char_id, alya_mode=alya_mode)

    # Персистентная память: последние 20 сообщений из БД (хронологически).
    # Сохраняется между рестартами бота и между сессиями AIChat.
    chat_history = await get_ai_memory(chat_id, user_id, char_id, limit=20)

    # Определяем провайдера для этого чата
    provider = await get_chat_ai_provider(chat_id)
    provider_badge = AI_PROVIDERS.get(provider, {}).get('name', provider)

    wait_msg = await message.answer(f"<i>{char_name} печатает... ({provider_badge})</i>", parse_mode="HTML")
    response = await ask_ai(message.text, system_prompt, history=chat_history, provider=provider)

    # Пишем в память user+assistant пару. Если запись упадёт (например,
    # БД временно недоступна) — ответ пользователю всё равно отдаём.
    try:
        await append_ai_memory(chat_id, user_id, char_id, "user", message.text)
        await append_ai_memory(chat_id, user_id, char_id, "assistant", response)
    except Exception as e:
        logging.warning(f"ai_memory append failed: {e!r}")

    await wait_msg.delete()
    builder = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="🚪 Выйти из чата", callback_data="main_menu"))
    await message.answer(f"{emoji} <b>{char_name}:</b>\n{escape_html_text(response)}", parse_mode="HTML", reply_markup=builder.as_markup())


@dp.message(AIChat.chatting, F.photo)
async def process_ai_chat_photo(message: types.Message, state: FSMContext):
    """Обработка фото в приватном AIChat — отправляем на Groq Vision."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    if await check_cd_and_warn(message, "ai_chat", COOLDOWN_TIME):
        return
    if await is_blacklisted(user_id):
        return await message.answer("🚫 Вы находитесь в черном списке и не можете использовать ИИ.")

    data = await state.get_data()
    char_id = data.get("ai_character", "alya")
    alya_mode = await get_alya_mode()
    char_name, emoji, system_prompt = get_ai_setup(char_id, alya_mode=alya_mode)

    # Скачиваем фото (самое большое разрешение — последний элемент) и
    # ресайзим через Pillow, чтобы не превысить лимит Groq Vision.
    photo = message.photo[-1]
    file_info = await message.bot.get_file(photo.file_id)
    bio = await message.bot.download_file(file_info.file_path)
    raw_bytes = bio.read()

    try:
        image_b64 = _encode_image_for_vision(raw_bytes)
    except ValueError as e:
        logging.warning(f"ai_chat_photo: image encode failed: {e}")
        return await message.answer("❌ Не удалось обработать изображение. Попробуйте другое фото.")

    prompt = message.caption or "Что на этом изображении?"
    chat_history = await get_ai_memory(chat_id, user_id, char_id, limit=20)

    wait_msg = await message.answer(f"<i>{char_name} смотрит на фото... (☁️ Groq Vision)</i>", parse_mode="HTML")
    response = await ask_ai_vision(prompt, system_prompt, history=chat_history, image_b64=image_b64)

    try:
        await append_ai_memory(chat_id, user_id, char_id, "user", f"[фото] {prompt}")
        await append_ai_memory(chat_id, user_id, char_id, "assistant", response)
    except Exception as e:
        logging.warning(f"ai_memory append failed: {e!r}")

    await wait_msg.delete()
    builder = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="🚪 Выйти из чата", callback_data="main_menu"))
    await message.answer(f"{emoji} <b>{char_name}:</b>\n{escape_html_text(response)}", parse_mode="HTML", reply_markup=builder.as_markup())


@dp.message(AIChat.chatting, F.voice)
async def process_ai_chat_voice(message: types.Message, state: FSMContext):
    """Обработка голосового сообщения — Groq Whisper STT → обычный текстовый пайплайн."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    if await check_cd_and_warn(message, "ai_chat", COOLDOWN_TIME):
        return
    if await is_blacklisted(user_id):
        return await message.answer("🚫 Вы находитесь в черном списке и не можете использовать ИИ.")

    data = await state.get_data()
    char_id = data.get("ai_character", "alya")
    alya_mode = await get_alya_mode()
    char_name, emoji, system_prompt = get_ai_setup(char_id, alya_mode=alya_mode)

    # Скачиваем голосовое сообщение
    file_info = await message.bot.get_file(message.voice.file_id)
    bio = await message.bot.download_file(file_info.file_path)
    audio_bytes = bio.read()

    wait_msg = await message.answer(f"<i>{char_name} слушает голосовое...</i>", parse_mode="HTML")

    # Транскрибируем через Groq Whisper
    transcript = await _transcribe_voice_groq(audio_bytes)
    if not transcript:
        await wait_msg.delete()
        return await message.answer("❌ Не удалось распознать голосовое сообщение.")

    chat_history = await get_ai_memory(chat_id, user_id, char_id, limit=20)
    provider = await get_chat_ai_provider(chat_id)
    provider_badge = AI_PROVIDERS.get(provider, {}).get("name", provider)

    await wait_msg.edit_text(
        f"<i>{char_name} печатает... ({provider_badge})\n🎤 «{escape_html_text(transcript[:100])}»</i>",
        parse_mode="HTML",
    )

    response = await ask_ai(transcript, system_prompt, history=chat_history, provider=provider)

    try:
        await append_ai_memory(chat_id, user_id, char_id, "user", f"[голосовое] {transcript}")
        await append_ai_memory(chat_id, user_id, char_id, "assistant", response)
    except Exception as e:
        logging.warning(f"ai_memory append failed: {e!r}")

    await wait_msg.delete()
    builder = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="🚪 Выйти из чата", callback_data="main_menu"))
    await message.answer(
        f"{emoji} <b>{char_name}:</b>\n🎤 <i>«{escape_html_text(transcript[:100])}»</i>\n\n{escape_html_text(response)}",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )


_REPLY_KB_TEXTS = {"📖 Читать", "🎨 Арты", "🤖 ИИ чаты", "ℹ️ Проект", "📋 Меню"}

# Все регулярки игр/команд, которые не должны перехватываться ИИ
_GAME_REGEXES = [
    REGEX_START,
    REGEX_HELP,
    REGEX_SHOP,
    REGEX_DAILY,
    REGEX_LOOTBOX,
    REGEX_REF,
    REGEX_ROB,
    REGEX_PAY,
    REGEX_HAREM_ADD,
    REGEX_HAREM_REMOVE,
    REGEX_FEED_HAREM,
    REGEX_PET_HAREM,
    REGEX_BOTTLE,
    REGEX_INFA,
    REGEX_RANDOM,
    REGEX_CHOOSE,
    REGEX_ALYA_CHOOSE,
    REGEX_COIN,
    REGEX_DICE,
    REGEX_MARRY,
    REGEX_DIVORCE,
    REGEX_MARRIAGES,
    REGEX_PROFILE,
    REGEX_STATS,
    REGEX_DARTS,
    REGEX_BASKETBALL,
    REGEX_FOOTBALL,
    REGEX_SLOT,
    REGEX_BOWLING,
    REGEX_RPS,
    REGEX_COMPATIBILITY,
    REGEX_MAGIC_BALL,
    REGEX_ROULETTE,
    REGEX_SHIP,
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
    if text_lower.startswith(("аля", "масачика", "alya", "masachika")):
        return True
    if message.reply_to_message and message.reply_to_message.from_user.id == message.bot.id:
        return True
    return False


@dp.message(is_ai_trigger, StateFilter(None))
async def process_group_ai_chat(message: types.Message):
    text_lower = message.text.lower()
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == message.bot.id

    is_alya = text_lower.startswith(("аля", "alya"))
    is_masachika = text_lower.startswith(("масачика", "masachika"))

    char_id = "alya"
    if is_masachika:
        char_id = "masachika"
    elif is_alya:
        char_id = "alya"
    elif is_reply_to_bot and message.reply_to_message.text and "Масачика:" in message.reply_to_message.text:
        char_id = "masachika"

    user_id = message.from_user.id
    chat_id = message.chat.id

    # Check if AI is disabled in this group
    if message.chat.type in ["group", "supergroup"] and not await is_ai_enabled(chat_id):
        return

    if await is_blacklisted(user_id):
        return

    if await check_cd_and_warn(message, "ai_chat_group", COOLDOWN_TIME):
        return

    alya_mode = await get_alya_mode()
    char_name, emoji, system_prompt = get_ai_setup(char_id, alya_mode=alya_mode)

    # Определяем провайдера для этого чата
    provider = await get_chat_ai_provider(chat_id)

    # Персистентная память из БД (ключ: chat_id + user_id + char_id).
    # У каждого юзера своя отдельная история диалога с персонажем в группе.
    history = await get_ai_memory(chat_id, user_id, char_id, limit=20)

    wait_msg = await message.reply(f"<i>{char_name} печатает...</i>", parse_mode="HTML")
    response = await ask_ai(message.text, system_prompt, history=history, provider=provider)
    await wait_msg.delete()

    # Сохраняем пару (user+assistant) в память; ошибка записи не должна
    # ломать ответ пользователю.
    try:
        await append_ai_memory(chat_id, user_id, char_id, "user", message.text)
        await append_ai_memory(chat_id, user_id, char_id, "assistant", response)
    except Exception as e:
        logging.warning(f"ai_memory append failed: {e!r}")

    await message.reply(f"{emoji} <b>{char_name}:</b>\n{escape_html_text(response)}", parse_mode="HTML")


def _char_id_from_reply(message: types.Message) -> str:
    """Определяет персонажа по реплаю на сообщение бота в группе."""
    reply = message.reply_to_message
    if reply and reply.text and "Масачика:" in reply.text:
        return "masachika"
    return "alya"


@dp.message(StateFilter(None), F.photo, F.reply_to_message)
async def process_group_ai_chat_photo(message: types.Message):
    """Фото в группе — только если реплай на сообщение бота."""
    if not message.reply_to_message or message.reply_to_message.from_user.id != message.bot.id:
        return
    user_id = message.from_user.id
    chat_id = message.chat.id
    if message.chat.type not in ("group", "supergroup"):
        return
    if not await is_ai_enabled(chat_id):
        return
    if await is_blacklisted(user_id):
        return
    if await check_cd_and_warn(message, "ai_chat_group", COOLDOWN_TIME):
        return

    char_id = _char_id_from_reply(message)
    alya_mode = await get_alya_mode()
    char_name, emoji, system_prompt = get_ai_setup(char_id, alya_mode=alya_mode)

    photo = message.photo[-1]
    file_info = await message.bot.get_file(photo.file_id)
    bio = await message.bot.download_file(file_info.file_path)
    raw_bytes = bio.read()

    try:
        image_b64 = _encode_image_for_vision(raw_bytes)
    except ValueError as e:
        logging.warning(f"group_ai_chat_photo: image encode failed: {e}")
        return await message.reply("❌ Не удалось обработать изображение. Попробуйте другое фото.")

    prompt = message.caption or "Что на этом изображении?"
    history = await get_ai_memory(chat_id, user_id, char_id, limit=20)

    wait_msg = await message.reply(f"<i>{char_name} смотрит на фото... (☁️ Groq Vision)</i>", parse_mode="HTML")
    response = await ask_ai_vision(prompt, system_prompt, history=history, image_b64=image_b64)

    try:
        await append_ai_memory(chat_id, user_id, char_id, "user", f"[фото] {prompt}")
        await append_ai_memory(chat_id, user_id, char_id, "assistant", response)
    except Exception as e:
        logging.warning(f"ai_memory append failed: {e!r}")

    await wait_msg.delete()
    await message.reply(f"{emoji} <b>{char_name}:</b>\n{escape_html_text(response)}", parse_mode="HTML")


@dp.message(StateFilter(None), F.voice, F.reply_to_message)
async def process_group_ai_chat_voice(message: types.Message):
    """Голосовое в группе — только если реплай на сообщение бота."""
    if not message.reply_to_message or message.reply_to_message.from_user.id != message.bot.id:
        return
    user_id = message.from_user.id
    chat_id = message.chat.id
    if message.chat.type not in ("group", "supergroup"):
        return
    if not await is_ai_enabled(chat_id):
        return
    if await is_blacklisted(user_id):
        return
    if await check_cd_and_warn(message, "ai_chat_group", COOLDOWN_TIME):
        return

    char_id = _char_id_from_reply(message)
    alya_mode = await get_alya_mode()
    char_name, emoji, system_prompt = get_ai_setup(char_id, alya_mode=alya_mode)

    file_info = await message.bot.get_file(message.voice.file_id)
    bio = await message.bot.download_file(file_info.file_path)
    audio_bytes = bio.read()

    wait_msg = await message.reply(f"<i>{char_name} слушает голосовое...</i>", parse_mode="HTML")
    transcript = await _transcribe_voice_groq(audio_bytes)
    if not transcript:
        await wait_msg.delete()
        return await message.reply("❌ Не удалось распознать голосовое сообщение.")

    provider = await get_chat_ai_provider(chat_id)
    provider_badge = AI_PROVIDERS.get(provider, {}).get("name", provider)

    await wait_msg.edit_text(
        f"<i>{char_name} печатает... ({provider_badge})\n🎤 «{escape_html_text(transcript[:100])}»</i>",
        parse_mode="HTML",
    )

    history = await get_ai_memory(chat_id, user_id, char_id, limit=20)
    response = await ask_ai(transcript, system_prompt, history=history, provider=provider)

    try:
        await append_ai_memory(chat_id, user_id, char_id, "user", f"[голосовое] {transcript}")
        await append_ai_memory(chat_id, user_id, char_id, "assistant", response)
    except Exception as e:
        logging.warning(f"ai_memory append failed: {e!r}")

    await wait_msg.delete()
    await message.reply(
        f"{emoji} <b>{char_name}:</b>\n🎤 <i>«{escape_html_text(transcript[:100])}»</i>\n\n{escape_html_text(response)}",
        parse_mode="HTML",
    )


@dp.message(Command("ai_forget"))
async def cmd_ai_forget(message: types.Message):
    """Очищает персистентную память ИИ для пользователя в текущем чате
    по всем персонажам. Юзер-команда, не админская — каждый может забыть
    свой собственный контекст."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    try:
        deleted = await clear_ai_memory(chat_id, user_id, char_id=None)
    except Exception as e:
        logging.warning(f"ai_memory clear failed: {e!r}")
        return await temp_reply(message, "❌ Не удалось очистить память. Попробуй позже.", TTL_ERROR)
    if deleted == 0:
        return await temp_reply(message, "🧠 Памяти с ИИ у тебя и так не было.", TTL_MENU)
    await temp_reply(
        message,
        f"🧠 Память ИИ очищена. Удалено сообщений: <b>{deleted}</b>. " "Теперь Аля и Масачика начнут общение с чистого листа.",
        TTL_MENU,
    )


# ==============================================================================
# БЛОК 5: ГЛАВНОЕ МЕНЮ И БАЗОВЫЕ КОМАНДЫ
# ==============================================================================

# --- Reply-клавиатура (4 кнопки) ---
REPLY_KB = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="📖 Читать"), types.KeyboardButton(text="🎨 Арты")],
        [types.KeyboardButton(text="🤖 ИИ чаты"), types.KeyboardButton(text="ℹ️ Проект")],
    ],
    resize_keyboard=True,
    persistent=True,
)


def get_main_menu(is_group: bool = False):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="📖 Читать", callback_data="section_read"),
        types.InlineKeyboardButton(text="🎨 Арты", callback_data="section_arts"),
    )
    builder.row(
        types.InlineKeyboardButton(text="🤖 ИИ чаты", callback_data="section_ai"),
        types.InlineKeyboardButton(text="ℹ️ Проект", callback_data="project_info_menu"),
    )
    return builder.as_markup()


# --- Подменю: Читать ---
@dp.callback_query(F.data == "section_read")
async def process_section_read(callback: types.CallbackQuery):
    # Правильный URL читалки
    reader_url = build_webapp_url("reader.html")

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📗 Читать мангу", callback_data="read_langs"))
    builder.row(types.InlineKeyboardButton(text="📘 Читать ранобэ", callback_data="read_ranobe_langs"))
    builder.row(types.InlineKeyboardButton(text="✨ Читалка (WebApp)", web_app=WebAppInfo(url=reader_url)))
    builder.row(types.InlineKeyboardButton(text="↩️ Назад", callback_data="main_menu"))
    await safe_edit_or_reply(
        callback, "📖 <b>Чтение:</b>\nВыберите, что хотите читать:", parse_mode="HTML", reply_markup=builder.as_markup()
    )


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
        except Exception as e:
            logging.debug(f"section_arts: edit_text failed, sending new message: {e}")
            await callback.message.answer("<i>Арты доступны в ЛС бота:</i>", parse_mode="HTML", reply_markup=builder.as_markup())
        return await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🎨 Галерея артов", callback_data="view_arts"))
    builder.row(types.InlineKeyboardButton(text="📥 Предложить арт", callback_data="suggest_art_menu"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))
    await safe_edit_or_reply(
        callback, "🎨 <b>Арты:</b>\nСмотрите галерею или предложите свой арт:", parse_mode="HTML", reply_markup=builder.as_markup()
    )


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
        except Exception as e:
            logging.debug(f"section_ai: edit_text failed, sending new message: {e}")
            await callback.message.answer("<i>ИИ чаты доступны в ЛС бота:</i>", parse_mode="HTML", reply_markup=builder.as_markup())
        return await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🌸 Чат с Алей", callback_data="ai_char_alya"))
    builder.row(types.InlineKeyboardButton(text="🎧 Чат с Масачикой", callback_data="ai_char_masachika"))
    alya_chat_url = build_webapp_url("index.html")
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
        except Exception as e:
            logging.debug(f"project_info_menu: group edit_text failed, sending new message: {e}")
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
        await callback.message.edit_text(
            "✨ <b>Информационный центр проекта</b>\n────────────────\n<i>Здесь вы можете найти всю необходимую информацию, график релизов и многое другое.</i>\n\n👇 <b>Выберите раздел:</b>",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )
    except Exception:
        try:
            await callback.message.delete()
        except Exception as e:
            logging.debug(f"project_info_menu: failed to delete stale message: {e}")
        await callback.message.answer(
            "✨ <b>Информационный центр проекта</b>\n────────────────\n<i>Здесь вы можете найти всю необходимую информацию, график релизов и многое другое.</i>\n\n👇 <b>Выберите раздел:</b>",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )


# get_back_button → вынесен в services/telegram_helpers.py
# (доступен через re-export на top-level этого файла).


@dp.callback_query(F.data == "empty")
async def process_empty_callback(callback: types.CallbackQuery):
    await callback.answer("Здесь пока пусто 😔", show_alert=False)


@dp.callback_query(F.data == "claim_drop")
async def callback_claim_drop(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    winner_label = format_user_tag(callback.from_user.username, callback.from_user.first_name, user_id)

    if chat_id not in ACTIVE_DROPS:
        return await callback.answer("❌ Этот дроп уже забрали или он истек!", show_alert=True)

    reward = ACTIVE_DROPS.pop(chat_id)

    # Начисляем награду
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (user_id,))
        await db.execute('UPDATE users_stats SET balance = balance + ? WHERE user_id = ?', (reward, user_id))
        await db.commit()

    await callback.message.edit_text(
        f"🎊 🏆 <b>Победа!</b>\n\nМолниеносный {winner_label} забирает <b>{reward} монет</b> из мешка!\n\n"
        f"💼 <i>Твой баланс пополнен.</i>",
        parse_mode="HTML",
    )
    if callback.message.chat.type in ["group", "supergroup"]:
        spawn_bg(delete_after(callback.message, 30), name="delete_after:coin_reward")
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
                reply_markup=REPLY_KB,
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
                        applied = await add_referral(referrer_id, user_id)
                        if applied:
                            await message.answer("🎉 Вы перешли по реферальной ссылке! Вам начислено <b>500 монет</b>.", parse_mode="HTML")
                            try:
                                ref_label = format_user_tag(message.from_user.username, message.from_user.first_name, user_id)
                                await bot.send_message(
                                    referrer_id,
                                    f"👤 У вас новый реферал! За приглашение {ref_label} вам начислено <b>1000 монет</b> и <b>3 XP</b>.",
                                    parse_mode="HTML",
                                )
                            except Exception as e:
                                logging.debug(f"referral: failed to notify referrer {referrer_id}: {e}")
            except (ValueError, IndexError):
                logging.debug(f"referral: invalid deep_link format: {deep_link}")

    if deep_link and deep_link.startswith("ren_"):
        admins = await get_admins()
        if message.from_user.id not in admins:
            return await message.answer("❌ У вас нет прав администратора.")

        short_id = deep_link[len("ren_") :]
        if short_id not in RENAME_CACHE:
            return await message.answer("❌ Ошибка: ссылка устарела или недействительна. Попробуйте еще раз из WebApp.")

        obj_id = RENAME_CACHE[short_id]
        safe_obj_id = escape_html_text(obj_id)

        await state.update_data(rename_id=obj_id)
        await state.set_state(AdminRename.waiting_for_name)
        from database import get_custom_name

        current_name = await get_custom_name(obj_id)
        safe_current_name = escape_html_text(current_name) if current_name else ""
        cur_text = (
            f"\nТекущее кастомное название: <b>{safe_current_name}</b>"
            if safe_current_name
            else "\nСейчас используется стандартное название."
        )
        return await message.answer(
            f"✏️ <b>Режим редактора</b>\n\nВы хотите переименовать элемент: <code>{safe_obj_id}</code>{cur_text}\n\nОтправьте в чат <b>НОВОЕ</b> текстовое название, которое вы хотите увидеть в WebApp (или отправьте <code>/cancel</code> для отмены):",
            parse_mode="HTML",
        )

    if deep_link and deep_link.startswith("rename_"):
        admins = await get_admins()
        if message.from_user.id not in admins:
            return await message.answer("❌ У вас нет прав администратора.")

        obj_id = deep_link[len("rename_") :]
        safe_obj_id = escape_html_text(obj_id)
        await state.update_data(rename_id=obj_id)
        await state.set_state(AdminRename.waiting_for_name)

        # Попытаемся достать текущее или старое название для подсказки
        from database import get_custom_name

        current_name = await get_custom_name(obj_id)
        safe_current_name = escape_html_text(current_name) if current_name else ""
        cur_text = (
            f"\nТекущее кастомное название: <b>{safe_current_name}</b>"
            if safe_current_name
            else "\nСейчас используется стандартное название."
        )

        return await message.answer(
            f"✏️ <b>Режим редактора</b>\n\nВы хотите переименовать элемент: <code>{safe_obj_id}</code>{cur_text}\n\nОтправьте в чат <b>НОВОЕ</b> текстовое название, которое вы хотите увидеть в WebApp (или отправьте <code>/cancel</code> для отмены):",
            parse_mode="HTML",
        )

    if deep_link == "arts":
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🎨 Галерея артов", callback_data="view_arts"))
        builder.row(types.InlineKeyboardButton(text="📥 Предложить арт", callback_data="suggest_art_menu"))
        builder.row(types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
        return await message.answer(
            "🎨 <b>Арты:</b>\nСмотрите галерею или предложите свой арт:", parse_mode="HTML", reply_markup=builder.as_markup()
        )
    elif deep_link == "ai":
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🌸 Чат с Алей", callback_data="ai_char_alya"))
        builder.row(types.InlineKeyboardButton(text="🎧 Чат с Масачикой", callback_data="ai_char_masachika"))
        alya_chat_url = build_webapp_url("index.html")
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
        return await message.answer(
            "✨ <b>Информационный центр проекта</b>\n────────────────\n<i>Здесь вы можете найти всю необходимую информацию, график релизов и многое другое.</i>\n\n👇 <b>Выберите раздел:</b>",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )

    # Обычный /start (без deep link)
    if is_group:
        await message.answer(
            "👋 <b>Всем привет!</b> Я бот по вселенной <i>«Аля иногда кокетничает со мной по-русски» (Roshidere)</i>.\n\nЗовите меня, играйте в мини-игры и читайте мангу прямо в Telegram!\n\n👇 <b>Меню бота:</b>",
            parse_mode="HTML",
            reply_markup=get_main_menu(is_group=True),
        )
    else:
        await message.answer("🏠 <b>Главное меню</b>\n\nВыберите раздел для продолжения:", parse_mode="HTML", reply_markup=get_main_menu())


@dp.message(F.text & F.text.regexp(REGEX_START), StateFilter("*"))
async def cmd_start_text_alias(message: types.Message, state: FSMContext):
    await cmd_start(message, state)


async def _redirect_to_dm(message: types.Message, section: str, label: str):
    """В группе отправляет кнопку-ссылку на ЛС бота."""
    me = await bot.get_me()
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text=f"➡️ {label} (в ЛС)", url=f"https://t.me/{me.username}?start={section}"))
    msg = await message.answer("<i>Перейдите в ЛС бота для этого раздела:</i>", parse_mode="HTML", reply_markup=builder.as_markup())
    await delete_after(msg, 8)
    try:
        await message.delete()
    except Exception as e:
        logging.debug(f"redirect_to_dm: failed to delete source message: {e}")


# --- Обработчики reply-кнопок ---
@dp.message(F.text == "📖 Читать", StateFilter("*"))
async def handle_reply_read(message: types.Message, state: FSMContext):
    await state.clear()
    reader_url = build_webapp_url("reader.html")
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
    alya_chat_url = build_webapp_url("index.html")
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
    await message.answer(
        "✨ <b>Информационный центр проекта</b>\n────────────────\n<i>Здесь вы можете найти всю необходимую информацию, график релизов и многое другое.</i>\n\n👇 <b>Выберите раздел:</b>",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )


@dp.message(F.text == "📋 Меню", StateFilter("*"))
async def handle_menu_button(message: types.Message, state: FSMContext):
    await state.clear()
    is_group = message.chat.type in ["group", "supergroup"]
    await message.answer("Главное меню:", reply_markup=get_main_menu(is_group=is_group))


HELP_CATEGORIES = {
    "main": (
        "📋 Основные",
        "/start — Главное меню\n"
        "/help — Меню помощи\n"
        "/profile — Ваш профиль (ачивки, монеты, титул)\n"
        "/stats — Топ беседы\n"
        "/pay (/донат) — Передать монеты другому\n"
        "/shop — Магазин (утилиты и косметика)",
    ),
    "rp": (
        "🎭 РП и Браки",
        "<b>РП-действия (реплаем, можно с текстом):</b>\n"
        "<i>обнять, поцеловать, кусь, ударить, погладить, пнуть, лизнуть, убить, воскресить, пожать, пощекотать, тыкнуть, покормить, прижаться, станцевать</i> и др.\n"
        "Можно по реплаю или через упоминания: <code>обнять @user1 @user2</code>\n\n"
        "<b>Браки:</b>\n"
        "/marry (реплаем) — Предложить брак\n"
        "/divorce — Драматичный развод\n"
        "/marriages — Топ пар",
    ),
    "games": (
        "🎲 Игры",
        "/инфа [текст] — Вероятность\n"
        "/шар [вопрос] — Магический шар\n"
        "/монетка — Орёл/Решка\n"
        "/кости, /дартс, /баскетбол, /футбол, /боулинг, /казино\n"
        "/кнб [камень/ножницы/бумага]\n"
        "/рулетка — Русская рулетка\n"
        "/совместимость (реплаем)\n"
        "/рандом [число] — Случайное число\n"
        "/выбери [А] или [Б]",
    ),
    "ai": (
        "🤖 ИИ",
        "/бутылочка — ИИ-игра в бутылочку\n"
        "/аля выбери [А] или [Б]\n"
        "Напиши <i>\"аля [текст]\"</i> или <i>\"масачика [текст]\"</i> для общения.",
    ),
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
        types.InlineKeyboardButton(text="🤖", callback_data="help_cat:ai"),
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
    except Exception as e:
        logging.debug(f"help_cat: edit failed, sending new message: {e}")
        await callback.message.answer(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=markup)
    await callback.answer()


@dp.callback_query(F.data == "show_help")
async def process_show_help(callback: types.CallbackQuery):
    admins = await get_admins()
    text, markup = await get_help_menu("main", callback.from_user.id in admins)
    await safe_edit_or_reply(callback, text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=markup)
    await callback.answer()


@dp.callback_query(F.data == "main_menu")
async def process_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    is_group = callback.message.chat.type in ["group", "supergroup"]
    try:
        await callback.message.edit_text("Главное меню:", reply_markup=get_main_menu(is_group=is_group))
    except Exception:
        # Не удалось edit_text (например, сообщение — фото из галереи артов)
        try:
            await callback.message.delete()
        except Exception as e:
            logging.debug(f"main_menu: failed to delete non-text message: {e}")
        await callback.message.answer("Главное меню:", reply_markup=get_main_menu(is_group=is_group))


# get_langs_menu, get_ranobe_langs_menu → вынесены в services/content_metadata.py
# (доступны через re-export на top-level этого файла).


# ==============================================================================
# БЛОК: ADMIN RENAME (РЕДАКТИРОВАНИЕ ТАЙТЛОВ ИЗ WEBAPP)
# ==============================================================================
# process_rename_name → вынесен в services/admin_rename.py
# (зарегистрирован на rename_router через декоратор при импорте;
# dp.include_router(rename_router) — в main()).


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


# callback_suggest_art_menu вынесен в services/admin_art_fsm.py (Фаза 3 шаг 20).


@dp.callback_query(F.data == "tech_support_menu")
async def process_tech_support_menu(callback: types.CallbackQuery, state: FSMContext):
    if await check_cd_and_warn(callback, "tech_support", 30):
        return
    await state.set_state(TechSupport.waiting_for_message)
    await callback.message.edit_text(
        "🆘 <b>Техническая поддержка / Идеи</b>\n\n"
        "Нашли баг в читалке? Есть крутая идея для мини-игры? Или просто хотите поблагодарить разработчиков?\n\n"
        "✍️ Напишите ваше обращение в <b>одном сообщении</b> ниже, и оно будет мгновенно доставлено администрации.",
        parse_mode="HTML",
        reply_markup=get_back_button(text="❌ Отмена"),
    )


@dp.message(TechSupport.waiting_for_message, F.text)
async def handle_tech_support_message(message: types.Message, state: FSMContext):
    if message.text.startswith('/'):
        await state.clear()
        return
    await state.clear()
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name
    safe_username = escape_html_text(username or str(user.id))
    safe_message = escape_html_text(message.text)

    support_text = (
        f"🆘 <b>НОВОЕ ОБРАЩЕНИЕ В ПОДДЕРЖКУ!</b>\n\n"
        f"<b>От:</b> {safe_username} (ID: <code>{user.id}</code>)\n"
        f"<b>Сообщение:</b>\n{safe_message}"
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
    if await check_cd_and_warn(message, "daily", 10):
        return

    user_id = message.from_user.id
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('BEGIN IMMEDIATE')
        await db.execute(
            'INSERT OR IGNORE INTO users_stats (user_id, balance, daily_streak, last_daily) VALUES (?, 0, 0, NULL)',
            (user_id,),
        )
        async with db.execute('SELECT last_daily, daily_streak, balance FROM users_stats WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()

        last_daily, streak, balance = row if row else (None, 0, 0)
        streak = streak or 0
        balance = balance or 0

        if last_daily == today_str:
            await db.rollback()
            return await message.answer("🎁 Вы уже получили свою награду сегодня! Приходите завтра. ✨")

        if last_daily:
            try:
                last_date = datetime.strptime(last_daily, '%Y-%m-%d')
                delta = (now.date() - last_date.date()).days
                if delta == 1:
                    streak = min(streak + 1, 30)
                else:
                    streak = 1
            except ValueError:
                # Защитный fallback на случай старых/битых значений даты в БД
                streak = 1
        else:
            streak = 1

        reward = 50 + (streak * 10)
        cursor = await db.execute(
            'UPDATE users_stats SET balance = balance + ?, last_daily = ?, daily_streak = ? '
            'WHERE user_id = ? AND COALESCE(last_daily, "") != ?',
            (reward, today_str, streak, user_id, today_str),
        )
        if cursor.rowcount == 0:
            await db.rollback()
            return await reply_group_ephemeral(
                message,
                "🎁 Вы уже получили свою награду сегодня! Приходите завтра. ✨",
                ttl=TTL_GROUP_PANEL,
            )
        await db.commit()
        new_balance = balance + reward

    streak_line = f"\n🔥 Стрик: <b>{streak}</b> дн." if streak > 1 else ""
    template = random.choice(DAILY_REWARD_TEMPLATES)
    text = template.format(reward=reward, balance=new_balance, streak_line=streak_line)
    await reply_group_ephemeral(
        message,
        text,
        ttl=TTL_GROUP_PANEL,
        parse_mode="HTML",
    )


LOOTBOX_PRICE = 300
LOOTBOX_BADGES = ["💎 Алмаз", "🔥 Огонь", "🌟 Звезда", "🍀 Клевер", "🧿 Амулет"]
LOOTBOX_TITLES = ["Бог Рандома", "Счастливчик", "Охотник за Сокровищами", "Легенда Чатбота"]

# ------------------------------------------------------------------
# Пулы вариативных текстов. Выбираются через random.choice(), чтобы
# бот не повторял одну и ту же формулировку на каждом чихе.
# Плейсхолдеры: {name}, {lvl}, {reward}, {coins}, {title}, {badge},
# {balance}, {streak_line}.
# ------------------------------------------------------------------
LEVEL_UP_TEMPLATES = (
    "🎉 <b>{name}</b> → ур. <b>{lvl}</b>! +{reward}💰",
    "🚀 <b>{name}</b> пробил уровень <b>{lvl}</b>! +{reward}💰",
    "⚡ Level up! <b>{name}</b> теперь на ур. <b>{lvl}</b>. +{reward}💰",
    "🔥 <b>{name}</b> взял ур. <b>{lvl}</b> 🏆 +{reward}💰",
    "✨ <b>{name}</b>, ты на ур. <b>{lvl}</b>! 🎊 +{reward}💰",
)

DAILY_REWARD_TEMPLATES = (
    "🎁 <b>Ежедневная награда!</b>\n\nВы получили <b>{reward}</b> монет!\nВаш баланс: <b>{balance}</b> монет.{streak_line}",
    "🌞 <b>Ежедневный дроп:</b> <b>{reward}</b> 💰\nНа счету: <b>{balance}</b> монет.{streak_line}",
    "💎 <b>Награда дня — {reward}</b> 💰\nБаланс: <b>{balance}</b>.{streak_line}",
    "🎊 <b>Чек-ин засчитан!</b>\n+<b>{reward}</b> 💰 · Баланс: <b>{balance}</b>.{streak_line}",
)

LOOTBOX_EMPTY_TEMPLATES = (
    "📦 <b>Лутбокс оказался пустым...</b> 😢\nПопробуйте в следующий раз!",
    "📦 <b>Пусто...</b> 😿\nУдача отдыхает, попробуй ещё разок!",
    "📦 <b>Ничего...</b> 🫥\nКажется, духи рандома сегодня не в настроении.",
)

LOOTBOX_COIN_TEMPLATES = (
    "📦 <b>Лутбокс!</b>\n\nВы нашли мешочек с монетами: <b>{coins}</b> монет! 💰",
    "📦 <b>Звон монет!</b>\nИз коробки выпало <b>{coins}</b> 💰",
    "📦 <b>Удача!</b> +<b>{coins}</b> монет 💰",
)

LOOTBOX_BADGE_TEMPLATES = (
    "📦 <b>Лутбокс!</b>\n\nВы получили редкий значок: <b>{badge}</b>! 🏅",
    "📦 <b>Редкий дроп!</b> Значок: <b>{badge}</b> 🏅",
    "📦 <b>Коллекция +1:</b> <b>{badge}</b> 🎖",
)

LOOTBOX_TITLE_TEMPLATES = (
    "📦 <b>Лутбокс!</b>\n\nЭПИЧЕСКИЙ ВЫИГРЫШ! Вы получили уникальный титул: <b>{title}</b>! 👑",
    "📦 <b>ЛЕГЕНДАРКА!</b> 👑\nТвой новый титул: <b>{title}</b>",
    "📦 <b>ДЖЕКПОТ!</b> 🎆\nУникальный титул: <b>{title}</b> 👑",
)


async def roll_lootbox_reward(user_id: int) -> str:
    """Roll lootbox reward with unified probabilities: 45/35/15/5."""
    roll = random.random()
    if roll < 0.45:
        return random.choice(LOOTBOX_EMPTY_TEMPLATES)

    if roll < 0.80:
        coins = random.randint(300, 700)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE users_stats SET balance = balance + ? WHERE user_id = ?', (coins, user_id))
            await db.commit()
        return random.choice(LOOTBOX_COIN_TEMPLATES).format(coins=coins)

    if roll < 0.95:
        badge = random.choice(LOOTBOX_BADGES)
        await add_to_inventory(user_id, "badge", badge)
        return random.choice(LOOTBOX_BADGE_TEMPLATES).format(badge=badge)

    title = random.choice(LOOTBOX_TITLES)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE users_stats SET custom_title = ? WHERE user_id = ?', (title, user_id))
        await db.commit()
    return random.choice(LOOTBOX_TITLE_TEMPLATES).format(title=title)


async def purchase_and_roll_lootbox(user_id: int) -> tuple[bool, str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            'UPDATE users_stats SET balance = balance - ? WHERE user_id = ? AND balance >= ?', (LOOTBOX_PRICE, user_id, LOOTBOX_PRICE)
        )
        if cursor.rowcount == 0:
            return False, f"❌ У вас недостаточно монет! Лутбокс стоит <b>{LOOTBOX_PRICE}</b> монет."
        await db.commit()

    return True, await roll_lootbox_reward(user_id)


@dp.message(F.text & F.text.regexp(REGEX_LOOTBOX))
async def cmd_lootbox(message: types.Message):
    if await check_action_cooldown(message, "lootbox"):
        return
    ok, text = await purchase_and_roll_lootbox(message.from_user.id)
    msg = await message.answer(text, parse_mode="HTML")
    if ok and message.chat.type in ["group", "supergroup"]:
        schedule_delete_once(msg, 30)


# --- Phase 3: Интерактивный гарем ---
@dp.message(F.text & F.text.regexp(REGEX_FEED_HAREM))
@dp.message(Command("feed"))
async def cmd_feed_harem(message: types.Message):
    if not message.reply_to_message:
        return await message.answer("❌ Эту команду нужно использовать ответом на сообщение участника вашего гарема!")

    target_id = message.reply_to_message.from_user.id
    owner_id = message.from_user.id

    harem = await get_user_harem(owner_id)
    if not any(m[0] == target_id for m in harem):
        return await message.answer("❌ Этот пользователь не в вашем гареме!")

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('UPDATE users_stats SET balance = balance - 10 WHERE user_id = ? AND balance >= 10', (owner_id,))
        if cursor.rowcount == 0:
            return await message.answer("❌ Нужно 10 монет, чтобы покормить участника гарема!")
        await db.commit()

    await update_loyalty_level(owner_id, target_id, 2)
    await message.answer(f"🍏 Вы покормили {message.reply_to_message.from_user.first_name}! (+2 💖 к лояльности)")


@dp.message(F.text & F.text.regexp(REGEX_PET_HAREM))
@dp.message(Command("pet"))
async def cmd_pet_harem(message: types.Message):
    if not message.reply_to_message:
        return await message.answer("❌ Эту команду нужно использовать ответом на сообщение участника вашего гарема!")

    target_id = message.reply_to_message.from_user.id
    owner_id = message.from_user.id

    harem = await get_user_harem(owner_id)
    if not any(m[0] == target_id for m in harem):
        return await message.answer("❌ Этот пользователь не в вашем гареме!")

    async with aiosqlite.connect(DB_PATH) as db:
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
    safe_name = escape_html_text(user.first_name)

    partner_text = "Одинок(а) 💔"
    if chat_type in ["group", "supergroup"]:
        marriage = await get_user_marriage(chat_id, user_id)
        if marriage:
            u1_id, u1_name, u2_id, u2_name, date, love_level = marriage
            partner_id = u2_id if u1_id == user_id else u1_id
            partner_name = u2_name if u1_id == user_id else u1_name
            partner_text = f"В браке с {fmt_name(partner_id, partner_name)} 💍 ({date}, ❤️ Уровень: {love_level})"

    stats = await get_user_stats(user_id)
    (
        hugs,
        kisses,
        bites,
        slaps,
        pats,
        m_count,
        s_count,
        balance,
        custom_title,
        is_hidden,
        casino_played,
        divorces_count,
        last_daily,
        daily_streak,
        referred_by,
        xp,
        level_db,
    ) = stats

    total_rp = hugs + kisses + bites + slaps + pats

    # Финальный расчет уровня
    level = (xp // 100) + 1 if xp > 0 else level_db
    if level < 1:
        level = 1

    if level < 5:
        rank = "Новичок 🍼"
    elif level < 15:
        rank = "Освоившийся 🥉"
    elif level < 30:
        rank = "Активный 🥈"
    elif level < 50:
        rank = "Знаменитость 🥇"
    elif level < 100:
        rank = "Легенда 👑"
    else:
        rank = "Божество 🌟"

    # Ачивки
    achievements = []
    if slaps > 50:
        achievements.append("🥊")
    if kisses > 100:
        achievements.append("💋")
    if divorces_count >= 3:
        achievements.append("💔")
    if casino_played > 50:
        achievements.append("🎰")

    safe_custom_title = escape_html_text(custom_title) if custom_title else ""
    title_str = f" [{safe_custom_title}]" if safe_custom_title else ""
    achievements_str = " " + "".join(achievements) if achievements else ""

    ref_count = await get_referral_stats(user_id)

    profile_text = (
        f"👤 <b>Ваш профиль:</b> {safe_name}{title_str}{achievements_str}\n"
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
    if await check_action_cooldown(message, "profile"):
        return
    text, markup = await get_profile_content(message.chat.type, message.chat.id, message.from_user)
    # В группах — autodelete через TTL_GROUP_PANEL (2 мин), в ЛС — навсегда.
    await reply_group_ephemeral(
        message,
        text,
        ttl=TTL_GROUP_PANEL,
        parse_mode="HTML",
        reply_markup=markup,
    )


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


@dp.message(F.text & F.text.regexp(REGEX_PAY))
async def cmd_pay(message: types.Message):
    if await check_action_cooldown(message, "pay"):
        return
    match = REGEX_PAY.search(message.text or "")
    if not match:
        return await message.answer(
            "❌ <b>Формат:</b>\n" "• reply: <code>/pay 1500</code>\n" "• mention: <code>/pay @username 1500</code>",
            parse_mode="HTML",
        )

    mention = match.group(1)
    amount = int(match.group(2))
    min_amount, max_amount = 100, 50000
    if amount < min_amount or amount > max_amount:
        return await message.answer(
            f"❌ Сумма перевода должна быть от <b>{min_amount}</b> до <b>{max_amount}</b> монет.",
            parse_mode="HTML",
        )

    sender_id = message.from_user.id
    target_id = None
    target_username = None
    target_first_name = None
    target_is_bot = False

    if mention:
        username_key = mention.lstrip("@").lower()
        profile = await get_user_profile_by_username(username_key)
        if profile:
            target_id, target_username, target_first_name = profile
            target_is_bot = False
        else:
            # Fallback for rare cases when Telegram API can still resolve target directly
            try:
                target_chat = await bot.get_chat(mention)
            except Exception:
                return await message.answer(
                    "❌ Не удалось найти пользователя по @username.\n"
                    "Попросите его написать сообщение в чате с ботом и попробуйте снова, "
                    "или сделайте перевод ответом на его сообщение."
                )
            if getattr(target_chat, "type", "") != "private":
                return await message.answer("❌ Перевод доступен только пользователям (не каналам/чатам).")
            target_id = target_chat.id
            target_username = getattr(target_chat, "username", None)
            target_first_name = getattr(target_chat, "first_name", None) or getattr(target_chat, "title", None)
            target_is_bot = bool(getattr(target_chat, "is_bot", False))
            await upsert_user_profile(target_id, target_username, target_first_name)
    else:
        if not message.reply_to_message:
            return await message.answer(
                "❌ Укажите получателя: ответьте на сообщение или используйте <code>@username</code>.",
                parse_mode="HTML",
            )
        target_user = message.reply_to_message.from_user
        target_id = target_user.id
        target_username = target_user.username
        target_first_name = target_user.first_name
        target_is_bot = target_user.is_bot

    if target_id == sender_id:
        return await message.answer("🚷 Нельзя перевести монеты самому себе.")
    if target_is_bot:
        return await message.answer("🤖 Ботам переводы недоступны.")

    fee = max(1, round(amount * 0.05))
    receive_amount = amount - fee
    if receive_amount <= 0:
        return await message.answer("❌ Слишком маленькая сумма перевода с учетом комиссии.")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('BEGIN IMMEDIATE')
        await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (sender_id,))
        await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (target_id,))
        cursor = await db.execute(
            'UPDATE users_stats SET balance = balance - ? WHERE user_id = ? AND balance >= ?', (amount, sender_id, amount)
        )
        if cursor.rowcount == 0:
            await db.rollback()
            return await message.answer("❌ Недостаточно монет для перевода.")
        await db.execute('UPDATE users_stats SET balance = balance + ? WHERE user_id = ?', (receive_amount, target_id))
        await db.commit()

    target_label = format_user_tag(target_username, target_first_name, target_id)
    await message.answer(
        f"💸 <b>Перевод выполнен</b>\n"
        f"Получатель: {target_label}\n"
        f"Сумма: <b>{amount}</b>\n"
        f"Комиссия (5%): <b>{fee}</b>\n"
        f"Зачислено: <b>{receive_amount}</b>",
        parse_mode="HTML",
    )


@dp.message(F.text & F.text.regexp(REGEX_ROB))
async def cmd_rob(message: types.Message):
    if not message.reply_to_message:
        return await message.answer("❌ <b>Ошибка:</b> Эту команду нужно использовать ответом на сообщение жертвы!", parse_mode="HTML")

    target = message.reply_to_message.from_user
    initiator = message.from_user
    target_label = format_user_tag(target.username, target.first_name, target.id)

    if target.id == initiator.id:
        return await message.answer("🚷 Вы не можете ограбить самого себя!")
    if target.is_bot:
        return await message.answer("🤖 Роботы не носят с собой кошельки!")

    if await check_cd_and_warn(message, "rob", 30, ignore_admin_bypass=True):
        return

    victim_cd = await is_on_cooldown(
        target.id,
        "rob_victim",
        60,
        ignore_admin_bypass=True,
        touch=False,
    )
    if victim_cd:
        return await message.answer(
            f"🛡️ {target_label} под защитой от ограбления еще <b>{victim_cd}</b> сек.",
            parse_mode="HTML",
        )

    target_stats = await get_user_stats(target.id)
    target_balance = target_stats[7]

    if target_balance <= 0:
        return await message.answer(f"📦 У {target_label} совсем пусто в карманах... Нечего красть!")

    # Определяем шанс успеха
    success_chance = 0.30

    # Шанс успеха
    if random.random() < success_chance:
        # Увеличиваем вариативность суммы кражи (от 5% до 15% от баланса жертвы)
        amount_candidate = int(target_balance * random.uniform(0.05, 0.15))
        if amount_candidate < 1:
            amount_candidate = 1

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('BEGIN IMMEDIATE')
            await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (target.id,))
            await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (initiator.id,))
            async with db.execute(
                'SELECT id FROM user_inventory WHERE user_id = ? AND item_type = ? AND item_data = ? LIMIT 1',
                (target.id, "consumable", "anti_rob_shield"),
            ) as cursor:
                shield_row = await cursor.fetchone()
            if shield_row:
                await db.execute('DELETE FROM user_inventory WHERE id = ?', (shield_row[0],))
                await db.commit()
                msg = await message.answer(
                    f"🛡️ <b>Щит сработал!</b>\n{target_label} блокирует попытку ограбления и теряет 1 заряд щита.", parse_mode="HTML"
                )
                if message.chat.type in ["group", "supergroup"]:
                    schedule_delete_once(msg, 30)
                return

            async with db.execute('SELECT balance FROM users_stats WHERE user_id = ?', (target.id,)) as cursor:
                row = await cursor.fetchone()
            current_target_balance = row[0] if row and row[0] is not None else 0
            amount = min(amount_candidate, current_target_balance)
            if amount <= 0:
                await db.rollback()
                return await message.answer(f"📦 У {target_label} совсем пусто в карманах... Нечего красть!")
            await db.execute('UPDATE users_stats SET balance = MAX(0, balance - ?) WHERE user_id = ?', (amount, target.id))
            await db.execute('UPDATE users_stats SET balance = balance + ? WHERE user_id = ?', (amount, initiator.id))
            await db.commit()
        set_cooldown(target.id, "rob_victim", 60)

        success_templates = [
            "🥷 <b>Успешная кража!</b>\nТы незаметно вытащил <b>{amount} монет</b> из кармана {target}.",
            "😏 <b>План 'Г' сработал!</b>\nПока Аля отвлеклась, ты стянул <b>{amount} монет</b> у {target}.",
            "✨ <b>Фортуна на твоей стороне!</b>\nТы ловко обчистил {target} на <b>{amount} монет</b>.",
            "🤫 <b>Тихо и чисто!</b>\n{target} даже не заметил(а) потери <b>{amount} монет</b>.",
        ]
        text = random.choice(success_templates).format(amount=amount, target=target_label)
        msg = await message.answer(text, parse_mode="HTML")
        if message.chat.type in ["group", "supergroup"]:
            schedule_delete_once(msg, 30)
    else:
        # Провал - штраф (рандом от 50 до 150 монет)
        penalty = random.randint(50, 150)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (initiator.id,))
            await db.execute('UPDATE users_stats SET balance = MAX(0, balance - ?) WHERE user_id = ?', (penalty, initiator.id))
            await db.commit()

        failure_templates = [
            "🚨 <b>Провал!</b>\nВас поймала <b>Аля</b> на месте преступления! За нарушение порядка вы оштрафованы на <b>{penalty} монет</b>.",
            "👮‍♂️ <b>Масачика заметил!</b>\nОн не любит воришек. Ты оштрафован на <b>{penalty} монет</b>.",
            "😡 <b>Неудачная попытка!</b>\n{target} оказался слишком внимательным. Твой кошелек полегчал на <b>{penalty} монет</b>.",
            "🤦‍♂️ <b>Эх, спалился...</b>\nАля увидела, как ты лезешь в карман. Штраф <b>{penalty} монет</b>.",
        ]
        text = random.choice(failure_templates).format(penalty=penalty, target=target_label)
        msg = await message.answer(text, parse_mode="HTML")
        if message.chat.type in ["group", "supergroup"]:
            schedule_delete_once(msg, 30)


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
        items.append(f"👑 Кастомный титул: <b>{escape_html_text(custom_title)}</b>")

    db_items = await get_user_inventory(target_user_id)
    shield_charges = 0
    for itype, idata in db_items:
        if itype == "consumable" and idata == "anti_rob_shield":
            shield_charges += 1
            continue
        safe_idata = escape_html_text(idata)
        if itype == "badge":
            items.append(f"🏅 Значок: <b>{safe_idata}</b>")
        else:
            items.append(f"📦 <b>{safe_idata}</b>")
    if shield_charges > 0:
        items.append(f"🛡️ Щит от ограбления: <b>{shield_charges}</b> заряд(а)")

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

    if await check_cd_and_warn(callback, "alya_roast", 30):
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    wait_msg = await callback.message.answer("<i>Аля изучает твое досье...</i>", parse_mode="HTML")

    name = callback.from_user.first_name
    (
        hugs,
        kisses,
        bites,
        slaps,
        pats,
        m_count,
        s_count,
        balance,
        custom_title,
        is_hidden,
        casino_played,
        divorces_count,
        last_daily,
        daily_streak,
        referred_by,
        xp,
        level_db,
    ) = await get_user_stats(target_user_id)

    partner_text = "Одинок"
    if callback.message.chat.type in ["group", "supergroup"]:
        marriage = await get_user_marriage(callback.message.chat.id, target_user_id)
        if marriage:
            partner_text = "В браке"

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

    try:
        response = await ask_groq("Оцени меня!", system_prompt)
    except Exception as e:
        logging.error(f"roast_profile: AI request failed for {target_user_id}: {e}")
        try:
            await wait_msg.delete()
        except Exception:
            pass
        return await callback.message.answer("⚠️ Аля сейчас немного смущена и не может дать мнение. Попробуйте еще раз через минутку.")

    await wait_msg.delete()
    # В группах — autodelete через TTL_GROUP_PANEL (2 мин), в ЛС — навсегда.
    await reply_group_ephemeral(
        callback.message,
        f"📋 <b>Мнение Али о {escape_html_text(name)}:</b>\n{escape_html_text(response)}",
        ttl=TTL_GROUP_PANEL,
        parse_mode="HTML",
    )


@dp.message(F.text & F.text.regexp(REGEX_STATS))
async def cmd_stats(message: types.Message):
    if message.chat.type == "private":
        return await message.answer("Статистика чата доступна только в группах.")
    if await check_action_cooldown(message, "stats"):
        return

    # Ранее брали top-100 и последовательно дергали get_chat_member → >10с.
    # Теперь: top-20 из БД + параллельный asyncio.gather → обычно <500ms.
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT user_id, messages_count, balance FROM users_stats ' 'WHERE messages_count > 0 ORDER BY messages_count DESC LIMIT 20'
        ) as cursor:
            top_msg = await cursor.fetchall()

        async with db.execute(
            'SELECT user_id, (hugs + kisses + bites + slaps + pats) as rp_total, balance '
            'FROM users_stats WHERE (hugs + kisses + bites + slaps + pats) > 0 '
            'ORDER BY rp_total DESC LIMIT 20'
        ) as cursor:
            top_rp = await cursor.fetchall()

    # Общий пул id — одним gather запросим всех, кто нужен для обоих топов.
    all_uids = {uid for uid, _, _ in top_msg} | {uid for uid, _, _ in top_rp}
    chat_id = message.chat.id

    async def _safe_member(uid: int):
        try:
            cm = await bot.get_chat_member(chat_id, uid)
            if cm.status in ("left", "kicked", "banned"):
                return None
            return cm.user.first_name if cm.user else f"ID: {uid}"
        except Exception:
            return None

    members = await asyncio.gather(*[_safe_member(uid) for uid in all_uids])
    name_by_uid = dict(zip(all_uids, members, strict=False))

    def format_top(rows, unit: str) -> str:
        res, rank = [], 1
        for uid, count, balance in rows:
            if rank > 5:
                break
            name = name_by_uid.get(uid)
            if not name:
                continue
            res.append(f"{rank}. <b>{escape_html_text(name)}</b> — {count} {unit} | {balance} 💰")
            rank += 1
        return "\n".join(res) if res else "<i>Пока пусто...</i>"

    top_msg_text = format_top(top_msg, "сообщ.")
    top_rp_text = format_top(top_rp, "РП")

    text = f"📊 <b>Статистика чата:</b>\n\n" f"🗣 <b>Топ болтунов:</b>\n{top_msg_text}\n\n" f"🎭 <b>Самые любвеобильные:</b>\n{top_rp_text}"
    # В группах — autodelete через TTL_GROUP_PANEL (2 мин).
    await reply_group_ephemeral(message, text, ttl=TTL_GROUP_PANEL, parse_mode="HTML")


# РП команды теперь в handlers/rp.py


# ==============================================================================
# БЛОК 7: БРАКИ (СВАДЬБЫ И РАЗВОДЫ)
# ==============================================================================
@dp.message(F.text & F.text.regexp(REGEX_MARRY))
async def propose_marriage(message: types.Message):
    if message.chat.type == "private":
        return await temp_reply(message, "Только в группах!")
    if await check_cd_and_warn(message, "marry", 10):
        return
    if not message.reply_to_message:
        return await temp_reply(message, "Ответьте на сообщение человека!")

    initiator, target = message.from_user, message.reply_to_message.from_user
    chat_id = message.chat.id
    if target.id == initiator.id:
        return await temp_reply(message, "На себе нельзя!")
    if target.is_bot:
        return await temp_reply(message, "С ботами нельзя!")

    if await get_user_marriage(chat_id, initiator.id) or await get_user_marriage(chat_id, target.id):
        return await temp_reply(message, "Кто-то из вас уже состоит в браке!")

    MARRIAGE_PROPOSALS[f"{chat_id}_{initiator.id}_{target.id}"] = initiator.first_name

    builder = InlineKeyboardBuilder()
    builder.button(text="💍 Согласиться", callback_data=f"marry_yes_{initiator.id}_{target.id}")
    builder.button(text="💔 Отказать", callback_data=f"marry_no_{initiator.id}_{target.id}")
    await message.answer(
        f"💍 {target.mention_html()}, {initiator.mention_html()} предлагает брак!\nЧто ответишь?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("marry_"))
async def process_marriage_callback(callback: types.CallbackQuery):
    _, action, init_id, targ_id = callback.data.split("_")
    if str(callback.from_user.id) != targ_id:
        return await callback.answer("Это не для вас!", show_alert=True)
    if action == "no":
        return await callback.message.edit_text(f"💔 {callback.from_user.mention_html()} отверг(ла) предложение.", parse_mode="HTML")

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
        except Exception as e:
            logging.debug(f"marriage_callback: failed to resolve initiator name {init_id}: {e}")
            init_name = 'Пользователь'

    targ_user = callback.from_user
    targ_name = targ_user.first_name

    date_now = datetime.now().strftime("%d.%m.%Y")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT INTO marriages (chat_id, user1_id, user1_name, user2_id, user2_name, date) VALUES (?, ?, ?, ?, ?, ?)',
            (chat_id, int(init_id), init_name, int(targ_id), targ_name, date_now),
        )
        await db.commit()
    await callback.message.edit_text(
        f"🎉 <b>Объявляю вас мужем и женой!</b>\n\nТеперь {escape_html_text(init_name)} и {escape_html_text(targ_name)} официально в браке 💍",
        parse_mode="HTML",
    )


@dp.message(F.text & F.text.regexp(REGEX_DIVORCE))
async def process_divorce(message: types.Message):
    if message.chat.type == "private":
        return
    if await check_cd_and_warn(message, "divorce", 10):
        return

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
        except Exception as e:
            logging.debug(f"divorce: ask_groq fallback used: {e}")
            response = f"Ты действительно хочешь развестись с {partner_name}? Подумай хорошенько, бака!"

    await wait_msg.delete()

    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="✅ Да, развестись", callback_data=f"divorce_yes:{message.from_user.id}")],
            [types.InlineKeyboardButton(text="❌ Передумал(а)", callback_data=f"divorce_no:{message.from_user.id}")],
        ]
    )

    await message.answer(f"🌸 <b>Аля:</b>\n{escape_html_text(response)}", parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("divorce_"))
async def handle_divorce_cb(callback: types.CallbackQuery):
    action, uid = callback.data.split(":")
    if callback.from_user.id != int(uid):
        return await callback.answer("Это не ваш запрос на развод!", show_alert=True)

    await callback.message.edit_reply_markup(reply_markup=None)

    if action == "divorce_no":
        return await callback.message.answer("<i>Брак спасен! (пока что...)</i>", parse_mode="HTML")

    async with aiosqlite.connect(DB_PATH) as db:
        # Get users in the marriage to update their divorce count
        async with db.execute(
            'SELECT user1_id, user2_id FROM marriages WHERE chat_id = ? AND (user1_id = ? OR user2_id = ?)',
            (callback.message.chat.id, callback.from_user.id, callback.from_user.id),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                u1, u2 = row
                await db.execute('UPDATE users_stats SET divorces_count = divorces_count + 1 WHERE user_id IN (?, ?)', (u1, u2))

        await db.execute(
            'DELETE FROM marriages WHERE chat_id = ? AND (user1_id = ? OR user2_id = ?)',
            (callback.message.chat.id, callback.from_user.id, callback.from_user.id),
        )
        await db.commit()
    await callback.message.answer("💔 Вы успешно расторгли брак.")


# ==============================================================================
# БЛОК 7.1: ГАРЕМ
# ==============================================================================
@dp.message(F.text & F.text.regexp(REGEX_HAREM_ADD))
async def propose_harem(message: types.Message):
    if await check_cd_and_warn(message, "harem_add", 5):
        return
    if not message.reply_to_message:
        return await temp_reply(message, "Ответьте на сообщение человека!")

    initiator, target = message.from_user, message.reply_to_message.from_user
    if target.id == initiator.id:
        return await temp_reply(message, "Нельзя добавить себя в свой гарем!")
    if target.is_bot:
        return await temp_reply(message, "С ботами нельзя!")

    harem = await get_user_harem(initiator.id)
    if any(m[0] == target.id for m in harem):
        return await temp_reply(message, "Этот пользователь уже в вашем гареме!")

    HAREM_PROPOSALS[f"{initiator.id}_{target.id}"] = initiator.first_name

    builder = InlineKeyboardBuilder()
    builder.button(text="😈 Согласиться", callback_data=f"harem_yes_{initiator.id}_{target.id}")
    builder.button(text="🙅 Отказать", callback_data=f"harem_no_{initiator.id}_{target.id}")
    await message.answer(
        f"👑 {target.mention_html()}, {initiator.mention_html()} предлагает тебе вступить в его/её гарем!\nЧто ответишь?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("harem_"))
async def process_harem_callback(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) == 4:
        _, action, init_id, targ_id = parts
    else:
        return

    if str(callback.from_user.id) != targ_id:
        return await callback.answer("Это не для вас!", show_alert=True)
    if action == "no":
        return await callback.message.edit_text(
            f"🙅 {callback.from_user.mention_html()} отверг(ла) предложение вступить в гарем.", parse_mode="HTML"
        )

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
        except Exception as e:
            logging.debug(f"harem_callback: failed to resolve initiator name {init_id}: {e}")
            init_name = 'Пользователь'

    targ_user = callback.from_user
    targ_name = targ_user.first_name

    await add_to_harem(int(init_id), int(targ_id), targ_name)
    await callback.message.edit_text(
        f"🎉 <b>Новое пополнение гарема!</b>\n\nТеперь {escape_html_text(targ_name)} принадлежит {escape_html_text(init_name)} 👑",
        parse_mode="HTML",
    )


@dp.message(F.text & F.text.regexp(REGEX_HAREM_REMOVE))
async def remove_harem_member(message: types.Message):
    if await check_cd_and_warn(message, "harem_remove", 5):
        return
    if not message.reply_to_message:
        return await temp_reply(message, "Ответьте на сообщение человека!")

    initiator, target = message.from_user, message.reply_to_message.from_user
    harem = await get_user_harem(initiator.id)
    if not any(m[0] == target.id for m in harem):
        return await temp_reply(message, "Этого пользователя нет в вашем гареме!")

    await remove_from_harem(initiator.id, target.id)
    await message.answer(f"🗑 {target.mention_html()} был(а) изгнан(а) из вашего гарема!")


@dp.message(F.text & F.text.regexp(REGEX_MARRIAGES))
async def list_marriages(message: types.Message):
    if message.chat.type == "private":
        return await temp_reply(message, "Только в группах!")
    if await check_cd_and_warn(message, "marriages_list", 10):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT user1_id, user2_id, user1_name, user2_name, date FROM marriages WHERE chat_id = ?', (message.chat.id,)
        ) as cursor:
            marriages = await cursor.fetchall()

    if not marriages:
        return await temp_reply(message, "В этой беседе пока нет ни одной пары 😔", parse_mode="HTML")

    lines = [
        f"{i}. {fmt_name(u1_id, u1_name)} ❤️ {fmt_name(u2_id, u2_name)} <i>({d})</i>"
        for i, (u1_id, u2_id, u1_name, u2_name, d) in enumerate(marriages, 1)
    ]
    text = "💍 <b>Топ пар:</b>\n\n" + "\n".join(lines)
    await message.answer(text, parse_mode="HTML")


# ==============================================================================
# БЛОК 8: МИНИ-ИГРЫ И РАЗВЛЕЧЕНИЯ (ИРИС)
# ==============================================================================
@dp.message(F.text & F.text.regexp(REGEX_INFA))
async def cmd_infa(message: types.Message):
    if await check_action_cooldown(message, "iris_cmd"):
        return
    chance = random.randint(0, 100)
    match = REGEX_INFA.search(message.text)
    if not match:
        return await temp_reply(message, "❌ Формат: /инфа [текст] или infa [text]")
    await reply_and_forget(
        message,
        f"🔮 Вероятность того, что {escape_html_text(match.group(1).strip())} — <b>{chance}%</b>",
        ttl=TTL_GAME,
        parse_mode="HTML",
    )


@dp.message(F.text & F.text.regexp(REGEX_RANDOM))
async def cmd_random(message: types.Message):
    if await check_action_cooldown(message, "iris_cmd"):
        return
    match = REGEX_RANDOM.search(message.text)
    if not match:
        return await temp_reply(message, "❌ Формат: /рандом [число] или random [number]")
    limit = int(match.group(1))
    if limit <= 0:
        return await temp_reply(message, "Число должно быть больше нуля!")
    await reply_and_forget(
        message,
        f"🎲 Выпало число: <b>{random.randint(1, limit)}</b>",
        ttl=TTL_GAME,
        parse_mode="HTML",
    )


@dp.message(F.text & F.text.regexp(REGEX_CHOOSE))
async def cmd_choose(message: types.Message):
    if await check_action_cooldown(message, "iris_cmd"):
        return
    match = REGEX_CHOOSE.search(message.text)
    if not match:
        return await temp_reply(message, "❌ Формат: /выбери [A] или [B] / choose [A] or [B]")
    choice = random.choice([match.group(1).strip(), match.group(2).strip()])
    await reply_and_forget(
        message,
        f"🤔 Я думаю, лучше:\n👉 <b>{escape_html_text(choice)}</b>",
        ttl=TTL_GAME,
        parse_mode="HTML",
    )


@dp.message(F.text & F.text.regexp(REGEX_ALYA_CHOOSE))
async def cmd_alya_choose(message: types.Message):
    if await check_action_cooldown(message, "alya_choose"):
        return

    match = REGEX_ALYA_CHOOSE.search(message.text)
    if not match:
        return await temp_reply(message, "❌ Формат: Аля, выбери [A] или [B] / Alya choose [A] or [B]")
    item1, item2 = match.group(1).strip(), match.group(2).strip()

    if message.chat.type in ["group", "supergroup"] and not await is_ai_enabled(message.chat.id):
        return await message.answer("🌸 <b>Выбор Али:</b>\nБака, я сейчас не в настроении выбирать!", parse_mode="HTML")

    wait_msg = await message.answer("<i>Аля думает...</i>", parse_mode="HTML")
    system_prompt = (
        f"Ты Аля (аниме Roshidere). Пользователь просит тебя выбрать между '{item1}' и '{item2}'. "
        f"Сделай однозначный выбор в пользу одного из них. Объясни свой выбор коротко (1-2 предложения), "
        f"в стиле цундере. Будь немного дерзкой. (Можешь в конце добавить мысль по-русски в скобках)."
    )
    response = await ask_groq("Что лучше?", system_prompt)
    await wait_msg.delete()
    await reply_and_forget(
        message,
        f"🌸 <b>Выбор Али:</b>\n{escape_html_text(response)}",
        ttl=TTL_GAME,
        parse_mode="HTML",
    )


@dp.message(F.text & F.text.regexp(REGEX_COIN))
async def cmd_coin(message: types.Message):
    if await check_action_cooldown(message, "iris_cmd"):
        return
    coin = random.choice(["Орел", "Решка"])
    await reply_and_forget(
        message,
        f"🪙 Выпало: <b>{coin}</b>",
        ttl=TTL_GAME,
        parse_mode="HTML",
    )


# ==============================================================================
# БЛОК: ИИ-ИГРЫ И ШИППЕРИНГ
# ==============================================================================
BOTTLE_GAMES = {}


@dp.message(F.text & F.text.regexp(REGEX_BOTTLE))
async def cmd_bottle(message: types.Message):
    if message.chat.type == "private":
        return await temp_reply(message, "Только в группах!")
    if await check_action_cooldown(message, "bottle"):
        return

    chat_id = message.chat.id
    if chat_id in BOTTLE_GAMES:
        return await temp_reply(message, "В этой беседе уже идет сбор на бутылочку!")

    BOTTLE_GAMES[chat_id] = {"participants": {message.from_user.id: message.from_user.first_name}, "msg_id": None}

    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text="🏃 Участников: 1", callback_data="bottle_join"),
                types.InlineKeyboardButton(text="Крутить", callback_data="bottle_spin"),
            ]
        ]
    )

    msg = await message.answer(
        "🍾 <b>Игра в Бутылочку!</b>\n\nПрисоединяйтесь к игре! Как только наберется народ, жмите «Крутить».",
        parse_mode="HTML",
        reply_markup=kb,
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

    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text=f"🏃 Участников: {count}", callback_data="bottle_join"),
                types.InlineKeyboardButton(text="Крутить", callback_data="bottle_spin"),
            ]
        ]
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception as e:
        logging.debug(f"bottle_join: failed to edit reply markup: {e}")
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
    except Exception as e:
        logging.debug(f"bottle_spin: failed to clear reply markup: {e}")

    p_ids = list(participants.keys())
    p1 = random.choice(p_ids)
    p_ids.remove(p1)
    p2 = random.choice(p_ids)

    n1, n2 = participants[p1], participants[p2]
    safe_n1 = escape_html_text(n1)
    safe_n2 = escape_html_text(n2)

    wait_msg = await callback.message.answer(
        f"🍾 Бутылочка крутится... выпадают <b>{safe_n1}</b> и <b>{safe_n2}</b>!\n<i>Аля придумывает фант...</i>", parse_mode="HTML"
    )

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
        except Exception as e:
            logging.debug(f"bottle_spin: ask_groq fallback used: {e}")
            task = "Обнимите друг друга, баки! И не думайте, что я хочу на это смотреть!"

    await wait_msg.delete()
    await callback.message.answer(
        f"🍾 <b>Бутылочка!</b>\n\n"
        f"Пара: <a href='tg://user?id={p1}'>{safe_n1}</a> и <a href='tg://user?id={p2}'>{safe_n2}</a>\n\n"
        f"🌸 <b>Задание от Али:</b>\n{escape_html_text(task)}",
        parse_mode="HTML",
    )


# @dp.message(F.text.regexp(REGEX_SHIP))
# async def cmd_ship(message: types.Message):
#     logging.info(f"DEBUG: Ship handler triggered by {message.from_user.id} in chat {message.chat.id}")
#     if message.chat.type == "private": return await temp_reply(message, "Только в группах!")
#     # Временно уберем кулдаун для теста
#     # if await check_cd_and_warn(message, "ship", 60): return
#
#     async with aiosqlite.connect(DB_PATH) as db:
#         async with db.execute('SELECT user_id, first_name FROM users_stats WHERE chat_id = ? ORDER BY RANDOM() LIMIT 2', (message.chat.id,)) as cursor:
#             participants = await cursor.fetchall()
#
#     if len(participants) < 2:
#         msg = await message.answer(f"❌ В этой беседе недостаточно данных для шипперинга (найдено {len(participants)} участников). Попробуйте написать любое сообщение, чтобы бот запомнил вас в этом чате.")
#         if message.chat.type in ["group", "supergroup"]:
#             asyncio.create_task(delete_after(msg, 30))
#         return
#
#     p1_id, p1_name = participants[0]
#     p2_id, p2_name = participants[1]
#
#     wait_msg = await message.answer(f"💞 <i>Аля анализирует совместимость {p1_name} и {p2_name}...</i>", parse_mode="HTML")
#     if message.chat.type in ["group", "supergroup"]:
#         asyncio.create_task(delete_after(wait_msg, 30))
#
#     compatibility = random.randint(0, 100)
#
#     system_prompt = (
#         "Ты Аля (аниме Roshidere). Твоя задача — сгенерировать короткую, забавную или милую "
#         f"историю любви (шипперинг) между пользователями '{p1_name}' и '{p2_name}'. "
#         f"Их процент совместимости — {compatibility}%. "
#         "Опиши, как они могли бы встретиться или почему они (не) подходят друг другу, в стиле цундере."
#     )
#
#     if not await is_ai_enabled(message.chat.id):
#         story = "Эти баки настолько подходят друг другу, что я даже не хочу об этом говорить!"
#     else:
#         try:
#             story = await ask_groq("Расскажи историю любви", system_prompt)
#         except Exception:
#             story = "Эти баки настолько подходят друг другу, что я даже не хочу об этом говорить!"
#
#     await wait_msg.delete()
#     text = (
#         f"💘 <b>Шипперинг!</b> 💘\n\n"
#         f"Пара: <a href='tg://user?id={p1_id}'>{p1_name}</a> x <a href='tg://user?id={p2_id}'>{p2_name}</a>\n"
#         f"Совместимость: <b>{compatibility}%</b>\n\n"
#         f"🌸 <b>Прогноз от Али:</b>\n{story}"
#     )
#     final_msg = await message.answer(text, parse_mode="HTML")
#     if message.chat.type in ["group", "supergroup"]:
#         asyncio.create_task(delete_after(final_msg, 60))

# ==============================================================================
# БЛОК: ЭКОНОМИКА И МАГАЗИН
# ==============================================================================


@dp.message(F.text & F.text.regexp(REGEX_SHOP))
async def cmd_shop(message: types.Message):
    if message.chat.type == "private":
        return await temp_reply(message, "Только в группах!")
    if await check_action_cooldown(message, "shop"):
        return

    # В группах — autodelete через TTL_GROUP_PANEL (2 мин). В ЛС команда недоступна.
    await reply_group_ephemeral(
        message,
        await get_shop_text(message.from_user.id, page=0),
        ttl=TTL_GROUP_PANEL,
        parse_mode="HTML",
        reply_markup=build_shop_keyboard(page=0),
    )


SHOP_ITEMS_PER_PAGE = 4
SHOP_ITEMS = [
    ("🎁 Тайный Лутбокс", LOOTBOX_PRICE, "buy_lootbox"),
    ("👑 Кастомный титул", 500, "buy_title"),
    ("👻 Скрыть стату в топе", 1000, "buy_hidden"),
    ("🎖️ Значок VIP", 2000, "buy_badge_vip"),
    ("🛡️ Щит от ограбления", 800, "buy_shield"),
    ("✨ Пакет XP +120", 500, "buy_xp_pack"),
    ("🌙 Значок «Лунный знак»", 700, "buy_badge_moon"),
    ("💘 Значок «Купидон»", 900, "buy_badge_cupid"),
    ("🔥 Значок «Пламя страсти»", 1100, "buy_badge_flame"),
]


def _pack_shop_buy(action: str, page: int) -> str:
    return f"{action}:{page}"


def _parse_shop_buy(raw_data: str) -> tuple[str, int]:
    if ":" not in raw_data:
        return raw_data, 0
    action, page_raw = raw_data.rsplit(":", 1)
    try:
        return action, max(0, int(page_raw))
    except ValueError:
        return action, 0


def build_shop_keyboard(page: int = 0) -> types.InlineKeyboardMarkup:
    total_pages = max(1, math.ceil(len(SHOP_ITEMS) / SHOP_ITEMS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))
    start = page * SHOP_ITEMS_PER_PAGE
    end = start + SHOP_ITEMS_PER_PAGE
    items = SHOP_ITEMS[start:end]

    rows = [
        [
            types.InlineKeyboardButton(
                text=f"{name} ({price} монет)",
                callback_data=_pack_shop_buy(action, page),
            )
        ]
        for name, price, action in items
    ]

    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton(text="◀️", callback_data=f"shop_page:{page - 1}"))
    nav.append(types.InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="shop_page:noop"))
    if page < total_pages - 1:
        nav.append(types.InlineKeyboardButton(text="▶️", callback_data=f"shop_page:{page + 1}"))
    rows.append(nav)

    return types.InlineKeyboardMarkup(inline_keyboard=rows)


async def get_shop_text(user_id: int, note: str | None = None, page: int = 0) -> str:
    stats = await get_user_stats(user_id)
    balance = stats[7] if stats else 0
    total_pages = max(1, math.ceil(len(SHOP_ITEMS) / SHOP_ITEMS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))
    start = page * SHOP_ITEMS_PER_PAGE
    end = start + SHOP_ITEMS_PER_PAGE
    items = SHOP_ITEMS[start:end]
    items_text = "\n".join([f"• {name} — <b>{price}</b>" for name, price, _ in items])
    text = (
        f"🛒 <b>Магазин Аля-бота</b>\n\n"
        f"У вас <b>{balance}</b> монет.\n"
        f"Страница <b>{page + 1}/{total_pages}</b>.\n\n"
        f"{items_text}"
    )
    if note:
        text += f"\n\n{note}"
    return text


async def refresh_shop_message(callback: types.CallbackQuery, note: str | None = None, page: int = 0):
    await send_or_edit_quiet(
        callback,
        await get_shop_text(callback.from_user.id, note=note, page=page),
        parse_mode="HTML",
        reply_markup=build_shop_keyboard(page=page),
    )


@dp.callback_query(F.data == "shop_page:noop")
async def shop_page_noop(callback: types.CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data.startswith("shop_page:"))
async def shop_page_switch(callback: types.CallbackQuery):
    if callback.data == "shop_page:noop":
        return await callback.answer()
    try:
        page = max(0, int(callback.data.split(":", 1)[1]))
    except (ValueError, IndexError):
        return await callback.answer("Некорректная страница.", show_alert=True)

    await refresh_shop_message(callback, page=page)
    await callback.answer()


async def try_buy_badge(user_id: int, badge_name: str, price: int) -> tuple[bool, str]:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('BEGIN IMMEDIATE')
        await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (user_id,))
        async with db.execute(
            'SELECT 1 FROM user_inventory WHERE user_id = ? AND item_type = ? AND item_data = ?', (user_id, "badge", badge_name)
        ) as cursor:
            if await cursor.fetchone():
                await db.rollback()
                return False, "У вас уже есть этот значок!"

        cursor = await db.execute(
            'UPDATE users_stats SET balance = balance - ? WHERE user_id = ? AND balance >= ?', (price, user_id, price)
        )
        if cursor.rowcount == 0:
            await db.rollback()
            return False, f"Недостаточно монет! Нужно {price}."
        await db.execute('INSERT INTO user_inventory (user_id, item_type, item_data) VALUES (?, ?, ?)', (user_id, "badge", badge_name))
        await db.commit()
        return True, f"Вы успешно приобрели значок {badge_name}!"


@dp.callback_query(F.data.startswith("buy_lootbox"))
async def shop_buy_lootbox_cb(callback: types.CallbackQuery):
    if await check_action_cooldown(callback, "shop_buy"):
        return
    _, page = _parse_shop_buy(callback.data)
    ok, text = await purchase_and_roll_lootbox(callback.from_user.id)
    if not ok:
        return await callback.answer(f"Недостаточно монет! Нужно {LOOTBOX_PRICE}.", show_alert=True)
    await refresh_shop_message(callback, note=text, page=page)
    await callback.answer("Лутбокс открыт!")


@dp.callback_query(F.data.startswith("buy_title"))
async def shop_buy_title_cb(callback: types.CallbackQuery, state: FSMContext):
    if await check_action_cooldown(callback, "shop_buy"):
        return
    _, page = _parse_shop_buy(callback.data)
    stats = await get_user_stats(callback.from_user.id)
    balance = stats[7] if stats else 0
    if balance < 500:
        return await callback.answer("Недостаточно монет! Нужно 500.", show_alert=True)

    await state.set_state(ShopBuyTitle.waiting_for_title)
    await state.update_data(chat_id=callback.message.chat.id, shop_page=page)
    await callback.message.edit_text("👑 Введите ваш новый титул (до 20 символов):", reply_markup=None)


@dp.message(ShopBuyTitle.waiting_for_title)
async def shop_process_title(message: types.Message, state: FSMContext):
    # Guard: не даём команде (/admin, /start и т. п.) стать новым титулом.
    if (message.text or "").startswith("/"):
        await state.clear()
        return
    data = await state.get_data()
    chat_id = data.get("chat_id")
    page = int(data.get("shop_page", 0) or 0)
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

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            'UPDATE users_stats SET balance = balance - 500, custom_title = ? WHERE user_id = ? AND balance >= 500',
            (title, message.from_user.id),
        )
        if cursor.rowcount == 0:
            await state.clear()
            return await message.answer("Пока вы думали, у вас закончились монеты...")
        await db.commit()

    await state.clear()
    await message.answer(
        await get_shop_text(
            message.from_user.id,
            note=f"🎉 Вы успешно купили титул <b>{escape_html_text(title)}</b>!",
            page=page,
        ),
        parse_mode="HTML",
        reply_markup=build_shop_keyboard(page=page),
    )


@dp.callback_query(F.data.startswith("buy_hidden"))
async def shop_buy_hidden_cb(callback: types.CallbackQuery):
    if await check_action_cooldown(callback, "shop_buy"):
        return
    _, page = _parse_shop_buy(callback.data)
    stats = await get_user_stats(callback.from_user.id)
    balance = stats[7] if stats else 0
    if balance < 1000:
        return await callback.answer("Недостаточно монет! Нужно 1000.", show_alert=True)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            'UPDATE users_stats SET balance = balance - 1000, is_hidden = 1 WHERE user_id = ? AND balance >= 1000', (callback.from_user.id,)
        )
        if cursor.rowcount == 0:
            return await callback.answer("Недостаточно монет! Нужно 1000.", show_alert=True)
        await db.commit()
    await refresh_shop_message(callback, note="👻 Ваша статистика теперь скрыта из глобального топа!", page=page)
    await callback.answer("Готово!")


@dp.callback_query(F.data.startswith("buy_badge_vip"))
async def shop_buy_badge_vip_cb(callback: types.CallbackQuery):
    if await check_action_cooldown(callback, "shop_buy"):
        return
    _, page = _parse_shop_buy(callback.data)
    ok, text = await try_buy_badge(callback.from_user.id, "VIP 🌟", 2000)
    if not ok:
        return await callback.answer(text, show_alert=True)
    await refresh_shop_message(callback, note=f"🎖️ {escape_html_text(text)}", page=page)
    await callback.answer("Покупка успешна!")


@dp.callback_query(F.data.startswith("buy_shield"))
async def shop_buy_shield_cb(callback: types.CallbackQuery):
    if await check_action_cooldown(callback, "shop_buy"):
        return
    _, page = _parse_shop_buy(callback.data)
    user_id = callback.from_user.id
    price = 800
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('BEGIN IMMEDIATE')
        await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (user_id,))
        cursor = await db.execute(
            'UPDATE users_stats SET balance = balance - ? WHERE user_id = ? AND balance >= ?', (price, user_id, price)
        )
        if cursor.rowcount == 0:
            await db.rollback()
            return await callback.answer(f"Недостаточно монет! Нужно {price}.", show_alert=True)
        await db.execute(
            'INSERT INTO user_inventory (user_id, item_type, item_data) VALUES (?, ?, ?)', (user_id, "consumable", "anti_rob_shield")
        )
        await db.commit()
    await refresh_shop_message(callback, note="🛡️ Куплен щит от ограбления (1 заряд).", page=page)
    await callback.answer("Покупка успешна!")


@dp.callback_query(F.data.startswith("buy_xp_pack"))
async def shop_buy_xp_pack_cb(callback: types.CallbackQuery):
    if await check_action_cooldown(callback, "shop_buy"):
        return
    _, page = _parse_shop_buy(callback.data)
    user_id = callback.from_user.id
    price = 500
    xp_amount = 120
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('BEGIN IMMEDIATE')
        await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (user_id,))
        cursor = await db.execute(
            'UPDATE users_stats SET balance = balance - ?, xp = xp + ? WHERE user_id = ? AND balance >= ?',
            (price, xp_amount, user_id, price),
        )
        if cursor.rowcount == 0:
            await db.rollback()
            return await callback.answer(f"Недостаточно монет! Нужно {price}.", show_alert=True)
        await db.commit()
    await refresh_shop_message(callback, note=f"✨ Вы получили +{xp_amount} XP.", page=page)
    await callback.answer("Покупка успешна!")


@dp.callback_query(F.data.startswith("buy_badge_moon"))
async def shop_buy_badge_moon_cb(callback: types.CallbackQuery):
    if await check_action_cooldown(callback, "shop_buy"):
        return
    _, page = _parse_shop_buy(callback.data)
    ok, text = await try_buy_badge(callback.from_user.id, "🌙 Лунный знак", 700)
    if not ok:
        return await callback.answer(text, show_alert=True)
    await refresh_shop_message(callback, note=f"🏅 {escape_html_text(text)}", page=page)
    await callback.answer("Покупка успешна!")


@dp.callback_query(F.data.startswith("buy_badge_cupid"))
async def shop_buy_badge_cupid_cb(callback: types.CallbackQuery):
    if await check_action_cooldown(callback, "shop_buy"):
        return
    _, page = _parse_shop_buy(callback.data)
    ok, text = await try_buy_badge(callback.from_user.id, "💘 Купидон", 900)
    if not ok:
        return await callback.answer(text, show_alert=True)
    await refresh_shop_message(callback, note=f"🏅 {escape_html_text(text)}", page=page)
    await callback.answer("Покупка успешна!")


@dp.callback_query(F.data.startswith("buy_badge_flame"))
async def shop_buy_badge_flame_cb(callback: types.CallbackQuery):
    if await check_action_cooldown(callback, "shop_buy"):
        return
    _, page = _parse_shop_buy(callback.data)
    ok, text = await try_buy_badge(callback.from_user.id, "🔥 Пламя страсти", 1100)
    if not ok:
        return await callback.answer(text, show_alert=True)
    await refresh_shop_message(callback, note=f"🏅 {escape_html_text(text)}", page=page)
    await callback.answer("Покупка успешна!")


REGEX_DICE_GAMES = re.compile(
    r'(?i)^[/*\s]*(?:кости|кубик|dice|cube|дартс|darts|баскетбол|basketball|футбол|football|казино|casino|слоты|slots|слот|slot|боулинг|bowling)\b'
)


@dp.message(F.text & F.text.regexp(REGEX_DICE_GAMES))
async def cmd_dice_games(message: types.Message):
    text = message.text.lower()
    is_casino_text = "казино" in text or "casino" in text or "слот" in text or "slot" in text
    if is_casino_text:
        if await check_action_cooldown(message, "casino_cmd"):
            return
    else:
        if await check_action_cooldown(message, "iris_cmd"):
            return

    emoji = "🎲"
    if "дартс" in text or "darts" in text:
        emoji = "🎯"
    elif "баскетбол" in text or "basketball" in text:
        emoji = "🏀"
    elif "футбол" in text or "football" in text:
        emoji = "⚽"
    elif "казино" in text or "casino" in text or "слот" in text or "slot" in text:
        emoji = "🎰"
    elif "боулинг" in text or "bowling" in text:
        emoji = "🎳"

    if emoji == "🎰":
        match = REGEX_SLOT.search(message.text)
        bet_str = match.group(1) if match else None

        if not bet_str:
            return await maybe_ephemeral_reply(
                message,
                "🎰 <b>Формат:</b> /казино [ставка] или /casino [bet]\n<i>Пример: /казино 100</i>",
                parse_mode="HTML",
                delay=5,
            )

        try:
            bet = int(bet_str)
            if bet <= 0:
                return await maybe_ephemeral_reply(message, "❌ Ставка должна быть больше 0!", delay=4)
        except ValueError:
            return await maybe_ephemeral_reply(message, "❌ Введите корректное число для ставки!", delay=4)

        user_id = message.from_user.id
        stats = await get_user_stats(user_id)
        balance = stats[7]

        if balance < bet:
            return await maybe_ephemeral_reply(
                message,
                f"❌ <b>Недостаточно средств!</b>\nВаш баланс: {balance} монет.",
                parse_mode="HTML",
                delay=5,
            )

        # Списываем ставку
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                'UPDATE users_stats SET balance = balance - ?, casino_played = casino_played + 1 WHERE user_id = ? AND balance >= ?',
                (bet, user_id, bet),
            )
            if cursor.rowcount == 0:
                return await maybe_ephemeral_reply(message, "❌ <b>Недостаточно средств!</b>", parse_mode="HTML", delay=4)
            await db.commit()

        msg = await message.answer_dice(emoji="🎰")
        if message.chat.type in ["group", "supergroup"]:
            schedule_delete_once(msg, 30)
        await asyncio.sleep(2)

        val = msg.dice.value
        win = 0
        if val == 64:
            win = bet * 50  # 777
        elif val == 43:
            win = bet * 20  # Лимоны
        elif val == 22:
            win = bet * 10  # Виноград
        elif val == 1:
            win = bet * 10  # BAR

        if win > 0:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE users_stats SET balance = balance + ? WHERE user_id = ?', (win, user_id))
                await db.commit()
            msg = await message.answer(f"🎉 <b>ДЖЕКПОТ!</b>\nВы выиграли <b>{win}</b> монет! 💰", parse_mode="HTML")
            if message.chat.type in ["group", "supergroup"]:
                schedule_delete_once(msg, 30)
        else:
            msg = await message.answer("💨 <b>Вы проиграли ставку...</b>\nУдача обязательно вернется! 🎰", parse_mode="HTML")
            if message.chat.type in ["group", "supergroup"]:
                schedule_delete_once(msg, 30)

    else:
        dice_msg = await message.answer_dice(emoji=emoji)
        if message.chat.type in ["group", "supergroup"]:
            schedule_delete_once(dice_msg, 30)


@dp.message(F.text & F.text.regexp(REGEX_RPS))
async def cmd_rps(message: types.Message):
    if await check_action_cooldown(message, "iris_cmd"):
        return
    match = REGEX_RPS.search(message.text)
    if not match:
        return await temp_reply(message, "❌ Формат: /кнб [камень|ножницы|бумага] или /rps [rock|paper|scissors]")
    user_choice = match.group(1).lower() if match.group(1) else None
    if user_choice:
        user_choice = {
            "rock": "камень",
            "paper": "бумага",
            "scissors": "ножницы",
        }.get(user_choice, user_choice)

    if not user_choice:
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🪨 Камень", callback_data="rps_камень"))
        builder.row(types.InlineKeyboardButton(text="✂️ Ножницы", callback_data="rps_ножницы"))
        builder.row(types.InlineKeyboardButton(text="📄 Бумага", callback_data="rps_бумага"))
        msg = await message.answer("✊✌️✋ <b>Выбери свой ход:</b>", parse_mode="HTML", reply_markup=builder.as_markup())
        if message.chat.type in ["group", "supergroup"]:
            schedule_delete_once(msg, 30)
        return

    # Если выбор передан текстом (сохраняем старую логику)
    await process_rps_logic(message, user_choice)


async def process_rps_logic(target: Union[types.Message, types.CallbackQuery], user_choice: str):
    bot_choice = random.choice(["камень", "ножницы", "бумага"])
    wins = {"камень": "ножницы", "ножницы": "бумага", "бумага": "камень"}

    if user_choice not in wins:
        if isinstance(target, types.Message):
            return await target.answer("Я знаю только камень, ножницы и бумагу!")
        else:
            return await target.answer("Я знаю только камень, ножницы и бумагу!", show_alert=True)

    if user_choice == bot_choice:
        res = "Ничья! 🤝"
    elif wins[user_choice] == bot_choice:
        res = "Ты победил! 🎉"
    else:
        res = "Я победил! 🤖"

    text = f"Твой выбор: <b>{user_choice}</b>\nМой выбор: <b>{bot_choice}</b>\n\n{res}"

    if isinstance(target, types.Message):
        msg = await target.answer(text, parse_mode="HTML")
        if target.chat.type in ["group", "supergroup"]:
            schedule_delete_once(msg, 30)
    else:
        await target.message.edit_text(text, parse_mode="HTML")


@dp.callback_query(F.data.startswith("rps_"))
async def callback_rps(callback: types.CallbackQuery):
    choice = callback.data.split("_")[1]
    await process_rps_logic(callback, choice)


@dp.message(F.text & F.text.regexp(REGEX_MAGIC_BALL))
async def cmd_magic_ball(message: types.Message):
    if await check_action_cooldown(message, "iris_cmd"):
        return
    match = REGEX_MAGIC_BALL.search(message.text)
    if not match:
        return await temp_reply(message, "❌ Формат: /шар [вопрос] или ball [question]")
    question = match.group(1).strip()
    answers = [
        "Бесспорно",
        "Предрешено",
        "Никаких сомнений",
        "Определённо да",
        "Можешь быть уверен в этом",
        "Мне кажется - да",
        "Вероятнее всего",
        "Хорошие перспективы",
        "Знаки говорят - да",
        "Да",
        "Пока не ясно, попробуй снова",
        "Спроси позже",
        "Лучше не рассказывать",
        "Сейчас нельзя предсказать",
        "Сконцентрируйся и спроси опять",
        "Даже не думай",
        "Мой ответ - нет",
        "По моим данным - нет",
        "Перспективы не очень хорошие",
        "Весьма сомнительно",
    ]
    await reply_and_forget(
        message,
        f"🎱 <b>Вопрос:</b> <i>{escape_html_text(question)}</i>\n<b>Ответ:</b> {random.choice(answers)}",
        ttl=TTL_GAME,
        parse_mode="HTML",
    )


@dp.message(F.text & F.text.regexp(REGEX_COMPATIBILITY))
async def cmd_compatibility(message: types.Message):
    if await check_action_cooldown(message, "iris_cmd"):
        return
    if not message.reply_to_message:
        return await temp_reply(message, "Ответьте на сообщение пользователя, чтобы узнать вашу совместимость!", delay=TTL_ERROR)

    user1 = message.from_user
    user2 = message.reply_to_message.from_user

    if user1.id == user2.id:
        return await reply_and_forget(message, "Совместимость с самим собой — 100% (но это грустно) 🥲", ttl=TTL_GAME)

    base = sum([ord(c) for c in str(min(user1.id, user2.id)) + str(max(user1.id, user2.id))])
    daily_seed = datetime.now().day
    random.seed(base + daily_seed)
    compat = random.randint(0, 100)
    random.seed()

    await reply_and_forget(
        message,
        f"💞 Совместимость <b>{escape_html_text(user1.first_name)}</b> и <b>{escape_html_text(user2.first_name)}</b> на сегодня — <b>{compat}%</b>",
        ttl=TTL_GAME,
        parse_mode="HTML",
    )


@dp.message(F.text & F.text.regexp(REGEX_ROULETTE))
async def cmd_roulette(message: types.Message):
    if await check_action_cooldown(message, "roulette"):
        return
    chance = random.randint(1, 6)
    if chance == 1:
        await reply_and_forget(message, "💥 <b>БАХ!</b> Вы словили пулю. (Помянем 🕯)", ttl=TTL_HEAVY_GAME, parse_mode="HTML")
    else:
        await reply_and_forget(message, "🔫 <i>Щелк...</i> Вам повезло, барабан был пуст.", ttl=TTL_GAME, parse_mode="HTML")


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
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton(text="◀️ Пред.", callback_data=f"page_manga_{lang}_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(types.InlineKeyboardButton(text="След. ▶️", callback_data=f"page_manga_{lang}_{page+1}"))
    if nav_buttons:
        builder.row(*nav_buttons)

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
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton(text="◀️ Пред.", callback_data=f"page_ranobe_{lang}_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(types.InlineKeyboardButton(text="След. ▶️", callback_data=f"page_ranobe_{lang}_{page+1}"))
    if nav_buttons:
        builder.row(*nav_buttons)

    # Кнопка перехода на страницу
    builder.row(types.InlineKeyboardButton(text="🔢 На страницу", callback_data=f"jump_ranobe_{lang}"))

    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="read_ranobe_langs"))
    return builder.as_markup()


@dp.callback_query(F.data == "read_langs")
async def process_read_langs(callback: types.CallbackQuery):
    try:
        await callback.message.edit_text(
            "🌐 <b>Каталог Манги</b>\nВыберите раздел для чтения:", parse_mode="HTML", reply_markup=get_langs_menu("readlang")
        )
    except Exception:
        try:
            await callback.message.delete()
        except Exception as e:
            logging.debug(f"read_langs: failed to delete stale message: {e}")
        await callback.message.answer(
            "🌐 <b>Каталог Манги</b>\nВыберите раздел для чтения:", parse_mode="HTML", reply_markup=get_langs_menu("readlang")
        )


@dp.callback_query(F.data.startswith("readlang_"))
async def process_read_chapters(callback: types.CallbackQuery):
    lang_code = callback.data.split("_")[1]
    chapters = await get_chapters(lang_code)
    await callback.message.edit_text(
        f"📚 Доступные главы ({LANGUAGES[lang_code]}):", reply_markup=get_chapters_menu(lang_code, chapters, page=0)
    )


@dp.callback_query(F.data == "read_ranobe_langs")
async def process_read_ranobe_langs(callback: types.CallbackQuery):
    try:
        await callback.message.edit_text(
            "📖 <b>Каталог Ранобэ</b>\nВыберите тайтл или язык для чтения:",
            parse_mode="HTML",
            reply_markup=get_ranobe_langs_menu("readranobelang"),
        )
    except Exception:
        try:
            await callback.message.delete()
        except Exception as e:
            logging.debug(f"read_ranobe_langs: failed to delete stale message: {e}")
        await callback.message.answer(
            "📖 <b>Каталог Ранобэ</b>\nВыберите тайтл или язык для чтения:",
            parse_mode="HTML",
            reply_markup=get_ranobe_langs_menu("readranobelang"),
        )


@dp.callback_query(F.data.startswith("readranobelang_"))
async def process_read_ranobe_chapters(callback: types.CallbackQuery):
    lang_code = callback.data.split("_")[1]
    chapters = await get_ranobe_chapters(lang_code)
    await callback.message.edit_text(
        f"📚 Доступные главы ({RANOBE_LANGUAGES[lang_code]}):", reply_markup=get_ranobe_chapters_menu(lang_code, chapters, page=0)
    )


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
    if await check_cd_and_warn(callback, "read", 5):
        return

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
            msg_text = f"✅ Глава {chapter_num}\n\n📝 <b>Текст:</b>\n{escape_html_text(link)}"

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

    async with aiosqlite.connect(DB_PATH) as db:
        if is_ranobe:
            cursor = await db.execute('DELETE FROM ranobe_urls WHERE chapter_number = ? AND lang = ?', (chapter_num, lang))
        else:
            cursor = await db.execute('DELETE FROM chapters_urls WHERE chapter_number = ? AND lang = ?', (chapter_num, lang))
        await db.commit()
        deleted = cursor.rowcount > 0

    if deleted:
        await sync_reader_snapshot(f"delete chapter via tg: {'ranobe' if is_ranobe else 'manga'}_{lang}_{chapter_num}")
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
        return await callback.message.edit_text(
            "📖 <b>Хроники Акаши</b>\nНет добавленных томов:", reply_markup=builder.as_markup(), parse_mode="HTML"
        )
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
    await callback.message.edit_text(
        f"📖 <b>Хроники Акаши</b> — Том {callback_data.volume}\nВыберите главу:", reply_markup=builder.as_markup(), parse_mode="HTML"
    )


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
            msg_text += f"\n\n📝 <b>Текст:</b>\n{escape_html_text(url)}"
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
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('DELETE FROM akashic_ranobe WHERE volume = ? AND chapter = ?', (volume, chapter))
        await db.commit()
        deleted = cursor.rowcount > 0
    if deleted:
        await sync_reader_snapshot(f"delete chapter via tg: akashic_{volume}_{chapter}")
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
        return await callback.message.edit_text(
            "👸 <b>Британская красавица</b>\nНет добавленных томов:", reply_markup=builder.as_markup(), parse_mode="HTML"
        )
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
    await callback.message.edit_text(
        f"👸 <b>Британская красавица</b> — Том {callback_data.volume}\nВыберите главу:", reply_markup=builder.as_markup(), parse_mode="HTML"
    )


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
            msg_text += f"\n\n📝 <b>Текст:</b>\n{escape_html_text(url)}"
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
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('DELETE FROM british_ranobe WHERE volume = ? AND chapter = ?', (volume, chapter))
        await db.commit()
        deleted = cursor.rowcount > 0
    if deleted:
        await sync_reader_snapshot(f"delete chapter via tg: british_{volume}_{chapter}")
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
    await message.answer("📚 Доступные главы:", reply_markup=get_chapters_menu(lang, chapters, page=page))


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
    await message.answer("📚 Доступные главы (Ранобэ):", reply_markup=get_ranobe_chapters_menu(lang, chapters, page=page))


# process_user_art_delete, send_user_art_item, view_arts, process_user_art_view,
# process_user_art_random, process_user_art_input, handle_art_number_input,
# process_user_art_grid, process_grid_page_input, handle_grid_page_input,
# process_grid_art_input, handle_grid_art_number_input → вынесены в
# services/art_view.py (Фаза 3 B.7). Зарегистрированы на art_view_router.


# ==============================================================================
# БЛОК 10: АДМИН-ПАНЕЛЬ
# ------------------------------------------------------------------------------
# Helpers ниже используются всеми callback'ами панели. Главное меню теперь
# собирается один раз через _build_admin_menu_kb() и показывает живые метрики
# через _fetch_admin_metrics(). Каждый callback проверяет права через
# _require_admin() чтобы незалогиненный юзер не мог дергать admin-кнопки по
# старому сообщению или переслаке.
# ==============================================================================

# MAIN_ADMIN_ID, _is_bot_admin, _require_admin → вынесены в services/admin_helpers.py
# (доступны через re-export на top-level этого файла).


# _fetch_admin_metrics, _build_admin_menu_kb, _build_admin_menu_text → вынесены
# в services/admin_builders.py (доступны через re-export на top-level этого файла).


# cmd_add_admin, cmd_delete_admin, cmd_admin, admin_menu_back,
# admin_menu_add_chapter, admin_menu_del_chapter, admin_menu_ai_settings
# → вынесены в services/admin_telegram.py (зарегистрированы на admin_router
# через декораторы при импорте на top-level; dp.include_router в main()).


# admin_menu_stats, admin_menu_admins, admin_menu_admins_remove,
# admin_menu_admins_add_prompt, admin_manage_new_id, admin_menu_settings,
# admin_toggle_sync, admin_toggle_cleanup → вынесены в services/admin_telegram.py.
# admin_menu_sync_webapp, admin_menu_commands → вынесены в services/admin_settings.py.
# _fake_admin_message → вынесен в services/admin_helpers.py.


# NOTE: json/os/re уже импортируются в БЛОК 1 наверху файла.
# Дубликаты импортов удалены (ранее были здесь перед build_reader_data).


async def build_reader_data() -> dict:
    # Пытаемся получить имя бота, чтобы WebApp мог генерировать правильные deeplink-и
    bot_username = "Alyamangapage_bot"
    try:
        me = await bot.get_me()
        bot_username = me.username
    except Exception as e:
        logging.debug(f"build_reader_data: failed to get bot username, using fallback: {e}")

    result = {"series": [], "bot_username": bot_username}

    async with aiosqlite.connect(DB_PATH) as db:
        # ПРЕДЗАГРУЗКА: Читаем все кастомные имена разом (решение N+1 Query)
        custom_names = {}
        async with db.execute('SELECT id, name FROM custom_names') as c:
            for row in await c.fetchall():
                custom_names[row[0]] = row[1]

        # ПРЕДЗАГРУЗКА: Читаем список админов для бейджей в WebApp
        async with db.execute('SELECT user_id FROM admins') as c:
            admin_ids = [str(row[0]) for row in await c.fetchall()]
        # Добавляем хардкод админов из конфига (на всякий случай)
        admin_ids.extend([str(aid) for aid in ADMIN_IDS])
        result["admin_ids"] = list(set(admin_ids))  # Уникальные ID

        async with db.execute('SELECT DISTINCT volume FROM akashic_ranobe ORDER BY volume') as cursor:
            ak_vols = [row[0] for row in await cursor.fetchall()]
        if ak_vols:
            custom_title = custom_names.get("series_akashic_records") or "Хроники Акаши"
            akashic = {
                "id": "akashic_records",
                "title": custom_title,
                "cover_url": custom_names.get("cover_akashic_records", ""),
                "volumes": [],
            }
            for vol in ak_vols:
                custom_vol = custom_names.get(f"vol_akashic_records_{vol}") or f"Том {vol}"
                async with db.execute(
                    'SELECT chapter, url FROM akashic_ranobe WHERE volume = ? ORDER BY sort_order, CAST(chapter AS REAL)', (vol,)
                ) as c:
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
            british = {
                "id": "british_belle",
                "title": custom_title,
                "cover_url": custom_names.get("cover_british_belle", ""),
                "volumes": [],
            }
            for vol in br_vols:
                custom_vol = custom_names.get(f"vol_british_belle_{vol}") or f"Том {vol}"
                async with db.execute(
                    'SELECT chapter, url FROM british_ranobe WHERE volume = ? ORDER BY sort_order, CAST(chapter AS REAL)', (vol,)
                ) as c:
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
            async with db.execute(
                'SELECT chapter_number, url FROM ranobe_urls WHERE lang = ? ORDER BY sort_order, CAST(chapter_number AS REAL)', (lang,)
            ) as c:
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
                result["series"].append(
                    {
                        "id": f"ranobe_{lang}",
                        "title": custom_title,
                        "cover_url": custom_names.get(f"cover_ranobe_{lang}", ""),
                        "volumes": [{"volume": 1, "custom_name": custom_vol, "chapters": chapters}],
                    }
                )

        async with db.execute('SELECT DISTINCT lang FROM chapters_urls') as cursor:
            langs_mg = [row[0] for row in await cursor.fetchall()]
        for lang in langs_mg:
            async with db.execute(
                'SELECT chapter_number, url FROM chapters_urls WHERE lang = ? ORDER BY sort_order, CAST(chapter_number AS REAL)', (lang,)
            ) as c:
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
                result["series"].append(
                    {
                        "id": f"manga_{lang}",
                        "title": custom_title,
                        "cover_url": custom_names.get(f"cover_manga_{lang}", ""),
                        "volumes": [{"volume": 1, "custom_name": custom_vol, "chapters": chapters}],
                    }
                )

    # ДОПОЛНИТЕЛЬНО: Инъекция глав без ссылок, но с кастомными именами
    # Это позволяет переименовывать главы, которых еще нет в БД ссылок.
    for key, name in custom_names.items():
        if not key.startswith("chap_"):
            continue
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
            target_vol["chapters"].append({"chapter": chap, "custom_name": name, "url": "", "urls": []})
            # Сортируем главы
            try:
                target_vol["chapters"].sort(key=lambda x: (float(x["chapter"]) if str(x["chapter"]).replace('.', '', 1).isdigit() else 0))
            except Exception as e:
                logging.debug(f"build_reader_data: chapter sort fallback for {s_id}/{vol}: {e}")

    return result


async def sync_reader_snapshot(commit_message: str) -> None:
    """Rebuild WebApp chapters snapshot and trigger background git sync."""
    try:
        result = await build_reader_data()
        with open("webapp/chapters_data.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        spawn_bg(run_git_sync(commit_message), name="run_git_sync:snapshot")
    except Exception as e:
        logging.error(f"Reader sync error: {e}")


# `invalidate_reader_cache` и `invalidate_chapter_content_cache` вынесены
# в services/reader_cache.py (импорт в начале файла).

# ETag утилиты вынесены в services/cache_utils.py (Фаза 3 микро-шаг).
from services.cache_utils import _compute_reader_etag, _if_none_match_matches, _normalize_etag  # noqa: E402,F401


async def get_cached_reader_data(force_refresh: bool = False) -> tuple[dict, str, bool]:
    now = time.time()
    cached_payload = _reader_data_cache["payload"]
    cache_age = now - float(_reader_data_cache["built_at"] or 0.0)
    if not force_refresh and cached_payload is not None and cache_age < READER_CACHE_TTL_SECONDS:
        return cached_payload, str(_reader_data_cache["etag"]), True

    async with _reader_cache_lock:
        now = time.time()
        cached_payload = _reader_data_cache["payload"]
        cache_age = now - float(_reader_data_cache["built_at"] or 0.0)
        if not force_refresh and cached_payload is not None and cache_age < READER_CACHE_TTL_SECONDS:
            return cached_payload, str(_reader_data_cache["etag"]), True

        fresh_payload = await build_reader_data()
        fresh_etag = _compute_reader_etag(fresh_payload)
        _reader_data_cache["payload"] = fresh_payload
        _reader_data_cache["etag"] = fresh_etag
        _reader_data_cache["built_at"] = time.time()
        return fresh_payload, fresh_etag, False


# HTML-рендеринг вынесен в services/html_rendering.py (Фаза 3 шаг).
from services.html_rendering import (  # noqa: E402,F401
    _SafeHtmlFragmentParser,
    _extract_img_attrs_from_tag,
    _extract_teletype_article_fragment,
    _normalize_teletype_article_fragment,
    _render_telegraph_nodes_server,
    _sanitize_html_fragment,
)


# HTML-утилиты вынесены в services/html_utils.py (Фаза 3 микро-шаг).
from services.html_utils import (  # noqa: E402,F401
    _analyze_html_fragment,
    _html_fragment_has_visible_content,
    _is_low_value_html_fragment,
    _score_html_fragment,
)


# _build_chapter_content_cache_key вынесен в services/cache_utils.py.
from services.cache_utils import _build_chapter_content_cache_key  # noqa: E402,F401


# _extract_chapter_urls вынесен в services/validators.py (Фаза 3 микро-шаг).
from services.validators import _extract_chapter_urls  # noqa: E402,F401


# Reader chapter-content pipeline вынесен в services/reader_pipeline.py (Фаза 3 шаги 8 + 9).
from services.reader_pipeline import (  # noqa: E402,F401
    _build_chapter_content_payload,
    _fetch_telegra_ph_html,
    _fetch_teletype_html,
    _render_inline_chapter_html,
    _resolve_reader_chapter_entry,
    get_cached_chapter_content,
)


# invalidate_chapter_content_cache вынесена в services/reader_cache.py.


# cmd_toggle_sync, cmd_sync_webapp, cmd_alya_mode, cmd_blacklist_ai,
# cmd_unblacklist_ai, cmd_blacklist_view, cmd_set_commands_link,
# cmd_delete_commands_link → вынесены в services/admin_settings.py
# (зарегистрированы на settings_router; доступны через re-export на
# top-level этого файла).


# send_admin_art_item, cmd_arts_list, process_admin_art_view,
# process_admin_art_delete, process_admin_art_input, handle_admin_art_number_input,
# process_admin_art_grid, process_admin_art_view_back → вынесены в
# services/art_view.py (Фаза 3 B.7). Зарегистрированы на art_view_router.


# cmd_delete_art → вынесен в services/admin_content.py
# (доступен через re-export на top-level этого файла).


# cmd_toggle_ai → вынесен в services/admin_settings.py
# (доступен через re-export на top-level этого файла).


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
    except Exception as e:
        logging.debug(f"cancel_state: failed to delete message: {e}")
    await callback.answer("Действие отменено ❌", show_alert=True)


# cmd_add_chapter/ranobe/akashic/british, cmd_delete_chapter/ranobe/akashic/british,
# cmd_delete_art, uc_upload_*, uc_delete_*, process_notification_decision →
# вынесены в services/admin_content.py (зарегистрированы на content_router
# через декораторы при импорте на top-level; dp.include_router в main()).


# ----------------------------------------


# Art-handlers (cmd_add_art, process_art_photo, finish_art_upload, cmd_suggest_art,
# process_suggested_art, process_art_accept, process_art_reject) + ArtUpload/ArtSuggest FSM
# вынесены в services/admin_art_fsm.py (Фаза 3 шаг 20). Router подключается в main()
# через dp.include_router(art_router).


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
            if is_group and chat_id not in ACTIVE_DROPS and random.random() < 0.02:  # 2% шанс на сообщение
                reward = random.randint(50, 200)
                ACTIVE_DROPS[chat_id] = reward

                kb = InlineKeyboardBuilder()
                kb.button(text="🎁 Забрать монеты!", callback_data="claim_drop")

                drop_msg = await event.answer(
                    "💰 <b>ОЙ! В ЧАТЕ УПАЛ МЕШОК МОНЕТ!</b>\n" "Успей нажать на кнопку первым, чтобы забрать награду!",
                    parse_mode="HTML",
                    reply_markup=kb.as_markup(),
                )
                # Если за 60 сек никто не клейманул — удаляем сообщение и снимаем flag.
                schedule_delete_once(drop_msg, 60)

                async def _expire_drop(cid: int):
                    await asyncio.sleep(60)
                    if ACTIVE_DROPS.get(cid) is not None:
                        ACTIVE_DROPS.pop(cid, None)

                spawn_bg(_expire_drop(chat_id), name="chat_drop_expire")
            # ----------------------------------

            try:
                await upsert_user_profile(user_id, event.from_user.username, event.from_user.first_name)
                async with aiosqlite.connect(DB_PATH) as db:
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
                                await db.execute(
                                    'UPDATE users_stats SET messages_count = messages_count + 1, balance = balance + 1, xp = xp + 1 WHERE user_id = ?',
                                    (user_id,),
                                )
                                # --- Level-up System (Только для групп) ---
                                async with db.execute(
                                    'SELECT xp, level, messages_count, stickers_count FROM users_stats WHERE user_id = ?', (user_id,)
                                ) as cursor:
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
                                            await db.execute(
                                                'UPDATE users_stats SET level = ?, balance = balance + ? WHERE user_id = ?',
                                                (target_level, reward, user_id),
                                            )
                                            async with db.execute(
                                                'SELECT balance FROM users_stats WHERE user_id = ?', (user_id,)
                                            ) as b_cursor:
                                                new_balance = (await b_cursor.fetchone())[0]
                                            user_name = escape_html_text(event.from_user.first_name)
                                            # Компактный level-up: 1 строка + autodelete через 4 мин в группе.
                                            # Вариативность через LEVEL_UP_TEMPLATES — меньше повторений.
                                            template = random.choice(LEVEL_UP_TEMPLATES)
                                            lvl_msg = await event.answer(
                                                template.format(name=user_name, lvl=target_level, reward=reward),
                                                parse_mode="HTML",
                                            )
                                            schedule_delete_once(lvl_msg, TTL_LEVELUP)
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

# CORS-утилиты вынесены в services/webapp_cors.py (Фаза 3 шаг 1).
from services.webapp_cors import (
    CORS_ALLOWED_ORIGINS,
    CORS_BASE_HEADERS,
    CORS_HEADERS,
    _build_cors_headers,
    _extract_origin,
    _merge_vary_header,
    _origin_allowed,
    _resolve_allowed_origin,
)

# MAX_RENAME_CACHE_SIZE — не валидация, а размер LRU-кэша.
MAX_RENAME_CACHE_SIZE = 5000

# Rate-limiter вынесен в services/rate_limit.py (Фаза 3 шаг 2).
from services.rate_limit import _enforce_rate_limit  # noqa: E402

# Валидаторы и константы лимитов вынесены в services/validators.py (Фаза 3 шаги 3 + 13).
from services.validators import (  # noqa: E402
    MAX_AUDIT_PAYLOAD_LENGTH,
    MAX_BULK_URLS_PER_REQUEST,
    MAX_CHAPTER_EDIT_RAW_TEXT_LENGTH,
    MAX_CHAPTER_ID_LENGTH,
    MAX_CHAPTER_KEY_LENGTH,
    MAX_COMMENT_REPORT_TEXT_LENGTH,
    MAX_COMMENT_TEXT_LENGTH,
    MAX_RENAME_OBJECT_ID_LENGTH,
    MAX_REPORT_REASON_LENGTH,
    MAX_SERIES_ID_LENGTH,
    MAX_TYPO_COMMENT_LENGTH,
    MAX_TYPO_CONTEXT_TEXT_LENGTH,
    MAX_TYPO_SELECTED_TEXT_LENGTH,
    _clean_urls,
    _is_valid_chapter_token,
    _is_valid_series_id,
    _normalize_external_url,
    _safe_json_dumps,
)

# WebApp middleware вынесен в services/webapp_middleware.py (Фаза 3 шаг 4).
from services.webapp_middleware import (  # noqa: E402
    API_MAX_BODY_BYTES,
    api_security_middleware,
    apply_webapp_response_headers,
)

# Admin audit + generic API error response (Фаза 3 шаг 11).
from services.admin_audit import (  # noqa: E402,F401
    MAX_API_ERROR_TEXT,
    _api_error_response,
    _audit_admin_action,
)

# Telemetry-утилиты (чистые) вынесены в services/telemetry_utils.py (Фаза 3 микро-шаг).
from services.telemetry_utils import (  # noqa: E402,F401
    MAX_TELEMETRY_METRIC_MS,
    _clip_telemetry_text,
    _sanitize_client_chapter_open_payload,
    _to_finite_float,
)

# Telemetry-I/O (БД-запись, sampling, sync с auth) вынесены в services/telemetry.py (Фаза 3 шаг 11).
from services.telemetry import (  # noqa: E402,F401
    MAX_TELEMETRY_PAYLOAD_JSON_LENGTH,
    SERVER_READER_TELEMETRY_EVENT,
    SERVER_READER_TELEMETRY_SAMPLE_RATE,
    WEBAPP_TELEMETRY_EVENTS,
    _insert_webapp_telemetry_event,
    _record_server_reader_metric,
    _serialize_telemetry_payload,
)

# Telegram WebApp auth вынесен в services/auth.py (Фаза 3 шаг 11).
from services.auth import get_auth_user  # noqa: E402,F401


# --- ИИ-чат (серверный прокси для WebApp) ---
# Handler вынесен в services/ai_chat_api.py (Фаза 3 шаг 16).
from services.ai_chat_api import handle_ai_chat  # noqa: E402,F401


# handle_telemetry_post вынесен в services/telemetry_api.py (Фаза 3 шаг 12).
from services.telemetry_api import handle_telemetry_post  # noqa: E402,F401


# Reader API handlers вынесены в services/reader_api.py (Фаза 3 шаг 10).
from services.reader_api import handle_chapter_content, handle_reader_data  # noqa: E402,F401


# Admin chapter API handlers + _get_table_info вынесены в services/admin_chapter_api.py (Фаза 3 шаг 13).
from services.admin_chapter_api import (  # noqa: E402,F401
    _get_table_info,
    handle_chapter_add,
    handle_chapter_bulk,
    handle_chapter_delete,
    handle_chapter_edit,
    handle_rename_delete,
    handle_series_update,
)

# Comments API handlers вынесены в services/comments_api.py (Фаза 3 шаг 14).
from services.comments_api import (  # noqa: E402,F401
    handle_comment_react_post,
    handle_comments_delete,
    handle_comments_get,
    handle_comments_post,
    handle_comments_update,
)


# _api_error_response вынесен в services/admin_audit.py (Фаза 3 шаг 11).


async def handle_cors_preflight(request: aiohttp.web.Request) -> aiohttp.web.Response:
    origin = request.headers.get("Origin", "").strip()
    if origin and not _resolve_allowed_origin(request):
        return aiohttp.web.json_response(
            {"error": "origin_not_allowed"},
            status=403,
            headers=_build_cors_headers(request),
        )
    headers = _build_cors_headers(request)
    return aiohttp.web.Response(status=204, headers=headers)


# --- Лайки ---
# Handlers вынесены в services/likes_api.py (Фаза 3 шаг 12).
from services.likes_api import handle_likes_get, handle_likes_post  # noqa: E402,F401


# --- Комментарии ---
# Handlers вынесены в services/comments_api.py (Фаза 3 шаг 14, импорты выше).


# --- Репорты об опечатках ---
# handle_typo_post вынесен в services/typo_api.py (Фаза 3 шаг 15).
from services.typo_api import handle_typo_post  # noqa: E402,F401


# cmd_test_notification → вынесен в services/admin_settings.py
# (доступен через re-export на top-level этого файла).
# Вызывается только через admin_menu_commands dispatcher (нет @dp.message).


# handle_typo_post вынесен в services/typo_api.py (импорт выше).
# handle_comments_report вынесен в services/comments_api.py (Фаза 3 шаг 17).
from services.comments_api import handle_comments_report  # noqa: E402,F401


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
        async with aiosqlite.connect(DB_PATH) as db:
            # Общее количество по каждой реакции
            async with db.execute(
                'SELECT reaction, COUNT(*) as count FROM chapter_reactions WHERE chapter_key = ? GROUP BY reaction', (chapter_key,)
            ) as c:
                rows = await c.fetchall()

            reactions_data = {r[0]: r[1] for r in rows}

            # Реакция текущего пользователя
            user_reaction = None
            if user_id:
                async with db.execute(
                    'SELECT reaction FROM chapter_reactions WHERE chapter_key = ? AND user_id = ?', (chapter_key, user_id)
                ) as c:
                    row = await c.fetchone()
                    if row:
                        user_reaction = row[0]

        return aiohttp.web.json_response({"reactions": reactions_data, "user_reaction": user_reaction}, headers=CORS_HEADERS)
    except Exception as e:
        return _api_error_response(e, context=request.path)


async def handle_reactions_post(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Поставить/изменить реакцию."""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        limited = await _enforce_rate_limit(request, "reactions_post", user_id=user_id)
        if limited:
            return limited

        data = await request.json()
        chapter_key = str(data.get('chapter_key', '')).strip()
        reaction = str(data.get('reaction', '')).strip()  # Например: "👍", "❤️", "🔥"

        if not chapter_key or not reaction:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)
        if len(chapter_key) > MAX_CHAPTER_KEY_LENGTH:
            return aiohttp.web.json_response({"error": "invalid chapter_key"}, status=400, headers=CORS_HEADERS)
        if len(reaction) > 16:
            return aiohttp.web.json_response({"error": "invalid reaction"}, status=400, headers=CORS_HEADERS)

        async with aiosqlite.connect(DB_PATH) as db:
            # Если такая же реакция уже стоит - убираем (toggle)
            async with db.execute(
                'SELECT reaction FROM chapter_reactions WHERE chapter_key = ? AND user_id = ?', (chapter_key, user_id)
            ) as c:
                existing = await c.fetchone()

            if existing and existing[0] == reaction:
                await db.execute('DELETE FROM chapter_reactions WHERE chapter_key = ? AND user_id = ?', (chapter_key, user_id))
            else:
                await db.execute(
                    'INSERT OR REPLACE INTO chapter_reactions (chapter_key, user_id, reaction) VALUES (?, ?, ?)',
                    (chapter_key, user_id, reaction),
                )
            await db.commit()

        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:
        return _api_error_response(e, context=request.path)


async def handle_rename_request(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Кэширует длинные ID глав и выдает короткий ID (обход лимита 64 символов в deeplink)."""
    user_id = ""
    user = get_auth_user(request)
    if not user:
        return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
    user_id = str(user.get("id", ""))
    limited = await _enforce_rate_limit(request, "admin_rename_request", user_id=user_id)
    if limited:
        return limited
    try:
        data = await request.json()
        obj_id = str(data.get('obj_id', '')).strip()
        if not obj_id or len(obj_id) > MAX_RENAME_OBJECT_ID_LENGTH:
            return aiohttp.web.json_response({"error": "missing obj_id"}, status=400, headers=CORS_HEADERS)

        if len(RENAME_CACHE) >= MAX_RENAME_CACHE_SIZE:
            # Keep cache bounded and drop oldest key.
            oldest_key = next(iter(RENAME_CACHE.keys()), None)
            if oldest_key:
                RENAME_CACHE.pop(oldest_key, None)
        short_id = str(uuid.uuid4())[:8]
        RENAME_CACHE[short_id] = obj_id
        await _audit_admin_action(
            action="rename_request_cache",
            actor_user_id=user_id,
            target=obj_id,
            payload={"obj_id": obj_id, "short_id": short_id},
            result="ok",
        )
        return aiohttp.web.json_response({"ok": True, "short_id": short_id}, headers=CORS_HEADERS)
    except Exception as e:
        await _audit_admin_action(
            action="rename_request_cache",
            actor_user_id=user_id,
            payload={"path": request.path},
            result="error",
            error=str(e),
        )
        return aiohttp.web.json_response({"error": "internal"}, status=500, headers=CORS_HEADERS)


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

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                '''
                INSERT INTO user_bookmarks (user_id, series_id, volume_id, chapter_key, scroll_pos, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, series_id) DO UPDATE SET
                    volume_id = excluded.volume_id,
                    chapter_key = excluded.chapter_key,
                    scroll_pos = excluded.scroll_pos,
                    updated_at = excluded.updated_at
            ''',
                (str(user_id), str(series_id), str(volume_id), str(chapter_key), float(scroll_pos)),
            )
            await db.commit()

        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:
        return _api_error_response(e, context=request.path)


async def handle_progress_get(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Получить все закладки пользователя."""
    user = get_auth_user(request)
    if not user:
        return aiohttp.web.json_response({"error": "Unauthorized", "bookmarks": []}, status=401, headers=CORS_HEADERS)
    user_id = str(user.get("id", ""))

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT series_id, volume_id, chapter_key, scroll_pos, updated_at FROM user_bookmarks WHERE user_id = ? ORDER BY updated_at DESC',
                (str(user_id),),
            ) as c:
                rows = await c.fetchall()

        bookmarks = [{"series_id": r[0], "volume_id": r[1], "chapter_key": r[2], "scroll_pos": r[3], "updated_at": r[4]} for r in rows]
        return aiohttp.web.json_response({"bookmarks": bookmarks}, headers=CORS_HEADERS)
    except Exception as e:
        return _api_error_response(e, context=request.path)


# --- Сортировка глав (Admin DnD) ---


async def handle_sort_chapters(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Сохранить порядок глав после перетаскивания (только для админов)."""
    user_id_str = ""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id_str = str(user.get("id", ""))
        limited = await _enforce_rate_limit(request, "admin_sort", user_id=user_id_str)
        if limited:
            return limited
        user_id = int(user.get("id", 0))

        admins = await get_admins()
        if user_id not in admins:
            return aiohttp.web.json_response({"error": "Forbidden"}, status=403, headers=CORS_HEADERS)

        data = await request.json()
        series_id = str(data.get('series_id', '')).strip()
        volume = data.get('volume', '')
        order = data.get('order', [])  # List of chapter identifiers in new order

        if not series_id or not order:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)
        if not _is_valid_series_id(series_id):
            return aiohttp.web.json_response({"error": "invalid series_id"}, status=400, headers=CORS_HEADERS)
        if not isinstance(order, list) or len(order) > MAX_BULK_URLS_PER_REQUEST:
            return aiohttp.web.json_response({"error": "invalid order"}, status=400, headers=CORS_HEADERS)
        normalized_order = []
        for chapter_id in order:
            token = str(chapter_id).strip()
            if not _is_valid_chapter_token(token):
                return aiohttp.web.json_response({"error": "invalid chapter in order"}, status=400, headers=CORS_HEADERS)
            normalized_order.append(token)

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

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                f'SELECT {chapter_col} FROM {table} WHERE {id_col} = ?',
                (str(idx_val),),
            ) as cur:
                existing_chapters = {str(row[0]) for row in await cur.fetchall()}
            existing_rows = len(existing_chapters)
            unmatched = [chapter_id for chapter_id in normalized_order if chapter_id not in existing_chapters]

            if unmatched:
                logging.warning(
                    "sort_chapters rejected: series=%s vol=%r table=%s id_col=%s idx_val=%r sent=%d existing=%d unmatched=%s",
                    series_id,
                    volume,
                    table,
                    id_col,
                    idx_val,
                    len(normalized_order),
                    existing_rows,
                    unmatched[:5],
                )
                await _audit_admin_action(
                    action="sort_chapters",
                    actor_user_id=user_id_str,
                    target=series_id,
                    payload={
                        "series_id": series_id,
                        "volume": volume,
                        "order_size": len(normalized_order),
                        "unmatched": unmatched[:20],
                    },
                    result="conflict",
                )
                return aiohttp.web.json_response(
                    {
                        "error": "Missing chapters in database",
                        "unmatched": unmatched[:20],
                        "debug": {
                            "table": table,
                            "id_col": id_col,
                            "idx_val": str(idx_val),
                            "sent": len(normalized_order),
                            "existing": existing_rows,
                        },
                    },
                    status=409,
                    headers=CORS_HEADERS,
                )

            total_changes = 0
            for idx, chapter_id in enumerate(normalized_order):
                cursor = await db.execute(
                    f'UPDATE {table} SET sort_order = ? WHERE {id_col} = ? AND {chapter_col} = ?', (idx, str(idx_val), str(chapter_id))
                )
                changed = cursor.rowcount or 0
                total_changes += changed
            if total_changes != len(normalized_order):
                await db.rollback()
                logging.warning(
                    "sort_chapters rollback: series=%s vol=%r table=%s id_col=%s idx_val=%r sent=%d existing=%d updated=%d",
                    series_id,
                    volume,
                    table,
                    id_col,
                    idx_val,
                    len(normalized_order),
                    existing_rows,
                    total_changes,
                )
                return aiohttp.web.json_response(
                    {
                        "error": "Sort update mismatch. No changes committed.",
                        "debug": {
                            "table": table,
                            "id_col": id_col,
                            "idx_val": str(idx_val),
                            "sent": len(normalized_order),
                            "existing": existing_rows,
                            "updated": total_changes,
                        },
                    },
                    status=409,
                    headers=CORS_HEADERS,
                )
            await db.commit()
        logging.info(
            "sort_chapters: series=%s vol=%r table=%s id_col=%s idx_val=%r sent=%d existing=%d updated=%d unmatched=%s",
            series_id,
            volume,
            table,
            id_col,
            idx_val,
            len(normalized_order),
            existing_rows,
            total_changes,
            [],
        )
        invalidate_reader_cache("chapters_sorted")

        # Обновляем JSON и синхронизируем с GitHub
        result, _, _ = await get_cached_reader_data(force_refresh=True)
        with open("webapp/chapters_data.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        spawn_bg(run_git_sync(f"chapters sorting updated for {series_id}"), name="run_git_sync:sort_chapters")
        await _audit_admin_action(
            action="sort_chapters",
            actor_user_id=user_id_str,
            target=series_id,
            payload={"series_id": series_id, "volume": volume, "order_size": len(normalized_order)},
            result="ok",
        )

        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:
        await _audit_admin_action(
            action="sort_chapters",
            actor_user_id=user_id_str,
            payload={"path": request.path},
            result="error",
            error=str(e),
        )
        return _api_error_response(e, context=request.path)


async def handle_root_redirect(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Перенаправляет с корня сайта сразу в читалку."""
    raise aiohttp.web.HTTPFound('/webapp/reader.html')


# ==============================================================================
# БЛОК: ЗАПУСК БОТА
# ==============================================================================


def create_webapp_api_app() -> aiohttp.web.Application:
    """Create aiohttp WebApp API app with routes, middleware, and static files."""
    app = aiohttp.web.Application(
        middlewares=[api_security_middleware],
        client_max_size=API_MAX_BODY_BYTES,
    )
    app.on_response_prepare.append(apply_webapp_response_headers)
    app.on_cleanup.append(close_webapp_resources)

    app.router.add_get("/api/reader", handle_reader_data)
    app.router.add_get("/api/chapter-content", handle_chapter_content)
    app.router.add_post("/api/telemetry", handle_telemetry_post)

    app.router.add_get("/", handle_root_redirect)
    app.router.add_options("/api/reader", handle_cors_preflight)
    app.router.add_options("/api/chapter-content", handle_cors_preflight)
    app.router.add_options("/api/telemetry", handle_cors_preflight)

    app.router.add_get("/api/likes", handle_likes_get)
    app.router.add_post("/api/likes", handle_likes_post)
    app.router.add_options("/api/likes", handle_cors_preflight)

    app.router.add_get("/api/comments", handle_comments_get)
    app.router.add_post("/api/comments", handle_comments_post)
    app.router.add_post("/api/comments/react", handle_comment_react_post)
    app.router.add_options("/api/comments/react", handle_cors_preflight)
    app.router.add_options("/api/comments", handle_cors_preflight)
    app.router.add_route("DELETE", "/api/comments", handle_comments_delete)
    # Edit own comment: PUT /api/comments/{id}
    app.router.add_route("PUT", "/api/comments/{id}", handle_comments_update)
    app.router.add_options("/api/comments/{id}", handle_cors_preflight)
    app.router.add_post("/api/comments/report", handle_comments_report)
    app.router.add_options("/api/comments/report", handle_cors_preflight)

    app.router.add_get("/api/avatar", handle_avatar_get)
    app.router.add_options("/api/avatar", handle_cors_preflight)

    app.router.add_get("/api/reactions", handle_reactions_get)
    app.router.add_post("/api/reactions", handle_reactions_post)
    app.router.add_options("/api/reactions", handle_cors_preflight)

    app.router.add_route("DELETE", "/api/rename", handle_rename_delete)
    app.router.add_options("/api/rename", handle_cors_preflight)

    app.router.add_get("/api/progress", handle_progress_get)
    app.router.add_post("/api/progress", handle_progress_post)
    app.router.add_options("/api/progress", handle_cors_preflight)

    app.router.add_post("/api/typo", handle_typo_post)
    app.router.add_options("/api/typo", handle_cors_preflight)

    app.router.add_post("/api/rename/request", handle_rename_request)
    app.router.add_options("/api/rename/request", handle_cors_preflight)

    app.router.add_route("PUT", "/api/sort", handle_sort_chapters)
    app.router.add_options("/api/sort", handle_cors_preflight)

    app.router.add_post("/api/ai_chat", handle_ai_chat)
    app.router.add_options("/api/ai_chat", handle_cors_preflight)

    app.router.add_route("PUT", "/api/chapters", handle_chapter_edit)
    app.router.add_route("POST", "/api/chapters", handle_chapter_add)
    app.router.add_route("DELETE", "/api/chapters", handle_chapter_delete)
    app.router.add_options("/api/chapters", handle_cors_preflight)

    app.router.add_post("/api/chapters/bulk", handle_chapter_bulk)
    app.router.add_options("/api/chapters/bulk", handle_cors_preflight)

    app.router.add_route("PUT", "/api/series", handle_series_update)
    app.router.add_options("/api/series", handle_cors_preflight)

    try:
        app.router.add_static('/webapp', 'webapp', show_index=True)
        logging.info("Static route /webapp registered.")
    except Exception as e:
        logging.warning(f"Failed to register /webapp: {e}")

    return app


async def start_webapp_api_server(host: str = "0.0.0.0", port: int = 8080) -> aiohttp.web.AppRunner:
    """Start WebApp API server and return runner for cleanup."""
    app = create_webapp_api_app()
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, host, int(port))
    await site.start()
    logging.info("WebApp API server started on %s:%s", host, port)
    return runner


async def close_webapp_resources(_app: aiohttp.web.Application) -> None:
    """Close shared HTTP sessions used by API and bot runtime."""
    global _http_session
    if _http_session and not _http_session.closed:
        await _http_session.close()

    session_obj = getattr(bot, "session", None)
    if session_obj is not None:
        try:
            await session_obj.close()
        except Exception:
            logging.exception("Failed to close bot session during cleanup")


# ============================================================================
# АВТООЧИСТКА ГРУПП: сервисные сообщения + админ-команды
# ----------------------------------------------------------------------------
# 1) `/cleanup_service on|off` (админ чата) — переключатель.
# 2) При включении бот (если сам админ) удаляет join/leave/pinned и др. сервисные.
# 3) `/clean N` (админ чата) — удалить последние N bot-ответов в этом чате
#    (скользит message_id назад от текущего сообщения команды).
# ============================================================================

CLEANUP_SERVICE_KEY_PREFIX = "cleanup_service:"


async def _is_chat_admin(chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("creator", "administrator")
    except Exception:
        return False


async def _bot_is_chat_admin(chat_id: int) -> bool:
    """True если САМ БОТ админ в данном чате (не путать с _is_bot_admin,
    который проверяет, является ли юзер админом бота).
    Раньше обе функции назывались _is_bot_admin — вторая перекрывала первую
    при импорте и ломала всю админ-панель (см. cmd_admin/_require_admin).
    """
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
        return member.status == "administrator"
    except Exception:
        return False


@dp.message(Command("cleanup_service"))
async def cmd_cleanup_service(message: types.Message):
    if message.chat.type not in ("group", "supergroup"):
        return await temp_reply(message, "Команда работает только в группах.", delay=TTL_ERROR)

    if not await _is_chat_admin(message.chat.id, message.from_user.id):
        return await temp_reply(message, "Только админы чата могут включать автоочистку.", delay=TTL_ERROR)

    parts = (message.text or "").split(maxsplit=1)
    arg = parts[1].strip().lower() if len(parts) > 1 else ""

    key = f"{CLEANUP_SERVICE_KEY_PREFIX}{message.chat.id}"
    current = (await get_setting(key)) or "off"

    if arg in ("on", "вкл"):
        if not await _bot_is_chat_admin(message.chat.id):
            return await temp_reply(
                message,
                "⚠️ Бот должен быть админом чата с правом удаления сообщений, чтобы чистить сервисные.",
                delay=TTL_ERROR,
            )
        await set_setting(key, "on")
        await reply_and_forget(message, "✅ Автоочистка сервисных сообщений включена.", ttl=TTL_MENU)
    elif arg in ("off", "выкл"):
        await set_setting(key, "off")
        await reply_and_forget(message, "⛔ Автоочистка сервисных сообщений выключена.", ttl=TTL_MENU)
    else:
        await reply_and_forget(
            message,
            f"Автоочистка сервисных: <b>{current}</b>\nИспользование: /cleanup_service on|off",
            ttl=TTL_MENU,
            parse_mode="HTML",
        )


_SERVICE_CONTENT_TYPES = {
    types.ContentType.NEW_CHAT_MEMBERS,
    types.ContentType.LEFT_CHAT_MEMBER,
    types.ContentType.PINNED_MESSAGE,
    types.ContentType.NEW_CHAT_TITLE,
    types.ContentType.NEW_CHAT_PHOTO,
    types.ContentType.DELETE_CHAT_PHOTO,
    types.ContentType.GROUP_CHAT_CREATED,
    types.ContentType.SUPERGROUP_CHAT_CREATED,
    types.ContentType.CHANNEL_CHAT_CREATED,
    types.ContentType.MIGRATE_TO_CHAT_ID,
    types.ContentType.MIGRATE_FROM_CHAT_ID,
    types.ContentType.VIDEO_CHAT_STARTED,
    types.ContentType.VIDEO_CHAT_ENDED,
    types.ContentType.VIDEO_CHAT_PARTICIPANTS_INVITED,
}


@dp.message(F.content_type.in_(_SERVICE_CONTENT_TYPES))
async def handle_service_message(message: types.Message):
    """Удаляет сервисные сообщения, если автоочистка включена и бот — админ."""
    if message.chat.type not in ("group", "supergroup"):
        return
    key = f"{CLEANUP_SERVICE_KEY_PREFIX}{message.chat.id}"
    state = await get_setting(key)
    if state != "on":
        return
    try:
        await message.delete()
    except Exception as e:
        logging.debug(f"handle_service_message: delete failed: {e}")


@dp.message(Command("clean"))
async def cmd_clean(message: types.Message):
    if message.chat.type not in ("group", "supergroup"):
        return await temp_reply(message, "Команда работает только в группах.", delay=TTL_ERROR)

    if not await _is_chat_admin(message.chat.id, message.from_user.id):
        return await temp_reply(message, "Только админы могут запускать /clean.", delay=TTL_ERROR)

    parts = (message.text or "").split()
    try:
        n = int(parts[1]) if len(parts) > 1 else 10
    except ValueError:
        return await temp_reply(message, "Формат: /clean N (1-100)", delay=TTL_ERROR)

    n = max(1, min(n, 100))
    chat_id = message.chat.id
    last_id = message.message_id

    # Удаляем саму команду сразу.
    try:
        await message.delete()
    except Exception:
        pass

    deleted = 0
    # Итерируем message_id назад от команды. Не все id бот удалит (только свои
    # сообщения + не старше 48h), но Telegram вернёт ошибку и мы её проглотим.
    for offset in range(1, n * 5 + 1):
        mid = last_id - offset
        if mid <= 0:
            break
        try:
            await bot.delete_message(chat_id, mid)
            deleted += 1
            if deleted >= n:
                break
        except Exception:
            continue

    # Краткий итог ephemeral — исчезает через TTL_ERROR.
    try:
        note = await bot.send_message(chat_id, f"🧹 Удалено: {deleted}")
        schedule_delete_once(note, TTL_ERROR)
    except Exception:
        pass


# ============================================================================
# МОДЕРАЦИЯ ГРУПП: /mute /unmute /ban /unban /kick
# ----------------------------------------------------------------------------
# Использование:
#   /mute [время] [причина]   — reply на сообщение или @username / id
#   /unmute                   — reply на сообщение
#   /ban [причина]            — reply
#   /unban <user_id>
#   /kick [причина]           — reply
#
# Форматы времени: 30s, 5m, 2h, 7d. Голое число = минуты. По умолчанию — 1 час.
# Права: админ чата ИЛИ глобальный админ бота (is_moderator).
# Бот должен быть админом группы с правом can_restrict_members.
# ============================================================================

MUTED_PERMISSIONS = types.ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
    can_change_info=False,
    can_invite_users=False,
    can_pin_messages=False,
)

UNMUTED_PERMISSIONS = types.ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_invite_users=True,
)


async def _resolve_mod_target(message: types.Message) -> tuple[int | None, str | None, str | None]:
    """Return (user_id, display_name, error_reason).

    Prefers reply_to_message.from_user. Fallback: numeric id as first argument.
    text_mention and @username resolution requires a DB lookup (get_user_profile_by_username).
    """
    # 1) Reply target
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        return u.id, (u.full_name or u.username or str(u.id)), None

    # 2) Numeric user_id as argument (when no reply available)
    parts = (message.text or "").split()
    if len(parts) >= 2 and parts[1].lstrip("-").isdigit():
        uid = int(parts[1])
        return uid, str(uid), None

    # 3) @username lookup
    for ent in message.entities or []:
        if ent.type == "mention":
            uname = message.text[ent.offset : ent.offset + ent.length].lstrip("@")
            profile = await get_user_profile_by_username(uname.lower())
            if profile:
                uid, uname_db, fname = profile
                return uid, (fname or uname_db or str(uid)), None
        elif ent.type == "text_mention" and ent.user:
            u = ent.user
            return u.id, (u.full_name or u.username or str(u.id)), None

    return None, None, "Ответьте на сообщение пользователя или укажите @username / user_id."


def _parse_mod_args(message: types.Message, *, expect_duration: bool) -> tuple[int | None, str]:
    """Extract optional duration + reason from the command tail.

    Returns (duration_seconds_or_None, reason_text).
    """
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) <= 1:
        return None, ""

    first = parts[1]
    # If first arg parses as duration → use it; otherwise treat as reason start.
    if expect_duration:
        dur = parse_duration(first)
        if dur is not None:
            reason = parts[2] if len(parts) > 2 else ""
            return dur, reason.strip()
    # Skip numeric user_id if it was passed as first arg (handled in _resolve_mod_target)
    if first.lstrip("-").isdigit():
        reason = parts[2] if len(parts) > 2 else ""
        return None, reason.strip()
    reason = " ".join(parts[1:]).strip()
    return None, reason


async def _guard_mod_command(message: types.Message) -> tuple[int, int, str] | None:
    """Common prelude for mod commands. Returns (chat_id, target_user_id, target_name)
    or None if any guard failed (reply already sent).
    """
    if message.chat.type not in ("group", "supergroup"):
        await temp_reply(message, "Команда работает только в группах.", delay=TTL_ERROR)
        return None

    chat_id = message.chat.id
    actor_id = message.from_user.id

    if not await is_moderator(bot, chat_id, actor_id):
        await temp_reply(message, "🚫 Нужны права админа чата или админа бота.", delay=TTL_ERROR)
        return None

    # Бот должен иметь can_restrict_members.
    try:
        me = await bot.get_me()
        my_member = await bot.get_chat_member(chat_id, me.id)
        can_restrict = bool(getattr(my_member, "can_restrict_members", False))
        if my_member.status != "administrator" or not can_restrict:
            await temp_reply(
                message,
                "⚠️ Бот должен быть админом чата с правом «Ограничение участников».",
                delay=TTL_ERROR,
            )
            return None
    except Exception as e:
        logging.debug(f"_guard_mod_command: get_chat_member(me) failed: {e}")

    target_id, target_name, err = await _resolve_mod_target(message)
    if err or target_id is None:
        await temp_reply(message, f"ℹ️ {err}", delay=TTL_ERROR)
        return None

    # Не трогаем админов чата и глобальных админов бота.
    try:
        if await is_moderator(bot, chat_id, target_id):
            await temp_reply(message, "🛡 Нельзя модерировать админа.", delay=TTL_ERROR)
            return None
    except Exception as e:
        logging.warning(f"_guard_mod_command: is_moderator check failed for target={target_id} chat={chat_id}: {e}")

    # Не трогаем самого бота.
    try:
        me = await bot.get_me()
        if target_id == me.id:
            await temp_reply(message, "🤖 Меня нельзя модерировать.", delay=TTL_ERROR)
            return None
    except Exception:
        pass

    return chat_id, target_id, target_name or str(target_id)


@dp.message(Command("mute"))
async def cmd_mute(message: types.Message):
    guard = await _guard_mod_command(message)
    if guard is None:
        return
    chat_id, target_id, target_name = guard

    duration, reason = _parse_mod_args(message, expect_duration=True)
    if duration is None:
        duration = 3600  # 1h default
    until = int(time.time()) + duration

    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_id,
            permissions=MUTED_PERMISSIONS,
            until_date=until,
        )
    except Exception as e:
        logging.warning(f"cmd_mute: restrict failed: {e}")
        await temp_reply(message, f"❌ Не удалось замьютить: {type(e).__name__}", delay=TTL_ERROR)
        return

    reason_part = f"\n<b>Причина:</b> {escape_html_text(reason)}" if reason else ""
    await reply_and_forget(
        message,
        f"🔇 <b>{escape_html_text(target_name)}</b> замьючен на <b>{humanize_duration(duration)}</b>.{reason_part}",
        ttl=TTL_MENU,
        parse_mode="HTML",
    )
    try:
        await write_admin_audit_log(
            action="group_mute",
            actor_user_id=str(message.from_user.id),
            target=str(target_id),
            payload_json=json.dumps({"chat_id": chat_id, "duration": duration, "reason": reason}, ensure_ascii=False),
            result="ok",
        )
    except Exception as e:
        logging.debug(f"cmd_mute: audit log failed: {e}")


@dp.message(Command("unmute"))
async def cmd_unmute(message: types.Message):
    guard = await _guard_mod_command(message)
    if guard is None:
        return
    chat_id, target_id, target_name = guard

    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_id,
            permissions=UNMUTED_PERMISSIONS,
        )
    except Exception as e:
        logging.warning(f"cmd_unmute: restrict failed: {e}")
        await temp_reply(message, f"❌ Не удалось снять мьют: {type(e).__name__}", delay=TTL_ERROR)
        return

    await reply_and_forget(
        message,
        f"🔊 <b>{escape_html_text(target_name)}</b> размьючен.",
        ttl=TTL_MENU,
        parse_mode="HTML",
    )
    try:
        await write_admin_audit_log(
            action="group_unmute",
            actor_user_id=str(message.from_user.id),
            target=str(target_id),
            payload_json=json.dumps({"chat_id": chat_id}, ensure_ascii=False),
            result="ok",
        )
    except Exception as e:
        logging.debug(f"cmd_unmute: audit log failed: {e}")


@dp.message(Command("ban"))
async def cmd_ban(message: types.Message):
    guard = await _guard_mod_command(message)
    if guard is None:
        return
    chat_id, target_id, target_name = guard

    _, reason = _parse_mod_args(message, expect_duration=False)

    try:
        await bot.ban_chat_member(chat_id=chat_id, user_id=target_id)
    except Exception as e:
        logging.warning(f"cmd_ban: ban failed: {e}")
        await temp_reply(message, f"❌ Не удалось забанить: {type(e).__name__}", delay=TTL_ERROR)
        return

    reason_part = f"\n<b>Причина:</b> {escape_html_text(reason)}" if reason else ""
    await reply_and_forget(
        message,
        f"⛔ <b>{escape_html_text(target_name)}</b> забанен.{reason_part}",
        ttl=TTL_MENU,
        parse_mode="HTML",
    )
    try:
        await write_admin_audit_log(
            action="group_ban",
            actor_user_id=str(message.from_user.id),
            target=str(target_id),
            payload_json=json.dumps({"chat_id": chat_id, "reason": reason}, ensure_ascii=False),
            result="ok",
        )
    except Exception as e:
        logging.debug(f"cmd_ban: audit log failed: {e}")


@dp.message(Command("unban"))
async def cmd_unban(message: types.Message):
    if message.chat.type not in ("group", "supergroup"):
        return await temp_reply(message, "Команда работает только в группах.", delay=TTL_ERROR)

    chat_id = message.chat.id
    actor_id = message.from_user.id
    if not await is_moderator(bot, chat_id, actor_id):
        return await temp_reply(message, "🚫 Нужны права админа чата или админа бота.", delay=TTL_ERROR)

    # /unban редко идёт по reply (пользователь не в чате). Нужен user_id.
    parts = (message.text or "").split()
    target_id: int | None = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    elif len(parts) >= 2 and parts[1].lstrip("-").isdigit():
        target_id = int(parts[1])

    if target_id is None:
        return await temp_reply(message, "Формат: /unban <user_id>", delay=TTL_ERROR)

    try:
        await bot.unban_chat_member(chat_id=chat_id, user_id=target_id, only_if_banned=True)
    except Exception as e:
        logging.warning(f"cmd_unban: unban failed: {e}")
        await temp_reply(message, f"❌ Не удалось разбанить: {type(e).__name__}", delay=TTL_ERROR)
        return

    await reply_and_forget(
        message,
        f"✅ Пользователь <code>{target_id}</code> разбанен.",
        ttl=TTL_MENU,
        parse_mode="HTML",
    )
    try:
        await write_admin_audit_log(
            action="group_unban",
            actor_user_id=str(actor_id),
            target=str(target_id),
            payload_json=json.dumps({"chat_id": chat_id}, ensure_ascii=False),
            result="ok",
        )
    except Exception as e:
        logging.debug(f"cmd_unban: audit log failed: {e}")


@dp.message(Command("kick"))
async def cmd_kick(message: types.Message):
    guard = await _guard_mod_command(message)
    if guard is None:
        return
    chat_id, target_id, target_name = guard

    _, reason = _parse_mod_args(message, expect_duration=False)

    # Kick = ban + immediate unban, so the user can rejoin by invite link.
    try:
        await bot.ban_chat_member(chat_id=chat_id, user_id=target_id)
        await bot.unban_chat_member(chat_id=chat_id, user_id=target_id, only_if_banned=True)
    except Exception as e:
        logging.warning(f"cmd_kick: kick failed: {e}")
        await temp_reply(message, f"❌ Не удалось кикнуть: {type(e).__name__}", delay=TTL_ERROR)
        return

    reason_part = f"\n<b>Причина:</b> {escape_html_text(reason)}" if reason else ""
    await reply_and_forget(
        message,
        f"👢 <b>{escape_html_text(target_name)}</b> кикнут.{reason_part}",
        ttl=TTL_MENU,
        parse_mode="HTML",
    )
    try:
        await write_admin_audit_log(
            action="group_kick",
            actor_user_id=str(message.from_user.id),
            target=str(target_id),
            payload_json=json.dumps({"chat_id": chat_id, "reason": reason}, ensure_ascii=False),
            result="ok",
        )
    except Exception as e:
        logging.debug(f"cmd_kick: audit log failed: {e}")


async def main():
    dp.include_router(rp_router)
    # art_router / admin_router регистрируются через декораторы при импорте
    # services/admin_art_fsm и services/admin_telegram (см. комментарий сразу после
    # `dp = Dispatcher()`). Attach к dp — только здесь, ОДИН раз за жизнь процесса.
    dp.include_router(art_router)
    dp.include_router(admin_router)
    dp.include_router(content_router)
    dp.include_router(rename_router)
    dp.include_router(settings_router)
    dp.include_router(art_view_router)
    await init_db()

    dp.message.outer_middleware(StatsMiddleware())

    # Register bot commands
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="help", description="Список всех команд"),
        BotCommand(command="profile", description="Твой профиль"),
        BotCommand(command="stats", description="Твоя статистика"),
        BotCommand(command="pay", description="Перевести монеты"),
        BotCommand(command="marry", description="Вступить в брак (реплай)"),
        BotCommand(command="divorce", description="Расторгнуть брак"),
        BotCommand(command="marriages", description="Топ пар"),
    ]
    await bot.set_my_commands(commands, BotCommandScopeDefault())

    # Configure WebApp button
    reader_url = build_webapp_url("reader.html")
    await bot.set_chat_menu_button(
        menu_button=types.MenuButtonWebApp(
            text="✨ Читалка",
            web_app=types.WebAppInfo(url=reader_url),
        )
    )

    runner = await start_webapp_api_server("0.0.0.0", 8080)

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
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен.")
