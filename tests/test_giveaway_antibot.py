from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import aiosqlite


def run(coro):
    return asyncio.run(coro)


def seed_active_giveaway(tmp_path, monkeypatch):
    import database
    from services import giveaways

    db_path = str(tmp_path / "giveaway-antibot.db")
    monkeypatch.setattr(database, "DB_PATH", db_path)

    run(database.init_db())
    giveaway_id = run(
        giveaways.create_giveaway(
            channel_id="@main_channel",
            prize="VIP",
            post_text="Post",
            winners_count=1,
            ends_at_utc=datetime(2026, 5, 2, 17, 0, tzinfo=timezone.utc),
            created_by=10,
        )
    )
    run(giveaways.set_giveaway_published(giveaway_id, 321))
    return db_path, giveaway_id


def test_monitor_snapshot_scores_fast_referral_burst_with_explanations(tmp_path, monkeypatch):
    from services import giveaways

    _db_path, giveaway_id = seed_active_giveaway(tmp_path, monkeypatch)
    opened_at = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

    for offset, user_id in enumerate(range(1001, 1007)):
        run(
            giveaways.record_giveaway_participant_event(
                giveaway_id,
                user_id,
                "webapp_open",
                referral_source="promoA",
                username=f"promo{offset}",
                first_name=f"Ali {offset}",
                language_code="ar",
                is_premium=False,
                created_at=opened_at + timedelta(seconds=offset),
            )
        )
        assert run(giveaways.add_giveaway_entry(giveaway_id, user_id, f"promo{offset}", f"Ali {offset}")) is True
        run(
            giveaways.record_giveaway_participant_event(
                giveaway_id,
                user_id,
                "giveaway_join",
                referral_source="promoA",
                created_at=opened_at + timedelta(seconds=offset + 4),
            )
        )

    snapshot = run(giveaways.get_giveaway_monitor_snapshot(giveaway_id, now=opened_at + timedelta(minutes=3)))

    assert snapshot["ok"] is True
    assert snapshot["counters"]["total"] == 6
    assert snapshot["counters"]["suspicious"] >= 1
    assert snapshot["referrals"][0]["source"] == "promoA"
    assert snapshot["referrals"][0]["participants"] == 6
    assert snapshot["audience"]["languages"]["ar"] == 6

    participant = next(item for item in snapshot["participants"] if item["user_id"] == 1001)
    flag_codes = {flag["code"] for flag in participant["risk_flags"]}
    assert participant["risk_score"] >= 60
    assert {"fast_registration", "referral_burst", "low_activity"}.issubset(flag_codes)
    assert all(flag["reason"] for flag in participant["risk_flags"])


def test_exclude_restore_and_trust_participant_are_audited(tmp_path, monkeypatch):
    import database
    from services import giveaways

    _db_path, giveaway_id = seed_active_giveaway(tmp_path, monkeypatch)
    run(giveaways.add_giveaway_entry(giveaway_id, 1001, "botty", "Botty"))

    excluded = run(
        giveaways.set_giveaway_entry_moderation(
            giveaway_id,
            1001,
            "excluded",
            actor_user_id=10,
            reason="Risk score review",
        )
    )
    restored = run(
        giveaways.set_giveaway_entry_moderation(
            giveaway_id,
            1001,
            "joined",
            actor_user_id=10,
            reason="Manual restore",
        )
    )
    trusted = run(
        giveaways.set_giveaway_entry_moderation(
            giveaway_id,
            1001,
            "trusted",
            actor_user_id=10,
            reason="Known active user",
        )
    )
    entry = run(giveaways.get_giveaway_entries(giveaway_id))[0]

    async def audit_rows():
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT action, actor_user_id, target, payload_json FROM admin_audit_log ORDER BY id") as cursor:
                return await cursor.fetchall()

    rows = run(audit_rows())

    assert excluded is True
    assert restored is True
    assert trusted is True
    assert entry.status == "trusted"
    assert [row[0] for row in rows] == [
        "giveaway_entry_excluded",
        "giveaway_entry_restored",
        "giveaway_entry_trusted",
    ]
    assert rows[0][1] == "10"
    assert rows[0][2] == f"giveaway:{giveaway_id}:user:1001"
    assert "Risk score review" in rows[0][3]


def test_winner_selection_and_reroll_skip_excluded_entries_and_store_history(tmp_path, monkeypatch):
    from services import giveaways

    _db_path, giveaway_id = seed_active_giveaway(tmp_path, monkeypatch)

    class Member:
        status = "member"

    class BotStub:
        async def get_chat_member(self, *, chat_id, user_id):
            return Member()

        async def send_message(self, **kwargs):
            return type("Msg", (), {"message_id": 88})()

    run(giveaways.add_giveaway_entry(giveaway_id, 1001, "winner", "Winner"))
    run(giveaways.add_giveaway_entry(giveaway_id, 1002, "excluded", "Excluded"))
    run(giveaways.add_giveaway_entry(giveaway_id, 1003, "replacement", "Replacement"))
    run(giveaways.set_giveaway_entry_moderation(giveaway_id, 1002, "excluded", actor_user_id=10, reason="Bot"))

    entries = run(giveaways.get_giveaway_entries(giveaway_id))

    async def is_subscribed(_user_id: int) -> bool:
        return True

    selected = run(giveaways.select_winners(entries, 2, is_subscribed=is_subscribed, shuffle=lambda values: values))
    assert [entry.user_id for entry in selected.winners] == [1001, 1003]

    run(giveaways.mark_winners(giveaway_id, [entries[0]]))
    run(giveaways.mark_giveaway_finished(giveaway_id))
    giveaway = run(giveaways.get_giveaway(giveaway_id))

    result = run(
        giveaways.reroll_giveaway_place(
            BotStub(),
            giveaway,
            1,
            actor_user_id=10,
            reason="Original winner excluded after review",
            shuffle=lambda values: values,
        )
    )
    history = run(giveaways.get_giveaway_reroll_history(giveaway_id))

    assert result.old_winner.user_id == 1001
    assert result.new_winner.user_id == 1003
    assert history[0]["place"] == 1
    assert history[0]["old_user_id"] == 1001
    assert history[0]["new_user_id"] == 1003
    assert history[0]["actor_user_id"] == "10"
    assert history[0]["reason"] == "Original winner excluded after review"
