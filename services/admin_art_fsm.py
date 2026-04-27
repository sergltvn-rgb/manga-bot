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

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import WEBAPP_URL
from database import get_admins
from services import arts
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


def _arts_webapp_url() -> str:
    return f"{WEBAPP_URL.rstrip('/')}/webapp/arts.html"


def _upload_keyboard() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="✅ Сохранить", callback_data="admin_art_upload_save"),
        types.InlineKeyboardButton(text="🧹 Очистить", callback_data="admin_art_upload_clear"),
    )
    builder.row(types.InlineKeyboardButton(text="❌ Отмена", callback_data="admin_art_upload_cancel"))
    return builder.as_markup()


async def _edit_or_answer(message: types.Message, text: str, reply_markup=None) -> None:
    try:
        await message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception:  # noqa: BLE001
        try:
            await message.delete()
        except Exception as e:  # noqa: BLE001
            logging.debug(f"art_admin: failed to delete stale message: {e}")
        await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


async def render_admin_arts_dashboard(message: types.Message) -> None:
    counts = await arts.get_art_counts()
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🖼 Галерея", callback_data="admin_arts_gallery"),
        types.InlineKeyboardButton(text=f"📥 Предложка ({counts['pending']})", callback_data="admin_arts_suggestions:0"),
    )
    builder.row(
        types.InlineKeyboardButton(text="➕ Загрузить", callback_data="admin_cmd_add_art"),
        types.InlineKeyboardButton(text="🌐 WebApp", web_app=WebAppInfo(url=_arts_webapp_url())),
    )
    builder.row(
        types.InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_arts"),
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu"),
    )
    text = (
        "🎨 <b>Арты</b>\n\n"
        f"🖼 В галерее: <b>{counts['visible']}</b>\n"
        f"🙈 Скрыто: <b>{counts['hidden']}</b>\n"
        f"📥 На проверке: <b>{counts['pending']}</b>\n"
        f"➕ Добавлено сегодня: <b>{counts['added_today']}</b>\n\n"
        "<i>Загрузка остается через Telegram, а удобная сетка доступна в WebApp.</i>"
    )
    await _edit_or_answer(message, text, builder.as_markup())


async def render_suggestions_page(message: types.Message, page: int = 0) -> None:
    limit = arts.SUGGESTION_PAGE_SIZE
    page = max(0, page)
    data = await arts.list_suggestions_page(status="pending", limit=limit, offset=page * limit)
    if page >= data.total_pages:
        page = data.total_pages - 1
        data = await arts.list_suggestions_page(status="pending", limit=limit, offset=page * limit)

    lines = [
        "📥 <b>Предложка артов</b>",
        f"Страница <b>{data.page}/{data.total_pages}</b> · ожидают проверки: <b>{data.total}</b>",
        "",
    ]
    if not data.items:
        lines.append("Очередь пустая. Все предложения уже разобраны.")
    else:
        for item in data.items:
            lines.append(f"• <b>#{item.id}</b> от <code>{item.user_id}</code> · {item.created_at or 'без даты'}")

    builder = InlineKeyboardBuilder()
    for item in data.items:
        builder.row(types.InlineKeyboardButton(text=f"Открыть #{item.id}", callback_data=f"admin_arts_suggest_item:{item.id}:{page}"))
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton(text="◀️", callback_data=f"admin_arts_suggestions:{page - 1}"))
    if page < data.total_pages - 1:
        nav.append(types.InlineKeyboardButton(text="▶️", callback_data=f"admin_arts_suggestions:{page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(
        types.InlineKeyboardButton(text="🔄 Обновить", callback_data=f"admin_arts_suggestions:{page}"),
        types.InlineKeyboardButton(text="⬅️ Арты", callback_data="admin_arts"),
    )
    await _edit_or_answer(message, "\n".join(lines), builder.as_markup())


async def send_suggestion_detail(callback: types.CallbackQuery, suggestion_id: int, page: int) -> None:
    item = await arts.get_suggestion(suggestion_id)
    if not item or item.status != "pending":
        await callback.answer("Заявка уже обработана.", show_alert=True)
        await render_suggestions_page(callback.message, page)
        return

    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="✅ Принять", callback_data=f"admin_arts_suggest_accept:{suggestion_id}:{page}"),
        types.InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin_arts_suggest_reject:{suggestion_id}:{page}"),
    )
    builder.row(types.InlineKeyboardButton(text="⬅️ К списку", callback_data=f"admin_arts_suggestions:{page}"))
    caption = (
        f"📥 <b>Предложка #{item.id}</b>\n"
        f"Автор: <code>{item.user_id}</code>\n"
        f"Дата: <b>{item.created_at or 'без даты'}</b>\n\n"
        "Проверьте качество, соответствие персонажу и отсутствие лишнего текста."
    )
    try:
        await callback.message.delete()
    except Exception as e:  # noqa: BLE001
        logging.debug(f"art_suggestion_detail: failed to delete list message: {e}")
    await callback.message.answer_photo(item.file_id, caption=caption, parse_mode="HTML", reply_markup=builder.as_markup())


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
        "➕ <b>Загрузка артов</b>\n\n"
        "Отправляйте фото одним или несколькими сообщениями. Я соберу их в черновик, а вы сохраните всё кнопкой ниже.\n\n"
        "Проверка перед сохранением:\n"
        "• похоже на каноничную Алю/Roshidere;\n"
        "• четкое, цветное, без сильного сжатия;\n"
        "• без лишнего текста и водяных знаков на пол-экрана.\n\n"
        "В черновике: <b>0</b>",
        parse_mode="HTML",
        reply_markup=_upload_keyboard(),
    )


