from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone


def run(coro):
    return asyncio.run(coro)


def body_json(response):
    return json.loads(response.body.decode("utf-8"))


def install_auth(monkeypatch, *, user_id=10, admins=(10,)):
    import services.admin_webapp_api as admin_api

    monkeypatch.setattr(admin_api, "get_auth_user", lambda _request: {"id": user_id, "first_name": "Admin"})
    monkeypatch.setattr(admin_api, "get_admins", lambda: asyncio.sleep(0, result=list(admins)))


def test_admin_giveaway_participants_endpoint_exposes_filters_and_risk(tmp_path, monkeypatch):
    from aiohttp.test_utils import make_mocked_request

    import database
    import services.admin_webapp_api as admin_api
    from services import giveaways

    db_path = tmp_path / "admin-giveaway-monitor.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    run(database.init_db())
    install_auth(monkeypatch)

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
    opened_at = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    for offset, user_id in enumerate(range(1001, 1006)):
        run(
            giveaways.record_giveaway_participant_event(
                giveaway_id,
                user_id,
                "webapp_open",
                referral_source="promoA",
                language_code="ar",
                created_at=opened_at,
            )
        )
        run(giveaways.add_giveaway_entry(giveaway_id, user_id, "fast", "Fast"))
        run(
            giveaways.record_giveaway_participant_event(
                giveaway_id,
                user_id,
                "giveaway_join",
                referral_source="promoA",
                created_at=opened_at,
            )
        )

    response = run(
        admin_api.handle_admin_giveaway_participants(
            make_mocked_request("GET", f"/api/admin/giveaways/{giveaway_id}/participants?filter=suspicious")
        )
    )
    payload = body_json(response)

    assert response.status == 200
    assert payload["ok"] is True
    assert payload["giveaway_id"] == giveaway_id
    assert payload["filter"] == "suspicious"
    assert payload["counters"]["total"] == 5
    assert payload["participants"][0]["user_id"] == 1001
    assert payload["participants"][0]["risk_score"] > 0
    assert payload["participants"][0]["risk_flags"]


def test_admin_giveaway_moderation_endpoint_requires_reason(tmp_path, monkeypatch):
    from aiohttp.test_utils import make_mocked_request

    import database
    import services.admin_webapp_api as admin_api
    from services import giveaways

    db_path = tmp_path / "admin-giveaway-moderation.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    run(database.init_db())
    install_auth(monkeypatch)
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
    run(giveaways.add_giveaway_entry(giveaway_id, 1001, "botty", "Botty"))

    request = make_mocked_request(
        "POST",
        f"/api/admin/giveaways/{giveaway_id}/participants/1001/moderation",
        headers={"Content-Type": "application/json"},
    )
    request._read_bytes = json.dumps({"status": "excluded", "reason": ""}).encode("utf-8")

    response = run(admin_api.handle_admin_giveaway_participant_moderation(request))
    payload = body_json(response)

    assert response.status == 400
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_request"
