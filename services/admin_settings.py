"""Admin settings commands + inline-меню dispatcher.

Вынесено из `bot.py` как шаг Фазы 3 B.6.

Содержит:

- **Синхронизация WebApp**: `/toggle_sync` (блокировка), `/sync_webapp`
  (push JSON snapshot в GitHub).
- **ИИ-настройки**: `/toggle_ai` (вкл/выкл в группе), `/alya_mode`.
- **Чёрный список ИИ**: `/blacklist_ai`, `/unblacklist_ai`, `/blacklist_view`.
- **"Все команды" ссылка**: `/set_commands_link`, `/delete_commands_link`.
- **Тест уведомлений админам**: `cmd_test_notification`.
- **Inline-меню dispatcher**: `admin_menu_sync_webapp` (callback
  `admin_sync_webapp`) + `admin_menu_commands` (`admin_cmd_*`) — маппят
  callback-action'ы в slash-команды через `_fake_admin_message`.

Модуль экспортирует:

- `settings_router` — подключается в `main()` bot.py.
- cmd-функции (для admin_menu_commands dispatcher + тестов).

Тяжёлые cross-deps (`DB_PATH`, `get_cached_reader_data`) подгружаются
lazy через `import bot` внутри handler'ов — безопасно, т.к.
`dp.include_router(...)` в `main()` и handler'ы вызываются runtime.
"""

from __future__ import annotations

import json
import logging
import traceback

import aiosqlite
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from database import (
    add_to_blacklist,
    delete_commands_link,
    get_admins,
    get_blacklist,
    remove_from_blacklist,
    set_commands_link,
    toggle_alya_mode,
    toggle_group_ai,
)
from services.admin_art_fsm import cmd_add_art
from services.admin_content import (
    cmd_add_akashic,
    cmd_add_british,
    cmd_add_chapter,
    cmd_add_ranobe,
    cmd_delete_akashic,
    cmd_delete_art,
    cmd_delete_british,
    cmd_delete_chapter,
    cmd_delete_ranobe,
)
from services.admin_helpers import _fake_admin_message, _require_admin
from services.telegram_helpers import escape_html_text
from utils import run_git_sync

settings_router = Router()


# ===========================================================================
# Синхронизация WebApp
# ===========================================================================


@settings_router.message(Command("toggle_sync"))
async def cmd_toggle_sync(message: types.Message):
    """`/toggle_sync` — переключить блокировку `sync_webapp`."""
    import bot

    admins = await get_admins()
    if message.from_user.id not in admins:
        return

    async with aiosqlite.connect(bot.DB_PATH) as db:
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
        await message.answer(
            "🔒 <b>Синхронизация заблокирована!</b>\n"
            "Теперь команда /sync_webapp не будет работать и ваши данные в WebApp "
            "в полной безопасности от перезаписи. Чтобы разблокировать, введите команду снова.",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "🔓 <b>Синхронизация разблокирована.</b>\nКоманда /sync_webapp снова активна.",
            parse_mode="HTML",
        )