@art_router.message(ArtUpload.waiting_for_photo, F.photo)
async def process_art_photo(message: types.Message):
    """Сохраняем file_id каждой фото-посылки в ART_CACHE до `/finish`."""
    ART_CACHE.setdefault(message.from_user.id, {})[message.message_id] = message.photo[-1].file_id
    await message.answer(
        f"🖼 Добавлено в черновик: <b>{len(ART_CACHE[message.from_user.id])}</b>\n" "Можно отправить еще фото или нажать <b>Сохранить</b>.",
        parse_mode="HTML",
        reply_markup=_upload_keyboard(),
    )


@art_router.message(ArtUpload.waiting_for_photo, Command("finish"))
async def finish_art_upload(message: types.Message, state: FSMContext):
    """`/finish` — сохранить всё из ART_CACHE в `arts`."""
    cache = ART_CACHE.pop(message.from_user.id, {})
    if not cache:
        return await message.answer("Пусто! Отмена.")

    for msg_id in sorted(cache.keys()):
        await arts.add_art(cache[msg_id], added_by=message.from_user.id, source="admin_upload")
    await message.answer(f"✅ Успешно загружено {len(cache)} качественных артов!")
    await state.clear()


@art_router.callback_query(F.data == "admin_arts")
async def callback_admin_arts(callback: types.CallbackQuery):
    admins = await get_admins()
    if callback.from_user.id not in admins:
        return await callback.answer("❌ У вас нет прав.", show_alert=True)
    await render_admin_arts_dashboard(callback.message)
    await callback.answer()


@art_router.callback_query(F.data == "admin_arts_gallery")
async def callback_admin_arts_gallery(callback: types.CallbackQuery):
    admins = await get_admins()
    if callback.from_user.id not in admins:
        return await callback.answer("❌ У вас нет прав.", show_alert=True)
    try:
        await callback.message.delete()
    except Exception as e:  # noqa: BLE001
        logging.debug(f"admin_arts_gallery: failed to delete dashboard: {e}")
    from services.art_view import send_admin_art_item

    await send_admin_art_item(callback.message.chat.id, 0, bot_instance=callback.bot)
    await callback.answer()


@art_router.callback_query(F.data == "admin_art_upload_save")
async def callback_art_upload_save(callback: types.CallbackQuery, state: FSMContext):
    admins = await get_admins()
    if callback.from_user.id not in admins:
        return await callback.answer("❌ У вас нет прав.", show_alert=True)
    cache = ART_CACHE.pop(callback.from_user.id, {})
    if not cache:
        return await callback.answer("Черновик пуст.", show_alert=True)
    for msg_id in sorted(cache.keys()):
        await arts.add_art(cache[msg_id], added_by=callback.from_user.id, source="admin_upload")
    await state.clear()
    await callback.message.edit_text(f"✅ <b>Сохранено артов:</b> {len(cache)}", parse_mode="HTML")
    await callback.answer("Сохранено")


@art_router.callback_query(F.data == "admin_art_upload_clear")
async def callback_art_upload_clear(callback: types.CallbackQuery):
    ART_CACHE[callback.from_user.id] = {}
    await callback.message.edit_text(
        "🧹 <b>Черновик очищен.</b>\n\nОтправьте новые фото или отмените загрузку.",
        parse_mode="HTML",
        reply_markup=_upload_keyboard(),
    )
    await callback.answer("Очищено")


@art_router.callback_query(F.data == "admin_art_upload_cancel")
async def callback_art_upload_cancel(callback: types.CallbackQuery, state: FSMContext):
    ART_CACHE.pop(callback.from_user.id, None)
    await state.clear()
    await callback.message.edit_text("❌ Загрузка артов отменена.", parse_mode="HTML")
    await callback.answer()


@art_router.callback_query(F.data.startswith("admin_arts_suggestions:"))
async def callback_admin_arts_suggestions(callback: types.CallbackQuery):
    admins = await get_admins()
    if callback.from_user.id not in admins:
        return await callback.answer("❌ У вас нет прав.", show_alert=True)
    page = int(callback.data.split(":")[1])
    await render_suggestions_page(callback.message, page)
    await callback.answer()


