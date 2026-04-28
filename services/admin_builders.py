"""Builder'ы для admin-панели: метрики, клавиатуры, тексты секций.

Чистые async-функции без handler-декораторов. Используются:

- `bot.py` (через re-export) — пока cmd_admin / admin_menu_* handlers
  остаются в bot.py.
- Будущие `services/admin_telegram/*.py` — когда handler'ы будут вынесены
  (шаги B.3+), импорт top-level без риска re-import цикла.

Функции:

- `_fetch_admin_metrics()` — одним блоком собирает live-метрики из БД для
  главного admin-меню (users, chapters, marriages, total_balance, комменты
  за сутки). Если какая-то таблица отсутствует — graceful fallback 0.
- `_build_admin_menu_kb()` — главная клавиатура `/admin`.
- `_build_admin_menu_text()` — HTML-текст главного меню с метриками.
- `_build_admins_list_kb(admins_list)` — клавиатура секции "Админы" с
  per-user "➖ Удалить" кнопками. Главного админа не показываем.
- `_render_admins_section(callback)` — edit_text главного меню в секцию
  "👑 Администраторы" (с их профилями).
- `_build_settings_text_and_kb()` — секция "⚙ Настройки" (sync-lock,
  cleanup-toggle, режим Али).

Вынесено из `bot.py` как шаг Фазы 3 шаг B.2 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlencode

import aiosqlite
from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import API_HOST, WEBAPP_URL
from database import DB_PATH, get_admins, get_setting
from services.admin_helpers import MAIN_ADMIN_ID
from services.telegram_helpers import escape_html_text


async def _fetch_admin_metrics() -> dict:
    """Одним блоком собирает живые метрики для главного меню /admin.

    Все значения — int'ы, безопасные к JSON-сериализации. Если какая-то
    таблица отсутствует в БД (например, `akashic_ranobe`/`british_ranobe`
    на старых инсталляциях) — возвращаем 0 и логируем debug. Main-handler
    ловит любую общую ошибку и возвращает dict с нулями (graceful).
    """
    metrics: dict = {
        "users_total": 0,
        "users_active_24h": 0,
        "msgs_24h": 0,
        "cmt_24h": 0,
        "ch_manga": 0,
        "ch_ranobe": 0,
        "ch_akashic": 0,
        "ch_british": 0,
        "marriages": 0,
        "total_balance": 0,
    }
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT COUNT(*) FROM users_stats') as c:
                row = await c.fetchone()
                metrics["users_total"] = row[0] if row else 0
            # messages за 24ч через events (если есть), иначе из users_stats диффа
            async with db.execute('SELECT COALESCE(SUM(balance), 0) FROM users_stats') as c:
                row = await c.fetchone()
                metrics["total_balance"] = row[0] if row else 0
            async with db.execute('SELECT COUNT(*) FROM chapters_urls') as c:
                row = await c.fetchone()
                metrics["ch_manga"] = row[0] if row else 0
            async with db.execute('SELECT COUNT(*) FROM ranobe_urls') as c:
                row = await c.fetchone()
                metrics["ch_ranobe"] = row[0] if row else 0
            try:
                async with db.execute('SELECT COUNT(*) FROM akashic_ranobe') as c:
                    row = await c.fetchone()
                    metrics["ch_akashic"] = row[0] if row else 0
            except Exception:  # noqa: BLE001 — таблица может отсутствовать на старых БД.
                pass
            try:
                async with db.execute('SELECT COUNT(*) FROM british_ranobe') as c:
                    row = await c.fetchone()
                    metrics["ch_british"] = row[0] if row else 0
            except Exception:  # noqa: BLE001 — таблица может отсутствовать на старых БД.
                pass
            try:
                async with db.execute('SELECT COUNT(*) FROM marriages') as c:
                    row = await c.fetchone()
                    metrics["marriages"] = row[0] if row else 0
            except Exception:  # noqa: BLE001 — таблица может отсутствовать на старых БД.
                pass
            # Комментарии за сутки (если таблица comments есть)
            try:
                async with db.execute("SELECT COUNT(*) FROM comments WHERE created_at >= datetime('now', '-1 day')") as c:
                    row = await c.fetchone()
                    metrics["cmt_24h"] = row[0] if row else 0
            except Exception as e:  # noqa: BLE001 — таблица comments может отсутствовать.
                logging.debug(f"_fetch_admin_metrics: cmt_24h skipped: {e}")
    except Exception as e:  # noqa: BLE001 — общий fallback: метрики не критичны, показываем нули.
        logging.debug(f"_fetch_admin_metrics: {e}")
    return metrics


def _admin_webapp_url() -> str:
    base = f"{WEBAPP_URL.rstrip('/')}/webapp/admin.html"
    query_items: list[tuple[str, str]] = []
    if API_HOST:
        query_items.append(("api", API_HOST))
    cache_buster = str(os.getenv("WEBAPP_CACHE_BUSTER", "")).strip()
    if cache_buster:
        query_items.append(("rev", cache_buster))
    query = urlencode(query_items)
    return f"{base}?{query}" if query else base


def _build_admin_menu_kb() -> types.InlineKeyboardMarkup:
    """Главная клавиатура /admin. Единая точка сборки — меняется 1 раз."""
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="🌐 Открыть админку", web_app=types.WebAppInfo(url=_admin_webapp_url())))
    b.row(
        types.InlineKeyboardButton(text="➕ Добавить главу", callback_data="admin_add_chapter"),
        types.InlineKeyboardButton(text="🗑 Удалить главу", callback_data="admin_del_chapter"),
    )
    b.row(
        types.InlineKeyboardButton(text="🔄 Синхронизация WebApp", callback_data="admin_sync_webapp"),
    )
    b.row(
        types.InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
        types.InlineKeyboardButton(text="👑 Админы", callback_data="admin_admins"),
    )
    b.row(
        types.InlineKeyboardButton(text="🎁 Розыгрыши", callback_data="admin_giveaways"),
        types.InlineKeyboardButton(text="🎨 Арты", callback_data="admin_arts"),
    )
    b.row(
        types.InlineKeyboardButton(text="⚙ Настройки", callback_data="admin_settings"),
        types.InlineKeyboardButton(text="🤖 ИИ", callback_data="admin_ai_settings"),
    )
    b.row(
        types.InlineKeyboardButton(text="🔔 Тест уведомлений", callback_data="admin_cmd_test_notification"),
    )
    return b.as_markup()


async def _build_admin_menu_text() -> str:
    """Текст главного меню с живыми метриками."""
    m = await _fetch_admin_metrics()
    ch_total = m["ch_manga"] + m["ch_ranobe"] + m["ch_akashic"] + m["ch_british"]
    return (
        "👑 <b>Панель управления</b>\n"
        f"👥 <b>{m['users_total']}</b> юзеров · "
        f"📚 <b>{ch_total}</b> глав · "
        f"🗨 <b>{m['cmt_24h']}</b> комм/сутки\n"
        f"💍 браков: <b>{m['marriages']}</b> · "
        f"💰 в обороте: <b>{m['total_balance']}</b>\n\n"
        "<i>Выберите раздел:</i>"
    )


async def _build_admins_list_kb(admins_list: list[int]) -> types.InlineKeyboardMarkup:
    """Клавиатура с кнопками удаления + add + back. Главного админа не показываем."""
    b = InlineKeyboardBuilder()
    for uid in admins_list:
        # Главного админа не даём удалить
        if uid == MAIN_ADMIN_ID:
            continue
        b.row(
            types.InlineKeyboardButton(
                text=f"➖ Удалить {uid}",
                callback_data=f"admin_rm:{uid}",
            )
        )
    b.row(
        types.InlineKeyboardButton(text="➕ Добавить", callback_data="admin_add_new"),
        types.InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_admins"),
    )
    b.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu"))
    return b.as_markup()


async def _render_admins_section(callback: types.CallbackQuery):
    """Перерисовывает главное меню в секцию "👑 Администраторы" (edit_text).

    Читает профили (`username`, `first_name`) для каждого админа, чтобы
    показать human-readable список. Если профиль не найден — fallback
    `user#<id>`. Главный админ помечен `⭐`.
    """
    admins_list = sorted(await get_admins())
    lines = ["👑 <b>Администраторы</b>\n"]
    for idx, uid in enumerate(admins_list, 1):
        profile = None
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute('SELECT username, first_name FROM user_profiles WHERE user_id = ?', (uid,)) as c:
                    profile = await c.fetchone()
        except Exception as e:  # noqa: BLE001 — профиль может отсутствовать, используем fallback.
            logging.debug(f"_render_admins_section: profile lookup failed for uid={uid}: {e}")
        if profile:
            uname, fname = profile
            display = escape_html_text(fname or uname or f"user#{uid}")
            at = f" (@{escape_html_text(uname)})" if uname else ""
        else:
            display, at = f"user#{uid}", ""
        star = " ⭐ главный" if uid == MAIN_ADMIN_ID else ""
        lines.append(f"{idx}. <code>{uid}</code> — <b>{display}</b>{at}{star}")
    text = "\n".join(lines)
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=await _build_admins_list_kb(admins_list),
    )


async def _build_settings_text_and_kb() -> tuple[str, types.InlineKeyboardMarkup]:
    """Секция "⚙ Настройки": sync-lock, cleanup-toggle, режим Али."""
    # Читаем актуальные значения тогглов из settings таблицы.
    sync_locked = False
    cleanup_on = False
    alya_mode = "normal"
    try:
        v = await get_setting("sync_locked")
        sync_locked = str(v or "0") == "1"
    except Exception as e:  # noqa: BLE001 — setting может отсутствовать, дефолт = False.
        logging.debug(f"_build_settings_text_and_kb: sync_locked read failed: {e}")
    try:
        v = await get_setting("cleanup_service")
        cleanup_on = str(v or "0") == "1"
    except Exception as e:  # noqa: BLE001 — setting может отсутствовать, дефолт = False.
        logging.debug(f"_build_settings_text_and_kb: cleanup_service read failed: {e}")
    try:
        v = await get_setting("alya_mode")
        if v:
            alya_mode = str(v)
    except Exception as e:  # noqa: BLE001 — setting может отсутствовать, дефолт = 'normal'.
        logging.debug(f"_build_settings_text_and_kb: alya_mode read failed: {e}")

    text = (
        "⚙ <b>Системные настройки</b>\n\n"
        f"🔒 Sync WebApp: <b>{'🔴 ЗАБЛОКИРОВАНА' if sync_locked else '🟢 активна'}</b>\n"
        f"🧹 Cleanup service-сообщений: <b>{'🟢 ВКЛ' if cleanup_on else '🔴 ВЫКЛ'}</b>\n"
        f"🧠 Режим Али: <b>{alya_mode}</b>\n"
    )
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(
            text=("🔓 Разблок. sync" if sync_locked else "🔒 Заблок. sync"),
            callback_data="admin_toggle_sync",
        ),
    )
    b.row(
        types.InlineKeyboardButton(
            text=("🧹 Cleanup: ВЫКЛ" if cleanup_on else "🧹 Cleanup: ВКЛ"),
            callback_data="admin_toggle_cleanup",
        ),
    )
    b.row(
        types.InlineKeyboardButton(text="🧠 Сменить режим Али", callback_data="admin_cmd_alya_mode"),
    )
    b.row(
        types.InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_settings"),
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu"),
    )
    return text, b.as_markup()
