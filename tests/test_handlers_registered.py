"""Smoke-тест регистрации Telegram-хендлеров.

Ловит баги класса:
  - забыли зарегистрировать `@dp.message(Command("X"))` — команда не отвечает;
  - случайно зарегистрировали одну и ту же команду дважды;
  - переопределили функцию-хендлер (shadowing), из-за чего в Dispatcher
    попал не тот callable — так было с `_is_bot_admin`.

Тест импортирует `bot` как модуль (без запуска polling), собирает
зарегистрированные хендлеры и валидирует инварианты.
"""

from __future__ import annotations

import re

import pytest


@pytest.fixture(scope="module")
def bot_module():
    """Импорт `bot` вызывает все `@dp.message(...)` декораторы,
    т. е. сразу же регистрирует хендлеры в Dispatcher'е.
    """
    import bot  # noqa: F401 — импорт ради side-effects регистрации

    return bot


def _iter_message_handlers(bot_module):
    """Возвращает `(filters, callback)` для всех message-хендлеров
    из встроенного router-а Dispatcher'а + всех подключённых роутеров.

    Доп. подключает известные module-level роутеры, которые attach'атся к
    Dispatcher только в `main()` (и потому недоступны при чистом импорте bot).
    """
    dp = bot_module.dp
    seen = []
    stack = [dp]
    # В aiogram 3 `Dispatcher` сам является роутером; подключённые
    # роутеры лежат в `.sub_routers` (или просто имеют свой message.handlers).
    # Дополнительно добавляем router'ы, которые attached только в main().
    try:
        from services.admin_art_fsm import art_router

        stack.append(art_router)
    except ImportError:
        pass
    try:
        from services.admin_telegram import admin_router

        stack.append(admin_router)
    except ImportError:
        pass
    try:
        from services.admin_content import content_router

        stack.append(content_router)
    except ImportError:
        pass
    try:
        from services.admin_rename import rename_router

        stack.append(rename_router)
    except ImportError:
        pass
    try:
        from services.admin_settings import settings_router

        stack.append(settings_router)
    except ImportError:
        pass
    try:
        from services.art_view import art_view_router

        stack.append(art_view_router)
    except ImportError:
        pass
    while stack:
        router = stack.pop()
        for h in router.message.handlers:
            seen.append(h)
        stack.extend(getattr(router, "sub_routers", []))
    return seen


def _extract_command_strings(handler) -> list[str]:
    """Пытается вытащить список `/command` строк из фильтров хендлера.
    Работает через repr — это hacky, но в aiogram 3 у `Command`-фильтра
    атрибуты хранят кортеж command-ов.
    """
    commands: list[str] = []
    for f in handler.filters:
        callback = getattr(f, "callback", f)
        # aiogram.filters.Command хранит строки в .commands
        cmds = getattr(callback, "commands", None)
        if cmds:
            for c in cmds:
                # c может быть str или CommandPatternType; берём .command атрибут либо str
                cmd_str = getattr(c, "command", None) or str(c)
                if isinstance(cmd_str, str):
                    commands.append(cmd_str.lstrip("/"))
        # fallback — парсим repr
        if not cmds:
            r = repr(callback)
            for m in re.finditer(r"command=['\"]([a-z_]+)['\"]", r):
                commands.append(m.group(1))
    return commands


# ---------- Ожидаемый набор команд ----------
# Если добавишь новую команду — допиши сюда. Если хендлер удаляется
# намеренно — тоже удаляется отсюда. Так тест служит живым списком.
EXPECTED_COMMANDS = {
    # Пользовательские
    "start",
    "cancel",
    "feed",
    "pet",
    "suggest_art",
    "arts_list",
    # Админ-панель (эти должны работать после shadowing-фикса `_is_bot_admin`)
    "admin",
    "add_admin",
    "delete_admin",
    # Админ-контент
    "add_chapter",
    "delete_chapter",
    "add_ranobe",
    "delete_ranobe",
    "add_akashic",
    "delete_akashic",
    "add_british",
    "delete_british",
    "add_art",
    "delete_art",
    # Админ-ссылки и тогглы
    "set_commands_link",
    "delete_commands_link",
    "sync_webapp",
    "toggle_sync",
    "alya_mode",
    "toggle_ai",
    "blacklist_ai",
    "unblacklist_ai",
    "blacklist_view",
    # Модерация
    "ban",
    "unban",
    "mute",
    "unmute",
    "kick",
    "clean",
    "cleanup_service",
    # Служебные
    "finish",
}


