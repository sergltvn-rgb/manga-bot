"""Art gallery navigation: user- и admin-side просмотр галереи артов.

Вынесено из `bot.py` как шаг Фазы 3 B.7 (завершает шаг 18).

Два параллельных потока (user + admin), объединённых общим FSM `ArtView`:

### User-side

- `view_arts` callback → входная точка из главного меню.
- Слайдер `user_art_view:<idx>` + `user_art_random`, `user_art_input`.
- Сетка `user_art_grid:<page>` (9 артов на страницу) + `grid_page_input`,
  `grid_art_input`.
- `user_art_delete` — кнопка "🗑 Удалить арт", показывается только админам;
  вызывает `delete_art_by_id` и перерисовывает слайдер.
- FSM states: `waiting_for_number`, `waiting_for_grid_page`,
  `waiting_for_grid_art_number` — для текстового ввода номеров.

### Admin-side (команда `/arts_list`)

- Полный CRUD по галерее: просмотр, удаление, "Номер арта", сетка 9 шт.
- Слайдер `admin_art_view:<idx>`, сетка `admin_art_grid:<page>`.
- FSM state `waiting_for_admin_number`.
- Callback `admin_art_view_back` — возврат из сетки в слайдер с очисткой
  media-group (auto_cleanup через 2 минуты в background).

Модуль экспортирует:

- `art_view_router` — подключается через `dp.include_router(...)` в `main()`.
- `ArtView` — FSM class (re-export для `/start` deeplink и тестов).
- `send_user_art_item`, `send_admin_art_item` — helper'ы (re-export для
  cross-module использования, например из admin_art_fsm после accept).

Модуль self-contained: все зависимости — из `services/` и `database/utils`.
Bot instance берём из `callback.bot` / `message.bot` — не импортируем `bot`.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import delete_art_by_id, get_admins, get_all_arts
from services.telegram_helpers import get_back_button
from utils import check_cd_and_warn, spawn_bg


class ArtView(StatesGroup):
    """FSM для ввода номеров артов/страниц в user- и admin-галереях."""

    waiting_for_number = State()
    waiting_for_admin_number = State()
    waiting_for_page = State()
    waiting_for_grid_page = State()
    waiting_for_grid_art_number = State()


art_view_router = Router()


# ===========================================================================
# Helper: рендер одного арта (user-side)
# ===========================================================================


async def send_user_art_item(
    chat_id: int,
    index: int,
    user_id: int,
    bot_instance,
    message_to_edit: types.Message | None = None,
):
    """Отправить/отредактировать сообщение с одним артом (user-side).

    `bot_instance` — явно пробрасываем aiogram Bot, чтобы не делать
    `import bot` и не зависеть от глобальной переменной. Берём из
    `callback.bot` / `message.bot` в вызывающем коде.
    """
    arts = await get_all_arts()
    if not arts:
        if message_to_edit:
            try:
                await message_to_edit.delete()
            except Exception as e:  # noqa: BLE001 — сообщение может быть уже удалено.
                logging.debug(f"user_art_item: failed to delete empty-gallery message: {e}")
        await bot_instance.send_message(chat_id, "Галерея пуста 😔", reply_markup=get_back_button())
        return

    # Зацикливание индекса
    if index < 0:
        index = len(arts) - 1
    if index >= len(arts):
        index = 0

    art_id, file_id = arts[index]

    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="⬅️", callback_data=f"user_art_view:{index - 1}"),
        types.InlineKeyboardButton(text="➡️", callback_data=f"user_art_view:{index + 1}"),
    )
    builder.row(
        types.InlineKeyboardButton(text="🎲 Случайный арт", callback_data="user_art_random"),
        types.InlineKeyboardButton(text="🔢 Номер арта", callback_data="user_art_input"),
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
                reply_markup=builder.as_markup(),
            )
        except Exception as e:  # noqa: BLE001
            if "not modified" not in str(e).lower():
                await bot_instance.send_photo(chat_id, photo=file_id, caption=caption, parse_mode="HTML", reply_markup=builder.as_markup())
                try:
                    await message_to_edit.delete()
                except Exception as e2:  # noqa: BLE001
                    logging.debug(f"user_art_item: failed to delete outdated media message: {e2}")
    else:
        await bot_instance.send_photo(chat_id, photo=file_id, caption=caption, parse_mode="HTML", reply_markup=builder.as_markup())


# ===========================================================================
# Helper: рендер одного арта (admin-side)
# ===========================================================================


async def send_admin_art_item(
    chat_id: int,
    index: int,
    bot_instance,
    message_to_edit: types.Message | None = None,
):
    """Отправить/отредактировать сообщение с одним артом (admin-side)."""
    arts = await get_all_arts()
    if not arts:
        if message_to_edit:
            try:
                await message_to_edit.delete()
            except Exception as e:  # noqa: BLE001
                logging.debug(f"admin_art_item: failed to delete empty-gallery message: {e}")
        await bot_instance.send_message(chat_id, "Галерея артов пуста 😔")
        return

    # Зацикливание индекса
    if index < 0:
        index = len(arts) - 1
    if index >= len(arts):
        index = 0

    art_id, file_id = arts[index]

    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_art_view:{index - 1}"),
        types.InlineKeyboardButton(text="Вперед ➡️", callback_data=f"admin_art_view:{index + 1}"),
    )
    builder.row(
        types.InlineKeyboardButton(text="🔢 Номер арта", callback_data="admin_art_input"),
        types.InlineKeyboardButton(text="🗑 Удалить арт", callback_data=f"admin_art_delete:{art_id}:{index}"),
    )
    builder.row(types.InlineKeyboardButton(text="📱 Режим сетки (9 шт)", callback_data="admin_art_grid:0"))

    caption = f"👑 <b>[Админ] Арт ID:</b> {art_id}\n<i>({index + 1} из {len(arts)})</i>"

    if message_to_edit:
        try:
            await message_to_edit.edit_media(
                media=types.InputMediaPhoto(media=file_id, caption=caption, parse_mode="HTML"),
                reply_markup=builder.as_markup(),
            )
        except Exception as e:  # noqa: BLE001
            if "not modified" not in str(e).lower():
                # На случай осечки — шлём новое фото, удаляем старое.
                await bot_instance.send_photo(chat_id, photo=file_id, caption=caption, parse_mode="HTML", reply_markup=builder.as_markup())
                try:
                    await message_to_edit.delete()
                except Exception as e2:  # noqa: BLE001
                    logging.debug(f"admin_art_item: failed to delete outdated media message: {e2}")
    else:
        await bot_instance.send_photo(chat_id, photo=file_id, caption=caption, parse_mode="HTML", reply_markup=builder.as_markup())


# ===========================================================================
# User-side: ввод и слайдер
# ===========================================================================


@art_view_router.callback_query(F.data.startswith("user_art_delete:"))
async def process_user_art_delete(callback: types.CallbackQuery):
    """Админская кнопка "🗑 Удалить арт" в user-слайдере."""
    admins = await get_admins()
    if callback.from_user.id not in admins:
        return await callback.answer("❌ У вас нет прав!", show_alert=True)

    data = callback.data.split(":")
    art_id = int(data[1])
    index = int(data[2])

    if await delete_art_by_id(art_id):
        await callback.answer("✅ Арт успешно удален.")
        await send_user_art_item(
            callback.message.chat.id,
            index,
            user_id=callback.from_user.id,
            bot_instance=callback.bot,
            message_to_edit=callback.message,
        )
    else:
        await callback.answer("❌ Ошибка при удалении арта.", show_alert=True)


@art_view_router.callback_query(F.data == "view_arts")
async def view_arts(callback: types.CallbackQuery):
    """Вход в галерею из главного меню (кнопка "🎨 Арты")."""
    if await check_cd_and_warn(callback, "arts", 5):
        return
    await callback.message.delete()
    await send_user_art_item(callback.message.chat.id, 0, user_id=callback.from_user.id, bot_instance=callback.bot)


@art_view_router.callback_query(F.data.startswith("user_art_view:"))
async def process_user_art_view(callback: types.CallbackQuery, state: FSMContext):
    """Слайдер: переход на конкретный индекс.

    Если юзер переходит из сетки — чистим media-group (сохранён в
    `user_grid_photos` FSM data).
    """
    data = await state.get_data()
    if "user_grid_photos" in data:
        for mid in data.get("user_grid_photos", []):
            try:
                await callback.bot.delete_message(callback.message.chat.id, mid)
            except Exception as e:  # noqa: BLE001
                logging.debug(f"user_art_view: failed to cleanup grid photo {mid}: {e}")
        await state.update_data(user_grid_photos=[])

    index = int(callback.data.split(":")[1])
    await send_user_art_item(
        callback.message.chat.id,
        index,
        user_id=callback.from_user.id,
        bot_instance=callback.bot,
        message_to_edit=callback.message,
    )
    await callback.answer()


@art_view_router.callback_query(F.data == "user_art_random")
async def process_user_art_random(callback: types.CallbackQuery):
    """🎲 Случайный арт."""
    arts = await get_all_arts()
    if not arts:
        return await callback.answer("Галерея пуста 😔", show_alert=True)
    index = random.randint(0, len(arts) - 1)
    await send_user_art_item(
        callback.message.chat.id,
        index,
        user_id=callback.from_user.id,
        bot_instance=callback.bot,
        message_to_edit=callback.message,
    )
    await callback.answer("🎲 Случайный арт!")


@art_view_router.callback_query(F.data == "user_art_input")
async def process_user_art_input(callback: types.CallbackQuery, state: FSMContext):
    """ "🔢 Номер арта" → запрос номера текстом."""
    arts = await get_all_arts()
    if not arts:
        return await callback.answer("Галерея пуста 😔", show_alert=True)
    await state.set_state(ArtView.waiting_for_number)
    await callback.message.answer(f"🔢 <b>Переход к арту</b>\nВведите номер арта от 1 до {len(arts)}:", parse_mode="HTML")
    await callback.answer()


@art_view_router.message(ArtView.waiting_for_number, F.text.isdigit())
async def handle_art_number_input(message: types.Message, state: FSMContext):
    """Валидация введённого номера арта (user-слайдер)."""
    await state.clear()
    num = int(message.text)
    arts = await get_all_arts()
    if 1 <= num <= len(arts):
        await send_user_art_item(message.chat.id, num - 1, user_id=message.from_user.id, bot_instance=message.bot)
    else:
        await message.answer(f"❌ Неверный номер! Введите число от 1 до {len(arts)}.")


# ===========================================================================
# User-side: сетка (9 артов на страницу)
# ===========================================================================


@art_view_router.callback_query(F.data.startswith("user_art_grid:"))
async def process_user_art_grid(callback: types.CallbackQuery, state: FSMContext):
    """Сетка артов (9 шт. на страницу) для user-side.

    Перед показом новой страницы чистим media-group предыдущей (сохранён
    в `user_grid_photos`) + запускаем auto_cleanup через 2 минуты.
    """
    data = await state.get_data()
    for mid in data.get("user_grid_photos", []):
        try:
            await callback.bot.delete_message(callback.message.chat.id, mid)
        except Exception as e:  # noqa: BLE001
            logging.debug(f"user_art_grid: failed to cleanup previous grid photo {mid}: {e}")

    page = int(callback.data.split(":")[1])
    arts = await get_all_arts()
    if not arts:
        return await callback.answer("Галерея пуста 😔", show_alert=True)

    limit = 9
    total_pages = math.ceil(len(arts) / limit)
    if page < 0:
        page = 0
    if page >= total_pages:
        page = total_pages - 1

    start = page * limit
    end = min(start + limit, len(arts))
    sliced = arts[start:end]

    if not sliced:
        return await callback.answer("Больше нет артов.", show_alert=True)

    # callback.message — это control message предыдущей страницы, уже удалён
    # циклом выше (его message_id лежит в user_grid_photos). Ловим BadRequest,
    # иначе exception прервёт handler до send_media_group и юзер увидит только
    # исчезновение старого сообщения без новой сетки. На первом заходе из
    # слайдера (user_grid_photos пуст) это сообщение существует — удалится штатно.
    try:
        await callback.message.delete()
    except Exception as e:  # noqa: BLE001
        logging.debug(f"user_art_grid: source message already deleted: {e}")

    media = [InputMediaPhoto(media=row[1]) for row in sliced]
    messages = await callback.bot.send_media_group(chat_id=callback.message.chat.id, media=media)
    photo_ids = [m.message_id for m in messages]

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="⬅️ Пред. стр", callback_data=f"user_art_grid:{page - 1}")
    if page < total_pages - 1:
        builder.button(text="След. стр ➡️", callback_data=f"user_art_grid:{page + 1}")

    builder.row(
        types.InlineKeyboardButton(text="🎚 К слайдеру", callback_data=f"user_art_view:{start}"),
        types.InlineKeyboardButton(text="🔢 Номер арта", callback_data="grid_art_input"),
    )
    builder.row(
        types.InlineKeyboardButton(text="📄 На страницу", callback_data="grid_page_input"),
        types.InlineKeyboardButton(text="⬅️ В меню", callback_data="main_menu"),
    )

    art_from = start + 1
    art_to = end
    control_msg = await callback.message.answer(
        f"📱 <b>Сетка артов</b>\n"
        f"🎨 Арты <b>{art_from}–{art_to}</b> из {len(arts)}\n"
        f"📄 Страница <b>{page + 1}</b> из <b>{total_pages}</b>",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )

    all_ids = photo_ids + [control_msg.message_id]
    await state.update_data(user_grid_photos=all_ids)

    async def auto_cleanup(chat_id: int, ids: list, fsm_state: FSMContext):
        await asyncio.sleep(120)
        # Проверяем, что текущие IDs в стейте совпадают — если нет, юзер перелистнул.
        data = await fsm_state.get_data()
        current_ids = data.get('user_grid_photos', [])
        if set(ids) != set(current_ids):
            return  # Устаревшая таска, данные уже удалены при перелистывании.
        for mid in ids:
            try:
                await callback.bot.delete_message(chat_id, mid)
            except Exception as e:  # noqa: BLE001
                logging.debug(f"user_art_grid:auto_cleanup failed for message {mid}: {e}")

    spawn_bg(
        auto_cleanup(callback.message.chat.id, all_ids, state),
        name="auto_cleanup:user_art_grid",
    )


@art_view_router.callback_query(F.data == "grid_page_input")
async def process_grid_page_input(callback: types.CallbackQuery, state: FSMContext):
    """ "📄 На страницу" → запрос номера страницы сетки текстом."""
    arts = await get_all_arts()
    if not arts:
        return await callback.answer("Галерея пуста 😔", show_alert=True)
    total_pages = math.ceil(len(arts) / 9)
    await state.set_state(ArtView.waiting_for_grid_page)
    await callback.message.answer(
        f"📄 <b>Переход к странице</b>\nВведите номер страницы от 1 до {total_pages}:",
        parse_mode="HTML",
    )
    await callback.answer()


@art_view_router.message(ArtView.waiting_for_grid_page, F.text.isdigit())
async def handle_grid_page_input(message: types.Message, state: FSMContext):
    """Валидация номера страницы сетки + эмуляция нажатия user_art_grid."""
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
        await message.bot.send_media_group(chat_id=message.chat.id, media=media)

        builder = InlineKeyboardBuilder()
        if page > 0:
            builder.button(text="⬅️ Пред. стр", callback_data=f"user_art_grid:{page - 1}")
        if page < total_pages - 1:
            builder.button(text="След. стр ➡️", callback_data=f"user_art_grid:{page + 1}")
        builder.row(
            types.InlineKeyboardButton(text="🎚 К слайдеру", callback_data=f"user_art_view:{start}"),
            types.InlineKeyboardButton(text="🔢 Номер арта", callback_data="grid_art_input"),
        )
        builder.row(
            types.InlineKeyboardButton(text="📄 На страницу", callback_data="grid_page_input"),
            types.InlineKeyboardButton(text="⬅️ В меню", callback_data="main_menu"),
        )
        await message.answer(
            f"📱 <b>Сетка артов</b>\n"
            f"🎨 Арты <b>{start+1}–{end}</b> из {len(arts)}\n"
            f"📄 Страница <b>{page+1}</b> из <b>{total_pages}</b>",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )
    else:
        await message.answer(f"❌ Неверный номер! Введите от 1 до {total_pages}.")


@art_view_router.callback_query(F.data == "grid_art_input")
async def process_grid_art_input(callback: types.CallbackQuery, state: FSMContext):
    """ "🔢 Номер арта" из сетки → запрос номера арта."""
    arts = await get_all_arts()
    if not arts:
        return await callback.answer("Галерея пуста 😔", show_alert=True)
    await state.set_state(ArtView.waiting_for_grid_art_number)
    await callback.message.answer(f"🔢 <b>Переход к арту</b>\nВведите номер арта от 1 до {len(arts)}:", parse_mode="HTML")
    await callback.answer()


@art_view_router.message(ArtView.waiting_for_grid_art_number, F.text.isdigit())
async def handle_grid_art_number_input(message: types.Message, state: FSMContext):
    """Валидация номера арта из сетки."""
    await state.clear()
    num = int(message.text)
    arts = await get_all_arts()
    if 1 <= num <= len(arts):
        await send_user_art_item(message.chat.id, num - 1, user_id=message.from_user.id, bot_instance=message.bot)
    else:
        await message.answer(f"❌ Неверный номер! Введите от 1 до {len(arts)}.")


# ===========================================================================
# Admin-side: команда `/arts_list` + слайдер + сетка
# ===========================================================================


@art_view_router.message(Command("arts_list"))
async def cmd_arts_list(message: types.Message):
    """`/arts_list` — открыть admin-слайдер галереи."""
    admins = await get_admins()
    if message.from_user.id not in admins:
        return
    await send_admin_art_item(message.chat.id, 0, bot_instance=message.bot)


@art_view_router.callback_query(F.data.startswith("admin_art_view:"))
async def process_admin_art_view(callback: types.CallbackQuery):
    """Admin-слайдер: переход на конкретный индекс."""
    index = int(callback.data.split(":")[1])
    await send_admin_art_item(callback.message.chat.id, index, bot_instance=callback.bot, message_to_edit=callback.message)
    await callback.answer()


@art_view_router.callback_query(F.data.startswith("admin_art_delete:"))
async def process_admin_art_delete(callback: types.CallbackQuery):
    """Admin-слайдер: удаление арта с последующим показом следующего."""
    data = callback.data.split(":")
    art_id = int(data[1])
    index = int(data[2])

    if await delete_art_by_id(art_id):
        await callback.answer("✅ Арт успешно удален.")
        # Показываем следующий или остаёмся в листе (цикл по index в send_admin_art_item).
        await send_admin_art_item(callback.message.chat.id, index, bot_instance=callback.bot, message_to_edit=callback.message)
    else:
        await callback.answer("❌ Ошибка при удалении арт.", show_alert=True)


@art_view_router.callback_query(F.data == "admin_art_input")
async def process_admin_art_input(callback: types.CallbackQuery, state: FSMContext):
    """Admin-слайдер: "🔢 Номер арта" → запрос номера текстом."""
    arts = await get_all_arts()
    if not arts:
        return await callback.answer("Галерея пуста 😔", show_alert=True)
    await state.set_state(ArtView.waiting_for_admin_number)
    await callback.message.answer(f"👑 <b>[Админ] Переход к арту</b>\nВведите номер арта от 1 до {len(arts)}:", parse_mode="HTML")
    await callback.answer()


@art_view_router.message(ArtView.waiting_for_admin_number, F.text.isdigit())
async def handle_admin_art_number_input(message: types.Message, state: FSMContext):
    """Валидация введённого номера арта (admin-слайдер)."""
    await state.clear()
    num = int(message.text)
    arts = await get_all_arts()
    if 1 <= num <= len(arts):
        await send_admin_art_item(message.chat.id, num - 1, bot_instance=message.bot)
    else:
        await message.answer(f"❌ Неверный номер! Введите число от 1 до {len(arts)}.")


@art_view_router.callback_query(F.data.startswith("admin_art_grid:"))
async def process_admin_art_grid(callback: types.CallbackQuery, state: FSMContext):
    """Admin: сетка артов (9 шт.) с удалением предыдущей + auto_cleanup."""
    # 1. Удаляем предыдущее превью (media group) если оно сохранено в state.
    data = await state.get_data()
    prev_photos = data.get("grid_photos", [])
    for mid in prev_photos:
        try:
            await callback.bot.delete_message(callback.message.chat.id, mid)
        except Exception as e:  # noqa: BLE001
            logging.debug(f"admin_art_grid: failed to cleanup previous photo {mid}: {e}")

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
    messages = await callback.bot.send_media_group(chat_id=callback.message.chat.id, media=media)
    photo_ids = [m.message_id for m in messages]

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="⬅️ Пред. стр", callback_data=f"admin_art_grid:{page - 1}")
    if end < len(arts):
        builder.button(text="След. стр ➡️", callback_data=f"admin_art_grid:{page + 1}")

    # Возврат в слайдер через admin_art_view_back (ниже).
    builder.button(text="🎚 К слайдеру", callback_data="admin_art_view_back")

    control_msg = await callback.message.answer(
        f"👑 <b>[Админ] Сетка артов</b>\n<i>Страница {page + 1} (Показаны {len(sliced)} из {len(arts)})</i>",
        parse_mode="HTML",
        reply_markup=builder.adjust(2).as_markup(),
    )

    # Сохраняем новые IDs для следующего перехода.
    await state.update_data(grid_photos=photo_ids)

    # Функция автоочистки через 2 минуты.
    async def auto_cleanup(chat_id: int, ids: list, fsm_state: FSMContext):
        await asyncio.sleep(120)
        # Проверяем, что текущие IDs в стейте совпадают — если нет, админ перелистнул.
        data = await fsm_state.get_data()
        current_ids = data.get('grid_photos', [])
        if set(ids) != set(current_ids):
            return  # Устаревшая таска, данные уже удалены при перелистывании.
        for mid in ids:
            try:
                await callback.bot.delete_message(chat_id, mid)
            except Exception as e:  # noqa: BLE001
                logging.debug(f"admin_art_grid:auto_cleanup failed for message {mid}: {e}")

    spawn_bg(
        auto_cleanup(callback.message.chat.id, photo_ids + [control_msg.message_id], state),
        name="auto_cleanup:admin_art_grid",
    )


@art_view_router.callback_query(F.data == "admin_art_view_back")
async def process_admin_art_view_back(callback: types.CallbackQuery, state: FSMContext):
    """Возврат из admin-сетки в слайдер с очисткой media-group."""
    data = await state.get_data()
    for mid in data.get("grid_photos", []):
        try:
            await callback.bot.delete_message(callback.message.chat.id, mid)
        except Exception as e:  # noqa: BLE001
            logging.debug(f"admin_art_view_back: failed to delete grid photo {mid}: {e}")
    await state.update_data(grid_photos=[])  # Очищаем.

    await callback.message.delete()
    await send_admin_art_item(callback.message.chat.id, 0, bot_instance=callback.bot)
