"""Telegram channel giveaways.

The module owns giveaway storage helpers, publication/finalization logic, and
the aiogram router. It intentionally does not import ``bot.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiosqlite
from aiogram import F, Router, types
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import database
from config import GIVEAWAY_CHANNEL_ID, GIVEAWAY_CHANNEL_URL
from services.admin_helpers import _is_bot_admin, _require_admin
from services.telegram_helpers import escape_html_text


def _load_moscow_tz():
    for key in ("Europe/Moscow",):
        try:
            return ZoneInfo(key)
        except ZoneInfoNotFoundError:
            continue
    return timezone(timedelta(hours=3), name="Europe/Moscow")


MSK_TZ = _load_moscow_tz()
GIVEAWAY_STATUS_DRAFT = "draft"
GIVEAWAY_STATUS_ACTIVE = "active"
GIVEAWAY_STATUS_FINISHING = "finishing"
GIVEAWAY_STATUS_FINISHED = "finished"
GIVEAWAY_STATUS_CANCELLED = "cancelled"
JOINED_STATUSES = {"member", "administrator", "creator"}
SUPPORTED_MEDIA_TYPES = {"photo", "video", "document", "animation"}
_DURATION_RE = re.compile(r"^(?P<count>\d+)(?P<unit>[mhd])$", re.IGNORECASE)


class GiveawayValidationError(ValueError):
    pass


class GiveawayPublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class Giveaway:
    id: int
    status: str
    channel_id: str
    message_id: int | None
    prize: str
    post_text: str
    winners_count: int
    ends_at_utc: datetime
    created_by: int
    media_type: str | None = None
    media_file_id: str | None = None
    replacements_count: int = 0


@dataclass(frozen=True)
class GiveawayEntry:
    giveaway_id: int
    user_id: int
    username: str | None
    first_name: str | None
    status: str
    is_winner: bool


@dataclass(frozen=True)
class WinnerSelectionResult:
    winners: list[GiveawayEntry]
    replaced_count: int


@dataclass(frozen=True)
class GiveawayVerificationChallenge:
    question: str
    answer: str
    options: list[str]


class GiveawayCreate(StatesGroup):
    waiting_for_channel = State()
    waiting_for_prize = State()
    waiting_for_end = State()
    waiting_for_winners = State()
    waiting_for_text = State()
    waiting_for_media = State()
    waiting_for_preview = State()


giveaway_router = Router()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_db(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _dt_from_db(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_giveaway_end(raw: str, *, now: datetime | None = None) -> datetime:
    text = (raw or "").strip()
    now_utc = (now or _utcnow()).astimezone(timezone.utc)

    duration_match = _DURATION_RE.match(text)
    if duration_match:
        count = int(duration_match.group("count"))
        if count <= 0:
            raise GiveawayValidationError("Duration must be positive.")
        unit = duration_match.group("unit").lower()
        delta = {"m": timedelta(minutes=count), "h": timedelta(hours=count), "d": timedelta(days=count)}[unit]
        return (now_utc + delta).astimezone(timezone.utc)

    try:
        local_dt = datetime.strptime(text, "%d.%m.%Y %H:%M").replace(tzinfo=MSK_TZ)
    except ValueError as exc:
        raise GiveawayValidationError("Use DD.MM.YYYY HH:MM or duration like 12h / 3d.") from exc

    ends_at = local_dt.astimezone(timezone.utc)
    if ends_at <= now_utc:
        raise GiveawayValidationError("Giveaway end time must be in the future.")
    return ends_at


def format_giveaway_end(ends_at_utc: datetime) -> str:
    return ends_at_utc.astimezone(MSK_TZ).strftime("%d.%m.%Y %H:%M")


def _channel_url(channel_id: str) -> str:
    if channel_id.startswith("@"):
        return f"https://t.me/{channel_id[1:]}"
    if channel_id == GIVEAWAY_CHANNEL_ID:
        return GIVEAWAY_CHANNEL_URL
    return str(channel_id)


def split_place_prizes(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    parts = [part.strip() for part in re.split(r"[;\n]+", text) if part.strip()]
    prizes: list[str] = []
    for idx, part in enumerate(parts, 1):
        cleaned = re.sub(rf"^\s*{idx}\s*(?:место|м\.|[).:-])\s*", "", part, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^\s*\d+\s*(?:место|м\.|[).:-])\s*", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^\s*\d+\s*[^:;\n]{0,24}:\s*", "", cleaned).strip()
        cleaned = re.sub(r"^[:\s-]+", "", cleaned).strip()
        prizes.append(cleaned or part)
    return prizes or [text]


def _format_prizes_block(raw: str, winners_count: int) -> str:
    prizes = split_place_prizes(raw)
    if not prizes:
        return "Приз уточняется"
    if len(prizes) == 1 and winners_count <= 1:
        return prizes[0]
    lines = []
    for idx in range(max(winners_count, len(prizes))):
        prize = prizes[idx] if idx < len(prizes) else prizes[-1]
        lines.append(f"{idx + 1} место — {prize}")
    return "\n".join(lines)


def _row_to_giveaway(row) -> Giveaway:
    return Giveaway(
        id=int(row[0]),
        status=str(row[1]),
        channel_id=str(row[2]),
        message_id=int(row[3]) if row[3] is not None else None,
        prize=str(row[4]),
        post_text=str(row[5]),
        media_type=row[6],
        media_file_id=row[7],
        winners_count=int(row[8]),
        ends_at_utc=_dt_from_db(str(row[9])),
        created_by=int(row[10]),
        replacements_count=int(row[11] or 0),
    )


async def create_giveaway(
    *,
    channel_id: str,
    prize: str,
    post_text: str,
    winners_count: int,
    ends_at_utc: datetime,
    created_by: int,
    media_type: str | None = None,
    media_file_id: str | None = None,
) -> int:
    if winners_count < 1:
        raise GiveawayValidationError("Winners count must be at least 1.")
    if not prize.strip() or not post_text.strip():
        raise GiveawayValidationError("Prize and post text are required.")
    if media_type and media_type not in SUPPORTED_MEDIA_TYPES:
        raise GiveawayValidationError(f"Unsupported media type: {media_type}")

    now = _dt_to_db(_utcnow())
    async with aiosqlite.connect(database.DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO giveaways (
                status, channel_id, prize, post_text, media_type, media_file_id,
                winners_count, ends_at_utc, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                GIVEAWAY_STATUS_DRAFT,
                channel_id,
                prize.strip(),
                post_text.strip(),
                media_type,
                media_file_id,
                winners_count,
                _dt_to_db(ends_at_utc),
                created_by,
                now,
            ),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def get_giveaway(giveaway_id: int) -> Giveaway | None:
    async with aiosqlite.connect(database.DB_PATH) as db:
        async with db.execute(
            """
            SELECT id, status, channel_id, message_id, prize, post_text, media_type,
                   media_file_id, winners_count, ends_at_utc, created_by, replacements_count
            FROM giveaways WHERE id = ?
            """,
            (giveaway_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return _row_to_giveaway(row) if row else None


async def set_giveaway_published(giveaway_id: int, message_id: int) -> None:
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute(
            """
            UPDATE giveaways
            SET status = ?, message_id = ?, published_at = ?
            WHERE id = ? AND status = ?
            """,
            (GIVEAWAY_STATUS_ACTIVE, message_id, _dt_to_db(_utcnow()), giveaway_id, GIVEAWAY_STATUS_DRAFT),
        )
        await db.commit()


async def list_due_giveaways(now: datetime | None = None) -> list[Giveaway]:
    now_db = _dt_to_db(now or _utcnow())
    async with aiosqlite.connect(database.DB_PATH) as db:
        async with db.execute(
            """
            SELECT id, status, channel_id, message_id, prize, post_text, media_type,
                   media_file_id, winners_count, ends_at_utc, created_by, replacements_count
            FROM giveaways
            WHERE status = ? AND ends_at_utc <= ?
            ORDER BY ends_at_utc, id
            """,
            (GIVEAWAY_STATUS_ACTIVE, now_db),
        ) as cursor:
            rows = await cursor.fetchall()
    return [_row_to_giveaway(row) for row in rows]


async def list_active_giveaways() -> list[Giveaway]:
    async with aiosqlite.connect(database.DB_PATH) as db:
        async with db.execute(
            """
            SELECT id, status, channel_id, message_id, prize, post_text, media_type,
                   media_file_id, winners_count, ends_at_utc, created_by, replacements_count
            FROM giveaways
            WHERE status IN (?, ?)
            ORDER BY ends_at_utc, id
            """,
            (GIVEAWAY_STATUS_ACTIVE, GIVEAWAY_STATUS_FINISHING),
        ) as cursor:
            rows = await cursor.fetchall()
    return [_row_to_giveaway(row) for row in rows]


async def claim_giveaway_finishing(giveaway_id: int) -> bool:
    async with aiosqlite.connect(database.DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE giveaways SET status = ? WHERE id = ? AND status = ?",
            (GIVEAWAY_STATUS_FINISHING, giveaway_id, GIVEAWAY_STATUS_ACTIVE),
        )
        await db.commit()
        return cursor.rowcount == 1


async def mark_giveaway_finished(giveaway_id: int, *, replacements_count: int = 0) -> bool:
    async with aiosqlite.connect(database.DB_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE giveaways
            SET status = ?, finished_at = COALESCE(finished_at, ?), replacements_count = ?
            WHERE id = ? AND status IN (?, ?)
            """,
            (
                GIVEAWAY_STATUS_FINISHED,
                _dt_to_db(_utcnow()),
                replacements_count,
                giveaway_id,
                GIVEAWAY_STATUS_ACTIVE,
                GIVEAWAY_STATUS_FINISHING,
            ),
        )
        await db.commit()
        return cursor.rowcount == 1


