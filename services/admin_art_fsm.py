"""Admin + user flow для галереи артов (aiogram Router).

Модуль экспортирует `art_router` — его нужно подключить через
`dp.include_router(art_router)` в `main()` bot.py.

Сценарии:

1. **Админ bulk-загружает арты**: `/add_art` → `ArtUpload.waiting_for_photo`.
   Админ шлёт серию фото, затем `/finish`. Фото собираются в
   `ART_CACHE[user_id]`, при `/finish` пишутся в таблицу `arts`.

2. **Пользователь предлагает арт**: `/suggest_art` или кнопка
   `suggest_art_menu` → `ArtSuggest.waiting_for_photo`. Одно фото.
   Пишется в `suggested_arts`, админам шлётся уведомление с кнопками
   "Принять"/"Отклонить" (callback'и `artaccept_{id}` / `artreject_{id}`).

3. **Админ модерирует**: `artaccept_*` переносит из `suggested_arts` в
   `arts`, удаляет из suggested, уведомляет автора. `artreject_*` просто
   удаляет заявку и уведомляет автора.

Все зависимости импортируются top-level из правильных модулей (НЕ `from bot
import ...`), чтобы избежать повторного импорта bot.py (ловушка `python bot.py`
→ sys.modules['__main__'] vs 'bot'). Bot instance берём из `event.bot`.

Вынесено из `bot.py` как шаг Фазы 3 шаг 20 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import logging

import aiosqlite
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import DB_PATH, get_admins
from services.shared_state import ART_CACHE
from services.telegram_helpers import format_user_tag, get_back_button
from utils import check_cd_and_warn


class ArtUpload(StatesGroup):
    """FSM: админ собирает серию фото через `/add_art`, завершает `/finish`."""

    waiting_for_photo = State()


class ArtSuggest(StatesGroup):
    """FSM: пользователь предлагает одно фото через `/suggest_art`."""

    waiting_for_photo = State()


art_router = Router()


# ---------------------------------------------------------------------------
# 1. Админ bulk-upload
# ---------------------------------------------------------------------------


@art_router.message(Command("add_art"))
async def cmd_add_art(message: types.Message, state: FSMContext):
    """`/add_art` (admin only) — начать bulk-загрузку артов."""
    admins = await get_admins()
    if message.from_user.id not in admins:
        return
    await state.set_state(ArtUpload.waiting_for_photo)
    ART_CACHE[message.from_user.id] = {}
    await message.answer(
        "❗️ <b>ПРАВИЛА АРТОВ:</b>\n1. Сверять внешность с аниме.\n2. Цветные и чёткие.\n3. БЕЗ перевода и текста.\n\nКидайте фото, затем /finish",
        parse_mode="HTML",
    )


@art_router.message(ArtUpload.waiting_for_photo, F.photo)
async def process_art_photo(message: types.Message):
    """Сохраняем file_id каждой фото-посылки в ART_CACHE до `/finish`."""
    ART_CACHE.setdefault(message.from_user.id, {})[message.message_id] = message.photo[-1].file_id


@art_router.message(ArtUpload.waiting_for_photo, Command("finish"))
async def finish_art_upload(message: types.Message, state: FSMContext):
    """`/finish` — сохранить всё из ART_CACHE в `arts`."""
    cache = ART_CACHE.pop(message.from_user.id, {})
    if not cache:
        return await message.answer("Пусто! Отмена.")

    async with aiosqlite.connect(DB_PATH) as db:
        for msg_id in sorted(cache.keys()):
            await db.execute("INSERT INTO arts (file_id) VALUES (?)", (cache[msg_id],))
        await db.commit()
    await message.answer(f"✅ Успешно загружено {len(cache)} качественных артов!")
    await state.clear()


# ---------------------------------------------------------------------------
# 2. User suggest (бот-команда + inline-кнопка)
# ---------------------------------------------------------------------------


_SUGGEST_INTRO = (
    "🖼 <b>Предложка артов</b>\n\n"
    "Отправьте <b>одну</b> красивую фотографию (арт), которую хотите предложить в нашу галерею.\n\n"
    "❗️ <b>Требования:</b>\n"
    "1. Рисовка качественная и приближена к аниме.\n"
    "2. Без вотермарок на пол-экрана и лишнего текста.\n"
    "3. Соответствие тематике Roshidere.\n\n"
    "<i>Все арты проходят ручную проверку администрацией.</i>"
)


@art_router.message(Command("suggest_art"))
async def cmd_suggest_art(message: types.Message, state: FSMContext):
    """`/suggest_art` — предложить один арт."""
    if await check_cd_and_warn(message, "suggest_art", 30):
        return
    await state.set_state(ArtSuggest.waiting_for_photo)
    await message.answer(_SUGGEST_INTRO, parse_mode="HTML")


@art_router.callback_query(F.data == "suggest_art_menu")
async def callback_suggest_art_menu(callback: types.CallbackQuery, state: FSMContext):
    """Inline-кнопка `suggest_art_menu` — тот же flow что и `/suggest_art`."""
    if await check_cd_and_warn(callback, "suggest_art", 30):
        return
    await state.set_state(ArtSuggest.waiting_for_photo)
    await callback.message.edit_text(
        _SUGGEST_INTRO,
        parse_mode="HTML",
        reply_markup=get_back_button(text="❌ Отмена"),
    )


@art_router.message(ArtSuggest.waiting_for_photo, F.photo)
async def process_suggested_art(message: types.Message, state: FSMContext):
    """Получаем одно фото от пользователя → запись в `suggested_arts` + уведомление админам."""
    file_id = message.photo[-1].file_id
    user_id = message.from_user.id
    safe_user_label = format_user_tag(message.from_user.username, message.from_user.first_name, user_id)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO suggested_arts (user_id, file_id) VALUES (?, ?)", (user_id, file_id))
        suggest_id = cursor.lastrowid
        await db.commit()

    await message.answer("✅ <b>Ваш арт отправлен на модерацию!</b> Вы получите уведомление, когда его проверят.", parse_mode="HTML")
    await state.clear()

    admins = await get_admins()

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принять", callback_data=f"artaccept_{suggest_id}")
    builder.button(text="❌ Отклонить", callback_data=f"artreject_{suggest_id}")

    bot = message.bot
    for admin_id in admins:
        try:
            await bot.send_photo(
                chat_id=admin_id,
                photo=file_id,
                caption=f"📝 <b>Новая предложка арта!</b>\nОт: {safe_user_label} (ID: <code>{user_id}</code>)\nВыберите действие:",
                parse_mode="HTML",
                reply_markup=builder.as_markup(),
            )
        except Exception as e:  # noqa: BLE001 — aiogram-ошибка не должна прервать цикл.
            logging.debug(f"suggested_art: failed to notify admin {admin_id}: {e}")


# ---------------------------------------------------------------------------
# 3. Admin moderation (accept/reject)
# ---------------------------------------------------------------------------


@art_router.callback_query(F.data.startswith("artaccept_"))
async def process_art_accept(callback: types.CallbackQuery):
    """Админ принимает предложенный арт → переносит в `arts`, уведомляет автора."""
    suggest_id = int(callback.data.split("_")[1])

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id, file_id FROM suggested_arts WHERE id = ?", (suggest_id,))
        row = await cursor.fetchone()

        if not row:
            return await callback.message.edit_caption(caption="❌ Заявка уже обработана или не существует.", reply_markup=None)

        user_id, file_id = row
        await db.execute("DELETE FROM suggested_arts WHERE id = ?", (suggest_id,))
        await db.execute("INSERT INTO arts (file_id) VALUES (?)", (file_id,))
        await db.commit()

    await callback.message.edit_caption(caption="✅ <b>Арт принят!</b> Добавлен в базу.", parse_mode="HTML", reply_markup=None)

    try:
        await callback.bot.send_message(
            chat_id=user_id,
            text="🎉 <b>Поздравляем!</b> Ваш предложенный арт прошел проверку и был добавлен в галерею бота!",
            parse_mode="HTML",
        )
    except Exception as e:  # noqa: BLE001
        logging.debug(f"art_accept: failed to notify user {user_id}: {e}")


@art_router.callback_query(F.data.startswith("artreject_"))
async def process_art_reject(callback: types.CallbackQuery):
    """Админ отклоняет предложенный арт → удаляет, уведомляет автора."""
    suggest_id = int(callback.data.split("_")[1])

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM suggested_arts WHERE id = ?", (suggest_id,))
        row = await cursor.fetchone()

        if not row:
            return await callback.message.edit_caption(caption="❌ Заявка уже обработана или не существует.", reply_markup=None)

        user_id = row[0]
        await db.execute("DELETE FROM suggested_arts WHERE id = ?", (suggest_id,))
        await db.commit()

    await callback.message.edit_caption(caption="❌ <b>Арт отклонен.</b> Заявка удалена.", parse_mode="HTML", reply_markup=None)

    try:
        await callback.bot.send_message(
            chat_id=user_id,
            text="😔 <b>К сожалению</b>, ваш предложенный арт был отклонен администрацией (возможно, не подошел по качеству или стилистике).",
            parse_mode="HTML",
        )
    except Exception as e:  # noqa: BLE001
        logging.debug(f"art_reject: failed to notify user {user_id}: {e}")
