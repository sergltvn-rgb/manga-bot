from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from http.cookies import SimpleCookie
from unittest.mock import AsyncMock

import aiosqlite


def run(coro):
    return asyncio.run(coro)


def signed_login_payload(bot_token: str, *, now: int, user_id: int = 42) -> dict:
    payload = {
        "id": str(user_id),
        "first_name": "Site",
        "last_name": "Reader",
        "username": "site_reader",
        "photo_url": "https://example.org/avatar.png",
        "auth_date": str(now),
    }
    data_check = "\n".join(f"{key}={payload[key]}" for key in sorted(payload))
    secret = hashlib.sha256(bot_token.encode("utf-8")).digest()
    payload["hash"] = hmac.new(secret, data_check.encode("utf-8"), hashlib.sha256).hexdigest()
    return payload


async def init_auth_db(db_path):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE web_sessions (
                session_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                user_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE chapter_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chapter_key TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_name TEXT DEFAULT '',
                text TEXT NOT NULL,
                parent_id INTEGER DEFAULT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT NULL
            )
            """
        )
        await db.commit()


class JsonRequest:
    path = "/api/comments"
    query = {}
    match_info = {}

    def __init__(self, payload=None, cookies=None):
        self._payload = payload or {}
        self.cookies = cookies or {}
        self.headers = {}
        if self.cookies:
            cookie = SimpleCookie()
            for key, value in self.cookies.items():
                cookie[key] = value
            self.headers["Cookie"] = cookie.output(header="", sep=";").strip()

    async def json(self):
        return self._payload


def test_telegram_login_payload_signature_and_expiry():
    from services.auth import validate_telegram_login_payload

    token = "1234567890:TEST_TOKEN_FOR_UNIT_TESTS_ONLY"
    now = 1_700_000_000
    payload = signed_login_payload(token, now=now)

    user = validate_telegram_login_payload(payload, bot_token=token, now=now)

    assert user is not None
    assert user["id"] == 42
    assert user["first_name"] == "Site"
    assert user["username"] == "site_reader"

    bad_payload = dict(payload, first_name="Tampered")
    assert validate_telegram_login_payload(bad_payload, bot_token=token, now=now) is None
    assert validate_telegram_login_payload(payload, bot_token=token, now=now + 90_000) is None


def test_get_auth_user_reads_valid_web_session_cookie(tmp_path, monkeypatch):
    from aiohttp.test_utils import make_mocked_request
    from multidict import CIMultiDict

    import database
    from services.auth import WEB_SESSION_COOKIE_NAME, create_web_session, get_auth_user

    db_path = tmp_path / "auth.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    run(init_auth_db(db_path))

    async def create():
        async with aiosqlite.connect(db_path) as db:
            return await create_web_session(
                db,
                {"id": 42, "first_name": "Site", "username": "site_reader"},
                now=int(time.time()),
            )

    token, _ = run(create())
    req = make_mocked_request("GET", "/api/auth/me", headers=CIMultiDict({"Cookie": f"{WEB_SESSION_COOKIE_NAME}={token}"}))

    assert get_auth_user(req) == {"id": 42, "first_name": "Site", "username": "site_reader"}


def test_expired_web_session_cookie_is_ignored(tmp_path, monkeypatch):
    from aiohttp.test_utils import make_mocked_request
    from multidict import CIMultiDict

    import database
    from services.auth import WEB_SESSION_COOKIE_NAME, _hash_session_token, get_auth_user

    db_path = tmp_path / "auth.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    run(init_auth_db(db_path))
    token = "expired-token"

    async def seed():
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                INSERT INTO web_sessions (session_hash, user_id, user_json, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (_hash_session_token(token), "42", json.dumps({"id": 42}), 1, 2),
            )
            await db.commit()

    run(seed())
    req = make_mocked_request("GET", "/api/auth/me", headers=CIMultiDict({"Cookie": f"{WEB_SESSION_COOKIE_NAME}={token}"}))

    assert get_auth_user(req) is None


def test_comments_post_accepts_web_session_cookie(tmp_path, monkeypatch):
    import database
    import bot
    import services.comments_api as comments_api
    from services.auth import WEB_SESSION_COOKIE_NAME, create_web_session

    db_path = tmp_path / "comments.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    monkeypatch.setattr(bot, "DB_PATH", str(db_path))
    monkeypatch.setattr(comments_api, "_enforce_rate_limit", AsyncMock(return_value=None))
    run(init_auth_db(db_path))

    async def create():
        async with aiosqlite.connect(db_path) as db:
            return await create_web_session(db, {"id": 42, "first_name": "Site"}, now=int(time.time()))

    token, _ = run(create())
    request = JsonRequest(
        {
            "chapter_key": "manga_ru_v1_ch1",
            "text": "Comment from the public site",
        },
        cookies={WEB_SESSION_COOKIE_NAME: token},
    )

    response = run(comments_api.handle_comments_post(request))

    assert response.status == 200
    body = json.loads(response.body.decode("utf-8"))
    assert body["ok"] is True

    async def read_comment():
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT user_id, user_name, text FROM chapter_comments") as cursor:
                return await cursor.fetchone()

    assert run(read_comment()) == ("42", "Site", "Comment from the public site")


def test_comments_post_without_web_session_stays_unauthorized():
    import services.comments_api as comments_api

    request = JsonRequest(
        {
            "chapter_key": "manga_ru_v1_ch1",
            "text": "No auth",
        }
    )

    response = run(comments_api.handle_comments_post(request))

    assert response.status == 401