async def cancel_giveaway(giveaway_id: int) -> bool:
    async with aiosqlite.connect(database.DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE giveaways SET status = ?, finished_at = ? WHERE id = ? AND status IN (?, ?)",
            (GIVEAWAY_STATUS_CANCELLED, _dt_to_db(_utcnow()), giveaway_id, GIVEAWAY_STATUS_ACTIVE, GIVEAWAY_STATUS_DRAFT),
        )
        await db.commit()
        return cursor.rowcount == 1


async def add_giveaway_entry(giveaway_id: int, user_id: int, username: str | None, first_name: str | None) -> bool:
    async with aiosqlite.connect(database.DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO giveaway_entries (
                giveaway_id, user_id, username, first_name, joined_at, status, is_winner
            )
            VALUES (?, ?, ?, ?, ?, 'joined', 0)
            """,
            (giveaway_id, user_id, username, first_name, _dt_to_db(_utcnow())),
        )
        await db.commit()
        return cursor.rowcount == 1


async def get_giveaway_entries(giveaway_id: int) -> list[GiveawayEntry]:
    async with aiosqlite.connect(database.DB_PATH) as db:
        async with db.execute(
            """
            SELECT giveaway_id, user_id, username, first_name, status, is_winner
            FROM giveaway_entries
            WHERE giveaway_id = ?
            ORDER BY joined_at, user_id
            """,
            (giveaway_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        GiveawayEntry(
            giveaway_id=int(row[0]),
            user_id=int(row[1]),
            username=row[2],
            first_name=row[3],
            status=str(row[4]),
            is_winner=bool(row[5]),
        )
        for row in rows
    ]


async def has_giveaway_entry(giveaway_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(database.DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
            (giveaway_id, user_id),
        ) as cursor:
            return await cursor.fetchone() is not None


async def count_giveaway_entries(giveaway_id: int) -> int:
    async with aiosqlite.connect(database.DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)) as cursor:
            row = await cursor.fetchone()
            return int(row[0] if row else 0)


def _make_verification_answer() -> tuple[str, str, list[str]]:
    left = random.randint(2, 9)
    right = random.randint(2, 9)
    answer = left + right
    options = {answer, answer + random.choice([-2, -1, 1, 2]), answer + random.choice([3, 4, -3, -4])}
    while len(options) < 3:
        options.add(answer + random.randint(-5, 5))
    ordered = [str(value) for value in options]
    random.shuffle(ordered)
    return f"{left} + {right}", str(answer), ordered


async def create_giveaway_verification_challenge(
    giveaway_id: int,
    user_id: int,
    *,
    answer_factory: Callable[[], tuple[str, str, list[str]]] | None = None,
) -> GiveawayVerificationChallenge:
    question, answer, options = (answer_factory or _make_verification_answer)()
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO giveaway_verifications (
                giveaway_id, user_id, question, answer, options_json, verified, created_at, verified_at
            )
            VALUES (?, ?, ?, ?, ?, 0, ?, NULL)
            """,
            (giveaway_id, user_id, question, answer, json.dumps(options, ensure_ascii=False), _dt_to_db(_utcnow())),
        )
        await db.commit()
    return GiveawayVerificationChallenge(question=question, answer=answer, options=list(options))


