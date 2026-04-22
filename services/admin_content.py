"""Admin content-FSM: добавление и удаление глав (manga/ranobe/akashic/british).

Вынесено из `bot.py` как шаг Фазы 3 B.5.

Экспортирует:

- `content_router` — нужно подключить через `dp.include_router(content_router)`
  в `main()` bot.py. Side-effect импорта регистрирует handler'ы.
- `UniversalContentUpload`, `UniversalContentDelete` — FSM states.
- `NotifyUsers` — FSM state для рассылки уведомлений после публикации главы.
- cmd-функции (`cmd_add_chapter`, `cmd_delete_art` и т.д.) —
  re-export для `admin_menu_commands` dispatcher'а в bot.py и тестов.

Содержит:

- 4 команды на добавление: `/add_chapter`, `/add_ranobe`, `/add_akashic`,
  `/add_british`.
- 4 команды на удаление: `/delete_chapter`, `/delete_ranobe`,
  `/delete_akashic`, `/delete_british`.
- 1 команда удаления арта: `/delete_art`.
- 3 FSM-шага upload: id (через callback для manga/ranobe или text для
  akashic/british), chapter, link. Последний шаг (link) запускает
  Telegraph-upload, sync БД и переход в NotifyUsers FSM.
- 2 FSM-шага delete: id, chapter (последний DELETE'ит из БД и sync'ит
  снепшот для WebApp).
- 1 handler на `notify_*` — рассылка по закладкам или всем пользователям.

Тяжёлые cross-dependencies (`sync_reader_snapshot`, `get_cached_reader_data`,
`build_reader_data`, database-функции для уведомлений) — lazy-imported
внутри handler'ов через `import bot`, чтобы не создавать cyclic import на
top-level. Это безопасно т.к. handler'ы вызываются runtime, когда bot.py
уже полностью загружен; `dp.include_router(...)` тоже выполняется только
в `main()`.
"""

from __future__ import annotations

import json
import logging

import aiosqlite
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import delete_art_by_id, get_admins
from services.content_metadata import CONTENT_TYPES, get_langs_menu, get_ranobe_langs_menu
from services.reader_cache import invalidate_reader_cache
from services.telegraph import upload_to_telegraph
from services.telegram_helpers import escape_html_text
from services.validators import _clean_urls
from utils import run_git_sync, spawn_bg


class UniversalContentUpload(StatesGroup):
    """Единый FSM для добавления контента (manga, ranobe, akashic, british).

    Шаги:
    - `waiting_for_id` — язык (callback `ucadd_<code>`) или номер тома (text).
    - `waiting_for_chapter` — номер/название главы.
    - `waiting_for_link` — ссылка(и) или текст для Telegraph-upload.
    """

    waiting_for_id = State()
    waiting_for_chapter = State()
    waiting_for_link = State()


class UniversalContentDelete(StatesGroup):
    """Единый FSM для удаления контента."""

    waiting_for_id = State()
    waiting_for_chapter = State()


class NotifyUsers(StatesGroup):
    """FSM рассылки: после публикации главы — выбор получателей."""

    waiting_for_decision = State()


content_router = Router()


# ===========================================================================
# Команды добавления контента
# ===========================================================================


@content_router.message(Command("add_chapter"))
async def cmd_add_chapter(message: types.Message, state: FSMContext):
    """`/add_chapter` — выбрать язык манги и ввести главу."""
    admins = await get_admins()
    if message.from_user.id not in admins:
        return
    await state.update_data(content_type='manga')
    await state.set_state(UniversalContentUpload.waiting_for_id)
    await message.answer("Выберите язык:", reply_markup=get_langs_menu("ucadd"))


@content_router.message(Command("add_ranobe"))
async def cmd_add_ranobe(message: types.Message, state: FSMContext):
    """`/add_ranobe` — выбрать тайтл ранобэ и ввести главу."""
    admins = await get_admins()
    if message.from_user.id not in admins:
        return
    await state.update_data(content_type='ranobe')
    await state.set_state(UniversalContentUpload.waiting_for_id)
    await message.answer("Выберите ранобэ:", reply_markup=get_ranobe_langs_menu("ucadd"))


