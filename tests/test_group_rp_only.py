import asyncio

import pytest


def run(coro):
    return asyncio.run(coro)


def test_rp_only_group_setting_roundtrip(tmp_path, monkeypatch):
    import database

    db_path = str(tmp_path / "rp-only.db")
    monkeypatch.setattr(database, "DB_PATH", db_path)

    run(database.init_db())

    assert run(database.is_rp_only_group(-1001)) is False
    assert run(database.set_rp_only_group(-1001, True)) is True
    assert run(database.is_rp_only_group(-1001)) is True
    assert run(database.set_rp_only_group(-1001, False)) is False
    assert run(database.is_rp_only_group(-1001)) is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/profile", False),
        ("/start@Alyamangapage_bot", False),
        ("/rp_only status", True),
        ("обнять", True),
        ("/обнять", True),
        ("*поцеловать мило", True),
        ("обычный текст", False),
    ],
)
def test_rp_only_allows_only_rp_and_control_commands(text, expected):
    from services.group_rp_only import is_allowed_in_rp_only_mode

    assert is_allowed_in_rp_only_mode(text) is expected


def test_rp_only_mode_does_not_filter_private_messages():
    from services.group_rp_only import should_block_message_in_rp_only_mode

    assert should_block_message_in_rp_only_mode("private", True, "/profile") is False


def test_rp_only_mode_blocks_group_commands_when_enabled():
    from services.group_rp_only import should_block_message_in_rp_only_mode

    assert should_block_message_in_rp_only_mode("supergroup", True, "/profile") is True
    assert should_block_message_in_rp_only_mode("supergroup", True, "/rp_only status") is False
    assert should_block_message_in_rp_only_mode("supergroup", True, "обнять") is False
    assert should_block_message_in_rp_only_mode("supergroup", False, "/profile") is False