async def is_giveaway_verified(giveaway_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(database.DB_PATH) as db:
        async with db.execute(
            "SELECT verified FROM giveaway_verifications WHERE giveaway_id = ? AND user_id = ?",
            (giveaway_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
            return bool(row and row[0])


async def verify_giveaway_answer(giveaway_id: int, user_id: int, answer: str) -> bool:
    async with aiosqlite.connect(database.DB_PATH) as db:
        async with db.execute(
            "SELECT answer FROM giveaway_verifications WHERE giveaway_id = ? AND user_id = ?",
            (giveaway_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
        if not row or str(row[0]) != str(answer).strip():
            return False
        await db.execute(
            "UPDATE giveaway_verifications SET verified = 1, verified_at = ? WHERE giveaway_id = ? AND user_id = ?",
            (_dt_to_db(_utcnow()), giveaway_id, user_id),
        )
        await db.commit()
        return True


async def mark_winners(giveaway_id: int, winners: list[GiveawayEntry]) -> None:
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute("UPDATE giveaway_entries SET is_winner = 0 WHERE giveaway_id = ?", (giveaway_id,))
        for winner in winners:
            await db.execute(
                "UPDATE giveaway_entries SET is_winner = 1 WHERE giveaway_id = ? AND user_id = ?",
                (giveaway_id, winner.user_id),
            )
        await db.commit()


async def select_winners(
    entries: list[GiveawayEntry],
    winners_count: int,
    *,
    is_subscribed: Callable[[int], Awaitable[bool]],
    shuffle: Callable[[list[GiveawayEntry]], list[GiveawayEntry] | None] | None = None,
) -> WinnerSelectionResult:
    pool = list(entries)
    if shuffle is None:
        random.shuffle(pool)
    else:
        shuffled = shuffle(pool)
        if shuffled is not None:
            pool = list(shuffled)

    winners: list[GiveawayEntry] = []
    replaced_count = 0
    for entry in pool:
        if len(winners) >= winners_count:
            break
        if await is_subscribed(entry.user_id):
            winners.append(entry)
        else:
            replaced_count += 1
    return WinnerSelectionResult(winners=winners, replaced_count=replaced_count)


async def is_channel_subscriber(bot, channel_id: str, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
    except Exception as exc:  # noqa: BLE001 - Telegram API may fail; fail closed for giveaways.
        logging.info("giveaway subscription check failed: channel=%s user=%s error=%s", channel_id, user_id, type(exc).__name__)
        return False
    raw_status = getattr(member, "status", "")
    status = getattr(raw_status, "value", raw_status)
    return str(status) in JOINED_STATUSES


def _telegram_error_text(exc: Exception) -> str:
    message = getattr(exc, "message", None) or str(exc)
    return str(message).strip() or type(exc).__name__


def _format_publish_error(exc: Exception) -> str:
    detail = _telegram_error_text(exc)
    lowered = detail.lower()
    if "chat not found" in lowered:
        hint = "Бот не видит канал. Проверьте @username/-100 id и добавьте бота администратором канала."
    elif "not enough rights" in lowered or "not enough privileges" in lowered or "need administrator" in lowered:
        hint = "У бота нет прав публикации. Выдайте ему права администратора с публикацией постов."
    elif "can't parse entities" in lowered or "entities" in lowered:
        hint = "Telegram не принял разметку текста. Попробуйте убрать нестандартные HTML-символы."
    elif "message is too long" in lowered or "caption is too long" in lowered:
        hint = "Текст слишком длинный для Telegram. Сократите описание или призы."
    else:
        hint = "Telegram отклонил публикацию. Точный ответ API ниже."
    return f"{hint}\n\nОтвет Telegram: {detail}"


async def validate_publish_channel(bot, channel_id: str) -> None:
    try:
        await bot.get_chat(chat_id=channel_id)
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id=channel_id, user_id=me.id)
    except TelegramAPIError as exc:
        raise GiveawayPublishError(_format_publish_error(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - keep diagnostics visible to the admin.
        raise GiveawayPublishError(_format_publish_error(exc)) from exc

    raw_status = getattr(member, "status", "")
    status = str(getattr(raw_status, "value", raw_status))
    if status not in {"administrator", "creator"}:
        raise GiveawayPublishError("Бот найден в канале, но он не администратор. Выдайте права администратора с публикацией постов.")
    can_post = getattr(member, "can_post_messages", True)
    if can_post is False:
        raise GiveawayPublishError("Бот администратор канала, но без права публикации постов.")


def _giveaway_post_text(giveaway: Giveaway) -> str:
    prizes = _format_prizes_block(giveaway.prize, giveaway.winners_count)
    return (
        f"🎁 <b>Розыгрыш</b>\n\n"
        f"{escape_html_text(giveaway.post_text)}\n\n"
        f"🏆 <b>Призы:</b>\n{escape_html_text(prizes)}\n\n"
        f"👥 <b>Победителей:</b> {giveaway.winners_count}\n"
        f"⏰ <b>Итоги:</b> {format_giveaway_end(giveaway.ends_at_utc)} МСК\n\n"
        "Нажмите кнопку ниже, чтобы участвовать."
    )


def _participation_markup(giveaway_id: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Участвовать", callback_data=f"giveaway_join:{giveaway_id}")
    builder.adjust(1)
    return builder.as_markup()


def _preview_markup() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Опубликовать", callback_data="giveaway_preview_publish")
    builder.button(text="Изменить текст", callback_data="giveaway_preview_edit_text")
    builder.button(text="Изменить призы", callback_data="giveaway_preview_edit_prizes")
    builder.button(text="Изменить медиа", callback_data="giveaway_preview_edit_media")
    builder.button(text="Отменить", callback_data="giveaway_preview_cancel")
    builder.adjust(1)
    return builder.as_markup()


def _verification_markup(giveaway_id: int, options: list[str]) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for option in options:
        builder.button(text=option, callback_data=f"giveaway_verify:{giveaway_id}:{option}")
    builder.adjust(3)
    return builder.as_markup()


async def publish_giveaway_post(bot, giveaway: Giveaway) -> int:
    text = _giveaway_post_text(giveaway)
    markup = _participation_markup(giveaway.id)
    if giveaway.media_type == "photo":
        msg = await bot.send_photo(
            chat_id=giveaway.channel_id, photo=giveaway.media_file_id, caption=text, parse_mode="HTML", reply_markup=markup
        )
    elif giveaway.media_type == "video":
        msg = await bot.send_video(
            chat_id=giveaway.channel_id, video=giveaway.media_file_id, caption=text, parse_mode="HTML", reply_markup=markup
        )
    elif giveaway.media_type == "document":
        msg = await bot.send_document(
            chat_id=giveaway.channel_id,
            document=giveaway.media_file_id,
            caption=text,
            parse_mode="HTML",
            reply_markup=markup,
        )
    elif giveaway.media_type == "animation":
        msg = await bot.send_animation(
            chat_id=giveaway.channel_id,
            animation=giveaway.media_file_id,
            caption=text,
            parse_mode="HTML",
            reply_markup=markup,
        )
    else:
        msg = await bot.send_message(
            chat_id=giveaway.channel_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=markup,
        )
    return int(msg.message_id)


def extract_media_from_message(message: types.Message | None) -> tuple[str | None, str | None]:
    if not message:
        return None, None
    if getattr(message, "photo", None):
        return "photo", message.photo[-1].file_id
    for media_type in ("video", "document", "animation"):
        media = getattr(message, media_type, None)
        if media:
            return media_type, media.file_id
    return None, None


def _parse_quick_create(text: str) -> tuple[datetime, int, str, str]:
    _, ends_at, winners_count, prize, post_text = _parse_quick_create_with_channel(text)
    return ends_at, winners_count, prize, post_text


def _parse_quick_create_with_channel(text: str) -> tuple[str, datetime, int, str, str]:
    raw = text.split(" ", 1)[1].strip() if " " in text else ""
    channel_id = GIVEAWAY_CHANNEL_ID
    if raw and not raw.startswith("|"):
        maybe_channel, sep, rest = raw.partition("|")
        candidate = maybe_channel.strip()
        if sep and (candidate.startswith("@") or candidate.startswith("-100")):
            channel_id = candidate
            raw = rest.strip()
    if raw.startswith("|"):
        raw = raw[1:].strip()
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) == 3:
        ends_raw, prize, post_text = parts
        winners_count = len(split_place_prizes(prize))
    elif len(parts) == 4:
        ends_raw, winners_raw, prize, post_text = parts
        try:
            winners_count = int(winners_raw)
        except ValueError as exc:
            raise GiveawayValidationError("Количество победителей должно быть числом.") from exc
    else:
        raise GiveawayValidationError("Формат: /giveaway_create [@channel] | 3d | Приз 1; Приз 2 | Текст поста")
    ends_at = parse_giveaway_end(ends_raw)
    if winners_count < 1:
        raise GiveawayValidationError("Нужен хотя бы один победитель.")
    prize = prize.strip()
    post_text = post_text.strip()
    if not prize or not post_text:
        raise GiveawayValidationError("Приз и текст поста обязательны.")
    return channel_id, ends_at, winners_count, prize, post_text


async def create_and_publish_giveaway(
    bot,
    *,
    created_by: int,
    channel_id: str = GIVEAWAY_CHANNEL_ID,
    ends_at_utc: datetime,
    winners_count: int,
    prize: str,
    post_text: str,
    media_type: str | None = None,
    media_file_id: str | None = None,
) -> int:
    await validate_publish_channel(bot, channel_id)
    giveaway_id = await create_giveaway(
        channel_id=channel_id,
        prize=prize,
        post_text=post_text,
        winners_count=winners_count,
        ends_at_utc=ends_at_utc,
        created_by=created_by,
        media_type=media_type,
        media_file_id=media_file_id,
    )
    giveaway = await get_giveaway(giveaway_id)
    if giveaway is None:
        raise RuntimeError("Giveaway was not created.")
    try:
        message_id = await publish_giveaway_post(bot, giveaway)
    except Exception:
        await cancel_giveaway(giveaway_id)
        raise
    await set_giveaway_published(giveaway_id, message_id)
    return giveaway_id


def _format_winner(entry: GiveawayEntry) -> str:
    name = escape_html_text(entry.first_name or entry.username or f"user#{entry.user_id}")
    return f'<a href="tg://user?id={entry.user_id}">{name}</a>'


def format_winner_lines(winners: list[GiveawayEntry], prize_text: str) -> str:
    prizes = split_place_prizes(prize_text)
    lines = []
    for idx, entry in enumerate(winners, 1):
        prize = prizes[idx - 1] if idx - 1 < len(prizes) else (prizes[-1] if prizes else "Приз")
        lines.append(f"{idx} место — {_format_winner(entry)}\n🏆 {escape_html_text(prize)}")
    return "\n\n".join(lines)


async def finalize_giveaway(bot, giveaway: Giveaway) -> bool:
    if not await claim_giveaway_finishing(giveaway.id):
        return False
    entries = await get_giveaway_entries(giveaway.id)

    async def is_subscribed(user_id: int) -> bool:
        return await is_channel_subscriber(bot, giveaway.channel_id, user_id)

    result = await select_winners(entries, giveaway.winners_count, is_subscribed=is_subscribed)
    await mark_winners(giveaway.id, result.winners)
    await mark_giveaway_finished(giveaway.id, replacements_count=result.replaced_count)

    participants_count = len(entries)
    if result.winners:
        winners_text = format_winner_lines(result.winners, giveaway.prize)
        shortage = ""
        if len(result.winners) < giveaway.winners_count:
            shortage = f"\n\nПодходящих участников было меньше, чем мест: выбрано {len(result.winners)} из {giveaway.winners_count}."
        replaced = f"\nЗамен из-за отписки: {result.replaced_count}." if result.replaced_count else ""
        text = (
            "🎉 <b>Итоги розыгрыша</b>\n\n"
            f"👥 Участников: <b>{participants_count}</b>\n\n"
            f"Победители:\n{winners_text}{replaced}{shortage}"
        )
    else:
        text = (
            "🎉 <b>Итоги розыгрыша</b>\n\n"
            f"👥 Участников: <b>{participants_count}</b>\n"
            "Победителей нет: не нашлось участников с актуальной подпиской."
        )
    await bot.send_message(chat_id=giveaway.channel_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    if giveaway.message_id:
        try:
            await bot.edit_message_reply_markup(chat_id=giveaway.channel_id, message_id=giveaway.message_id, reply_markup=None)
        except Exception as exc:  # noqa: BLE001 - result post is more important than removing old button.
            logging.debug("giveaway: failed to remove old markup: %s", exc)
    return True


async def run_giveaway_scheduler(bot, *, interval_seconds: int = 30) -> None:
    while True:
        try:
            for giveaway in await list_due_giveaways():
                try:
                    await finalize_giveaway(bot, giveaway)
                except Exception as exc:  # noqa: BLE001 - keep scheduler alive.
                    logging.exception("giveaway finalization failed: id=%s error=%s", giveaway.id, exc)
        except Exception as exc:  # noqa: BLE001 - keep scheduler alive.
            logging.exception("giveaway scheduler failed: %s", exc)
        await asyncio.sleep(interval_seconds)


def _admin_giveaway_menu() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Создать розыгрыш", callback_data="admin_giveaway_create")
    builder.button(text="Активные розыгрыши", callback_data="admin_giveaway_active")
    builder.button(text="Назад", callback_data="admin_menu")
    builder.adjust(1)
    return builder.as_markup()


@giveaway_router.message(Command("giveaway_create"))
async def cmd_giveaway_create(message: types.Message, state: FSMContext):
    if not await _is_bot_admin(message.from_user.id):
        return
    try:
        channel_id, ends_at, winners_count, prize, post_text = _parse_quick_create_with_channel(message.text or "")
    except GiveawayValidationError as exc:
        return await message.answer(str(exc))
    media_type, media_file_id = extract_media_from_message(message.reply_to_message)
    await state.update_data(
        channel_id=channel_id,
        ends_at_utc=_dt_to_db(ends_at),
        winners_count=winners_count,
        prize=prize,
        post_text=post_text,
        media_type=media_type,
        media_file_id=media_file_id,
    )
    await _show_giveaway_preview(message, state)


@giveaway_router.callback_query(F.data == "admin_giveaways")
async def admin_giveaways_menu(callback: types.CallbackQuery):
    if not await _require_admin(callback):
        return
    await callback.message.edit_text(
        f"Розыгрыши. Основной канал: {GIVEAWAY_CHANNEL_ID}",
        reply_markup=_admin_giveaway_menu(),
    )
    await callback.answer()


@giveaway_router.callback_query(F.data == "admin_giveaway_create")
async def admin_giveaway_create(callback: types.CallbackQuery, state: FSMContext):
    if not await _require_admin(callback):
        return
    await state.set_state(GiveawayCreate.waiting_for_channel)
    await callback.message.edit_text(
        f"Введите канал для публикации и проверки подписки: @channel или -100...\n\n"
        f"Для основного {GIVEAWAY_CHANNEL_ID} отправьте /skip.\nДля отмены: /cancel"
    )
    await callback.answer()


@giveaway_router.message(StateFilter(GiveawayCreate.waiting_for_channel, GiveawayCreate.waiting_for_media), Command("skip"))
async def giveaway_create_skip(message: types.Message, state: FSMContext):
    if not await _is_bot_admin(message.from_user.id):
        return await state.clear()
    current_state = await state.get_state()
    if current_state == GiveawayCreate.waiting_for_media.state:
        return await _finish_giveaway_wizard(message, state, None, None)
    await state.update_data(channel_id=GIVEAWAY_CHANNEL_ID)
    await state.set_state(GiveawayCreate.waiting_for_end)
    await message.answer("Когда завершить розыгрыш? Время указывайте по МСК. Например: 27.04.2026 20:00, 12h или 3d.")


@giveaway_router.message(StateFilter(GiveawayCreate.waiting_for_channel))
async def giveaway_create_channel(message: types.Message, state: FSMContext):
    if not await _is_bot_admin(message.from_user.id):
        return await state.clear()
    channel_id = (message.text or "").strip()
    if not (channel_id.startswith("@") or channel_id.startswith("-100")):
        return await message.answer("Канал должен быть в формате @channel или -100... Можно отправить /skip.")
    await state.update_data(channel_id=channel_id)
    await state.set_state(GiveawayCreate.waiting_for_end)
    await message.answer("Когда завершить розыгрыш? Время указывайте по МСК. Например: 27.04.2026 20:00, 12h или 3d.")


@giveaway_router.message(StateFilter(GiveawayCreate.waiting_for_prize))
async def giveaway_create_prize(message: types.Message, state: FSMContext):
    if not await _is_bot_admin(message.from_user.id):
        return await state.clear()
    prize = (message.text or "").strip()
    if not prize or prize.startswith("/"):
        return await message.answer("Введите приз текстом или отмените через /cancel.")
    await state.update_data(prize=prize)
    data = await state.get_data()
    if data.get("preview_edit") == "prizes":
        await state.update_data(preview_edit=None)
        return await _show_giveaway_preview(message, state)
    await state.set_state(GiveawayCreate.waiting_for_text)
    await message.answer("Отправьте текст поста для канала.")


@giveaway_router.message(StateFilter(GiveawayCreate.waiting_for_end))
async def giveaway_create_end(message: types.Message, state: FSMContext):
    if not await _is_bot_admin(message.from_user.id):
        return await state.clear()
    try:
        ends_at = parse_giveaway_end(message.text or "")
    except GiveawayValidationError as exc:
        return await message.answer(str(exc))
    await state.update_data(ends_at_utc=_dt_to_db(ends_at))
    await state.set_state(GiveawayCreate.waiting_for_winners)
    await message.answer("Сколько победителей выбрать? Введите число от 1.")


@giveaway_router.message(StateFilter(GiveawayCreate.waiting_for_winners))
async def giveaway_create_winners(message: types.Message, state: FSMContext):
    if not await _is_bot_admin(message.from_user.id):
        return await state.clear()
    try:
        winners_count = int((message.text or "").strip())
    except ValueError:
        return await message.answer("Количество победителей должно быть числом.")
    if winners_count < 1:
        return await message.answer("Нужен хотя бы один победитель.")
    await state.update_data(winners_count=winners_count)
    await state.set_state(GiveawayCreate.waiting_for_prize)
    await message.answer(
        "Введите призы по местам. Можно одной строкой через ;\n" "Например: 1 место: VIP; 2 место: 500 монет; 3 место: роль"
    )


@giveaway_router.message(StateFilter(GiveawayCreate.waiting_for_text))
async def giveaway_create_text(message: types.Message, state: FSMContext):
    if not await _is_bot_admin(message.from_user.id):
        return await state.clear()
    post_text = (message.text or message.caption or "").strip()
    if not post_text:
        return await message.answer("Текст поста обязателен.")
    await state.update_data(post_text=post_text)
    data = await state.get_data()
    if data.get("preview_edit") == "text":
        await state.update_data(preview_edit=None)
        return await _show_giveaway_preview(message, state)
    await state.set_state(GiveawayCreate.waiting_for_media)
    await message.answer("Отправьте фото/видео/документ/GIF для поста или /skip, если медиа не нужно.")


@giveaway_router.message(StateFilter(GiveawayCreate.waiting_for_media))
async def giveaway_create_media(message: types.Message, state: FSMContext):
    media_type, media_file_id = extract_media_from_message(message)
    if not media_type:
        return await message.answer("Поддерживается фото, видео, документ или GIF. Можно отправить /skip.")
    await _finish_giveaway_wizard(message, state, media_type, media_file_id)


async def _finish_giveaway_wizard(message: types.Message, state: FSMContext, media_type: str | None, media_file_id: str | None):
    if not await _is_bot_admin(message.from_user.id):
        return await state.clear()
    await state.update_data(media_type=media_type, media_file_id=media_file_id)
    await _show_giveaway_preview(message, state)


async def _show_giveaway_preview(message: types.Message, state: FSMContext):
    data = await state.get_data()
    giveaway = Giveaway(
        id=0,
        status=GIVEAWAY_STATUS_DRAFT,
        channel_id=str(data.get("channel_id") or GIVEAWAY_CHANNEL_ID),
        message_id=None,
        prize=str(data["prize"]),
        post_text=str(data["post_text"]),
        winners_count=int(data["winners_count"]),
        ends_at_utc=_dt_from_db(data["ends_at_utc"]),
        created_by=message.from_user.id,
        media_type=data.get("media_type"),
        media_file_id=data.get("media_file_id"),
    )
    media_note = f"\n\nМедиа: {giveaway.media_type}" if giveaway.media_type else "\n\nМедиа: нет"
    await state.set_state(GiveawayCreate.waiting_for_preview)
    await message.answer(
        "Предпросмотр перед публикацией:\n\n" + _giveaway_post_text(giveaway) + media_note,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=_preview_markup(),
    )


async def _publish_giveaway_from_state(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        giveaway_id = await create_and_publish_giveaway(
            message.bot,
            created_by=message.from_user.id,
            channel_id=str(data.get("channel_id") or GIVEAWAY_CHANNEL_ID),
            ends_at_utc=_dt_from_db(data["ends_at_utc"]),
            winners_count=int(data["winners_count"]),
            prize=str(data["prize"]),
            post_text=str(data["post_text"]),
            media_type=data.get("media_type"),
            media_file_id=data.get("media_file_id"),
        )
    except GiveawayPublishError as exc:
        logging.warning("giveaway publish failed: %s", exc)
        return await message.answer(f"Не удалось опубликовать розыгрыш:\n{exc}")
    except Exception as exc:  # noqa: BLE001 - show admin the publication failure.
        logging.exception("giveaway wizard failed")
        return await message.answer(f"Не удалось опубликовать розыгрыш:\n{_format_publish_error(exc)}")
    await state.clear()
    await message.answer(f"Розыгрыш #{giveaway_id} опубликован в {data.get('channel_id') or GIVEAWAY_CHANNEL_ID}.")


@giveaway_router.callback_query(StateFilter(GiveawayCreate.waiting_for_preview), F.data == "giveaway_preview_publish")
async def giveaway_preview_publish(callback: types.CallbackQuery, state: FSMContext):
    if not await _require_admin(callback):
        return
    await _publish_giveaway_from_state(callback.message, state)
    await callback.answer()


@giveaway_router.callback_query(StateFilter(GiveawayCreate.waiting_for_preview), F.data == "giveaway_preview_edit_text")
async def giveaway_preview_edit_text(callback: types.CallbackQuery, state: FSMContext):
    if not await _require_admin(callback):
        return
    await state.update_data(preview_edit="text")
    await state.set_state(GiveawayCreate.waiting_for_text)
    await callback.message.answer("Отправьте новый текст поста.")
    await callback.answer()


@giveaway_router.callback_query(StateFilter(GiveawayCreate.waiting_for_preview), F.data == "giveaway_preview_edit_prizes")
async def giveaway_preview_edit_prizes(callback: types.CallbackQuery, state: FSMContext):
    if not await _require_admin(callback):
        return
    await state.update_data(preview_edit="prizes")
    await state.set_state(GiveawayCreate.waiting_for_prize)
    await callback.message.answer("Отправьте новый список призов по местам.")
    await callback.answer()


@giveaway_router.callback_query(StateFilter(GiveawayCreate.waiting_for_preview), F.data == "giveaway_preview_edit_media")
async def giveaway_preview_edit_media(callback: types.CallbackQuery, state: FSMContext):
    if not await _require_admin(callback):
        return
    await state.set_state(GiveawayCreate.waiting_for_media)
    await callback.message.answer("Отправьте новое медиа или /skip, чтобы убрать медиа.")
    await callback.answer()


@giveaway_router.callback_query(StateFilter(GiveawayCreate.waiting_for_preview), F.data == "giveaway_preview_cancel")
async def giveaway_preview_cancel(callback: types.CallbackQuery, state: FSMContext):
    if not await _require_admin(callback):
        return
    await state.clear()
    await callback.message.answer("Розыгрыш отменён.")
    await callback.answer()


@giveaway_router.callback_query(F.data == "admin_giveaway_active")
async def admin_giveaway_active(callback: types.CallbackQuery):
    if not await _require_admin(callback):
        return
    active = await list_active_giveaways()
    if not active:
        text = "Активных розыгрышей нет."
    else:
        lines = ["Активные розыгрыши:"]
        for item in active:
            count = await count_giveaway_entries(item.id)
            lines.append(f"#{item.id}: {item.prize} · участников {count} · до {format_giveaway_end(item.ends_at_utc)}")
        text = "\n".join(lines)
    builder = InlineKeyboardBuilder()
    for item in active[:10]:
        builder.button(text=f"Завершить #{item.id}", callback_data=f"giveaway_finish:{item.id}")
        builder.button(text=f"Отменить #{item.id}", callback_data=f"giveaway_cancel:{item.id}")
    builder.button(text="Назад", callback_data="admin_giveaways")
    builder.adjust(2, 1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@giveaway_router.callback_query(F.data.startswith("giveaway_finish:"))
async def admin_giveaway_finish_now(callback: types.CallbackQuery):
    if not await _require_admin(callback):
        return
    giveaway_id = int(callback.data.split(":", 1)[1])
    giveaway = await get_giveaway(giveaway_id)
    if giveaway is None or giveaway.status != GIVEAWAY_STATUS_ACTIVE:
        return await callback.answer("Розыгрыш не найден или уже закрыт.", show_alert=True)
    await finalize_giveaway(callback.bot, giveaway)
    await callback.answer("Розыгрыш завершён.")
    await admin_giveaway_active(callback)


@giveaway_router.callback_query(F.data.startswith("giveaway_cancel:"))
async def admin_giveaway_cancel(callback: types.CallbackQuery):
    if not await _require_admin(callback):
        return
    giveaway_id = int(callback.data.split(":", 1)[1])
    if not await cancel_giveaway(giveaway_id):
        return await callback.answer("Розыгрыш не найден или уже закрыт.", show_alert=True)
    await callback.answer("Розыгрыш отменён.")
    await admin_giveaway_active(callback)


@giveaway_router.callback_query(F.data.startswith("giveaway_join:"))
async def giveaway_join(callback: types.CallbackQuery):
    giveaway_id = int(callback.data.split(":", 1)[1])
    giveaway = await get_giveaway(giveaway_id)
    if giveaway is None or giveaway.status != GIVEAWAY_STATUS_ACTIVE:
        return await callback.answer("Розыгрыш уже завершён.", show_alert=True)
    if await has_giveaway_entry(giveaway_id, callback.from_user.id):
        return await callback.answer("Вы уже участвуете.", show_alert=False)
    if not await is_channel_subscriber(callback.bot, giveaway.channel_id, callback.from_user.id):
        return await callback.answer(
            f"Участвовать могут только подписчики канала {_channel_url(giveaway.channel_id)}",
            show_alert=True,
        )
    if not await is_giveaway_verified(giveaway_id, callback.from_user.id):
        challenge = await create_giveaway_verification_challenge(giveaway_id, callback.from_user.id)
        try:
            await callback.bot.send_message(
                chat_id=callback.from_user.id,
                text=(
                    f"Проверка участия в розыгрыше #{giveaway_id}\n\n" f"Ответьте на простой вопрос: сколько будет {challenge.question}?"
                ),
                reply_markup=_verification_markup(giveaway_id, challenge.options),
            )
        except TelegramAPIError:
            return await callback.answer(
                "Для защиты от ботов нужно пройти проверку в ЛС. Откройте личный чат с ботом, нажмите Start и затем нажмите участвовать ещё раз.",
                show_alert=True,
            )
        return await callback.answer("Я отправил проверку в личные сообщения. Ответьте там, и я добавлю вас в участники.", show_alert=True)
    added = await add_giveaway_entry(
        giveaway_id,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.first_name,
    )
    await callback.answer("Вы участвуете!" if added else "Вы уже участвуете.", show_alert=False)


@giveaway_router.callback_query(F.data.startswith("giveaway_verify:"))
async def giveaway_verify(callback: types.CallbackQuery):
    try:
        _, giveaway_id_raw, answer = callback.data.split(":", 2)
        giveaway_id = int(giveaway_id_raw)
    except (ValueError, AttributeError):
        return await callback.answer("Некорректная проверка.", show_alert=True)
    if not await verify_giveaway_answer(giveaway_id, callback.from_user.id, answer):
        return await callback.answer(
            "Неверный ответ. Нажмите кнопку участия в канале ещё раз, чтобы получить новую проверку.", show_alert=True
        )
    giveaway = await get_giveaway(giveaway_id)
    if giveaway is None or giveaway.status != GIVEAWAY_STATUS_ACTIVE:
        return await callback.answer("Розыгрыш уже завершён.", show_alert=True)
    if not await is_channel_subscriber(callback.bot, giveaway.channel_id, callback.from_user.id):
        return await callback.answer("Подписка на канал больше не найдена.", show_alert=True)
    added = await add_giveaway_entry(
        giveaway_id,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.first_name,
    )
    text = "Проверка пройдена, вы добавлены в участники." if added else "Проверка пройдена, вы уже участвуете."
    try:
        await callback.message.edit_text(text)
    except Exception:  # noqa: BLE001 - callback answer is enough if DM message can't be edited.
        pass
    await callback.answer(text, show_alert=True)