@content_router.message(Command("add_akashic"))
async def cmd_add_akashic(message: types.Message, state: FSMContext):
    """`/add_akashic` — добавить главу Хроник Акаши."""
    admins = await get_admins()
    if message.from_user.id not in admins:
        return
    await state.update_data(content_type='akashic')
    await state.set_state(UniversalContentUpload.waiting_for_id)
    await message.answer("📖 <b>Добавление Хроник Акаши</b>\nВведите номер тома (число):", parse_mode="HTML")


@content_router.message(Command("add_british"))
async def cmd_add_british(message: types.Message, state: FSMContext):
    """`/add_british` — добавить главу Британской красавицы."""
    admins = await get_admins()
    if message.from_user.id not in admins:
        return
    await state.update_data(content_type='british')
    await state.set_state(UniversalContentUpload.waiting_for_id)
    await message.answer("👸 <b>Добавление Британской красавицы</b>\nВведите номер тома (число):", parse_mode="HTML")


# ===========================================================================
# FSM upload шаги
# ===========================================================================


@content_router.callback_query(UniversalContentUpload.waiting_for_id, F.data.startswith("ucadd_"))
async def uc_upload_id_callback(callback: types.CallbackQuery, state: FSMContext):
    """Manga/Ranobe: выбор языка через inline-кнопку."""
    await state.update_data(content_id=callback.data.split("_", 1)[1])
    await state.set_state(UniversalContentUpload.waiting_for_chapter)
    data = await state.get_data()
    prompt = "Введите номер главы (или название, слитно):" if data.get('content_type') == 'ranobe' else "Введите номер главы:"
    await callback.message.edit_text(prompt)


@content_router.message(UniversalContentUpload.waiting_for_id)
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


@content_router.message(UniversalContentUpload.waiting_for_chapter)
async def uc_upload_chapter(message: types.Message, state: FSMContext):
    """Получить номер/название главы и перейти к вводу ссылки."""
    await state.update_data(chapter=message.text.strip())
    await state.set_state(UniversalContentUpload.waiting_for_link)
    await message.answer("🔗 Отправьте ссылку на главу (можно несколько ссылок, каждую с новой строки, " "если глава разделена):")


