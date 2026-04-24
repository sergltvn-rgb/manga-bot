from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest


def run(coro):
    return asyncio.run(coro)


class TestGiveawayTimeParsing:
    def test_parse_absolute_moscow_time_to_utc(self):
        from services.giveaways import parse_giveaway_end

        now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)

        result = parse_giveaway_end("27.04.2026 20:00", now=now)

        assert result == datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc)

    def test_parse_duration_hours_to_utc(self):
        from services.giveaways import parse_giveaway_end

        now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)

        result = parse_giveaway_end("12h", now=now)

        assert result == datetime(2026, 4, 25, 0, 0, tzinfo=timezone.utc)

    def test_parse_duration_days_to_utc(self):
        from services.giveaways import parse_giveaway_end

        now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)

        result = parse_giveaway_end("3d", now=now)

        assert result == datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)

    def test_rejects_past_absolute_time(self):
        from services.giveaways import GiveawayValidationError, parse_giveaway_end

        now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)

        with pytest.raises(GiveawayValidationError):
            parse_giveaway_end("24.04.2026 10:00", now=now)

    def test_rejects_bad_format(self):
        from services.giveaways import GiveawayValidationError, parse_giveaway_end

        with pytest.raises(GiveawayValidationError):
            parse_giveaway_end("tomorrow")

    def test_quick_create_accepts_leading_pipe_format(self):
        from services.giveaways import _parse_quick_create

        ends_at, winners_count, prize, post_text = _parse_quick_create("/giveaway_create | 27.04.2026 20:00 | 3 | VIP | Участвуем")

        assert ends_at == datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc)
        assert winners_count == 3
        assert prize == "VIP"
        assert post_text == "Участвуем"

    def test_quick_create_derives_winners_from_place_prizes(self):
        from services.giveaways import _parse_quick_create_with_channel, split_place_prizes

        channel_id, ends_at, winners_count, prize, post_text = _parse_quick_create_with_channel(
            "/giveaway_create @test_channel | 27.04.2026 20:00 | 1 место: VIP; 2 место: 500 монет | Текст"
        )

        assert channel_id == "@test_channel"
        assert ends_at == datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc)
        assert winners_count == 2
        assert split_place_prizes(prize) == ["VIP", "500 монет"]
        assert post_text == "Текст"


class TestGiveawayDb:
    def test_create_giveaway_and_unique_entries(self, tmp_path, monkeypatch):
        import database

        from services import giveaways

        db_path = str(tmp_path / "giveaways.db")
        monkeypatch.setattr(database, "DB_PATH", db_path)

        run(database.init_db())
        giveaway_id = run(
            giveaways.create_giveaway(
                channel_id="@alya_novel",
                prize="VIP title",
                post_text="Test giveaway",
                winners_count=2,
                ends_at_utc=datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc),
                created_by=6210312655,
                media_type="photo",
                media_file_id="file-1",
            )
        )

        first = run(giveaways.add_giveaway_entry(giveaway_id, 1001, "alice", "Alice"))
        duplicate = run(giveaways.add_giveaway_entry(giveaway_id, 1001, "alice", "Alice"))
        second = run(giveaways.add_giveaway_entry(giveaway_id, 1002, None, "Bob"))
        entries = run(giveaways.get_giveaway_entries(giveaway_id))

        assert first is True
        assert duplicate is False
        assert second is True
        assert [entry.user_id for entry in entries] == [1001, 1002]

    def test_due_active_giveaways_and_finish_are_idempotent(self, tmp_path, monkeypatch):
        import database

        from services import giveaways

        db_path = str(tmp_path / "giveaways.db")
        monkeypatch.setattr(database, "DB_PATH", db_path)

        run(database.init_db())
        giveaway_id = run(
            giveaways.create_giveaway(
                channel_id="@alya_novel",
                prize="Prize",
                post_text="Post",
                winners_count=1,
                ends_at_utc=datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc),
                created_by=6210312655,
            )
        )
        run(giveaways.set_giveaway_published(giveaway_id, 42))

        due = run(giveaways.list_due_giveaways(datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)))
        first_finish = run(giveaways.mark_giveaway_finished(giveaway_id))
        second_finish = run(giveaways.mark_giveaway_finished(giveaway_id))

        assert [item.id for item in due] == [giveaway_id]
        assert first_finish is True
        assert second_finish is False

    def test_verification_challenge_passes_only_correct_answer(self, tmp_path, monkeypatch):
        import database

        from services import giveaways

        db_path = str(tmp_path / "giveaways.db")
        monkeypatch.setattr(database, "DB_PATH", db_path)

        run(database.init_db())
        challenge = run(giveaways.create_giveaway_verification_challenge(1, 1001, answer_factory=lambda: ("2 + 2", "4", ["3", "4", "5"])))

        assert challenge.question == "2 + 2"
        assert challenge.options == ["3", "4", "5"]
        assert run(giveaways.is_giveaway_verified(1, 1001)) is False
        assert run(giveaways.verify_giveaway_answer(1, 1001, "3")) is False
        assert run(giveaways.verify_giveaway_answer(1, 1001, "4")) is True
        assert run(giveaways.is_giveaway_verified(1, 1001)) is True


