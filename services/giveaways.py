"""Telegram channel giveaways.

The module owns giveaway storage helpers, publication/finalization logic, and
the aiogram router. It intentionally does not import ``bot.py``.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import random
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiosqlite
from aiogram import F, Router, types
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import database
from config import GIVEAWAY_CHANNEL_ID, GIVEAWAY_CHANNEL_URL, GIVEAWAY_MINI_APP_SHORT_NAME
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
GIVEAWAY_STATUS_SCHEDULED = "scheduled"
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
    publish_at_utc: datetime | None = None
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
    joined_at_utc: datetime | None = None
    winner_place: int | None = None


@dataclass(frozen=True)
class GiveawayParticipantStats:
    giveaway_id: int
    channel_id: str
    prize: str
    winners_count: int
    ends_at_utc: datetime
    entries_count: int


@dataclass(frozen=True)
class GiveawayRequiredChannel:
    giveaway_id: int
    channel_id: str
    title: str
    url: str


@dataclass(frozen=True)
class GiveawaySubscriptionCheck:
    is_allowed: bool
    missing_channels: list[str]


@dataclass(frozen=True)
class WinnerSelectionResult:
    winners: list[GiveawayEntry]
    replaced_count: int


@dataclass(frozen=True)
class GiveawayRerollResult:
    place: int
    old_winner: GiveawayEntry
    new_winner: GiveawayEntry


@dataclass(frozen=True)
class GiveawayVerificationChallenge:
    question: str
    answer: str
    options: list[str]


class GiveawayCreate(StatesGroup):
    waiting_for_channel = State()
    waiting_for_required_channels = State()
    waiting_for_publish = State()
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


def parse_giveaway_publish(raw: str, *, now: datetime | None = None) -> datetime | None:
    text = (raw or "").strip().lower()
    if text in {"/now", "now", "сейчас", "сразу", "/skip"}:
        return None
    return parse_giveaway_end(raw, now=now)


def format_giveaway_publish(publish_at_utc: datetime | None) -> str:
    if publish_at_utc is None:
        return "сразу"
    return format_giveaway_end(publish_at_utc)


def _channel_url(channel_id: str) -> str:
    if channel_id.startswith("@"):
        return f"https://t.me/{channel_id[1:]}"
    if channel_id == GIVEAWAY_CHANNEL_ID:
        return GIVEAWAY_CHANNEL_URL
    return str(channel_id)


def parse_required_channels(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    parts = [part.strip() for part in re.split(r"[\s,;]+", text) if part.strip()]
    invalid = [part for part in parts if not (part.startswith("@") or part.startswith("-100"))]
    if invalid:
        raise GiveawayValidationError("Каналы должны быть в формате @channel или -100... Можно отправить /skip.")
    return _normalize_required_channel_ids(parts)


def _normalize_required_channel_ids(channel_ids: list[str] | tuple[str, ...], *, primary_channel_id: str | None = None) -> list[str]:
    seen = {primary_channel_id} if primary_channel_id else set()
    normalized: list[str] = []
    for raw in channel_ids:
        channel_id = str(raw or "").strip()
        if not channel_id or channel_id in seen:
            continue
        seen.add(channel_id)
        normalized.append(channel_id)
    return normalized


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
        publish_at_utc=_dt_from_db(str(row[11])) if row[11] else None,
        replacements_count=int(row[12] or 0),
    )


async def create_giveaway(
    *,
    channel_id: str,
    prize: str,
    post_text: str,
    winners_count: int,
    ends_at_utc: datetime,
    created_by: int,
    publish_at_utc: datetime | None = None,
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
                winners_count, ends_at_utc, created_by, created_at, publish_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                _dt_to_db(publish_at_utc) if publish_at_utc else None,
            ),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def get_giveaway(giveaway_id: int) -> Giveaway | None:
    async with aiosqlite.connect(database.DB_PATH) as db:
        async with db.execute(
            """
            SELECT id, status, channel_id, message_id, prize, post_text, media_type,
                   media_file_id, winners_count, ends_at_utc, created_by, publish_at_utc, replacements_count
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
            WHERE id = ? AND status IN (?, ?)
            """,
            (
                GIVEAWAY_STATUS_ACTIVE,
                message_id,
                _dt_to_db(_utcnow()),
                giveaway_id,
                GIVEAWAY_STATUS_DRAFT,
                GIVEAWAY_STATUS_SCHEDULED,
            ),
        )
        await db.commit()


async def schedule_giveaway_publication(giveaway_id: int) -> bool:
    async with aiosqlite.connect(database.DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE giveaways SET status = ? WHERE id = ? AND status = ?",
            (GIVEAWAY_STATUS_SCHEDULED, giveaway_id, GIVEAWAY_STATUS_DRAFT),
        )
        await db.commit()
        return cursor.rowcount == 1


async def list_due_publication_giveaways(now: datetime | None = None) -> list[Giveaway]:
    now_db = _dt_to_db(now or _utcnow())
    async with aiosqlite.connect(database.DB_PATH) as db:
        async with db.execute(
            """
            SELECT id, status, channel_id, message_id, prize, post_text, media_type,
                   media_file_id, winners_count, ends_at_utc, created_by, publish_at_utc, replacements_count
            FROM giveaways
            WHERE status = ? AND publish_at_utc IS NOT NULL AND publish_at_utc <= ?
            ORDER BY publish_at_utc, id
            """,
            (GIVEAWAY_STATUS_SCHEDULED, now_db),
        ) as cursor:
            rows = await cursor.fetchall()
    return [_row_to_giveaway(row) for row in rows]


async def list_due_giveaways(now: datetime | None = None) -> list[Giveaway]:
    now_db = _dt_to_db(now or _utcnow())
    async with aiosqlite.connect(database.DB_PATH) as db:
        async with db.execute(
            """
            SELECT id, status, channel_id, message_id, prize, post_text, media_type,
                   media_file_id, winners_count, ends_at_utc, created_by, publish_at_utc, replacements_count
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
                   media_file_id, winners_count, ends_at_utc, created_by, publish_at_utc, replacements_count
            FROM giveaways
            WHERE status IN (?, ?, ?)
            ORDER BY ends_at_utc, id
            """,
            (GIVEAWAY_STATUS_SCHEDULED, GIVEAWAY_STATUS_ACTIVE, GIVEAWAY_STATUS_FINISHING),
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
            "UPDATE giveaways SET status = ?, finished_at = ? WHERE id = ? AND status IN (?, ?, ?)",
            (
                GIVEAWAY_STATUS_CANCELLED,
                _dt_to_db(_utcnow()),
                giveaway_id,
                GIVEAWAY_STATUS_ACTIVE,
                GIVEAWAY_STATUS_DRAFT,
                GIVEAWAY_STATUS_SCHEDULED,
            ),
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
            SELECT giveaway_id, user_id, username, first_name, status, is_winner, joined_at, winner_place
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
            joined_at_utc=_dt_from_db(str(row[6])) if row[6] else None,
            winner_place=int(row[7]) if row[7] is not None else None,
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


async def set_giveaway_required_channels(giveaway_id: int, channel_ids: list[str]) -> None:
    normalized = _normalize_required_channel_ids(channel_ids)
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute("DELETE FROM giveaway_required_channels WHERE giveaway_id = ?", (giveaway_id,))
        await db.executemany(
            """
            INSERT INTO giveaway_required_channels (giveaway_id, channel_id, title, url)
            VALUES (?, ?, ?, ?)
            """,
            [(giveaway_id, channel_id, channel_id, _channel_url(channel_id)) for channel_id in normalized],
        )
        await db.commit()


async def get_giveaway_required_channels(giveaway_id: int) -> list[GiveawayRequiredChannel]:
    async with aiosqlite.connect(database.DB_PATH) as db:
        async with db.execute(
            """
            SELECT giveaway_id, channel_id, title, url
            FROM giveaway_required_channels
            WHERE giveaway_id = ?
            ORDER BY rowid
            """,
            (giveaway_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        GiveawayRequiredChannel(
            giveaway_id=int(row[0]),
            channel_id=str(row[1]),
            title=str(row[2]),
            url=str(row[3]),
        )
        for row in rows
    ]


async def get_required_channel_ids(giveaway_id: int) -> list[str]:
    return [item.channel_id for item in await get_giveaway_required_channels(giveaway_id)]


async def list_recent_giveaways(*, created_by: int | None = None, limit: int = 20) -> list[Giveaway]:
    limit = max(1, min(int(limit), 50))
    params: list[object] = []
    where = ""
    if created_by is not None:
        where = "WHERE created_by = ?"
        params.append(created_by)
    params.append(limit)
    async with aiosqlite.connect(database.DB_PATH) as db:
        async with db.execute(
            f"""
            SELECT id, status, channel_id, message_id, prize, post_text, media_type,
                   media_file_id, winners_count, ends_at_utc, created_by, publish_at_utc, replacements_count
            FROM giveaways
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ) as cursor:
            rows = await cursor.fetchall()
    return [_row_to_giveaway(row) for row in rows]