@settings_router.message(Command("sync_webapp"))
async def cmd_sync_webapp(message: types.Message):
    """`/sync_webapp` — собрать JSON snapshot БД и запушить в GitHub Pages."""
    import bot

    admins = await get_admins()
    if message.from_user.id not in admins:
        return

    # Проверка на блокировку синхронизации
    async with aiosqlite.connect(bot.DB_PATH) as db:
        try:
            async with db.execute('SELECT locked FROM sync_settings WHERE id = 1') as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    return await message.answer(
                        "🔒 Синхронизация сейчас заблокирована. Разблокируйте её командой " "/toggle_sync перед использованием.",
                        parse_mode="HTML",
                    )
        except Exception as e:  # noqa: BLE001 — таблица может отсутствовать на старых инсталляциях.
            logging.debug(f"sync_webapp: sync_settings table check skipped: {e}")

    msg = await message.answer("🔄 <i>Собираем данные из БД для WebApp...</i>", parse_mode="HTML")
    try:
        # build_reader_data() сам читает custom_names из БД — источник истины один.
        result, _, _ = await bot.get_cached_reader_data(force_refresh=True)

        with open("webapp/chapters_data.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        await msg.edit_text("🔄 <i>Публикуем данные в Github Pages. Ожидайте...</i>", parse_mode="HTML")

        # Асинхронная git-синхронизация (не блокирует Event Loop).
        success, output = await run_git_sync("sync webapp db")

        if success:
            await msg.edit_text(
                "✅ <b>Успешно!</b> Главы синхронизированы с WebApp. " "(Они появятся в приложении в течение 1-2 минут)",
                parse_mode="HTML",
            )
        else:
            await msg.edit_text(
                f"⚠️ База обновлена локально. <code>git push</code> не прошел.\n\n"
                f"<b>Ответ сервера:</b>\n<pre>{escape_html_text(output)}</pre>\n\n"
                f"Скорее всего, у бота на сервере нет прав для git push.",
                parse_mode="HTML",
            )

    except Exception as e:  # noqa: BLE001 — показываем traceback админу.
        err_msg = traceback.format_exc()
        await msg.edit_text(
            f"❌ <b>Ошибка:</b> {escape_html_text(e)}\n<pre>{escape_html_text(err_msg)}</pre>",
            parse_mode="HTML",
        )


# ===========================================================================
# ИИ-настройки
# ===========================================================================


@settings_router.message(Command("toggle_ai"))
async def cmd_toggle_ai(message: types.Message):
    """`/toggle_ai` — вкл/выкл общение с ИИ в текущей группе.

    Разрешено bot-админам (таблица `admins`) и админам группы
    (creator/administrator по `get_chat_member`).
    """
    if message.chat.type not in ["group", "supergroup"]:
        return await message.answer("Эту команду можно использовать только в группе!")

    admins = await get_admins()
    is_bot_admin = message.from_user.id in admins

    is_group_admin = False
    if not is_bot_admin:
        try:
            member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
            is_group_admin = member.status in ["creator", "administrator"]
        except Exception as e:  # noqa: BLE001 — get_chat_member может падать на приватных группах.
            logging.debug(f"toggle_ai: failed to get chat member status: {e}")

    if not is_bot_admin and not is_group_admin:
        return await message.answer("Только администраторы могут использовать эту команду.")

    enabled = await toggle_group_ai(message.chat.id)

    if enabled:
        await message.answer("✅ <b>Общение с ИИ в этой группе ВКЛЮЧЕНО.</b>", parse_mode="HTML")
    else:
        await message.answer("❌ <b>Общение с ИИ в этой группе ВЫКЛЮЧЕНО.</b>", parse_mode="HTML")


@settings_router.message(Command("alya_mode"))
async def cmd_alya_mode(message: types.Message):
    """`/alya_mode` — переключить режим реплик Али."""
    admins = await get_admins()
    if message.from_user.id not in admins:
        return
    new_mode = await toggle_alya_mode()
    await message.answer(f"✅ Режим Али изменен на: <b>{new_mode}</b>", parse_mode="HTML")


# ===========================================================================
# Чёрный список ИИ
# ===========================================================================


@settings_router.message(Command("blacklist_ai"))
async def cmd_blacklist_ai(message: types.Message):
    """`/blacklist_ai <user_id>` — запретить user_id писать ИИ."""
    admins = await get_admins()
    if message.from_user.id not in admins:
        return
    try:
        user_id = int(message.text.split()[1])
        if await add_to_blacklist(user_id):
            await message.answer(f"✅ Пользователь {user_id} добавлен в черный список ИИ.")
        else:
            await message.answer(f"Пользователь {user_id} УЖЕ в черном списке ИИ.")
    except (IndexError, ValueError):
        await message.answer("❌ Формат: /blacklist_ai <ID_пользователя>")


@settings_router.message(Command("unblacklist_ai"))
async def cmd_unblacklist_ai(message: types.Message):
    """`/unblacklist_ai <user_id>` — вернуть user_id доступ к ИИ."""
    admins = await get_admins()
    if message.from_user.id not in admins:
        return
    try:
        user_id = int(message.text.split()[1])
        if await remove_from_blacklist(user_id):
            await message.answer(f"✅ Пользователь {user_id} удален из черного списка ИИ.")
        else:
            await message.answer(f"Пользователя {user_id} НЕТ в черном списке ИИ.")
    except (IndexError, ValueError):
        await message.answer("❌ Формат: /unblacklist_ai <ID_пользователя>")


@settings_router.message(Command("blacklist_view"))
async def cmd_blacklist_view(message: types.Message):
    """`/blacklist_view` — показать все user_id в чёрном списке ИИ."""
    admins = await get_admins()
    if message.from_user.id not in admins:
        return
    bl = await get_blacklist()
    if not bl:
        return await message.answer("📝 Чёрный список ИИ пуст.")
    lines = [f"<code>{uid}</code>" for uid in bl]
    await message.answer(f"🚫 <b>Чёрный список ИИ ({len(bl)}):</b>\n" + "\n".join(lines), parse_mode="HTML")


# ===========================================================================
# "Все команды" ссылка
# ===========================================================================


@settings_router.message(Command("set_commands_link"))
async def cmd_set_commands_link(message: types.Message):
    """`/set_commands_link <url>` — установить ссылку "Все команды"."""
    admins = await get_admins()
    if message.from_user.id not in admins:
        return
    try:
        url = message.text.split(maxsplit=1)[1]
        await set_commands_link(url)
        await message.answer(f"✅ Установлена ссылка на все команды: {url}")
    except IndexError:
        await message.answer("❌ Формат: /set_commands_link <ссылка>")


@settings_router.message(Command("delete_commands_link"))
async def cmd_delete_commands_link(message: types.Message):
    """`/delete_commands_link` — удалить ссылку "Все команды"."""
    admins = await get_admins()
    if message.from_user.id not in admins:
        return
    await delete_commands_link()
    await message.answer("✅ Ссылка на все команды удалена.")


# ===========================================================================
# Тест уведомлений
# ===========================================================================


async def cmd_test_notification(message: types.Message):
    """Тестовая рассылка админам — используется из admin-меню и как
    обычная функция. НЕ декорируется напрямую, вызывается через
    `admin_menu_commands` dispatcher по callback `admin_cmd_test_notification`.
    """
    admins = await get_admins()
    if message.from_user.id not in admins:
        return

    await message.answer(
        f"🔔 <b>Тест уведомлений</b>\n"
        f"Список админов: <code>{admins}</code>\n"
        f"Твой ID: <code>{message.from_user.id}</code>\n\n"
        "Сейчас попробую отправить тестовое сообщение...",
        parse_mode="HTML",
    )

    count = 0
    for admin_id in admins:
        try:
            await message.bot.send_message(admin_id, "✅ Тестовое уведомление из системы репортов!")
            count += 1
        except Exception as e:  # noqa: BLE001 — показываем админу какой именно id не получил.
            await message.answer(f"❌ Ошибка для {admin_id}: {e}")

    await message.answer(f"🏁 Тест завершен. Отправлено: {count}/{len(admins)}")


# ===========================================================================
# Admin inline-меню dispatcher'ы
# ===========================================================================


@settings_router.callback_query(F.data == "admin_sync_webapp")
async def admin_menu_sync_webapp(callback: types.CallbackQuery):
    """Кнопка "🔄 Синхронизация WebApp" → вызов `cmd_sync_webapp`."""
    if not await _require_admin(callback):
        return
    await callback.message.delete()
    msg = _fake_admin_message(callback, "/sync_webapp")
    if msg is None:
        return await callback.answer("⚠️ Не удалось запустить действие.", show_alert=True)
    await cmd_sync_webapp(msg)
    await callback.answer()


@settings_router.callback_query(F.data.startswith("admin_cmd_"))
async def admin_menu_commands(callback: types.CallbackQuery, state: FSMContext):
    """Dispatcher для admin inline-меню: callback `admin_cmd_<name>`.

    Маппит action в соответствующую slash-команду (cmd_add_chapter, etc),
    оборачивает callback в fake-message и вызывает handler напрямую.

    `stateful_commands` — те, что требуют FSM context (add/delete + add_art
    инициализирующие state).
    """
    if not await _require_admin(callback):
        return
    cmd = callback.data.replace("admin_cmd_", "")
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
        "test_notification": cmd_test_notification,
    }
    stateful_commands = {
        "add_chapter",
        "add_ranobe",
        "add_akashic",
        "add_british",
        "add_art",
        "delete_chapter",
        "delete_ranobe",
        "delete_akashic",
        "delete_british",
    }
    if cmd not in commands:
        return await callback.answer("Неизвестная команда.", show_alert=True)

    msg = _fake_admin_message(callback, f"/{cmd}")
    if msg is None:
        return await callback.answer("⚠️ Не удалось запустить действие.", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:  # noqa: BLE001 — message может быть уже удалён.
        pass
    try:
        if cmd in stateful_commands:
            await commands[cmd](msg, state)
        else:
            await commands[cmd](msg)
    except Exception as e:
        logging.exception(f"admin_menu_commands: cmd={cmd} failed", exc_info=e)
        return await callback.answer(f"❌ {type(e).__name__}", show_alert=True)
    await callback.answer()
