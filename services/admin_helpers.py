"""Security-слой admin-панели: проверка прав и fake-Message фабрика.

Чистые helper'ы без aiogram-handler'ов, без router'а. Могут использоваться как
в `bot.py` (через re-export), так и в будущих `services/admin_telegram/*`
модулях через top-level import без риска повторного импорта `bot.py`.

Вынесено из `bot.py` как шаг Фазы 3 шаг B.1 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).

Что здесь:

- `MAIN_ADMIN_ID` — хард-кодед id главного админа; его нельзя удалить.
- `_is_bot_admin(user_id)` — `True` если `user_id` в таблице `admins` БД.
- `_require_admin(event)` — единая проверка для Message/CallbackQuery:
  сообщение — молча возвращает `False`; callback — отвечает `🚫 Нет прав`.
- `_fake_admin_message(callback, text)` — строит fake `types.Message` с
  подменённым `from_user` и `text`, чтобы callback `admin_cmd_*` мог
  проксировать вызов к `@dp.message(Command("X"))` handler'у.
"""

from __future__ import annotations

import logging
from typing import Union

from aiogram import types

from database import get_admins

MAIN_ADMIN_ID = 6210312655


async def _is_bot_admin(user_id: int) -> bool:
    """True если user_id в списке админов бота.

    Единственная точка правды для проверки admin-статуса. Исторически был
    shadowing-баг: в bot.py существовала вторая функция с той же сигнатурой,
    из-за чего `/admin` молчал (см. `scripts/check_no_shadowing.py`).
    """
    try:
        admins = await get_admins()
        is_admin = user_id in admins
        logging.debug(f"_is_bot_admin: uid={user_id} is_admin={is_admin} admins={admins}")
        return is_admin
    except Exception as e:  # noqa: BLE001 — отказ БД ⇒ no admin access.
        logging.warning(f"_is_bot_admin: get_admins failed: {e}")
        return False


async def _require_admin(event: Union[types.Message, types.CallbackQuery]) -> bool:
    """Единая проверка прав админа.

    - Для `Message` — молча возвращает `False` (не спамим в чат).
    - Для `CallbackQuery` — отвечает через `answer("🚫 Нет прав.")` и
      возвращает `False`. Это нужно чтобы пользователь не видел бесконечный
      loading spinner после нажатия кнопки в старом/чужом admin-сообщении.
    """
    uid = event.from_user.id if event.from_user else 0
    if await _is_bot_admin(uid):
        return True
    if isinstance(event, types.CallbackQuery):
        try:
            await event.answer("🚫 Нет прав.", show_alert=False)
        except Exception:  # noqa: BLE001 — aiogram может уже закрыть callback.
            pass
    return False


def _fake_admin_message(callback: types.CallbackQuery, text: str) -> types.Message | None:
    """Фабрика fake-Message для проксирования callback → `@dp.message(Command)`.

    Зачем: админское inline-меню (`admin_cmd_*`) должно вызывать те же
    handler'ы что и slash-команды (`/add_chapter`, `/sync_webapp`, …).
    Вместо дублирования логики строим новый `types.Message`, копируя
    `callback.message` и подменяя `from_user` (чтобы проверки прав увидели
    реального админа, а не бота) и `text` (на нужную команду).

    Возвращает `None` если построить fake-Message не удалось — caller должен
    показать пользователю alert вроде "⚠️ Не удалось запустить действие".

    NB: безопасная замена старого `model_copy` hack'а — пробуем сначала
    pydantic v2 API, затем v1 fallback (на случай смены версии aiogram).
    """
    msg = callback.message
    if not isinstance(msg, types.Message):
        return None
    try:
        # aiogram 3.x — pydantic v2
        return msg.model_copy(update={"from_user": callback.from_user, "text": text})
    except Exception:  # noqa: BLE001 — fall through to v1.
        try:
            # pydantic v1 fallback
            return msg.copy(update={"from_user": callback.from_user, "text": text})
        except Exception as e:  # noqa: BLE001 — last resort.
            logging.warning(f"_fake_admin_message: build failed: {e}")
            return None