@content_router.message(UniversalContentUpload.waiting_for_link, F.text)
async def uc_upload_link(message: types.Message, state: FSMContext):
    """Финальный шаг upload: сохранить ссылку(и) в БД, синхронизировать WebApp.

    Логика:
    1. Если в сообщении есть ссылки — сохраняем как есть.
    2. Если текст >20 символов без ссылок — конвертируем в Telegraph-страницу.
    3. Иначе fallback: сохраняем текст как есть.

    После сохранения — invalidate кеш, записать JSON snapshot для WebApp,
    запушить в GitHub (background). Затем перейти в `NotifyUsers` FSM для
    выбора получателей уведомления.
    """
    # Lazy import чтобы избежать cyclic с bot.py. Handler вызывается только
    # в runtime, когда bot.py полностью загружен.
    import bot

    data = await state.get_data()
    ctype = data.get('content_type', 'manga')
    ct = CONTENT_TYPES.get(ctype, CONTENT_TYPES['manga'])
    content_id = data.get('content_id', '')
    chapter = data.get('chapter', '')
    text_input = message.html_text.strip()

    links = _clean_urls(text_input)

    if links:
        link = " ".join(links)
    elif len(text_input) > 20:
        # Чистый текст главы без ссылок -> собираем Telegraph-страницу.
        wait_msg = await message.answer("📝 <i>Готовлю страницу Telegraph...</i>", parse_mode="HTML")
        id_label = ct['names_map'].get(str(content_id), str(content_id)) if ct['names_map'] else f"Том {content_id}"
        title = f"{ct['emoji']} {ct['name']} — {id_label}, Глава {chapter}"
        new_link = await upload_to_telegraph(title, text_input)
        if new_link:
            link = new_link
            await wait_msg.delete()
        else:
            await wait_msg.edit_text("⚠️ Не удалось загрузить в Телеграф, сохраняю как есть.")
            link = text_input  # Fallback
    else:
        # Совсем короткий текст без ссылок — сохраняем как есть.
        link = text_input

    async with aiosqlite.connect(bot.DB_PATH) as db:
        # Получаем текущий макс. sort_order для этого тайтла/тома
        async with db.execute(f'SELECT MAX(sort_order) FROM {ct["table"]} WHERE {ct["id_col"]} = ?', (content_id,)) as cursor:
            row = await cursor.fetchone()
            next_order = (row[0] or 0) + 1 if row else 1

        await db.execute(
            f'INSERT INTO {ct["table"]} ({ct["id_col"]}, {ct["chapter_col"]}, {ct["url_col"]}, sort_order) '
            f'VALUES (?, ?, ?, ?) '
            f'ON CONFLICT({ct["id_col"]}, {ct["chapter_col"]}) DO UPDATE SET {ct["url_col"]}=excluded.{ct["url_col"]}',
            (content_id, chapter, link, next_order),
        )
        await db.commit()

    # СИНХРОНИЗАЦИЯ: Обновляем JSON и пушим в GitHub
    try:
        invalidate_reader_cache("chapter_uploaded_via_bot")
        result, _, _ = await bot.get_cached_reader_data(force_refresh=True)
        with open("webapp/chapters_data.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        spawn_bg(run_git_sync(f"tg upload sync: {content_id}"), name="run_git_sync:tg_upload")
    except Exception as e:  # noqa: BLE001 — sync-сбой не должен ломать upload, только логируем.
        logging.error(f"Sync error: {e}")

    # Формируем имя для уведомления
    id_label = ct['names_map'].get(str(content_id), str(content_id)) if ct['names_map'] else f"Том {content_id}"
    await message.answer(f"✅ {ct['emoji']} {ct['name']}: глава {chapter} ({id_label}) добавлена!\n🔗 Ссылка: {link}")

    builder = InlineKeyboardBuilder()
    builder.button(text="🔔 Разослать по закладкам", callback_data="notify_bookmarks")
    builder.button(text="📢 Разослать ВСЕМ", callback_data="notify_all")
    builder.button(text="❌ Отмена", callback_data="notify_no")
    builder.adjust(1)
    series_key = (
        f"manga_{content_id}"
        if ctype == "manga"
        else f"ranobe_{content_id}"
        if ctype == "ranobe"
        else "akashic_records"
        if ctype == "akashic"
        else "british_belle"
        if ctype == "british"
        else str(content_id)
    )

    await state.set_state(NotifyUsers.waiting_for_decision)
    safe_id_label = escape_html_text(id_label)
    safe_chapter = escape_html_text(chapter)
    safe_link = escape_html_text(link)
    await state.update_data(
        notify_text=f"{ct['emoji']} <b>Вышла новая глава {ct['name']}!</b>\n{safe_id_label}, Глава {safe_chapter}\n🔗 {safe_link}",
        series_id=series_key,
    )
    await message.answer("Выберите способ уведомления:", reply_markup=builder.as_markup())


# ===========================================================================
# Уведомления после публикации главы
# ===========================================================================


@content_router.callback_query(NotifyUsers.waiting_for_decision, F.data.startswith("notify_"))
async def process_notification_decision(callback: types.CallbackQuery, state: FSMContext):
    """После публикации — выбор получателей: по закладкам / всем / отмена."""
    import asyncio

    from database import get_all_users, get_users_with_bookmark

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
            await callback.bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")
            count += 1
            await asyncio.sleep(0.05)
        except Exception as e:  # noqa: BLE001 — типичный "chat not found"/"forbidden", это не ошибка.
            logging.debug(f"notifications: failed to send to {user_id}: {e}")

    await callback.message.answer(f"✅ Рассылка завершена!\nСообщение получили <b>{count}</b> пользователей.", parse_mode="HTML")


# ===========================================================================
# Команды удаления контента
# ===========================================================================


@content_router.message(Command("delete_chapter"))
async def cmd_delete_chapter(message: types.Message, state: FSMContext):
    """`/delete_chapter` — удалить главу манги."""
    admins = await get_admins()
    if message.from_user.id not in admins:
        return
    await state.update_data(content_type='manga')
    await state.set_state(UniversalContentDelete.waiting_for_id)
    await message.answer("Выберите язык для удаления главы манги:", reply_markup=get_langs_menu("ucdel"))


@content_router.message(Command("delete_ranobe"))
async def cmd_delete_ranobe(message: types.Message, state: FSMContext):
    """`/delete_ranobe` — удалить главу ранобэ."""
    admins = await get_admins()
    if message.from_user.id not in admins:
        return
    await state.update_data(content_type='ranobe')
    await state.set_state(UniversalContentDelete.waiting_for_id)
    await message.answer("Выберите ранобэ для удаления главы:", reply_markup=get_ranobe_langs_menu("ucdel"))


@content_router.message(Command("delete_akashic"))
async def cmd_delete_akashic(message: types.Message, state: FSMContext):
    """`/delete_akashic` — удалить главу Хроник Акаши."""
    admins = await get_admins()
    if message.from_user.id not in admins:
        return
    await state.update_data(content_type='akashic')
    await state.set_state(UniversalContentDelete.waiting_for_id)
    await message.answer("🗑 <b>Удаление Хроник Акаши</b>\nВведите номер тома (число):", parse_mode="HTML")


@content_router.message(Command("delete_british"))
async def cmd_delete_british(message: types.Message, state: FSMContext):
    """`/delete_british` — удалить главу Британской красавицы."""
    admins = await get_admins()
    if message.from_user.id not in admins:
        return
    await state.update_data(content_type='british')
    await state.set_state(UniversalContentDelete.waiting_for_id)
    await message.answer("🗑 <b>Удаление Британской красавицы</b>\nВведите номер тома (число):", parse_mode="HTML")


@content_router.message(Command("delete_art"))
async def cmd_delete_art(message: types.Message):
    """`/delete_art <id>` — удалить арт из БД по числовому id."""
    admins = await get_admins()
    if message.from_user.id not in admins:
        return
    try:
        art_id = int(message.text.split()[1])
        if await delete_art_by_id(art_id):
            await message.answer(f"✅ Арт с ID {art_id} успешно удален.")
        else:
            await message.answer(f"❌ Арт с ID {art_id} не найден.")
    except (IndexError, ValueError):
        await message.answer("❌ Формат: /delete_art <ID_арта>")


# ===========================================================================
# FSM delete шаги
# ===========================================================================


@content_router.callback_query(UniversalContentDelete.waiting_for_id, F.data.startswith("ucdel_"))
async def uc_delete_id_callback(callback: types.CallbackQuery, state: FSMContext):
    """Manga/Ranobe: выбор языка для удаления через inline-кнопку."""
    await state.update_data(content_id=callback.data.split("_", 1)[1])
    await state.set_state(UniversalContentDelete.waiting_for_chapter)
    await callback.message.edit_text("Введите номер/название главы для удаления:")


@content_router.message(UniversalContentDelete.waiting_for_id)
async def uc_delete_id_text(message: types.Message, state: FSMContext):
    """Akashic/British: ввод номера тома текстом для удаления."""
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


@content_router.message(UniversalContentDelete.waiting_for_chapter)
async def uc_delete_chapter(message: types.Message, state: FSMContext):
    """Финальный шаг delete: DELETE из БД + sync WebApp snapshot."""
    import bot

    data = await state.get_data()
    ctype = data.get('content_type', 'manga')
    ct = CONTENT_TYPES.get(ctype, CONTENT_TYPES['manga'])
    content_id = data.get('content_id', '')
    chapter = message.text.strip()

    async with aiosqlite.connect(bot.DB_PATH) as db:
        cursor = await db.execute(
            f'DELETE FROM {ct["table"]} WHERE {ct["chapter_col"]} = ? AND {ct["id_col"]} = ?',
            (chapter, content_id),
        )
        deleted = cursor.rowcount > 0
        id_label = ct['names_map'].get(str(content_id), str(content_id)) if ct['names_map'] else f"Том {content_id}"
        if deleted:
            await message.answer(f"✅ {ct['emoji']} {ct['name']}: глава {chapter} ({id_label}) успешно удалена из базы!")
        else:
            await message.answer(f"❌ {ct['emoji']} {ct['name']}: глава {chapter} ({id_label}) не найдена!")
        await db.commit()
    if deleted:
        await bot.sync_reader_snapshot(f"delete chapter via fsm: {ctype}_{content_id}_{chapter}")
    await state.clear()