@art_router.callback_query(F.data.startswith("admin_arts_suggest_item:"))
async def callback_admin_arts_suggest_item(callback: types.CallbackQuery):
    admins = await get_admins()
    if callback.from_user.id not in admins:
        return await callback.answer("❌ У вас нет прав.", show_alert=True)
    _, suggestion_id, page = callback.data.rsplit(":", 2)
    await send_suggestion_detail(callback, int(suggestion_id), int(page))
    await callback.answer()


@art_router.callback_query(F.data.startswith("admin_arts_suggest_accept:"))
async def callback_admin_arts_suggest_accept(callback: types.CallbackQuery):
    admins = await get_admins()
    if callback.from_user.id not in admins:
        return await callback.answer("❌ У вас нет прав.", show_alert=True)
    _, suggestion_id, page = callback.data.rsplit(":", 2)
    item = await arts.get_suggestion(int(suggestion_id))
    accepted = await arts.approve_suggested_art(int(suggestion_id), reviewed_by=callback.from_user.id)
    if not accepted:
        return await callback.answer("Заявка уже обработана.", show_alert=True)
    await callback.message.edit_caption(
        caption=f"✅ <b>Арт принят.</b>\nДобавлен в галерею как #{accepted.id}.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardBuilder()
        .row(types.InlineKeyboardButton(text="⬅️ К списку", callback_data=f"admin_arts_suggestions:{page}"))
        .as_markup(),
    )
    if item:
        try:
            await callback.bot.send_message(
                item.user_id,
                "🎉 <b>Ваш арт принят!</b> Он добавлен в галерею бота.",
                parse_mode="HTML",
            )
        except Exception as e:  # noqa: BLE001
            logging.debug(f"art_accept: failed to notify user {item.user_id}: {e}")
    await callback.answer("Принято")


@art_router.callback_query(F.data.startswith("admin_arts_suggest_reject:"))
async def callback_admin_arts_suggest_reject(callback: types.CallbackQuery):
    admins = await get_admins()
    if callback.from_user.id not in admins:
        return await callback.answer("❌ У вас нет прав.", show_alert=True)
    _, suggestion_id, page = callback.data.rsplit(":", 2)
    item = await arts.get_suggestion(int(suggestion_id))
    rejected = await arts.reject_suggested_art(int(suggestion_id), reviewed_by=callback.from_user.id)
    if not rejected:
        return await callback.answer("Заявка уже обработана.", show_alert=True)
    await callback.message.edit_caption(
        caption="❌ <b>Арт отклонен.</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardBuilder()
        .row(types.InlineKeyboardButton(text="⬅️ К списку", callback_data=f"admin_arts_suggestions:{page}"))
        .as_markup(),
    )
    if item:
        try:
            await callback.bot.send_message(
                item.user_id,
                "😔 <b>Ваш арт отклонен.</b> Скорее всего, он не подошел по качеству или стилистике.",
                parse_mode="HTML",
            )
        except Exception as e:  # noqa: BLE001
            logging.debug(f"art_reject: failed to notify user {item.user_id}: {e}")
    await callback.answer("Отклонено")


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
    suggest_id = await arts.add_suggested_art(user_id=user_id, file_id=file_id)

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
    item = await arts.get_suggestion(suggest_id)
    if not item:
        return await callback.message.edit_caption(caption="❌ Заявка уже обработана или не существует.", reply_markup=None)
    accepted = await arts.approve_suggested_art(suggest_id, reviewed_by=callback.from_user.id)
    if not accepted:
        return await callback.message.edit_caption(caption="❌ Заявка уже обработана или не существует.", reply_markup=None)
    user_id = item.user_id

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
    item = await arts.get_suggestion(suggest_id)
    if not item:
        return await callback.message.edit_caption(caption="❌ Заявка уже обработана или не существует.", reply_markup=None)
    rejected = await arts.reject_suggested_art(suggest_id, reviewed_by=callback.from_user.id)
    if not rejected:
        return await callback.message.edit_caption(caption="❌ Заявка уже обработана или не существует.", reply_markup=None)
    user_id = item.user_id

    await callback.message.edit_caption(caption="❌ <b>Арт отклонен.</b> Заявка удалена.", parse_mode="HTML", reply_markup=None)

    try:
        await callback.bot.send_message(
            chat_id=user_id,
            text="😔 <b>К сожалению</b>, ваш предложенный арт был отклонен администрацией (возможно, не подошел по качеству или стилистике).",
            parse_mode="HTML",
        )
    except Exception as e:  # noqa: BLE001
        logging.debug(f"art_reject: failed to notify user {user_id}: {e}")