class TestGiveawayWinnerSelection:
    def test_selects_only_current_subscribers_and_counts_replacements(self):
        from services.giveaways import GiveawayEntry, select_winners

        entries = [
            GiveawayEntry(1, 10, "u10", "Ten", "joined", False),
            GiveawayEntry(1, 11, "u11", "Eleven", "joined", False),
            GiveawayEntry(1, 12, "u12", "Twelve", "joined", False),
        ]

        async def is_subscribed(user_id: int) -> bool:
            return user_id != 10

        result = run(select_winners(entries, 2, is_subscribed=is_subscribed, shuffle=lambda values: values))

        assert [entry.user_id for entry in result.winners] == [11, 12]
        assert result.replaced_count == 1

    def test_selects_all_available_when_not_enough_entries(self):
        from services.giveaways import GiveawayEntry, select_winners

        entries = [GiveawayEntry(1, 20, "u20", "Twenty", "joined", False)]

        async def is_subscribed(user_id: int) -> bool:
            return True

        result = run(select_winners(entries, 3, is_subscribed=is_subscribed, shuffle=lambda values: values))

        assert [entry.user_id for entry in result.winners] == [20]
        assert result.replaced_count == 0

    def test_winner_lines_include_place_specific_prizes(self):
        from services.giveaways import GiveawayEntry, format_winner_lines

        winners = [
            GiveawayEntry(1, 20, "u20", "Twenty", "joined", True),
            GiveawayEntry(1, 21, "u21", "Twenty One", "joined", True),
        ]

        lines = format_winner_lines(winners, "VIP; 500 монет")

        assert "1 место" in lines
        assert "VIP" in lines
        assert "2 место" in lines
        assert "500 монет" in lines

    def test_winner_links_do_not_use_t_me_previews(self):
        from services.giveaways import GiveawayEntry, format_winner_lines

        winners = [GiveawayEntry(1, 20, "u20", "Twenty", "joined", True)]

        lines = format_winner_lines(winners, "VIP")

        assert "tg://user?id=20" in lines
        assert "https://t.me/" not in lines

    def test_subscription_check_accepts_enum_value_status(self):
        from services.giveaways import is_channel_subscriber

        class Status:
            value = "member"

        class Member:
            status = Status()

        class BotStub:
            async def get_chat_member(self, *, chat_id, user_id):
                return Member()

        assert run(is_channel_subscriber(BotStub(), "@alya_novel", 100)) is True


class TestGiveawayPublishing:
    def test_publish_text_giveaway_uses_send_message(self):
        from services.giveaways import Giveaway, publish_giveaway_post

        class BotStub:
            def __init__(self):
                self.calls = []

            async def send_message(self, **kwargs):
                self.calls.append(("send_message", kwargs))
                return type("Msg", (), {"message_id": 55})()

        giveaway = Giveaway(
            id=1,
            status="draft",
            channel_id="@alya_novel",
            message_id=None,
            prize="Prize",
            post_text="Post text",
            winners_count=1,
            ends_at_utc=datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc),
            created_by=6210312655,
            media_type=None,
            media_file_id=None,
        )
        bot = BotStub()

        message_id = run(publish_giveaway_post(bot, giveaway))

        assert message_id == 55
        assert bot.calls[0][0] == "send_message"
        assert bot.calls[0][1]["chat_id"] == "@alya_novel"
        assert "Участвовать" in bot.calls[0][1]["reply_markup"].inline_keyboard[0][0].text
        assert "МСК" in bot.calls[0][1]["text"]
        assert "Призы" in bot.calls[0][1]["text"]
        assert bot.calls[0][1]["disable_web_page_preview"] is True

    def test_publish_photo_giveaway_uses_send_photo(self):
        from services.giveaways import Giveaway, publish_giveaway_post

        class BotStub:
            def __init__(self):
                self.calls = []

            async def send_photo(self, **kwargs):
                self.calls.append(("send_photo", kwargs))
                return type("Msg", (), {"message_id": 56})()

        giveaway = Giveaway(
            id=2,
            status="draft",
            channel_id="@alya_novel",
            message_id=None,
            prize="Prize",
            post_text="Post text",
            winners_count=1,
            ends_at_utc=datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc),
            created_by=6210312655,
            media_type="photo",
            media_file_id="photo-file",
        )
        bot = BotStub()

        message_id = run(publish_giveaway_post(bot, giveaway))

        assert message_id == 56
        assert bot.calls[0][0] == "send_photo"
        assert bot.calls[0][1]["photo"] == "photo-file"

    def test_preview_markup_has_publish_and_edit_buttons(self):
        from services.giveaways import _preview_markup

        markup = _preview_markup()
        buttons = [button.text for row in markup.inline_keyboard for button in row]

        assert "Опубликовать" in buttons
        assert "Изменить текст" in buttons
        assert "Изменить призы" in buttons
        assert "Отменить" in buttons

    def test_publish_error_formats_chat_not_found_hint(self):
        from services.giveaways import _format_publish_error

        text = _format_publish_error(Exception("Bad Request: chat not found"))

        assert "Бот не видит канал" in text
        assert "chat not found" in text
