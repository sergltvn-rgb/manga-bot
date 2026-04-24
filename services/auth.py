"""Authentication helpers for Telegram WebApp and public reader site APIs."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from http.cookies import SimpleCookie

import aiohttp.web
import aiosqlite

from config import BOT_TOKEN
from utils import validate_telegram_data

WEB_SESSION_COOKIE_NAME = "reader_session"
WEB_SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
TELEGRAM_LOGIN_MAX_AGE_SECONDS = 60 * 60 * 24
TELEGRAM_LOGIN_FUTURE_SKEW_SECONDS = 300


def _now() -> int:
    return int(time.time())


def _get_db_path() -> str:
    import database

    return database.DB_PATH


def _hash_session_token(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _normalize_login_user(payload: dict) -> dict:
    user: dict = {"id": int(payload["id"])}
    for key in ("first_name", "last_name", "username", "photo_url"):
        value = payload.get(key)
        if value not in (None, ""):
            user[key] = str(value)
    if payload.get("auth_date") not in (None, ""):
        user["auth_date"] = int(payload["auth_date"])
    return user


def validate_telegram_login_payload(
    payload: dict,
    *,
    bot_token: str = BOT_TOKEN,
    now: int | None = None,
    max_age_seconds: int = TELEGRAM_LOGIN_MAX_AGE_SECONDS,
) -> dict | None:
    """Validate Telegram Login Widget payload and return a normalized user."""
    if not isinstance(payload, dict):
        return None
    received_hash = str(payload.get("hash", "")).strip()
    if not received_hash or not payload.get("id") or not payload.get("auth_date"):
        return None
    try:
        auth_date = int(str(payload["auth_date"]))
        user_id = int(str(payload["id"]))
    except (TypeError, ValueError):
        return None
    if user_id <= 0:
        return None

    current_time = _now() if now is None else int(now)
    if auth_date > current_time + TELEGRAM_LOGIN_FUTURE_SKEW_SECONDS:
        return None
    if current_time - auth_date > max_age_seconds:
        return None

    data_check_string = "\n".join(f"{key}={payload[key]}" for key in sorted(k for k in payload if k != "hash") if payload[key] is not None)
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        return None
    return _normalize_login_user(payload)


async def ensure_web_sessions_table(db: aiosqlite.Connection) -> None:
    await db.execute(
        """CREATE TABLE IF NOT EXISTS web_sessions (
            session_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            user_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )"""
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_web_sessions_user ON web_sessions(user_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_web_sessions_expires ON web_sessions(expires_at)")


async def create_web_session(
    db: aiosqlite.Connection,
    user: dict,
    *,
    now: int | None = None,
    ttl_seconds: int = WEB_SESSION_TTL_SECONDS,
) -> tuple[str, int]:
    """Create a persistent web session and return raw cookie token + expiry."""
    await ensure_web_sessions_table(db)
    created_at = _now() if now is None else int(now)
    expires_at = created_at + int(ttl_seconds)
    token = secrets.token_urlsafe(32)
    user_id = str(user.get("id", ""))
    if not user_id:
        raise ValueError("missing user id")
    await db.execute(
        """
        INSERT OR REPLACE INTO web_sessions (session_hash, user_id, user_json, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            _hash_session_token(token),
            user_id,
            json.dumps(user, ensure_ascii=False, separators=(",", ":")),
            created_at,
            expires_at,
        ),
    )
    await db.commit()
    return token, expires_at


def revoke_web_session_token(token: str) -> None:
    if not token:
        return
    try:
        with sqlite3.connect(_get_db_path()) as db:
            db.execute("DELETE FROM web_sessions WHERE session_hash = ?", (_hash_session_token(token),))
            db.commit()
    except sqlite3.Error:
        return


def _get_web_session_user(token: str, *, now: int | None = None) -> dict | None:
    if not token:
        return None
    current_time = _now() if now is None else int(now)
    try:
        with sqlite3.connect(_get_db_path()) as db:
            row = db.execute(
                "SELECT user_json, expires_at FROM web_sessions WHERE session_hash = ?",
                (_hash_session_token(token),),
            ).fetchone()
            if not row:
                return None
            user_json, expires_at = row
            if int(expires_at) <= current_time:
                db.execute("DELETE FROM web_sessions WHERE session_hash = ?", (_hash_session_token(token),))
                db.commit()
                return None
    except (sqlite3.Error, TypeError, ValueError):
        return None
    try:
        user = json.loads(user_json)
    except Exception:  # noqa: BLE001
        return None
    return user if isinstance(user, dict) and user.get("id") else None


def _get_cookie_token(request: aiohttp.web.Request) -> str:
    token = request.cookies.get(WEB_SESSION_COOKIE_NAME, "")
    if token:
        return token
    raw_cookie = request.headers.get("Cookie", "")
    if not raw_cookie:
        return ""
    cookie = SimpleCookie()
    try:
        cookie.load(raw_cookie)
    except Exception:  # noqa: BLE001
        return ""
    morsel = cookie.get(WEB_SESSION_COOKIE_NAME)
    return morsel.value if morsel else ""


def get_auth_user(request: aiohttp.web.Request) -> dict | None:
    """Return Telegram user from WebApp initData or from public-site session cookie."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("tma "):
        init_data = auth_header[4:]
    else:
        init_data = request.query.get("initData", "")

    if init_data:
        parsed = validate_telegram_data(init_data, BOT_TOKEN)
        if not parsed or "user" not in parsed:
            return None
        try:
            return json.loads(parsed["user"])
        except Exception:  # noqa: BLE001
            return None

    return _get_web_session_user(_get_cookie_token(request))
