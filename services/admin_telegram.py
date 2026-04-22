"""Admin-панель: Router + handlers главного меню и управления админами.

Вынесено из `bot.py` как шаги Фазы 3 B.3 (главное меню) и B.4 (management).

Экспортирует:

- `admin_router` — нужно подключить через `dp.include_router(admin_router)`
  в `main()` bot.py. Side-effect импорта регистрирует handler'ы.
- `AdminManage` — FSM для добавления админа через inline-кнопку.
- `cmd_admin` — re-export для admin_menu_commands dispatcher'а в bot.py.

Handler'ы этого модуля:

Главное меню `/admin` (B.3):
- `cmd_admin` — команда `/admin`, очищает state и открывает главное меню.
- `admin_menu_back` (`admin_menu`) — вернуться в главное меню.
- `admin_menu_add_chapter` (`admin_add_chapter`) — подменю "что добавить?".
- `admin_menu_del_chapter` (`admin_del_chapter`) — подменю "что удалить?".
- `admin_menu_ai_settings` (`admin_ai_settings`) — подменю настроек ИИ.
- `admin_menu_stats` (`admin_stats`) — секция 📊 Статистика.
- `admin_menu_settings` (`admin_settings`) — секция ⚙ Настройки.
- `admin_toggle_sync` (`admin_toggle_sync`) — тоггл sync-lock.
- `admin_toggle_cleanup` (`admin_toggle_cleanup`) — тоггл cleanup-service.

Management админов (B.4):
- `cmd_add_admin` — `/add_admin <id>`.
- `cmd_delete_admin` — `/delete_admin <id>` (с защитой главного админа).
- `admin_menu_admins` (`admin_admins`) — секция 👑 Администраторы.
- `admin_menu_admins_remove` (`admin_rm:<id>`) — удалить админа из списка.
- `admin_menu_admins_add_prompt` (`admin_add_new`) — запустить FSM для ввода id.
- `admin_manage_new_id` (FSM-шаг) — получить id нового админа.

Оставлено в bot.py (до следующих шагов):
- `admin_menu_sync_webapp` — вызывает `cmd_sync_webapp` (settings, ещё в bot.py).
- `admin_menu_commands` (`admin_cmd_*` dispatcher) — диспетчит в cmd_* из
  bot.py (content FSM ещё не вынесен).
"""

from __future__ import annotations

import logging

from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import add_admin, get_setting, remove_admin, set_setting
from services.admin_builders import (
    _build_admin_menu_kb,
    _build_admin_menu_text,
    _build_settings_text_and_kb,
    _fetch_admin_metrics,
    _render_admins_section,
)
from services.admin_helpers import MAIN_ADMIN_ID, _is_bot_admin, _require_admin


class AdminManage(StatesGroup):
    """FSM для управления админами из `/admin`-панели.

    Единственное состояние — `waiting_for_new_admin_id`: активируется
    нажатием `➕ Добавить` в секции админов и ожидает числовой user_id
    одним сообщением.
    """

    waiting_for_new_admin_id = State()


admin_router = Router()


# ===========================================================================
# B.3 — Главное меню /admin
# ===========================================================================


@admin_router.message(Command("admin"), StateFilter("*"))
async def cmd_admin(message: types.Message, state: FSMContext):
    """`/admin` — открыть главное меню администратора.

    `StateFilter("*")` + `state.clear()` гарантируют, что команда всегда
    выбивает юзера из любого висящего FSM-диалога (иначе state-handler
    мог бы перехватить команду раньше).
    """
    await state.clear()
    if not await _is_bot_admin(message.from_user.id):
        return
    try:
        await message.answer(
            await _build_admin_menu_text(),
            parse_mode="HTML",
            reply_markup=_build_admin_menu_kb(),
        )
    except Exception as e:  # noqa: BLE001 — Telegram может отказать (rate limit, forbidden).
        logging.exception(f"cmd_admin: answer failed: {e}")


@admin_router.callback_query(F.data == "admin_menu")
async def admin_menu_back(callback: types.CallbackQuery):
    """Вернуться в главное меню (`⬅️ Назад` из любой секции)."""
    if not await _require_admin(callback):
        return
    await callback.message.edit_text(
        await _build_admin_menu_text(),
        parse_mode="HTML",
        reply_markup=_build_admin_menu_kb(),
    )
    await callback.answer()


