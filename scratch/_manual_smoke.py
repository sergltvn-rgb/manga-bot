"""One-shot ручной прогон логики tests/test_handlers_registered.py без pytest.
Используется разработчиком пока `pytest` не установлен в venv.
Можно удалить после первого успешного `pytest tests/ -q`.
"""
import os
import sys
from inspect import signature

os.environ.setdefault("BOT_TOKEN", "1234567890:TEST_TOKEN_FOR_UNIT_TESTS_ONLY")
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("WEBAPP_URL", "https://example.com/")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re  # noqa: E402
import bot  # noqa: E402


def iter_message_handlers(b):
    seen = []
    stack = [b.dp]
    while stack:
        router = stack.pop()
        for h in router.message.handlers:
            seen.append(h)
        stack.extend(getattr(router, "sub_routers", []))
    return seen


def extract_command_strings(handler):
    commands = []
    for f in handler.filters:
        callback = getattr(f, "callback", f)
        cmds = getattr(callback, "commands", None)
        if cmds:
            for c in cmds:
                cmd_str = getattr(c, "command", None) or str(c)
                if isinstance(cmd_str, str):
                    commands.append(cmd_str.lstrip("/"))
        if not cmds:
            r = repr(callback)
            for m in re.finditer(r"command=['\"]([a-z_]+)['\"]", r):
                commands.append(m.group(1))
    return commands


EXPECTED_COMMANDS = {
    "start", "cancel", "feed", "pet", "suggest_art", "arts_list",
    "admin", "add_admin", "delete_admin",
    "add_chapter", "delete_chapter", "add_ranobe", "delete_ranobe",
    "add_akashic", "delete_akashic", "add_british", "delete_british",
    "add_art", "delete_art",
    "set_commands_link", "delete_commands_link", "sync_webapp", "toggle_sync",
    "alya_mode", "toggle_ai", "blacklist_ai", "unblacklist_ai", "blacklist_view",
    "ban", "unban", "mute", "unmute", "kick", "clean", "cleanup_service",
    "finish",
}

handlers = iter_message_handlers(bot)
print(f"[1] total message handlers: {len(handlers)}")

cmd_count = {}
for h in handlers:
    for c in extract_command_strings(h):
        cmd_count[c] = cmd_count.get(c, 0) + 1

dupes = {c: n for c, n in cmd_count.items() if n > 1}
print(f"[2] duplicate command regs: {dupes}")

actual = set(cmd_count)
missing = EXPECTED_COMMANDS - actual
extra = actual - EXPECTED_COMMANDS
print(f"[3] unique commands registered: {len(actual)}")
print(f"[3] missing (expected but not found): {sorted(missing)}")
print(f"[3] extra (found but not in EXPECTED_COMMANDS): {sorted(extra)}")

cmd_admin = getattr(bot, "cmd_admin", None)
print(f"[4] cmd_admin present: {cmd_admin is not None}")
if cmd_admin:
    params = list(signature(cmd_admin).parameters)
    print(f"[4] cmd_admin params: {params}")

is_bot_admin = getattr(bot, "_is_bot_admin", None)
print(f"[5] _is_bot_admin present: {is_bot_admin is not None}")
if is_bot_admin:
    params = list(signature(is_bot_admin).parameters)
    print(f"[5] _is_bot_admin params (must be ['user_id']): {params}")

ok = (
    not dupes
    and not missing
    and cmd_admin is not None
    and is_bot_admin is not None
    and list(signature(is_bot_admin).parameters) == ["user_id"]
    and list(signature(cmd_admin).parameters)[0] == "message"
)
print(f"\nRESULT: {'OK' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
