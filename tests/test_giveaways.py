from __future__ import annotations

import asyncio
import zipfile
from datetime import datetime, timezone
from io import BytesIO

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

        ends_at, winners_count, prize, post_text = _parse_quick_create("/giveaway_create | 27.04.2027 20:00 | 3 | VIP | Участвуем")

        assert ends_at == datetime(2027, 4, 27, 17, 0, tzinfo=timezone.utc)
        assert winners_count == 3
        assert prize == "VIP"
        assert post_text == "Участвуем"

    def test_quick_create_derives_winners_from_place_prizes(self):
        from services.giveaways import _parse_quick_create_with_channel, split_place_prizes

        channel_id, ends_at, winners_count, prize, post_text = _parse_quick_create_with_channel(
            "/giveaway_create @test_channel | 27.04.2027 20:00 | 1 место: VIP; 2 место: 500 монет | Текст"
        )

        assert channel_id == "@test_channel"
        assert ends_at == datetime(2027, 4, 27, 17, 0, tzinfo=timezone.utc)
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

    def test_admin_participant_stats_include_active_giveaways_with_counts(self, tmp_path, monkeypatch):
        import database

        from services import giveaways

        db_path = str(tmp_path / "giveaways.db")
        monkeypatch.setattr(database, "DB_PATH", db_path)

        run(database.init_db())
        first_id = run(
            giveaways.create_giveaway(
                channel_id="@test_channel",
                prize="First prize",
                post_text="First post",
                winners_count=1,
                ends_at_utc=datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc),
                created_by=6210312655,
            )
        )
        second_id = run(
            giveaways.create_giveaway(
                channel_id="@test_channel",
                prize="Second prize",
                post_text="Second post",
                winners_count=2,
                ends_at_utc=datetime(2026, 4, 28, 17, 0, tzinfo=timezone.utc),
                created_by=6210312655,
            )
        )
        run(giveaways.set_giveaway_published(first_id, 101))
        run(giveaways.set_giveaway_published(second_id, 102))
        run(giveaways.add_giveaway_entry(first_id, 1001, "alice", "Alice"))
        run(giveaways.add_giveaway_entry(first_id, 1002, "bob", "Bob"))

        stats = run(giveaways.list_giveaway_participant_stats())

        assert [(item.giveaway_id, item.entries_count) for item in stats] == [(first_id, 2), (second_id, 0)]

    def test_required_channels_roundtrip_and_old_giveaway_defaults_to_empty(self, tmp_path, monkeypatch):
        import database

        from services import giveaways

        db_path = str(tmp_path / "giveaways.db")
        monkeypatch.setattr(database, "DB_PATH", db_path)

        run(database.init_db())
        giveaway_id = run(
            giveaways.create_giveaway(
                channel_id="@main_channel",
                prize="Prize",
                post_text="Post",
                winners_count=1,
                ends_at_utc=datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc),
                created_by=6210312655,
            )
        )

        assert run(giveaways.get_giveaway_required_channels(giveaway_id)) == []

        run(giveaways.set_giveaway_required_channels(giveaway_id, ["@extra_one", "@extra_two"]))
        channels = run(giveaways.get_giveaway_required_channels(giveaway_id))

        assert [item.channel_id for item in channels] == ["@extra_one", "@extra_two"]
        assert [item.title for item in channels] == ["@extra_one", "@extra_two"]

    def test_scheduled_giveaway_due_publication_roundtrip(self, tmp_path, monkeypatch):
        import database

        from services import giveaways

        db_path = str(tmp_path / "giveaways.db")
        monkeypatch.setattr(database, "DB_PATH", db_path)

        publish_at = datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc)
        run(database.init_db())
        giveaway_id = run(
            giveaways.create_giveaway(
                channel_id="@main_channel",
                prize="Prize",
                post_text="Post",
                winners_count=1,
                ends_at_utc=datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc),
                created_by=6210312655,
                publish_at_utc=publish_at,
            )
        )
        run(giveaways.schedule_giveaway_publication(giveaway_id))

        early = run(giveaways.list_due_publication_giveaways(datetime(2026, 4, 25, 9, 59, tzinfo=timezone.utc)))
        due = run(giveaways.list_due_publication_giveaways(datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc)))
        giveaway = run(giveaways.get_giveaway(giveaway_id))

        assert early == []
        assert [item.id for item in due] == [giveaway_id]
        assert giveaway.status == giveaways.GIVEAWAY_STATUS_SCHEDULED
        assert giveaway.publish_at_utc == publish_at

    def test_export_entries_csv_contains_participants_and_winners(self, tmp_path, monkeypatch):
        import database

        from services import giveaways

        db_path = str(tmp_path / "giveaways.db")
        monkeypatch.setattr(database, "DB_PATH", db_path)

        run(database.init_db())
        giveaway_id = run(
            giveaways.create_giveaway(
                channel_id="@main_channel",
                prize="Prize",
                post_text="Post",
                winners_count=1,
                ends_at_utc=datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc),
                created_by=6210312655,
            )
        )
        run(giveaways.add_giveaway_entry(giveaway_id, 1001, "alice", "Alice"))
        run(giveaways.mark_winners(giveaway_id, [giveaways.GiveawayEntry(giveaway_id, 1001, "alice", "Alice", "joined", True)]))

        csv_text = run(giveaways.build_giveaway_entries_csv(giveaway_id))

        assert "giveaway_id,user_id,username,first_name,joined_at_utc,joined_at_msk,status,is_winner,winner_place" in csv_text
        assert f"{giveaway_id},1001,alice,Alice," in csv_text
        assert ",joined,1" in csv_text

    def test_export_entries_xlsx_is_formatted_for_excel(self, tmp_path, monkeypatch):
        import database

        from services import giveaways

        db_path = str(tmp_path / "giveaways.db")
        monkeypatch.setattr(database, "DB_PATH", db_path)

        run(database.init_db())
        giveaway_id = run(
            giveaways.create_giveaway(
                channel_id="@main_channel",
                prize="Prize",
                post_text="Post",
                winners_count=1,
                ends_at_utc=datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc),
                created_by=6210312655,
            )
        )
        run(giveaways.add_giveaway_entry(giveaway_id, 1001, "alice", "Alice"))
        run(giveaways.mark_winners(giveaway_id, [giveaways.GiveawayEntry(giveaway_id, 1001, "alice", "Alice", "joined", True)]))

        xlsx_bytes = run(giveaways.build_giveaway_entries_xlsx(giveaway_id))

        with zipfile.ZipFile(BytesIO(xlsx_bytes)) as archive:
            names = set(archive.namelist())
            sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
            workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")

        assert "xl/worksheets/sheet1.xml" in names
        assert "xl/worksheets/sheet2.xml" in names
        assert "Участники" in workbook_xml
        assert "Сводка" in workbook_xml
        assert "Победитель" in sheet_xml
        assert "Да" in sheet_xml
        assert '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>' in sheet_xml
        assert '<autoFilter ref="A1:I2"/>' in sheet_xml

    def test_mark_winners_stores_winner_places(self, tmp_path, monkeypatch):
        import database

        from services import giveaways

        db_path = str(tmp_path / "giveaways.db")
        monkeypatch.setattr(database, "DB_PATH", db_path)

        run(database.init_db())
        giveaway_id = run(
            giveaways.create_giveaway(
                channel_id="@main_channel",
                prize="VIP; Coins",
                post_text="Post",
                winners_count=2,
                ends_at_utc=datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc),
                created_by=6210312655,
            )
        )
        run(giveaways.add_giveaway_entry(giveaway_id, 1001, "alice", "Alice"))
        run(giveaways.add_giveaway_entry(giveaway_id, 1002, "bob", "Bob"))

        entries = run(giveaways.get_giveaway_entries(giveaway_id))
        run(giveaways.mark_winners(giveaway_id, entries))
        winners = run(giveaways.get_giveaway_winners(giveaway_id))

        assert [(winner.user_id, winner.winner_place) for winner in winners] == [(1001, 1), (1002, 2)]

    def test_clone_giveaway_copies_content_and_required_channels_without_entries(self, tmp_path, monkeypatch):
        import database

        from services import giveaways

        db_path = str(tmp_path / "giveaways.db")
        monkeypatch.setattr(database, "DB_PATH", db_path)

        run(database.init_db())
        source_id = run(
            giveaways.create_giveaway(
                channel_id="@main_channel",
                prize="Prize",
                post_text="Post",
                winners_count=2,
                ends_at_utc=datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc),
                created_by=111,
                media_type="photo",
                media_file_id="photo-file",
            )
        )
        run(giveaways.set_giveaway_required_channels(source_id, ["@extra_channel"]))
        run(giveaways.add_giveaway_entry(source_id, 1001, "alice", "Alice"))

        cloned_id = run(
            giveaways.clone_giveaway(
                source_id,
                created_by=222,
                ends_at_utc=datetime(2026, 5, 1, 17, 0, tzinfo=timezone.utc),
            )
        )
        cloned = run(giveaways.get_giveaway(cloned_id))

        assert cloned.channel_id == "@main_channel"
        assert cloned.prize == "Prize"
        assert cloned.post_text == "Post"
        assert cloned.winners_count == 2
        assert cloned.media_file_id == "photo-file"
        assert cloned.created_by == 222
        assert run(giveaways.get_required_channel_ids(cloned_id)) == ["@extra_channel"]
        assert run(giveaways.get_giveaway_entries(cloned_id)) == []

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

    def test_rerolls_requested_place_and_keeps_other_winners(self, tmp_path, monkeypatch):
        import database

        from services import giveaways

        db_path = str(tmp_path / "giveaways.db")
        monkeypatch.setattr(database, "DB_PATH", db_path)

        class Member:
            status = "member"

        class BotStub:
            def __init__(self):
                self.calls = []

            async def get_chat_member(self, *, chat_id, user_id):
                return Member()

            async def send_message(self, **kwargs):
                self.calls.append(("send_message", kwargs))
                return type("Msg", (), {"message_id": 88})()

        run(database.init_db())
        giveaway_id = run(
            giveaways.create_giveaway(
                channel_id="@main_channel",
                prize="VIP; Coins",
                post_text="Post",
                winners_count=2,
                ends_at_utc=datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc),
                created_by=6210312655,
            )
        )
        run(giveaways.set_giveaway_published(giveaway_id, 123))
        run(giveaways.add_giveaway_entry(giveaway_id, 1001, "alice", "Alice"))
        run(giveaways.add_giveaway_entry(giveaway_id, 1002, "bob", "Bob"))
        run(giveaways.add_giveaway_entry(giveaway_id, 1003, "cara", "Cara"))
        entries = run(giveaways.get_giveaway_entries(giveaway_id))
        run(giveaways.mark_winners(giveaway_id, entries[:2]))
        run(giveaways.mark_giveaway_finished(giveaway_id))
        giveaway = run(giveaways.get_giveaway(giveaway_id))

        result = run(giveaways.reroll_giveaway_place(BotStub(), giveaway, 1, shuffle=lambda values: values))
        winners = run(giveaways.get_giveaway_winners(giveaway_id))

        assert result.old_winner.user_id == 1001
        assert result.new_winner.user_id == 1003
        assert [(winner.user_id, winner.winner_place) for winner in winners] == [(1003, 1), (1002, 2)]

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

    def test_required_subscription_check_reports_missing_extra_channels(self):
        from services.giveaways import Giveaway, check_giveaway_required_subscriptions

        class Member:
            status = "member"

        class Left:
            status = "left"

        class BotStub:
            async def get_chat_member(self, *, chat_id, user_id):
                return Member() if chat_id == "@main_channel" else Left()

        giveaway = Giveaway(
            id=1,
            status="active",
            channel_id="@main_channel",
            message_id=10,
            prize="Prize",
            post_text="Post",
            winners_count=1,
            ends_at_utc=datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc),
            created_by=6210312655,
        )

        result = run(check_giveaway_required_subscriptions(BotStub(), giveaway, ["@extra_channel"], 1001))

        assert result.is_allowed is False
        assert result.missing_channels == ["@extra_channel"]

    def test_webapp_status_reports_missing_channels_and_join_state(self, tmp_path, monkeypatch):
        import database

        from services import giveaways

        db_path = str(tmp_path / "giveaways.db")
        monkeypatch.setattr(database, "DB_PATH", db_path)

        class Member:
            status = "member"

        class Left:
            status = "left"

        class BotStub:
            async def get_chat_member(self, *, chat_id, user_id):
                return Member() if chat_id == "@main_channel" else Left()

        run(database.init_db())
        giveaway_id = run(
            giveaways.create_giveaway(
                channel_id="@main_channel",
                prize="Prize",
                post_text="Post",
                winners_count=1,
                ends_at_utc=datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc),
                created_by=6210312655,
            )
        )
        run(giveaways.set_giveaway_published(giveaway_id, 10))
        run(giveaways.set_giveaway_required_channels(giveaway_id, ["@extra_channel"]))

        status = run(giveaways.get_giveaway_webapp_status(BotStub(), giveaway_id, 1001))

        assert status["status"] == "active"
        assert status["is_allowed"] is False
        assert status["joined"] is False
        assert status["missing_channels"] == ["@extra_channel"]


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

    def test_mini_app_deeplink_uses_direct_app_payload(self):
        from services.giveaways import build_giveaway_mini_app_deeplink

        assert (
            build_giveaway_mini_app_deeplink("Alyamangapage_bot", 42, "randomizer")
            == "https://t.me/Alyamangapage_bot/randomizer?startapp=giveaway_42"
        )

    def test_mini_app_deeplink_requires_short_name(self):
        from services.giveaways import build_giveaway_mini_app_deeplink

        assert build_giveaway_mini_app_deeplink("Alyamangapage_bot", 42) is None

    def test_participation_markup_falls_back_to_callback_check(self):
        from services.giveaways import _participation_markup

        markup = _participation_markup(42)
        buttons = [button for row in markup.inline_keyboard for button in row]

        assert [button.callback_data for button in buttons] == ["giveaway_join:42", "giveaway_check:42"]
        assert all(button.url is None for button in buttons)

    def test_participation_markup_can_show_participant_count(self):
        from services.giveaways import _participation_markup

        markup = _participation_markup(42, entries_count=7)
        buttons = [button for row in markup.inline_keyboard for button in row]

        assert buttons[0].callback_data == "giveaway_join:42"
        assert buttons[1].callback_data == "giveaway_count:42"
        assert "7" in buttons[1].text

    def test_refresh_giveaway_participation_markup_updates_old_post_counter(self, tmp_path, monkeypatch):
        import database

        from services import giveaways

        db_path = str(tmp_path / "giveaways.db")
        monkeypatch.setattr(database, "DB_PATH", db_path)
        monkeypatch.setattr(giveaways, "GIVEAWAY_MINI_APP_SHORT_NAME", "")

        class BotStub:
            def __init__(self):
                self.calls = []

            async def edit_message_reply_markup(self, **kwargs):
                self.calls.append(("edit_message_reply_markup", kwargs))

        run(database.init_db())
        giveaway_id = run(
            giveaways.create_giveaway(
                channel_id="@main_channel",
                prize="Prize",
                post_text="Post",
                winners_count=1,
                ends_at_utc=datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc),
                created_by=6210312655,
            )
        )
        run(giveaways.set_giveaway_published(giveaway_id, 123))
        run(giveaways.add_giveaway_entry(giveaway_id, 1001, "alice", "Alice"))
        giveaway = run(giveaways.get_giveaway(giveaway_id))
        bot = BotStub()

        run(giveaways.refresh_giveaway_participation_markup(bot, giveaway))

        buttons = [button for row in bot.calls[0][1]["reply_markup"].inline_keyboard for button in row]
        assert bot.calls[0][1]["chat_id"] == "@main_channel"
        assert bot.calls[0][1]["message_id"] == 123
        assert any(button.callback_data == "giveaway_count:1" and "1" in button.text for button in buttons)

    def test_finalize_sends_result_without_editing_original_post(self, tmp_path, monkeypatch):
        import database

        from services import giveaways

        db_path = str(tmp_path / "giveaways.db")
        monkeypatch.setattr(database, "DB_PATH", db_path)

        class Member:
            status = "member"

        class BotStub:
            def __init__(self):
                self.calls = []

            async def get_chat_member(self, *, chat_id, user_id):
                return Member()

            async def send_message(self, **kwargs):
                self.calls.append(("send_message", kwargs))
                return type("Msg", (), {"message_id": 77})()

            async def edit_message_reply_markup(self, **kwargs):
                self.calls.append(("edit_message_reply_markup", kwargs))

        run(database.init_db())
        giveaway_id = run(
            giveaways.create_giveaway(
                channel_id="@main_channel",
                prize="Prize",
                post_text="Post",
                winners_count=1,
                ends_at_utc=datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc),
                created_by=6210312655,
            )
        )
        run(giveaways.set_giveaway_published(giveaway_id, 123))
        run(giveaways.add_giveaway_entry(giveaway_id, 1001, "alice", "Alice"))
        giveaway = run(giveaways.get_giveaway(giveaway_id))
        bot = BotStub()

        assert run(giveaways.finalize_giveaway(bot, giveaway)) is True

        assert "edit_message_reply_markup" not in [call[0] for call in bot.calls]
        assert bot.calls[0][0] == "send_message"
        assert bot.calls[0][1]["chat_id"] == "@main_channel"

    def test_finalize_sends_private_admin_summary(self, tmp_path, monkeypatch):
        import database

        from services import giveaways

        db_path = str(tmp_path / "giveaways.db")
        monkeypatch.setattr(database, "DB_PATH", db_path)

        class Member:
            status = "member"

        class BotStub:
            def __init__(self):
                self.calls = []

            async def get_chat_member(self, *, chat_id, user_id):
                return Member()

            async def send_message(self, **kwargs):
                self.calls.append(("send_message", kwargs))
                return type("Msg", (), {"message_id": 77})()

        run(database.init_db())
        giveaway_id = run(
            giveaways.create_giveaway(
                channel_id="@main_channel",
                prize="Prize",
                post_text="Post",
                winners_count=1,
                ends_at_utc=datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc),
                created_by=6210312655,
            )
        )
        run(giveaways.set_giveaway_published(giveaway_id, 123))
        run(giveaways.add_giveaway_entry(giveaway_id, 1001, "alice", "Alice"))
        giveaway = run(giveaways.get_giveaway(giveaway_id))
        bot = BotStub()

        assert run(giveaways.finalize_giveaway(bot, giveaway)) is True

        assert [call[1]["chat_id"] for call in bot.calls] == ["@main_channel", 6210312655]

    def test_preview_markup_has_publish_and_edit_buttons(self):
        from services.giveaways import _preview_markup

        markup = _preview_markup()
        buttons = [button.text for row in markup.inline_keyboard for button in row]

        assert "✅ Опубликовать" in buttons
        assert "✍️ Текст поста" in buttons
        assert "🏆 Призы" in buttons
        assert "❌ Отменить" in buttons

    def test_subscription_scope_explains_primary_channel_when_no_extra_channels(self):
        from services.giveaways import _format_subscription_scope

        text = _format_subscription_scope("@main_channel", [])

        assert "Основной канал: @main_channel" in text
        assert "проверяется всегда" in text
        assert "Доп. каналы: не указаны" in text
        assert "нет" not in text

    def test_admin_giveaway_card_explains_subscription_and_prize_lines(self):
        from services.giveaways import GIVEAWAY_STATUS_ACTIVE, Giveaway, _format_admin_giveaway_card

        giveaway = Giveaway(
            id=9,
            status=GIVEAWAY_STATUS_ACTIVE,
            channel_id="@main_channel",
            message_id=123,
            prize="1 место: VIP; 2 место: 500 монет",
            post_text="Post",
            winners_count=2,
            ends_at_utc=datetime(2026, 5, 1, 20, 28, tzinfo=timezone.utc),
            created_by=6210312655,
        )

        text = _format_admin_giveaway_card(giveaway, entries_count=179, required_channels=[])

        assert "Основной канал: @main_channel" in text
        assert "проверяется всегда" in text
        assert "Доп. каналы: не указаны" in text
        assert "1 место" in text
        assert "VIP" in text
        assert "\n2 место" in text

    def test_admin_giveaway_menu_has_participants_button(self):
        from services.giveaways import _admin_giveaway_menu

        markup = _admin_giveaway_menu()
        buttons = [button.text for row in markup.inline_keyboard for button in row]

        assert "Участники" in buttons

    def test_publish_error_formats_chat_not_found_hint(self):
        from services.giveaways import _format_publish_error

        text = _format_publish_error(Exception("Bad Request: chat not found"))

        assert "Бот не видит канал" in text
        assert "chat not found" in text