@admin_router.callback_query(F.data == "admin_add_chapter")
async def admin_menu_add_chapter(callback: types.CallbackQuery):
    """Подменю "➕ Что добавить?"."""
    if not await _require_admin(callback):
        return
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="Манга", callback_data="admin_cmd_add_chapter"),
        types.InlineKeyboardButton(text="Ранобэ", callback_data="admin_cmd_add_ranobe"),
    )
    builder.row(
        types.InlineKeyboardButton(text="Хроники Акаши", callback_data="admin_cmd_add_akashic"),
        types.InlineKeyboardButton(text="Брит. красавица", callback_data="admin_cmd_add_british"),
    )
    builder.row(types.InlineKeyboardButton(text="Арт", callback_data="admin_cmd_add_art"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu"))
    await callback.message.edit_text("➕ <b>Что добавить?</b>", parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()


@admin_router.callback_query(F.data == "admin_del_chapter")
async def admin_menu_del_chapter(callback: types.CallbackQuery):
    """Подменю "🗑 Что удалить?"."""
    if not await _require_admin(callback):
        return
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="Манга", callback_data="admin_cmd_delete_chapter"),
        types.InlineKeyboardButton(text="Ранобэ", callback_data="admin_cmd_delete_ranobe"),
    )
    builder.row(
        types.InlineKeyboardButton(text="Хроники Акаши", callback_data="admin_cmd_delete_akashic"),
        types.InlineKeyboardButton(text="Брит. красавица", callback_data="admin_cmd_delete_british"),
    )
    builder.row(types.InlineKeyboardButton(text="Арт", callback_data="admin_cmd_delete_art"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu"))
    await callback.message.edit_text("🗑 <b>Что удалить?</b>", parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()


@admin_router.callback_query(F.data == "admin_ai_settings")
async def admin_menu_ai_settings(callback: types.CallbackQuery):
    """Подменю "🤖 Настройки ИИ"."""
    if not await _require_admin(callback):
        return
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="Вкл/выкл ИИ", callback_data="admin_cmd_toggle_ai"),
        types.InlineKeyboardButton(text="Режим Али", callback_data="admin_cmd_alya_mode"),
    )
    builder.row(
        types.InlineKeyboardButton(text="ЧС (ИИ)", callback_data="admin_cmd_blacklist_ai"),
        types.InlineKeyboardButton(text="Удалить из ЧС", callback_data="admin_cmd_unblacklist_ai"),
    )
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu"))
    await callback.message.edit_text("🤖 <b>Настройки ИИ:</b>", parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()


@admin_router.callback_query(F.data == "admin_stats")
async def admin_menu_stats(callback: types.CallbackQuery):
    """Секция "📊 Статистика" — детализированные метрики."""
    if not await _require_admin(callback):
        return
    m = await _fetch_admin_metrics()
    text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Пользователи: <b>{m['users_total']}</b>\n"
        f"💰 В обороте: <b>{m['total_balance']}</b>\n\n"
        f"📚 <b>Главы</b>\n"
        f"├ Манга: <b>{m['ch_manga']}</b>\n"
        f"├ Ранобэ: <b>{m['ch_ranobe']}</b>\n"
        f"├ Хроники Акаши: <b>{m['ch_akashic']}</b>\n"
        f"└ Брит. красавица: <b>{m['ch_british']}</b>\n\n"
        f"🗨 Комментариев за сутки: <b>{m['cmt_24h']}</b>\n"
        f"💍 Активных браков: <b>{m['marriages']}</b>"
    )
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_stats"))
    b.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu"))
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=b.as_markup())
    await callback.answer()


@admin_router.callback_query(F.data == "admin_settings")
async def admin_menu_settings(callback: types.CallbackQuery):
    """Секция "⚙ Настройки" — системные тогглы."""
    if not await _require_admin(callback):
        return
    text, kb = await _build_settings_text_and_kb()
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(F.data == "admin_toggle_sync")
async def admin_toggle_sync(callback: types.CallbackQuery):
    """Тоггл `sync_locked`: блокирует/разблокирует команду `/sync_webapp`."""
    if not await _require_admin(callback):
        return
    try:
        cur = await get_setting("sync_locked")
        new_val = "0" if str(cur or "0") == "1" else "1"
        await set_setting("sync_locked", new_val)
    except Exception as e:  # noqa: BLE001 — setting read/write может упасть.
        return await callback.answer(f"Ошибка: {type(e).__name__}", show_alert=True)
    text, kb = await _build_settings_text_and_kb()
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer("✅ Sync toggled")


@admin_router.callback_query(F.data == "admin_toggle_cleanup")
async def admin_toggle_cleanup(callback: types.CallbackQuery):
    """Тоггл `cleanup_service`: включает/выключает авто-удаление service-сообщений."""
    if not await _require_admin(callback):
        return
    try:
        cur = await get_setting("cleanup_service")
        new_val = "0" if str(cur or "0") == "1" else "1"
        await set_setting("cleanup_service", new_val)
    except Exception as e:  # noqa: BLE001 — setting read/write может упасть.
        return await callback.answer(f"Ошибка: {type(e).__name__}", show_alert=True)
    text, kb = await _build_settings_text_and_kb()
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer("✅ Cleanup toggled")


# ===========================================================================
# B.4 — Management админов
# ===========================================================================


@admin_router.message(Command("add_admin"))
async def cmd_add_admin(message: types.Message):
    """`/add_admin <user_id>` — назначить админом по числовому id."""
    if not await _is_bot_admin(message.from_user.id):
        return
    try:
        new_admin = int(message.text.split()[1])
        await add_admin(new_admin)
        await message.answer(f"✅ Пользователь {new_admin} назначен администратором.")
    except (IndexError, ValueError):
        await message.answer("❌ Формат: /add_admin <id_пользователя>")


@admin_router.message(Command("delete_admin"))
async def cmd_delete_admin(message: types.Message):
    """`/delete_admin <user_id>` — удалить админа (главного нельзя)."""
    if not await _is_bot_admin(message.from_user.id):
        return
    try:
        del_admin = int(message.text.split()[1])
        if del_admin == MAIN_ADMIN_ID:
            return await message.answer("❌ Главного администратора удалить нельзя!")
        await remove_admin(del_admin)
        await message.answer(f"✅ Пользователь {del_admin} удален из администраторов.")
    except (IndexError, ValueError):
        await message.answer("❌ Формат: /delete_admin <id_пользователя>")


@admin_router.callback_query(F.data == "admin_admins")
async def admin_menu_admins(callback: types.CallbackQuery):
    """Секция "👑 Администраторы" — список + per-user кнопки удаления."""
    if not await _require_admin(callback):
        return
    await _render_admins_section(callback)
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_rm:"))
async def admin_menu_admins_remove(callback: types.CallbackQuery):
    """`admin_rm:<id>` — кнопка "➖ Удалить" в секции админов."""
    if not await _require_admin(callback):
        return
    try:
        uid = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return await callback.answer("Некорректный id.", show_alert=True)
    if uid == MAIN_ADMIN_ID:
        return await callback.answer("Главного админа удалить нельзя.", show_alert=True)
    try:
        await remove_admin(uid)
    except Exception as e:  # noqa: BLE001 — БД может отказать, нужно показать админу alert.
        logging.warning(f"admin_menu_admins_remove: {e}")
        return await callback.answer(f"Ошибка: {type(e).__name__}", show_alert=True)
    await callback.answer(f"✅ Удалён: {uid}")
    await _render_admins_section(callback)


@admin_router.callback_query(F.data == "admin_add_new")
async def admin_menu_admins_add_prompt(callback: types.CallbackQuery, state: FSMContext):
    """`admin_add_new` — кнопка "➕ Добавить" → запрос user_id через FSM."""
    if not await _require_admin(callback):
        return
    await state.set_state(AdminManage.waiting_for_new_admin_id)
    await callback.message.edit_text(
        "➕ <b>Добавление админа</b>\n\nОтправьте числовой <code>user_id</code> нового админа "
        "одним сообщением в этот чат.\n\n<i>Для отмены — /cancel</i>",
        parse_mode="HTML",
    )
    await callback.answer()


@admin_router.message(StateFilter(AdminManage.waiting_for_new_admin_id))
async def admin_manage_new_id(message: types.Message, state: FSMContext):
    """FSM-шаг: получить числовой user_id от админа и добавить его в БД.

    Guards:
    - Не-админ не должен попасть сюда (state всё равно очищаем на всякий случай).
    - Если пришла команда (`/...`) — чистим state и пропускаем к её handler'у.
    - Если не число — остаёмся в state и просим повторить.
    """
    if not await _is_bot_admin(message.from_user.id):
        return await state.clear()
    text = (message.text or "").strip()
    # Guard: команда вроде /admin не должна считаться "новым id" — чистим state
    # и даём команде пройти к Command-handler'у на следующем апдейте.
    if text.startswith("/"):
        await state.clear()
        return
    if not text.lstrip("-").isdigit():
        return await message.answer("❌ Нужно число (user_id). Попробуйте ещё раз или /cancel.")
    new_admin = int(text)
    try:
        await add_admin(new_admin)
    except Exception as e:  # noqa: BLE001 — БД-сбой, показываем админу ошибку и выходим из FSM.
        await state.clear()
        return await message.answer(f"❌ Ошибка: {type(e).__name__}")
    await state.clear()
    await message.answer(
        f"✅ Админ добавлен: <code>{new_admin}</code>",
        parse_mode="HTML",
        reply_markup=_build_admin_menu_kb(),
    )
