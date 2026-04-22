"""Admin rename FSM: изменение кастомного названия тайтла/тома/главы из WebApp.

Вынесено из `bot.py` как шаг Фазы 3 B.6.

Сценарий:

1. WebApp отправляет deeplink вида `t.me/<bot>?start=rename_<obj_id>`,
   который запускает `start`-handler (в bot.py) и ставит
   `AdminRename.waiting_for_name` state с `rename_id` в FSM data.
2. Админ отправляет новое название сообщением.
3. `process_rename_name` валидирует, сохраняет в таблицу `custom_names`,
   инвалидирует кеш, пушит JSON-снепшот в GitHub Pages.

Модуль экспортирует:

- `rename_router` — нужно подключить через `dp.include_router(...)`
  в `main()` bot.py. Side-effect импорта регистрирует `process_rename_name`.
- `AdminRename` — FSM class, re-export для тестов и `/start` deeplink-handler'а.
"""

from __future__ import annotations

import json
import logging
import traceback

from aiogram import Router, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import set_custom_name
from services.reader_cache import invalidate_reader_cache
from services.telegram_helpers import escape_html_text
from utils import run_git_sync


class AdminRename(StatesGroup):
    """FSM для rename-потока из WebApp."""

    waiting_for_name = State()


rename_router = Router()


@rename_router.message(StateFilter(AdminRename.waiting_for_name))
async def process_rename_name(message: types.Message, state: FSMContext):
    """Сохранить новое имя объекта (серии/тома/главы) и засинхронить WebApp.

    Если пользователь внезапно отправил команду (`/...`) — отмена FSM.
    Пустое имя отсекаем, иначе удалим предыдущее кастомное (раньше тут была
    другая бага: `new_name` вообще не присваивалась → NameError при любом
    вводе — fix в истории).
    """
    # Lazy import чтобы избежать cyclic с bot.py. Handler вызывается только
    # в runtime, когда bot.py полностью загружен.
    import bot

    if message.text and message.text.startswith('/'):
        await state.clear()
        return

    data = await state.get_data()
    obj_id = data.get('rename_id')

    if not obj_id:
        await state.clear()
        return await message.answer("❌ Ошибка: ID объекта не найден.")

    new_name = (message.text or "").strip()
    if not new_name:
        return await message.answer("❌ Новое название не может быть пустым.")

    try:
        await set_custom_name(obj_id, new_name)
        invalidate_reader_cache("custom_name_changed")
        await state.clear()
        safe_new_name = escape_html_text(new_name)

        msg = await message.answer(
            f"✅ Успешно! Новое название:\n<b>{safe_new_name}</b>\n\n" "🔄 <i>Синхронизирую изменения с Github Pages...</i>",
            parse_mode="HTML",
        )

        # Синхронизация JSON snapshot для WebApp.
        result, _, _ = await bot.get_cached_reader_data(force_refresh=True)

        with open("webapp/chapters_data.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        success, output = await run_git_sync("sync webapp renamed item")
        if success:
            await msg.edit_text(
                "✅ <b>Готово!</b> Название сохранено.\n\n" "Вы можете открыть читалку и проверить результат.",
                parse_mode="HTML",
            )
        else:
            await msg.edit_text(
                f"⚠️ База обновлена локально, но <code>git push</code> не прошел.\n\n"
                f"<b>Ответ сервера:</b>\n<pre>{escape_html_text(output)}</pre>",
                parse_mode="HTML",
            )

    except Exception as e:  # noqa: BLE001 — логируем любую ошибку и показываем админу.
        err_msg = traceback.format_exc()
        logging.error(f"process_rename_name failed: {e}")
        await message.answer(
            f"❌ <b>Ошибка:</b> {escape_html_text(e)}\n<pre>{escape_html_text(err_msg)}</pre>",
            parse_mode="HTML",
        )