async def clone_giveaway(
    source_giveaway_id: int,
    *,
    created_by: int,
    ends_at_utc: datetime,
    publish_at_utc: datetime | None = None,
) -> int:
    source = await get_giveaway(source_giveaway_id)
    if source is None:
        raise GiveawayValidationError("Giveaway was not found.")
    cloned_id = await create_giveaway(
        channel_id=source.channel_id,
        prize=source.prize,
        post_text=source.post_text,
        winners_count=source.winners_count,
        ends_at_utc=ends_at_utc,
        created_by=created_by,
        publish_at_utc=publish_at_utc,
        media_type=source.media_type,
        media_file_id=source.media_file_id,
    )
    await set_giveaway_required_channels(cloned_id, await get_required_channel_ids(source_giveaway_id))
    return cloned_id


async def build_giveaway_entries_csv(giveaway_id: int) -> str:
    entries = await get_giveaway_entries(giveaway_id)
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        ["giveaway_id", "user_id", "username", "first_name", "joined_at_utc", "joined_at_msk", "status", "is_winner", "winner_place"]
    )
    for entry in entries:
        joined_at_utc = entry.joined_at_utc.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if entry.joined_at_utc else ""
        joined_at_msk = entry.joined_at_utc.astimezone(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S") if entry.joined_at_utc else ""
        writer.writerow(
            [
                entry.giveaway_id,
                entry.user_id,
                entry.username or "",
                entry.first_name or "",
                joined_at_utc,
                joined_at_msk,
                entry.status,
                1 if entry.is_winner else 0,
                entry.winner_place or "",
            ]
        )
    return output.getvalue()


def _xlsx_col(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _xlsx_cell(row: int, col: int, value: object, *, style: int | None = None) -> str:
    ref = f"{_xlsx_col(col)}{row}"
    style_attr = f' s="{style}"' if style is not None else ""
    if isinstance(value, bool):
        value = "Да" if value else "Нет"
    if isinstance(value, int):
        return f'<c r="{ref}"{style_attr}><v>{value}</v></c>'
    text = xml_escape("" if value is None else str(value))
    return f'<c r="{ref}" t="inlineStr"{style_attr}><is><t>{text}</t></is></c>'


def _xlsx_sheet_xml(rows: list[list[object]], *, widths: list[int], freeze_header: bool = False, auto_filter: bool = False) -> str:
    row_count = max(1, len(rows))
    col_count = max(1, max((len(row) for row in rows), default=1))
    dimension = f"A1:{_xlsx_col(col_count)}{row_count}"
    cols = "".join(f'<col min="{idx}" max="{idx}" width="{width}" customWidth="1"/>' for idx, width in enumerate(widths[:col_count], 1))
    pane = (
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
        if freeze_header
        else '<selection activeCell="A1" sqref="A1"/>'
    )
    sheet_rows = []
    for row_idx, row in enumerate(rows, 1):
        cells = []
        for col_idx, value in enumerate(row, 1):
            style = 1 if row_idx == 1 else 2 if col_idx == 8 and value == "Да" else None
            cells.append(_xlsx_cell(row_idx, col_idx, value, style=style))
        sheet_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')
    filter_xml = f'<autoFilter ref="{dimension}"/>' if auto_filter else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="{dimension}"/>'
        f'<sheetViews><sheetView workbookViewId="0">{pane}</sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="18"/>'
        f'<cols>{cols}</cols>'
        f'<sheetData>{"".join(sheet_rows)}</sheetData>'
        f'{filter_xml}'
        '</worksheet>'
    )


def _xlsx_styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/><color rgb="FFFFFFFF"/></font></fonts>'
        '<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF8B5CF6"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFE9D5FF"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>'
        '<border><left style="thin"><color rgb="FFE5E7EB"/></left><right style="thin"><color rgb="FFE5E7EB"/></right>'
        '<top style="thin"><color rgb="FFE5E7EB"/></top><bottom style="thin"><color rgb="FFE5E7EB"/></bottom><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>'
        '<xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyFill="1" applyBorder="1"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )


async def build_giveaway_entries_xlsx(giveaway_id: int) -> bytes:
    giveaway = await get_giveaway(giveaway_id)
    entries = await get_giveaway_entries(giveaway_id)
    participant_rows: list[list[object]] = [
        ["Giveaway ID", "User ID", "Username", "Имя", "Вошел UTC", "Вошел МСК", "Статус", "Победитель", "Место"]
    ]
    for entry in entries:
        joined_at_utc = entry.joined_at_utc.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if entry.joined_at_utc else ""
        joined_at_msk = entry.joined_at_utc.astimezone(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S") if entry.joined_at_utc else ""
        participant_rows.append(
            [
                entry.giveaway_id,
                entry.user_id,
                f"@{entry.username}" if entry.username else "",
                entry.first_name or "",
                joined_at_utc,
                joined_at_msk,
                entry.status,
                "Да" if entry.is_winner else "Нет",
                entry.winner_place or "",
            ]
        )

    summary_rows: list[list[object]] = [["Поле", "Значение"]]
    if giveaway is not None:
        summary_rows.extend(
            [
                ["ID", giveaway.id],
                ["Статус", giveaway.status],
                ["Канал", giveaway.channel_id],
                ["Призы", giveaway.prize],
                ["Победителей", giveaway.winners_count],
                ["Участников", len(entries)],
                ["Финиш МСК", format_giveaway_end(giveaway.ends_at_utc)],
            ]
        )
    else:
        summary_rows.append(["ID", giveaway_id])

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Участники" sheetId="1" r:id="rId1"/><sheet name="Сводка" sheetId="2" r:id="rId2"/></sheets>'
        '</workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/styles.xml", _xlsx_styles_xml())
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            _xlsx_sheet_xml(participant_rows, widths=[13, 14, 20, 24, 22, 22, 16, 16, 10], freeze_header=True, auto_filter=True),
        )
        archive.writestr("xl/worksheets/sheet2.xml", _xlsx_sheet_xml(summary_rows, widths=[20, 42]))
    return output.getvalue()


async def list_giveaway_participant_stats() -> list[GiveawayParticipantStats]:
    async with aiosqlite.connect(database.DB_PATH) as db:
        async with db.execute(
            """
            SELECT g.id, g.channel_id, g.prize, g.winners_count, g.ends_at_utc, COUNT(e.user_id)
            FROM giveaways g
            LEFT JOIN giveaway_entries e ON e.giveaway_id = g.id
            WHERE g.status IN (?, ?, ?)
            GROUP BY g.id, g.channel_id, g.prize, g.winners_count, g.ends_at_utc
            ORDER BY g.ends_at_utc, g.id
            """,
            (GIVEAWAY_STATUS_SCHEDULED, GIVEAWAY_STATUS_ACTIVE, GIVEAWAY_STATUS_FINISHING),
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        GiveawayParticipantStats(
            giveaway_id=int(row[0]),
            channel_id=str(row[1]),
            prize=str(row[2]),
            winners_count=int(row[3]),
            ends_at_utc=_dt_from_db(str(row[4])),
            entries_count=int(row[5]),
        )
        for row in rows
    ]


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
        await db.execute("UPDATE giveaway_entries SET is_winner = 0, winner_place = NULL WHERE giveaway_id = ?", (giveaway_id,))
        for place, winner in enumerate(winners, 1):
            await db.execute(
                "UPDATE giveaway_entries SET is_winner = 1, winner_place = ? WHERE giveaway_id = ? AND user_id = ?",
                (place, giveaway_id, winner.user_id),
            )
        await db.commit()


async def get_giveaway_winners(giveaway_id: int) -> list[GiveawayEntry]:
    entries = await get_giveaway_entries(giveaway_id)
    winners = [entry for entry in entries if entry.is_winner]
    winners.sort(
        key=lambda entry: (
            entry.winner_place if entry.winner_place is not None else 999999,
            entry.joined_at_utc or datetime.min.replace(tzinfo=timezone.utc),
            entry.user_id,
        )
    )
    return [
        GiveawayEntry(
            giveaway_id=entry.giveaway_id,
            user_id=entry.user_id,
            username=entry.username,
            first_name=entry.first_name,
            status=entry.status,
            is_winner=entry.is_winner,
            joined_at_utc=entry.joined_at_utc,
            winner_place=entry.winner_place if entry.winner_place is not None else place,
        )
        for place, entry in enumerate(winners, 1)
    ]


async def _normalize_winner_places(giveaway_id: int) -> list[GiveawayEntry]:
    winners = await get_giveaway_winners(giveaway_id)
    async with aiosqlite.connect(database.DB_PATH) as db:
        for place, winner in enumerate(winners, 1):
            await db.execute(
                "UPDATE giveaway_entries SET winner_place = ? WHERE giveaway_id = ? AND user_id = ? AND is_winner = 1",
                (place, giveaway_id, winner.user_id),
            )
        await db.commit()
    return await get_giveaway_winners(giveaway_id)


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


async def reroll_giveaway_place(
    bot,
    giveaway: Giveaway,
    place: int,
    *,
    shuffle: Callable[[list[GiveawayEntry]], list[GiveawayEntry] | None] | None = None,
) -> GiveawayRerollResult:
    if giveaway.status != GIVEAWAY_STATUS_FINISHED:
        raise GiveawayValidationError("Перевыбор доступен только после завершения розыгрыша.")
    if place < 1 or place > giveaway.winners_count:
        raise GiveawayValidationError("Некорректное место для перевыбора.")

    winners = await _normalize_winner_places(giveaway.id)
    if place > len(winners):
        raise GiveawayValidationError("Для этого места нет текущего победителя.")
    old_winner = winners[place - 1]
    current_winner_ids = {winner.user_id for winner in winners}
    entries = [entry for entry in await get_giveaway_entries(giveaway.id) if entry.user_id not in current_winner_ids]
    if shuffle is None:
        random.shuffle(entries)
    else:
        shuffled = shuffle(entries)
        if shuffled is not None:
            entries = list(shuffled)

    required_channel_ids = await get_required_channel_ids(giveaway.id)
    new_winner = None
    for entry in entries:
        subscription = await check_giveaway_required_subscriptions(bot, giveaway, required_channel_ids, entry.user_id)
        if subscription.is_allowed:
            new_winner = entry
            break
    if new_winner is None:
        raise GiveawayValidationError("Нет подходящего участника для замены.")

    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute(
            "UPDATE giveaway_entries SET is_winner = 0, winner_place = NULL WHERE giveaway_id = ? AND user_id = ?",
            (giveaway.id, old_winner.user_id),
        )
        await db.execute(
            "UPDATE giveaway_entries SET is_winner = 1, winner_place = ? WHERE giveaway_id = ? AND user_id = ?",
            (place, giveaway.id, new_winner.user_id),
        )
        await db.commit()

    result = GiveawayRerollResult(
        place=place,
        old_winner=old_winner,
        new_winner=GiveawayEntry(
            giveaway_id=new_winner.giveaway_id,
            user_id=new_winner.user_id,
            username=new_winner.username,
            first_name=new_winner.first_name,
            status=new_winner.status,
            is_winner=True,
            joined_at_utc=new_winner.joined_at_utc,
            winner_place=place,
        ),
    )
    await publish_giveaway_reroll_result(bot, giveaway, result)
    return result


async def is_channel_subscriber(bot, channel_id: str, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
    except Exception as exc:  # noqa: BLE001 - Telegram API may fail; fail closed for giveaways.
        logging.info("giveaway subscription check failed: channel=%s user=%s error=%s", channel_id, user_id, type(exc).__name__)
        return False
    raw_status = getattr(member, "status", "")
    status = getattr(raw_status, "value", raw_status)
    return str(status) in JOINED_STATUSES


async def validate_subscription_channel(bot, channel_id: str) -> None:
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
        raise GiveawayPublishError(f"Бот должен быть администратором канала {channel_id}, чтобы проверять подписку участников.")


async def check_giveaway_required_subscriptions(
    bot,
    giveaway: Giveaway,
    required_channel_ids: list[str],
    user_id: int,
) -> GiveawaySubscriptionCheck:
    channels = [giveaway.channel_id] + _normalize_required_channel_ids(required_channel_ids, primary_channel_id=giveaway.channel_id)
    missing = []
    for channel_id in channels:
        if not await is_channel_subscriber(bot, channel_id, user_id):
            missing.append(channel_id)
    return GiveawaySubscriptionCheck(is_allowed=not missing, missing_channels=missing)


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
    elif "member list is inaccessible" in lowered:
        hint = "\u0411\u043e\u0442 \u043d\u0435 \u043c\u043e\u0436\u0435\u0442 \u043f\u0440\u043e\u0432\u0435\u0440\u044f\u0442\u044c \u0443\u0447\u0430\u0441\u0442\u043d\u0438\u043a\u043e\u0432 \u044d\u0442\u043e\u0433\u043e \u043a\u0430\u043d\u0430\u043b\u0430. \u0414\u043e\u0431\u0430\u0432\u044c\u0442\u0435 \u0431\u043e\u0442\u0430 \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u043e\u043c \u043a\u0430\u043d\u0430\u043b\u0430, \u0438\u043d\u0430\u0447\u0435 Telegram \u043d\u0435 \u0434\u0430\u0441\u0442 \u043f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0443."
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


def _format_required_channels(channel_ids: list[str]) -> str:
    return ", ".join(channel_ids) if channel_ids else "не указаны"


def _format_subscription_scope(channel_id: str, required_channel_ids: list[str] | None = None) -> str:
    extra_channels = _normalize_required_channel_ids(required_channel_ids or [], primary_channel_id=channel_id)
    lines = [f"Основной канал: {channel_id} (проверяется всегда)"]
    lines.append(f"Доп. каналы: {_format_required_channels(extra_channels)}")
    return "\n".join(lines)


def build_giveaway_mini_app_deeplink(bot_username: str, giveaway_id: int, app_short_name: str = "") -> str | None:
    username = str(bot_username or "").lstrip("@")
    short_name = str(app_short_name or "").strip().strip("/")
    if not username or not short_name:
        return None
    return f"https://t.me/{username}/{quote(short_name)}?startapp={quote(f'giveaway_{int(giveaway_id)}')}"


async def get_giveaway_webapp_status(bot, giveaway_id: int, user_id: int) -> dict:
    giveaway = await get_giveaway(giveaway_id)
    if giveaway is None:
        return {"ok": False, "status": "not_found", "giveaway_id": giveaway_id}

    required_channel_ids = await get_required_channel_ids(giveaway.id)
    subscription = await check_giveaway_required_subscriptions(bot, giveaway, required_channel_ids, user_id)
    required_channels = [{"channel_id": giveaway.channel_id, "title": giveaway.channel_id, "url": _channel_url(giveaway.channel_id)}] + [
        {"channel_id": item.channel_id, "title": item.title, "url": item.url} for item in await get_giveaway_required_channels(giveaway.id)
    ]
    return {
        "ok": True,
        "giveaway_id": giveaway.id,
        "status": giveaway.status,
        "is_active": giveaway.status == GIVEAWAY_STATUS_ACTIVE,
        "is_allowed": subscription.is_allowed,
        "missing_channels": subscription.missing_channels,
        "required_channels": required_channels,
        "joined": await has_giveaway_entry(giveaway.id, user_id),
        "ends_at": format_giveaway_end(giveaway.ends_at_utc),
        "winners_count": giveaway.winners_count,
        "prize": giveaway.prize,
    }


def _giveaway_post_text(giveaway: Giveaway, required_channel_ids: list[str] | None = None) -> str:
    prizes = _format_prizes_block(giveaway.prize, giveaway.winners_count)
    required = _normalize_required_channel_ids(required_channel_ids or [], primary_channel_id=giveaway.channel_id)
    required_line = ""
    if required:
        required_line = f"\n📌 <b>Доп. подписка:</b> {escape_html_text(_format_required_channels(required))}\n"
    return (
        f"🎁 <b>Розыгрыш</b>\n\n"
        f"{escape_html_text(giveaway.post_text)}\n\n"
        f"🏆 <b>Призы:</b>\n{escape_html_text(prizes)}\n\n"
        f"👥 <b>Победителей:</b> {giveaway.winners_count}\n"
        f"⏰ <b>Итоги:</b> {format_giveaway_end(giveaway.ends_at_utc)} МСК\n"
        f"{required_line}\n"
        "Нажмите кнопку ниже, чтобы участвовать."
    )


def _participation_markup(
    giveaway_id: int,
    *,
    mini_app_url: str | None = None,
    entries_count: int | None = None,
) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Участвовать", callback_data=f"giveaway_join:{giveaway_id}")
    if entries_count is not None:
        builder.button(text=f"Участников: {entries_count}", callback_data=f"giveaway_count:{giveaway_id}")
    if mini_app_url:
        builder.button(text="Проверить подписку", url=mini_app_url)
    else:
        builder.button(text="Проверить подписку", callback_data=f"giveaway_check:{giveaway_id}")
    builder.adjust(1)
    return builder.as_markup()


def _preview_markup() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Опубликовать", callback_data="giveaway_preview_publish")
    builder.button(text="🕒 Время публикации", callback_data="giveaway_preview_edit_publish")
    builder.button(text="✍️ Текст поста", callback_data="giveaway_preview_edit_text")
    builder.button(text="🏆 Призы", callback_data="giveaway_preview_edit_prizes")
    builder.button(text="📌 Каналы подписки", callback_data="giveaway_preview_edit_required")
    builder.button(text="🖼 Медиа", callback_data="giveaway_preview_edit_media")
    builder.button(text="❌ Отменить", callback_data="giveaway_preview_cancel")
    builder.adjust(1)
    return builder.as_markup()


def _verification_markup(giveaway_id: int, options: list[str]) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for option in options:
        builder.button(text=option, callback_data=f"giveaway_verify:{giveaway_id}:{option}")
    builder.adjust(3)
    return builder.as_markup()


async def publish_giveaway_post(bot, giveaway: Giveaway, required_channel_ids: list[str] | None = None) -> int:
    if required_channel_ids is None:
        try:
            required_channel_ids = await get_required_channel_ids(giveaway.id)
        except aiosqlite.Error:
            required_channel_ids = []
    text = _giveaway_post_text(giveaway, required_channel_ids)
    mini_app_url = None
    if GIVEAWAY_MINI_APP_SHORT_NAME:
        try:
            me = await bot.get_me()
            mini_app_url = build_giveaway_mini_app_deeplink(me.username, giveaway.id, GIVEAWAY_MINI_APP_SHORT_NAME)
        except Exception as exc:  # noqa: BLE001 - regular participation button must still publish.
            logging.debug("giveaway: failed to build mini app link: %s", exc)
    try:
        entries_count = await count_giveaway_entries(giveaway.id) if giveaway.id else 0
    except aiosqlite.Error:
        entries_count = 0
    markup = _participation_markup(giveaway.id, mini_app_url=mini_app_url, entries_count=entries_count)
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


async def refresh_giveaway_participation_markup(bot, giveaway: Giveaway) -> None:
    if not giveaway.message_id or giveaway.status != GIVEAWAY_STATUS_ACTIVE:
        return
    mini_app_url = None
    if GIVEAWAY_MINI_APP_SHORT_NAME:
        try:
            me = await bot.get_me()
            mini_app_url = build_giveaway_mini_app_deeplink(me.username, giveaway.id, GIVEAWAY_MINI_APP_SHORT_NAME)
        except Exception as exc:  # noqa: BLE001 - callback flow must not fail because of the Mini App link.
            logging.debug("giveaway: failed to build mini app link during refresh: %s", exc)
    try:
        await bot.edit_message_reply_markup(
            chat_id=giveaway.channel_id,
            message_id=giveaway.message_id,
            reply_markup=_participation_markup(
                giveaway.id,
                mini_app_url=mini_app_url,
                entries_count=await count_giveaway_entries(giveaway.id),
            ),
        )
    except TelegramAPIError as exc:
        if "message is not modified" not in _telegram_error_text(exc).lower():
            logging.info("giveaway: failed to refresh participation markup id=%s error=%s", giveaway.id, _telegram_error_text(exc))


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
    required_channel_ids: list[str] | None = None,
    publish_at_utc: datetime | None = None,
) -> int:
    await validate_publish_channel(bot, channel_id)
    normalized_required_channel_ids = _normalize_required_channel_ids(required_channel_ids or [], primary_channel_id=channel_id)
    for required_channel_id in normalized_required_channel_ids:
        await validate_subscription_channel(bot, required_channel_id)
    if publish_at_utc and ends_at_utc <= publish_at_utc:
        raise GiveawayValidationError("Giveaway end time must be after publication time.")
    giveaway_id = await create_giveaway(
        channel_id=channel_id,
        prize=prize,
        post_text=post_text,
        winners_count=winners_count,
        ends_at_utc=ends_at_utc,
        created_by=created_by,
        publish_at_utc=publish_at_utc,
        media_type=media_type,
        media_file_id=media_file_id,
    )
    await set_giveaway_required_channels(giveaway_id, normalized_required_channel_ids)
    giveaway = await get_giveaway(giveaway_id)
    if giveaway is None:
        raise RuntimeError("Giveaway was not created.")
    if publish_at_utc and publish_at_utc > _utcnow():
        await schedule_giveaway_publication(giveaway_id)
        return giveaway_id
    try:
        message_id = await publish_giveaway_post(bot, giveaway, normalized_required_channel_ids)
    except Exception:
        await cancel_giveaway(giveaway_id)
        raise
    await set_giveaway_published(giveaway_id, message_id)
    return giveaway_id


async def publish_scheduled_giveaway(bot, giveaway: Giveaway) -> bool:
    if giveaway.status != GIVEAWAY_STATUS_SCHEDULED:
        return False
    required_channel_ids = await get_required_channel_ids(giveaway.id)
    try:
        message_id = await publish_giveaway_post(bot, giveaway, required_channel_ids)
    except Exception as exc:  # noqa: BLE001 - scheduler must keep running; admin gets details.
        logging.exception("scheduled giveaway publish failed: id=%s error=%s", giveaway.id, exc)
        await cancel_giveaway(giveaway.id)
        await _notify_giveaway_creator(
            bot,
            giveaway,
            f"Не удалось опубликовать запланированный розыгрыш #{giveaway.id}:\n{_format_publish_error(exc)}",
        )
        return False
    await set_giveaway_published(giveaway.id, message_id)
    await _notify_giveaway_creator(bot, giveaway, f"Запланированный розыгрыш #{giveaway.id} опубликован в {giveaway.channel_id}.")
    return True


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


async def publish_giveaway_reroll_result(bot, giveaway: Giveaway, result: GiveawayRerollResult) -> None:
    prizes = split_place_prizes(giveaway.prize)
    prize = prizes[result.place - 1] if result.place - 1 < len(prizes) else (prizes[-1] if prizes else "Приз")
    text = (
        "🔁 <b>Перевыбор победителя</b>\n\n"
        f"<b>Место:</b> {result.place}\n"
        f"<b>Приз:</b> {escape_html_text(prize)}\n\n"
        f"Было: {_format_winner(result.old_winner)}\n"
        f"Стало: {_format_winner(result.new_winner)}"
    )
    await bot.send_message(chat_id=giveaway.channel_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    await _notify_giveaway_creator(bot, giveaway, f"Перевыбор {result.place} места в розыгрыше #{giveaway.id} выполнен.\n\n{text}")


async def _notify_giveaway_creator(bot, giveaway: Giveaway, text: str) -> None:
    try:
        await bot.send_message(chat_id=giveaway.created_by, text=text, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramAPIError as exc:
        logging.info("giveaway: failed to notify creator id=%s error=%s", giveaway.id, _telegram_error_text(exc))


async def finalize_giveaway(bot, giveaway: Giveaway) -> bool:
    if not await claim_giveaway_finishing(giveaway.id):
        return False
    entries = await get_giveaway_entries(giveaway.id)
    required_channel_ids = await get_required_channel_ids(giveaway.id)

    async def is_subscribed(user_id: int) -> bool:
        result = await check_giveaway_required_subscriptions(bot, giveaway, required_channel_ids, user_id)
        return result.is_allowed

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
    try:
        await bot.send_message(chat_id=giveaway.channel_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramAPIError as exc:
        logging.warning("giveaway result post failed: id=%s error=%s", giveaway.id, _telegram_error_text(exc))
        await _notify_giveaway_creator(
            bot,
            giveaway,
            f"Итоги розыгрыша #{giveaway.id} посчитаны, но пост в канал отправить не удалось:\n{escape_html_text(_telegram_error_text(exc))}\n\n{text}",
        )
        return True
    await _notify_giveaway_creator(bot, giveaway, f"Розыгрыш #{giveaway.id} завершен.\n\n{text}")
    return True


async def run_giveaway_scheduler(bot, *, interval_seconds: int = 30) -> None:
    while True:
        try:
            for giveaway in await list_due_publication_giveaways():
                await publish_scheduled_giveaway(bot, giveaway)
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
    builder.button(text="➕ Создать розыгрыш", callback_data="admin_giveaway_create")
    builder.button(text="📋 Активные розыгрыши", callback_data="admin_giveaway_active")
    builder.button(text="Участники", callback_data="admin_giveaway_participants")
    builder.button(text="👤 Мои розыгрыши", callback_data="admin_giveaway_mine")
    builder.button(text="📚 История и Excel", callback_data="admin_giveaway_history")
    builder.button(text="⬅️ Назад", callback_data="admin_menu")
    builder.adjust(1)
    return builder.as_markup()


def _giveaway_status_label(status: str) -> str:
    labels = {
        GIVEAWAY_STATUS_DRAFT: "черновик",
        GIVEAWAY_STATUS_SCHEDULED: "запланирован",
        GIVEAWAY_STATUS_ACTIVE: "активен",
        GIVEAWAY_STATUS_FINISHING: "завершается",
        GIVEAWAY_STATUS_FINISHED: "завершен",
        GIVEAWAY_STATUS_CANCELLED: "отменен",
    }
    return labels.get(status, status)


def _giveaway_status_icon(status: str) -> str:
    icons = {
        GIVEAWAY_STATUS_SCHEDULED: "🕒",
        GIVEAWAY_STATUS_ACTIVE: "🟢",
        GIVEAWAY_STATUS_FINISHING: "🟡",
        GIVEAWAY_STATUS_FINISHED: "✅",
        GIVEAWAY_STATUS_CANCELLED: "⛔",
    }
    return icons.get(status, "⚪")


def _format_admin_giveaway_card(item: Giveaway, *, entries_count: int, required_channels: list[str] | None = None) -> str:
    subscription_scope = _format_subscription_scope(item.channel_id, required_channels or [])
    prizes = _format_prizes_block(item.prize, item.winners_count)
    lines = [
        f"{_giveaway_status_icon(item.status)} <b>Розыгрыш #{item.id}</b>",
        f"Статус: <b>{escape_html_text(_giveaway_status_label(item.status))}</b>",
        f"Канал публикации: {escape_html_text(item.channel_id)}",
        f"Подписка:\n{escape_html_text(subscription_scope)}",
        f"Участники: <b>{entries_count}</b> · мест: <b>{item.winners_count}</b>",
        f"Финиш: <b>{format_giveaway_end(item.ends_at_utc)} МСК</b>",
        f"Призы:\n{escape_html_text(prizes)}",
    ]
    if item.status == GIVEAWAY_STATUS_SCHEDULED:
        lines.insert(2, f"Публикация: <b>{format_giveaway_publish(item.publish_at_utc)} МСК</b>")
    if item.replacements_count:
        lines.append(f"Перевыборов: <b>{item.replacements_count}</b>")
    return "\n".join(lines)


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
        required_channel_ids=[],
        publish_at_utc=None,
    )
    await _show_giveaway_preview(message, state)


@giveaway_router.callback_query(F.data == "admin_giveaways")
async def admin_giveaways_menu(callback: types.CallbackQuery):
    if not await _require_admin(callback):
        return
    await callback.message.edit_text(
        (
            "🎁 <b>Розыгрыши</b>\n"
            f"Основной канал: <code>{escape_html_text(GIVEAWAY_CHANNEL_ID)}</code>\n\n"
            "Здесь создаются посты, проверяются подписки, смотрятся участники, выгружается Excel и запускается перевыбор победителя."
        ),
        parse_mode="HTML",
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


@giveaway_router.message(
    StateFilter(
        GiveawayCreate.waiting_for_channel,
        GiveawayCreate.waiting_for_required_channels,
        GiveawayCreate.waiting_for_publish,
        GiveawayCreate.waiting_for_media,
    ),
    Command("skip"),
)
async def giveaway_create_skip(message: types.Message, state: FSMContext):
    if not await _is_bot_admin(message.from_user.id):
        return await state.clear()
    current_state = await state.get_state()
    if current_state == GiveawayCreate.waiting_for_media.state:
        return await _finish_giveaway_wizard(message, state, None, None)
    if current_state == GiveawayCreate.waiting_for_required_channels.state:
        await state.update_data(required_channel_ids=[])
        data = await state.get_data()
        if data.get("preview_edit") == "required_channels":
            await state.update_data(preview_edit=None)
            return await _show_giveaway_preview(message, state)
        await state.set_state(GiveawayCreate.waiting_for_publish)
        return await message.answer(
            "Когда опубликовать розыгрыш? Отправьте /skip или /now для публикации сразу. Можно 30m, 12h, 3d или 27.04.2026 20:00 по МСК."
        )
    if current_state == GiveawayCreate.waiting_for_publish.state:
        await state.update_data(publish_at_utc=None)
        data = await state.get_data()
        if data.get("preview_edit") == "publish":
            await state.update_data(preview_edit=None)
            return await _show_giveaway_preview(message, state)
        await state.set_state(GiveawayCreate.waiting_for_end)
        return await message.answer("Когда завершить розыгрыш? Время указывайте по МСК. Например: 27.04.2026 20:00, 12h или 3d.")
    await state.update_data(channel_id=GIVEAWAY_CHANNEL_ID)
    await state.set_state(GiveawayCreate.waiting_for_required_channels)
    await message.answer("Укажите доп. каналы для проверки подписки через пробел или отправьте /skip.")


@giveaway_router.message(StateFilter(GiveawayCreate.waiting_for_channel))
async def giveaway_create_channel(message: types.Message, state: FSMContext):
    if not await _is_bot_admin(message.from_user.id):
        return await state.clear()
    channel_id = (message.text or "").strip()
    if not (channel_id.startswith("@") or channel_id.startswith("-100")):
        return await message.answer("Канал должен быть в формате @channel или -100... Можно отправить /skip.")
    await state.update_data(channel_id=channel_id)
    await state.set_state(GiveawayCreate.waiting_for_required_channels)
    await message.answer("Укажите доп. каналы для проверки подписки через пробел или отправьте /skip.")


@giveaway_router.message(StateFilter(GiveawayCreate.waiting_for_required_channels))
async def giveaway_create_required_channels(message: types.Message, state: FSMContext):
    if not await _is_bot_admin(message.from_user.id):
        return await state.clear()
    try:
        channel_ids = parse_required_channels(message.text or "")
    except GiveawayValidationError as exc:
        return await message.answer(str(exc))
    data = await state.get_data()
    channel_ids = _normalize_required_channel_ids(channel_ids, primary_channel_id=str(data.get("channel_id") or GIVEAWAY_CHANNEL_ID))
    for channel_id in channel_ids:
        try:
            await validate_subscription_channel(message.bot, channel_id)
        except GiveawayPublishError as exc:
            return await message.answer(f"Не удалось добавить канал проверки {channel_id}:\n{exc}")
    await state.update_data(required_channel_ids=channel_ids)
    data = await state.get_data()
    if data.get("preview_edit") == "required_channels":
        await state.update_data(preview_edit=None)
        return await _show_giveaway_preview(message, state)
    await state.set_state(GiveawayCreate.waiting_for_publish)
    await message.answer(
        "Когда опубликовать розыгрыш? Отправьте /skip или /now для публикации сразу. Можно 30m, 12h, 3d или 27.04.2026 20:00 по МСК."
    )


@giveaway_router.message(StateFilter(GiveawayCreate.waiting_for_publish))
async def giveaway_create_publish_time(message: types.Message, state: FSMContext):
    if not await _is_bot_admin(message.from_user.id):
        return await state.clear()
    try:
        publish_at = parse_giveaway_publish(message.text or "")
    except GiveawayValidationError as exc:
        return await message.answer(str(exc))
    await state.update_data(publish_at_utc=_dt_to_db(publish_at) if publish_at else None)
    data = await state.get_data()
    if data.get("preview_edit") == "publish":
        await state.update_data(preview_edit=None)
        return await _show_giveaway_preview(message, state)
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
    data = await state.get_data()
    publish_at = _dt_from_db(data["publish_at_utc"]) if data.get("publish_at_utc") else None
    if publish_at and ends_at <= publish_at:
        return await message.answer("Время завершения должно быть позже времени публикации.")
    await state.update_data(ends_at_utc=_dt_to_db(ends_at))
    if data.get("repeat_source_id"):
        return await _show_giveaway_preview(message, state)
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
        publish_at_utc=_dt_from_db(data["publish_at_utc"]) if data.get("publish_at_utc") else None,
        media_type=data.get("media_type"),
        media_file_id=data.get("media_file_id"),
    )
    required_channel_ids = list(data.get("required_channel_ids") or [])
    media_label = giveaway.media_type or "нет"
    subscription_scope = _format_subscription_scope(giveaway.channel_id, required_channel_ids)
    await state.set_state(GiveawayCreate.waiting_for_preview)
    await message.answer(
        "🧾 <b>Предпросмотр перед публикацией</b>\n\n"
        + "<b>Настройки розыгрыша:</b>\n"
        + f"• Канал публикации: {escape_html_text(giveaway.channel_id)}\n"
        + f"• Публикация: {format_giveaway_publish(giveaway.publish_at_utc)} МСК\n"
        + f"• Подписка:\n{escape_html_text(subscription_scope)}\n"
        + f"• Медиа: {escape_html_text(media_label)}\n\n"
        + "<b>Так будет выглядеть пост:</b>\n\n"
        + _giveaway_post_text(giveaway, required_channel_ids),
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
            required_channel_ids=list(data.get("required_channel_ids") or []),
            publish_at_utc=_dt_from_db(data["publish_at_utc"]) if data.get("publish_at_utc") else None,
        )
    except GiveawayPublishError as exc:
        logging.warning("giveaway publish failed: %s", exc)
        return await message.answer(f"Не удалось опубликовать розыгрыш:\n{exc}")
    except Exception as exc:  # noqa: BLE001 - show admin the publication failure.
        logging.exception("giveaway wizard failed")
        return await message.answer(f"Не удалось опубликовать розыгрыш:\n{_format_publish_error(exc)}")
    await state.clear()
    publish_at = _dt_from_db(data["publish_at_utc"]) if data.get("publish_at_utc") else None
    if publish_at and publish_at > _utcnow():
        await message.answer(
            f"Розыгрыш #{giveaway_id} запланирован на {format_giveaway_publish(publish_at)} МСК в {data.get('channel_id') or GIVEAWAY_CHANNEL_ID}."
        )
    else:
        await message.answer(f"Розыгрыш #{giveaway_id} опубликован в {data.get('channel_id') or GIVEAWAY_CHANNEL_ID}.")


@giveaway_router.callback_query(StateFilter(GiveawayCreate.waiting_for_preview), F.data == "giveaway_preview_publish")
async def giveaway_preview_publish(callback: types.CallbackQuery, state: FSMContext):
    if not await _require_admin(callback):
        return
    await _publish_giveaway_from_state(callback.message, state)
    await callback.answer()


@giveaway_router.callback_query(StateFilter(GiveawayCreate.waiting_for_preview), F.data == "giveaway_preview_edit_publish")
async def giveaway_preview_edit_publish(callback: types.CallbackQuery, state: FSMContext):
    if not await _require_admin(callback):
        return
    await state.update_data(preview_edit="publish")
    await state.set_state(GiveawayCreate.waiting_for_publish)
    await callback.message.answer("Отправьте новое время публикации: /now для публикации сразу, 30m, 12h, 3d или DD.MM.YYYY HH:MM по МСК.")
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


@giveaway_router.callback_query(StateFilter(GiveawayCreate.waiting_for_preview), F.data == "giveaway_preview_edit_required")
async def giveaway_preview_edit_required(callback: types.CallbackQuery, state: FSMContext):
    if not await _require_admin(callback):
        return
    await state.update_data(preview_edit="required_channels")
    await state.set_state(GiveawayCreate.waiting_for_required_channels)
    await callback.message.answer("Отправьте новые доп. каналы проверки через пробел или /skip, чтобы убрать их.")
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
        text = "📋 <b>Активные розыгрыши</b>\n\nСейчас нет активных или запланированных розыгрышей."
    else:
        lines = ["📋 <b>Активные и запланированные розыгрыши</b>"]
        for item in active:
            count = await count_giveaway_entries(item.id)
            required = await get_required_channel_ids(item.id)
            lines.append("")
            lines.append(_format_admin_giveaway_card(item, entries_count=count, required_channels=required))
        text = "\n".join(lines)
    builder = InlineKeyboardBuilder()
    for item in active[:10]:
        if item.status == GIVEAWAY_STATUS_ACTIVE:
            builder.button(text=f"🏁 Завершить #{item.id}", callback_data=f"giveaway_finish:{item.id}")
            builder.button(text=f"🔄 Обновить кнопку #{item.id}", callback_data=f"giveaway_refresh_markup:{item.id}")
        builder.button(text=f"⛔ Отменить #{item.id}", callback_data=f"giveaway_cancel:{item.id}")
    builder.button(text="🔄 Обновить кнопки всех активных", callback_data="giveaway_refresh_markups")
    builder.button(text="⬅️ Назад", callback_data="admin_giveaways")
    builder.adjust(2, 2, 1, 1)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    except TelegramAPIError as exc:
        if "message is not modified" not in _telegram_error_text(exc).lower():
            raise
    await callback.answer()


@giveaway_router.callback_query(F.data == "admin_giveaway_participants")
async def admin_giveaway_participants(callback: types.CallbackQuery):
    if not await _require_admin(callback):
        return
    stats = await list_giveaway_participant_stats()
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить", callback_data="admin_giveaway_participants")
    builder.button(text="⬅️ Назад", callback_data="admin_giveaways")
    builder.adjust(1)
    if not stats:
        text = "📈 <b>Участники розыгрышей</b>\n\nАктивных розыгрышей пока нет."
    else:
        total = sum(item.entries_count for item in stats)
        lines = ["📈 <b>Участники активных розыгрышей</b>", f"Всего участников: <b>{total}</b>"]
        for item in stats:
            subscription_scope = _format_subscription_scope(item.channel_id, await get_required_channel_ids(item.giveaway_id))
            prizes = _format_prizes_block(item.prize, item.winners_count)
            lines.append("")
            lines.append(
                f"🎁 <b>Розыгрыш #{item.giveaway_id}</b>\n"
                f"Канал публикации: {escape_html_text(item.channel_id)}\n"
                f"Подписка:\n{escape_html_text(subscription_scope)}\n"
                f"Участники: <b>{item.entries_count}</b> · мест: <b>{item.winners_count}</b>\n"
                f"Финиш: <b>{format_giveaway_end(item.ends_at_utc)} МСК</b>\n"
                f"Призы:\n{escape_html_text(prizes)}"
            )
        text = "\n".join(lines)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    except TelegramAPIError as exc:
        if "message is not modified" not in _telegram_error_text(exc).lower():
            raise
    await callback.answer()


@giveaway_router.callback_query(F.data == "admin_giveaway_history")
async def admin_giveaway_history(callback: types.CallbackQuery):
    if not await _require_admin(callback):
        return
    items = await list_recent_giveaways(limit=10)
    await _render_giveaway_history(callback, items, title="История розыгрышей:", refresh_callback="admin_giveaway_history")


@giveaway_router.callback_query(F.data == "admin_giveaway_mine")
async def admin_giveaway_mine(callback: types.CallbackQuery):
    if not await _require_admin(callback):
        return
    items = await list_recent_giveaways(created_by=callback.from_user.id, limit=10)
    await _render_giveaway_history(callback, items, title="Мои розыгрыши:", refresh_callback="admin_giveaway_mine")


async def _render_giveaway_history(
    callback: types.CallbackQuery,
    items: list[Giveaway],
    *,
    title: str,
    refresh_callback: str,
) -> None:
    builder = InlineKeyboardBuilder()
    if not items:
        text = f"<b>{escape_html_text(title)}</b>\nПока пусто."
    else:
        lines = [f"<b>{escape_html_text(title)}</b>"]
        for item in items:
            count = await count_giveaway_entries(item.id)
            required = await get_required_channel_ids(item.id)
            lines.append("")
            lines.append(_format_admin_giveaway_card(item, entries_count=count, required_channels=required))
            builder.button(text=f"📊 Excel #{item.id}", callback_data=f"giveaway_export:{item.id}")
            if item.status == GIVEAWAY_STATUS_FINISHED:
                builder.button(text=f"🎲 Перевыбор #{item.id}", callback_data=f"giveaway_reroll_menu:{item.id}")
            builder.button(text=f"🔁 Повторить #{item.id}", callback_data=f"giveaway_repeat:{item.id}")
        text = "\n".join(lines)
    builder.button(text="🔄 Обновить", callback_data=refresh_callback)
    builder.button(text="⬅️ Назад", callback_data="admin_giveaways")
    builder.adjust(2, 1, 1)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    except TelegramAPIError as exc:
        if "message is not modified" not in _telegram_error_text(exc).lower():
            raise
    await callback.answer()


@giveaway_router.callback_query(F.data.startswith("giveaway_export:"))
async def admin_giveaway_export(callback: types.CallbackQuery):
    if not await _require_admin(callback):
        return
    giveaway_id = int(callback.data.split(":", 1)[1])
    xlsx_bytes = await build_giveaway_entries_xlsx(giveaway_id)
    filename = f"giveaway_{giveaway_id}_entries.xlsx"
    await callback.message.answer_document(
        types.BufferedInputFile(xlsx_bytes, filename=filename),
        caption=f"Excel-таблица участников розыгрыша #{giveaway_id}",
    )
    await callback.answer("XLSX готов.")


@giveaway_router.callback_query(F.data.startswith("giveaway_repeat:"))
async def admin_giveaway_repeat(callback: types.CallbackQuery, state: FSMContext):
    if not await _require_admin(callback):
        return
    giveaway_id = int(callback.data.split(":", 1)[1])
    giveaway = await get_giveaway(giveaway_id)
    if giveaway is None:
        return await callback.answer("Розыгрыш не найден.", show_alert=True)
    await state.update_data(
        repeat_source_id=giveaway_id,
        channel_id=giveaway.channel_id,
        required_channel_ids=await get_required_channel_ids(giveaway_id),
        winners_count=giveaway.winners_count,
        prize=giveaway.prize,
        post_text=giveaway.post_text,
        media_type=giveaway.media_type,
        media_file_id=giveaway.media_file_id,
    )
    await state.set_state(GiveawayCreate.waiting_for_publish)
    await callback.message.answer(
        f"Повтор розыгрыша #{giveaway_id}. Когда опубликовать новый пост? Отправьте /skip или /now для публикации сразу."
    )
    await callback.answer()


@giveaway_router.callback_query(F.data.startswith("giveaway_reroll_menu:"))
async def admin_giveaway_reroll_menu(callback: types.CallbackQuery):
    if not await _require_admin(callback):
        return
    giveaway_id = int(callback.data.split(":", 1)[1])
    giveaway = await get_giveaway(giveaway_id)
    if giveaway is None or giveaway.status != GIVEAWAY_STATUS_FINISHED:
        return await callback.answer("Перевыбор доступен только для завершенного розыгрыша.", show_alert=True)
    winners = await _normalize_winner_places(giveaway_id)
    if not winners:
        return await callback.answer("В этом розыгрыше нет победителей для перевыбора.", show_alert=True)
    builder = InlineKeyboardBuilder()
    lines = [f"Перевыбор места в розыгрыше #{giveaway_id}:"]
    for winner in winners:
        place = winner.winner_place or 1
        lines.append(f"{place} место: {winner.first_name or winner.username or winner.user_id}")
        builder.button(text=f"{place} место", callback_data=f"giveaway_reroll:{giveaway_id}:{place}")
    builder.button(text="Назад", callback_data="admin_giveaway_history")
    builder.adjust(2, 1)
    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())
    await callback.answer()


@giveaway_router.callback_query(F.data.startswith("giveaway_reroll:"))
async def admin_giveaway_reroll_place(callback: types.CallbackQuery):
    if not await _require_admin(callback):
        return
    _, giveaway_id_raw, place_raw = callback.data.split(":", 2)
    giveaway_id = int(giveaway_id_raw)
    place = int(place_raw)
    giveaway = await get_giveaway(giveaway_id)
    if giveaway is None:
        return await callback.answer("Розыгрыш не найден.", show_alert=True)
    try:
        result = await reroll_giveaway_place(callback.bot, giveaway, place)
    except GiveawayValidationError as exc:
        return await callback.answer(str(exc), show_alert=True)
    await callback.message.answer(
        f"Перевыбор {result.place} места выполнен: {result.old_winner.first_name or result.old_winner.username} → "
        f"{result.new_winner.first_name or result.new_winner.username}."
    )
    await callback.answer("Готово.")


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


@giveaway_router.callback_query(F.data.startswith("giveaway_refresh_markup:"))
async def admin_giveaway_refresh_markup(callback: types.CallbackQuery):
    if not await _require_admin(callback):
        return
    giveaway_id = int(callback.data.split(":", 1)[1])
    giveaway = await get_giveaway(giveaway_id)
    if giveaway is None or giveaway.status != GIVEAWAY_STATUS_ACTIVE:
        return await callback.answer("Можно обновлять только активный опубликованный розыгрыш.", show_alert=True)
    await refresh_giveaway_participation_markup(callback.bot, giveaway)
    await callback.answer("Кнопка обновлена.")


@giveaway_router.callback_query(F.data == "giveaway_refresh_markups")
async def admin_giveaway_refresh_markups(callback: types.CallbackQuery):
    if not await _require_admin(callback):
        return
    updated = 0
    for giveaway in await list_active_giveaways():
        if giveaway.status == GIVEAWAY_STATUS_ACTIVE:
            await refresh_giveaway_participation_markup(callback.bot, giveaway)
            updated += 1
    await callback.answer(f"Обновлено активных кнопок: {updated}.", show_alert=True)


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
    required_channel_ids = await get_required_channel_ids(giveaway_id)
    subscription = await check_giveaway_required_subscriptions(callback.bot, giveaway, required_channel_ids, callback.from_user.id)
    if not subscription.is_allowed:
        return await callback.answer(
            "Участвовать могут только подписчики каналов:\n"
            + "\n".join(_channel_url(channel_id) for channel_id in subscription.missing_channels),
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
    if added:
        await refresh_giveaway_participation_markup(callback.bot, giveaway)
    await callback.answer("Вы участвуете!" if added else "Вы уже участвуете.", show_alert=False)


@giveaway_router.callback_query(F.data.startswith("giveaway_count:"))
async def giveaway_count(callback: types.CallbackQuery):
    giveaway_id = int(callback.data.split(":", 1)[1])
    count = await count_giveaway_entries(giveaway_id)
    await callback.answer(f"Участников: {count}", show_alert=False)


@giveaway_router.callback_query(F.data.startswith("giveaway_check:"))
async def giveaway_check_subscription(callback: types.CallbackQuery):
    giveaway_id = int(callback.data.split(":", 1)[1])
    giveaway = await get_giveaway(giveaway_id)
    if giveaway is None or giveaway.status != GIVEAWAY_STATUS_ACTIVE:
        return await callback.answer("Розыгрыш уже завершён.", show_alert=True)
    if await has_giveaway_entry(giveaway_id, callback.from_user.id):
        return await callback.answer("Вы уже участвуете.", show_alert=True)

    required_channel_ids = await get_required_channel_ids(giveaway_id)
    subscription = await check_giveaway_required_subscriptions(callback.bot, giveaway, required_channel_ids, callback.from_user.id)
    if not subscription.is_allowed:
        return await callback.answer(
            "Не хватает подписки на каналы:\n" + "\n".join(_channel_url(channel_id) for channel_id in subscription.missing_channels),
            show_alert=True,
        )

    return await callback.answer(
        "Подписка подтверждена. Теперь нажмите «Участвовать», чтобы пройти защиту и попасть в список.",
        show_alert=True,
    )


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
    required_channel_ids = await get_required_channel_ids(giveaway_id)
    subscription = await check_giveaway_required_subscriptions(callback.bot, giveaway, required_channel_ids, callback.from_user.id)
    if not subscription.is_allowed:
        return await callback.answer(
            "Подписка больше не найдена:\n" + "\n".join(_channel_url(channel_id) for channel_id in subscription.missing_channels),
            show_alert=True,
        )
    added = await add_giveaway_entry(
        giveaway_id,
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.first_name,
    )
    if added:
        await refresh_giveaway_participation_markup(callback.bot, giveaway)
    text = "Проверка пройдена, вы добавлены в участники." if added else "Проверка пройдена, вы уже участвуете."
    try:
        await callback.message.edit_text(text)
    except Exception:  # noqa: BLE001 - callback answer is enough if DM message can't be edited.
        pass
    await callback.answer(text, show_alert=True)