def test_handlers_import_cleanly(bot_module):
    """Сам факт: модуль `bot` импортируется без ошибок (нет SyntaxError,
    круговых импортов или падения на top-level side-effect'ах)."""
    assert bot_module.dp is not None
    assert bot_module.bot is not None


def test_no_duplicate_command_registrations(bot_module):
    """Каждая /command должна быть зарегистрирована ровно один раз.
    Дубли ведут к тому, что Dispatcher вызывает только первый хендлер,
    а второй — мёртвый код / забытая дубляшка."""
    handlers = _iter_message_handlers(bot_module)
    cmd_count: dict[str, int] = {}
    for h in handlers:
        for cmd in _extract_command_strings(h):
            cmd_count[cmd] = cmd_count.get(cmd, 0) + 1
    dupes = {c: n for c, n in cmd_count.items() if n > 1}
    assert not dupes, f"Duplicate command registrations: {dupes}"


def test_core_admin_commands_registered(bot_module):
    """Узкий и конкретный тест — базовые админ-команды зарегистрированы.
    Именно `/admin` исторически молчал из-за shadowing `_is_bot_admin`.
    """
    handlers = _iter_message_handlers(bot_module)
    all_cmds: set[str] = set()
    for h in handlers:
        all_cmds.update(_extract_command_strings(h))
    for must_have in ("admin", "start", "add_admin", "delete_admin"):
        assert must_have in all_cmds, f"Command /{must_have} is not registered"


def test_expected_command_set_is_complete(bot_module):
    """Сравниваем ожидаемый набор команд со списком, реально
    попавшим в Dispatcher. Позволяет ловить:
      (a) тихое удаление хендлера (не должен был исчезнуть);
      (b) тихое добавление новой команды (надо обновить EXPECTED_COMMANDS
          или выложить список в `/commands_list.txt`).
    """
    handlers = _iter_message_handlers(bot_module)
    actual: set[str] = set()
    for h in handlers:
        actual.update(_extract_command_strings(h))

    missing = EXPECTED_COMMANDS - actual
    extra = actual - EXPECTED_COMMANDS
    assert not missing, f"Expected commands not registered: {sorted(missing)}"
    # `extra` — не fail, а warning-подсказка: можно добавить в EXPECTED_COMMANDS.
    if extra:
        print(f"\n[info] new commands not yet in EXPECTED_COMMANDS: {sorted(extra)}")


def test_admin_handler_is_the_right_function(bot_module):
    """Защита от повторения shadowing-бага: `cmd_admin` должен принимать
    `(message, state)`, а не `(chat_id)`. Если кто-то добавит вторую
    функцию с тем же именем и сигнатурой (chat_id), тест завалится."""
    from inspect import signature

    cmd_admin = getattr(bot_module, "cmd_admin", None)
    assert cmd_admin is not None, "cmd_admin function must exist in bot module"
    params = list(signature(cmd_admin).parameters)
    assert params[0] == "message", f"cmd_admin first param should be `message`, got {params}"
    assert "state" in params, f"cmd_admin must take FSMContext `state`, got {params}"

    # Проверяем, что `_is_bot_admin` принимает user_id, а не chat_id —
    # buy-back от истории (имя раньше было переопределено).
    is_bot_admin = getattr(bot_module, "_is_bot_admin", None)
    assert is_bot_admin is not None
    admin_params = list(signature(is_bot_admin).parameters)
    assert admin_params == ["user_id"], f"_is_bot_admin must accept exactly `user_id`, got {admin_params}"
