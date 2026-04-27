from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any

import aiosqlite

import database
from database import get_admins


ART_PAGE_SIZE = 12
SUGGESTION_PAGE_SIZE = 5


@dataclass(frozen=True)
class ArtItem:
    id: int
    file_id: str
    added_by: int | None
    source: str
    created_at: str | None
    accepted_at: str | None
    is_hidden: bool
    tags: str
    note: str


@dataclass(frozen=True)
class ArtSuggestion:
    id: int
    user_id: int
    file_id: str
    status: str
    created_at: str | None
    reviewed_by: int | None
    reviewed_at: str | None
    accepted_art_id: int | None
    reject_reason: str | None


@dataclass(frozen=True)
class Page:
    items: list[Any]
    total: int
    limit: int
    offset: int

    @property
    def page(self) -> int:
        return (self.offset // self.limit) + 1 if self.limit > 0 else 1

    @property
    def total_pages(self) -> int:
        return max(1, ceil(self.total / self.limit)) if self.limit > 0 else 1


def _db_path() -> str:
    return database.DB_PATH


def _art_from_row(row) -> ArtItem:
    return ArtItem(
        id=int(row[0]),
        file_id=str(row[1]),
        added_by=row[2],
        source=row[3] or "legacy",
        created_at=row[4],
        accepted_at=row[5],
        is_hidden=bool(row[6]),
        tags=row[7] or "",
        note=row[8] or "",
    )


def _suggestion_from_row(row) -> ArtSuggestion:
    return ArtSuggestion(
        id=int(row[0]),
        user_id=int(row[1]),
        file_id=str(row[2]),
        status=row[3] or "pending",
        created_at=row[4],
        reviewed_by=row[5],
        reviewed_at=row[6],
        accepted_art_id=row[7],
        reject_reason=row[8],
    )


async def _ensure_schema(db: aiosqlite.Connection) -> None:
    await database.ensure_art_schema(db)


async def _is_admin(actor_id: int | None) -> bool:
    if not actor_id:
        return False
    return int(actor_id) in await get_admins()


async def add_art(
    file_id: str,
    *,
    added_by: int | None = None,
    source: str = "admin_upload",
    tags: str = "",
    note: str = "",
) -> int:
    async with aiosqlite.connect(_db_path()) as db:
        await _ensure_schema(db)
        cursor = await db.execute(
            """
            INSERT INTO arts (file_id, added_by, source, created_at, accepted_at, is_hidden, tags, note)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0, ?, ?)
            """,
            (file_id, added_by, source, tags, note),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def list_arts_page(
    *,
    limit: int = ART_PAGE_SIZE,
    offset: int = 0,
    include_hidden: bool = False,
    only_hidden: bool = False,
) -> Page:
    where: list[str] = []
    params: list[Any] = []
    if only_hidden:
        where.append("COALESCE(is_hidden, 0) = 1")
    elif not include_hidden:
        where.append("COALESCE(is_hidden, 0) = 0")
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    async with aiosqlite.connect(_db_path()) as db:
        await _ensure_schema(db)
        async with db.execute(f"SELECT COUNT(*) FROM arts {where_sql}", params) as cursor:
            total_row = await cursor.fetchone()
            total = int(total_row[0] if total_row else 0)
        async with db.execute(
            f"""
            SELECT id, file_id, added_by, source, created_at, accepted_at, is_hidden, tags, note
            FROM arts
            {where_sql}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, int(limit), int(offset)),
        ) as cursor:
            items = [_art_from_row(row) for row in await cursor.fetchall()]
    return Page(items=items, total=total, limit=int(limit), offset=int(offset))


async def get_art(art_id: int) -> ArtItem | None:
    async with aiosqlite.connect(_db_path()) as db:
        await _ensure_schema(db)
        async with db.execute(
            """
            SELECT id, file_id, added_by, source, created_at, accepted_at, is_hidden, tags, note
            FROM arts
            WHERE id = ?
            """,
            (art_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return _art_from_row(row) if row else None


async def hide_art(art_id: int, *, actor_id: int | None) -> bool:
    if not await _is_admin(actor_id):
        return False
    async with aiosqlite.connect(_db_path()) as db:
        await _ensure_schema(db)
        cursor = await db.execute("UPDATE arts SET is_hidden = 1 WHERE id = ?", (art_id,))
        await db.commit()
        return bool(cursor.rowcount)


async def unhide_art(art_id: int, *, actor_id: int | None) -> bool:
    if not await _is_admin(actor_id):
        return False
    async with aiosqlite.connect(_db_path()) as db:
        await _ensure_schema(db)
        cursor = await db.execute("UPDATE arts SET is_hidden = 0 WHERE id = ?", (art_id,))
        await db.commit()
        return bool(cursor.rowcount)


async def delete_art(art_id: int, *, actor_id: int | None) -> bool:
    if not await _is_admin(actor_id):
        return False
    async with aiosqlite.connect(_db_path()) as db:
        await _ensure_schema(db)
        cursor = await db.execute("DELETE FROM arts WHERE id = ?", (art_id,))
        await db.commit()
        return bool(cursor.rowcount)


async def add_suggested_art(user_id: int, file_id: str) -> int:
    async with aiosqlite.connect(_db_path()) as db:
        await _ensure_schema(db)
        cursor = await db.execute(
            """
            INSERT INTO suggested_arts (user_id, file_id, status, created_at)
            VALUES (?, ?, 'pending', CURRENT_TIMESTAMP)
            """,
            (user_id, file_id),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def list_suggestions_page(*, status: str = "pending", limit: int = SUGGESTION_PAGE_SIZE, offset: int = 0) -> Page:
    where = ""
    params: list[Any] = []
    if status != "all":
        where = "WHERE status = ?"
        params.append(status)
    async with aiosqlite.connect(_db_path()) as db:
        await _ensure_schema(db)
        async with db.execute(f"SELECT COUNT(*) FROM suggested_arts {where}", params) as cursor:
            total_row = await cursor.fetchone()
            total = int(total_row[0] if total_row else 0)
        async with db.execute(
            f"""
            SELECT id, user_id, file_id, status, created_at, reviewed_by, reviewed_at, accepted_art_id, reject_reason
            FROM suggested_arts
            {where}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, int(limit), int(offset)),
        ) as cursor:
            items = [_suggestion_from_row(row) for row in await cursor.fetchall()]
    return Page(items=items, total=total, limit=int(limit), offset=int(offset))


async def get_suggestion(suggestion_id: int) -> ArtSuggestion | None:
    async with aiosqlite.connect(_db_path()) as db:
        await _ensure_schema(db)
        async with db.execute(
            """
            SELECT id, user_id, file_id, status, created_at, reviewed_by, reviewed_at, accepted_art_id, reject_reason
            FROM suggested_arts
            WHERE id = ?
            """,
            (suggestion_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return _suggestion_from_row(row) if row else None


async def approve_suggested_art(suggestion_id: int, *, reviewed_by: int) -> ArtItem | None:
    async with aiosqlite.connect(_db_path()) as db:
        await _ensure_schema(db)
        async with db.execute(
            "SELECT user_id, file_id, status FROM suggested_arts WHERE id = ?",
            (suggestion_id,),
        ) as cursor:
            suggestion = await cursor.fetchone()
        if not suggestion or suggestion[2] != "pending":
            return None

        user_id, file_id, _status = suggestion
        cursor = await db.execute(
            """
            INSERT INTO arts (file_id, added_by, source, created_at, accepted_at, is_hidden, tags, note)
            VALUES (?, ?, 'suggestion', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0, '', '')
            """,
            (file_id, user_id),
        )
        art_id = int(cursor.lastrowid)
        await db.execute(
            """
            UPDATE suggested_arts
            SET status = 'accepted', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP, accepted_art_id = ?
            WHERE id = ?
            """,
            (reviewed_by, art_id, suggestion_id),
        )
        await db.commit()
    return await get_art(art_id)


async def reject_suggested_art(suggestion_id: int, *, reviewed_by: int, reason: str = "") -> bool:
    async with aiosqlite.connect(_db_path()) as db:
        await _ensure_schema(db)
        cursor = await db.execute(
            """
            UPDATE suggested_arts
            SET status = 'rejected', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP, reject_reason = ?
            WHERE id = ? AND status = 'pending'
            """,
            (reviewed_by, reason, suggestion_id),
        )
        await db.commit()
        return bool(cursor.rowcount)


async def get_art_counts() -> dict[str, int]:
    async with aiosqlite.connect(_db_path()) as db:
        await _ensure_schema(db)
        async with db.execute("SELECT COUNT(*) FROM arts WHERE COALESCE(is_hidden, 0) = 0") as cursor:
            visible = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM arts WHERE COALESCE(is_hidden, 0) = 1") as cursor:
            hidden = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM suggested_arts WHERE status = 'pending'") as cursor:
            pending = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM arts WHERE date(created_at) = date('now')") as cursor:
            added_today = (await cursor.fetchone())[0]
    return {
        "visible": int(visible),
        "hidden": int(hidden),
        "pending": int(pending),
        "added_today": int(added_today),
    }


def _art_to_payload(item: ArtItem, *, include_file_id: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": item.id,
        "source": item.source,
        "created_at": item.created_at,
        "is_hidden": item.is_hidden,
        "tags": item.tags,
        "note": item.note,
        "media_url": f"/api/arts/media/{item.id}",
    }
    if include_file_id:
        payload["file_id"] = item.file_id
    return payload


def _suggestion_to_payload(item: ArtSuggestion) -> dict[str, Any]:
    return {
        "id": item.id,
        "user_id": item.user_id,
        "status": item.status,
        "created_at": item.created_at,
        "reviewed_by": item.reviewed_by,
        "reviewed_at": item.reviewed_at,
        "accepted_art_id": item.accepted_art_id,
        "reject_reason": item.reject_reason,
        "media_url": f"/api/arts/suggestions/{item.id}/media",
    }


async def get_arts_webapp_payload(
    *,
    user_id: int | None,
    is_admin: bool,
    limit: int = ART_PAGE_SIZE,
    offset: int = 0,
    only_hidden: bool = False,
) -> dict[str, Any]:
    page = await list_arts_page(
        limit=limit,
        offset=offset,
        include_hidden=is_admin,
        only_hidden=only_hidden if is_admin else False,
    )
    return {
        "ok": True,
        "user_id": user_id,
        "is_admin": is_admin,
        "total": page.total,
        "page": page.page,
        "total_pages": page.total_pages,
        "items": [_art_to_payload(item, include_file_id=is_admin) for item in page.items],
    }


async def get_suggestions_webapp_payload(*, limit: int = SUGGESTION_PAGE_SIZE, offset: int = 0) -> dict[str, Any]:
    page = await list_suggestions_page(status="pending", limit=limit, offset=offset)
    return {
        "ok": True,
        "total": page.total,
        "page": page.page,
        "total_pages": page.total_pages,
        "items": [_suggestion_to_payload(item) for item in page.items],
    }
