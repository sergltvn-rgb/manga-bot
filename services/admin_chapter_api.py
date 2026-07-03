"""WebApp admin-handlers для редактирования контента глав.

6 endpoints (все требуют admin-role):

- `handle_rename_delete` — DELETE custom-name для главы/серии.
- `handle_chapter_edit` — PUT URL главы (+ автогенерация Telegraph-поста из
  plain-text если URL'ов нет).
- `handle_chapter_bulk` — POST массовое добавление с авто-нумерацией.
- `handle_chapter_add` — POST одиночная глава (409 если уже есть).
- `handle_chapter_delete` — DELETE глава + связанный custom_name.
- `handle_series_update` — PUT мета-серии (обложка).

Общий паттерн:
1. `get_auth_user` → `_enforce_rate_limit` → `admins` check.
2. Валидация `series_id`/`chapter`/`url` через `services/validators`.
3. `_get_table_info` маппит `series_id` → таблица БД.
4. UPSERT в таблицу с `sort_order` (для новых записей — `MAX+1`).
5. `invalidate_reader_cache` → `get_cached_reader_data(force_refresh=True)` →
   перезапись `webapp/chapters_data.json` → `spawn_bg(run_git_sync(...))` →
   `_audit_admin_action`.

Большой блок lazy-импортов из bot.py (`DB_PATH`, `get_admins`, `spawn_bg` и т.д.)
в начале каждого handler'а — чтобы избежать цикл `bot.py ↔ services/`.

Вынесено из `bot.py` как шаг Фазы 3 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import json
import logging
import re

import aiohttp.web
import aiosqlite

from services.admin_audit import _api_error_response, _audit_admin_action
from services.auth import get_auth_user
from services.rate_limit import _enforce_rate_limit
from services.validators import (
    MAX_BULK_URLS_PER_REQUEST,
    MAX_CHAPTER_EDIT_RAW_TEXT_LENGTH,
    MAX_RENAME_OBJECT_ID_LENGTH,
    _clean_urls,
    _is_valid_chapter_token,
    _is_valid_series_id,
    _normalize_external_url,
)
from services.webapp_cors import CORS_HEADERS


def _volume_int(value, default: int = 1) -> int:
    if value in (None, "", "null"):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _get_table_info(series_id: str, volume):
    """Маппинг `series_id` → `(table_name, chapter_col, where_clause, params_fn)`.

    Используется во всех admin-handler'ах для определения физической таблицы
    БД. Возвращает `None` для неизвестной серии.
    """
    if series_id == "akashic_records":
        return ("akashic_ranobe", "chapter", "volume = ? AND chapter = ?", lambda v, c: (v, c))
    elif series_id == "british_belle":
        return ("british_ranobe", "chapter", "volume = ? AND chapter = ?", lambda v, c: (v, c))
    elif series_id.startswith("ranobe_"):
        lang = series_id.replace("ranobe_", "")
        return (
            "ranobe_urls",
            "chapter_number",
            "chapter_number = ? AND lang = ? AND volume = ?",
            lambda v, c: (c, lang, _volume_int(v)),
        )
    elif series_id.startswith("manga_"):
        lang = series_id.replace("manga_", "")
        return (
            "chapters_urls",
            "chapter_number",
            "chapter_number = ? AND lang = ? AND volume = ?",
            lambda v, c: (c, lang, _volume_int(v)),
        )
    return None


async def _check_admin(request: aiohttp.web.Request, user_id: str) -> aiohttp.web.Response | None:
    """Проверяет что user_id в списке админов. Возвращает 403 Response или None."""
    from bot import get_admins

    admins = await get_admins()
    try:
        if int(user_id) not in admins:
            return aiohttp.web.json_response({"error": "forbidden"}, status=403, headers=CORS_HEADERS)
    except (ValueError, TypeError):
        return aiohttp.web.json_response({"error": "forbidden"}, status=403, headers=CORS_HEADERS)
    return None


async def _sync_reader_json() -> None:
    """После правки БД: пересобирает cached reader-data и пишет JSON-файл.

    Клиент WebApp читает `webapp/chapters_data.json` напрямую как fallback,
    поэтому он должен быть свежим.
    """
    from bot import get_cached_reader_data

    result, _, _ = await get_cached_reader_data(force_refresh=True)
    with open("webapp/chapters_data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


async def handle_rename_delete(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """DELETE: сброс кастомного имени элемента обратно в дефолт. Только для AdminMode."""
    from bot import DB_PATH, invalidate_reader_cache, run_git_sync, spawn_bg

    user_id = ""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        limited = await _enforce_rate_limit(request, "admin_rename_delete", user_id=user_id)
        if limited:
            return limited

        data = await request.json()
        obj_id = data.get("obj_id", "").strip()
        if not obj_id or len(obj_id) > MAX_RENAME_OBJECT_ID_LENGTH:
            return aiohttp.web.json_response({"error": "missing obj_id"}, status=400, headers=CORS_HEADERS)

        forbidden = await _check_admin(request, user_id)
        if forbidden is not None:
            return forbidden

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM custom_names WHERE id = ?", (obj_id,))
            await db.commit()
        invalidate_reader_cache("custom_name_deleted")

        await _sync_reader_json()
        spawn_bg(run_git_sync("reset custom name via webapp"), name="run_git_sync:reset_custom_name")
        await _audit_admin_action(
            action="rename_delete",
            actor_user_id=user_id,
            target=obj_id,
            payload={"obj_id": obj_id},
            result="ok",
        )

        return aiohttp.web.json_response({"ok": True, "obj_id": obj_id}, headers=CORS_HEADERS)
    except Exception as e:  # noqa: BLE001 — любая ошибка → audit + 500.
        await _audit_admin_action(
            action="rename_delete",
            actor_user_id=user_id,
            payload={"path": request.path},
            result="error",
            error=str(e),
        )
        return _api_error_response(e, context=request.path)


async def handle_chapter_edit(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """PUT: обновить URL главы. Только для админов.

    Если в `url` нет HTTP(S)-ссылок, но есть >30 символов текста — генерирует
    Telegraph-пост и берёт его URL как содержимое главы.
    """
    from bot import DB_PATH, get_custom_name, invalidate_reader_cache, run_git_sync, spawn_bg, upload_to_telegraph

    user_id = ""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        limited = await _enforce_rate_limit(request, "admin_chapter_edit", user_id=user_id)
        if limited:
            return limited
        forbidden = await _check_admin(request, user_id)
        if forbidden is not None:
            return forbidden

        data = await request.json()
        series_id = str(data.get("series_id", "")).strip()
        volume = data.get("volume")
        chapter = str(data.get("chapter", "")).strip()
        name = str(data.get("name", "") or "").strip()
        new_url_raw = str(data.get("url", "")).strip()
        content_html = str(data.get("content_html", "") or "").strip()
        raw_content = content_html or new_url_raw

        if not series_id or not chapter or not raw_content:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)
        if not _is_valid_series_id(series_id):
            return aiohttp.web.json_response({"error": "invalid series_id"}, status=400, headers=CORS_HEADERS)
        if not _is_valid_chapter_token(chapter):
            return aiohttp.web.json_response({"error": "invalid chapter"}, status=400, headers=CORS_HEADERS)
        if len(raw_content) > MAX_CHAPTER_EDIT_RAW_TEXT_LENGTH:
            return aiohttp.web.json_response({"error": "payload too large"}, status=400, headers=CORS_HEADERS)
        if series_id in ("akashic_records", "british_belle") and volume in (None, "", "null"):
            return aiohttp.web.json_response({"error": "missing volume"}, status=400, headers=CORS_HEADERS)

        info = _get_table_info(series_id, volume)
        if not info:
            return aiohttp.web.json_response({"error": "unknown series"}, status=400, headers=CORS_HEADERS)

        links = [] if content_html else _clean_urls(new_url_raw)

        # Конвертируем только если ВООБЩЕ нет ссылок и текст большой.
        if not links and len(raw_content) > 30:
            title = f"Глава {chapter}"
            s_name = await get_custom_name(f"series_{series_id}") or series_id
            title = f"{s_name} — Глава {chapter}"
            telegraph_url = await upload_to_telegraph(title, raw_content)
            if telegraph_url:
                links = [telegraph_url]

        if not links:
            return aiohttp.web.json_response({"error": "invalid or unsupported URL"}, status=400, headers=CORS_HEADERS)
        if len(links) > MAX_BULK_URLS_PER_REQUEST:
            return aiohttp.web.json_response({"error": "too many urls"}, status=400, headers=CORS_HEADERS)
        new_url = " ".join(links)

        table, _, _, _ = info

        async with aiosqlite.connect(DB_PATH) as db:
            if series_id in ("akashic_records", "british_belle"):
                async with db.execute(f"SELECT MAX(sort_order) FROM {table} WHERE volume=?", (volume,)) as cur:
                    row = await cur.fetchone()
                    next_order = (row[0] or 0) + 1
                await db.execute(
                    f"INSERT INTO {table} (volume, chapter, url, sort_order) VALUES (?, ?, ?, ?) "
                    f"ON CONFLICT(volume, chapter) DO UPDATE SET url=excluded.url",
                    (volume, chapter, new_url, next_order),
                )
                vol_token = volume
            elif series_id.startswith("ranobe_"):
                lang = series_id.split("_", 1)[1] if "_" in series_id else "ru"
                volume_int = _volume_int(volume)
                async with db.execute(f"SELECT MAX(sort_order) FROM {table} WHERE lang=? AND volume=?", (lang, volume_int)) as cur:
                    row = await cur.fetchone()
                    next_order = (row[0] or 0) + 1
                await db.execute(
                    f"INSERT INTO {table} (chapter_number, lang, volume, url, sort_order) VALUES (?, ?, ?, ?, ?) "
                    f"ON CONFLICT(chapter_number, lang, volume) DO UPDATE SET url=excluded.url",
                    (chapter, lang, volume_int, new_url, next_order),
                )
                vol_token = volume_int
            else:
                lang = series_id.split("_", 1)[1] if "_" in series_id else "ru"
                volume_int = _volume_int(volume)
                async with db.execute(f"SELECT MAX(sort_order) FROM {table} WHERE lang=? AND volume=?", (lang, volume_int)) as cur:
                    row = await cur.fetchone()
                    next_order = (row[0] or 0) + 1
                await db.execute(
                    f"INSERT INTO {table} (chapter_number, lang, volume, url, sort_order) VALUES (?, ?, ?, ?, ?) "
                    f"ON CONFLICT(chapter_number, lang, volume) DO UPDATE SET url=excluded.url",
                    (chapter, lang, volume_int, new_url, next_order),
                )
                vol_token = volume_int
            if name:
                name_clean = name[:120].strip()
                await db.execute(
                    "INSERT OR REPLACE INTO custom_names (id, name) VALUES (?, ?)",
                    (f"chap_{series_id}_{vol_token}_{chapter}", name_clean),
                )
            await db.commit()
        invalidate_reader_cache("chapter_url_edited")

        await _sync_reader_json()
        spawn_bg(run_git_sync("URL edited via webapp editor"), name="run_git_sync:url_edit")
        await _audit_admin_action(
            action="chapter_edit",
            actor_user_id=user_id,
            target=f"{series_id}:{chapter}",
            payload={"series_id": series_id, "volume": volume, "chapter": chapter, "url_count": len(links)},
            result="ok",
        )

        return aiohttp.web.json_response({"ok": True}, headers=CORS_HEADERS)
    except Exception as e:  # noqa: BLE001 — любая ошибка → audit + 500.
        logging.error(f"Chapter Edit API Error: {e}")
        await _audit_admin_action(
            action="chapter_edit",
            actor_user_id=user_id,
            payload={"path": request.path},
            result="error",
            error=str(e),
        )
        return _api_error_response(e, context=request.path)


async def handle_chapter_bulk_preview(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST: validate a bulk chapter upload without writing to the database."""
    from bot import DB_PATH

    user_id = ""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        limited = await _enforce_rate_limit(request, "admin_chapter_bulk_preview", user_id=user_id)
        if limited:
            return limited
        forbidden = await _check_admin(request, user_id)
        if forbidden is not None:
            return forbidden

        data = await request.json()
        series_id = str(data.get("series_id", "")).strip()
        volume = data.get("volume")
        start_chapter = data.get("start_chapter", 1)
        urls = data.get("urls", [])

        if not series_id or not urls:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)
        if not _is_valid_series_id(series_id):
            return aiohttp.web.json_response({"error": "invalid series_id"}, status=400, headers=CORS_HEADERS)
        if series_id in ("akashic_records", "british_belle") and volume in (None, "", "null"):
            return aiohttp.web.json_response({"error": "missing volume"}, status=400, headers=CORS_HEADERS)
        if not isinstance(urls, list):
            return aiohttp.web.json_response({"error": "urls must be array"}, status=400, headers=CORS_HEADERS)
        if len(urls) > MAX_BULK_URLS_PER_REQUEST:
            return aiohttp.web.json_response({"error": "too many urls"}, status=400, headers=CORS_HEADERS)
        try:
            start_chapter_int = int(str(start_chapter))
        except Exception:  # noqa: BLE001
            return aiohttp.web.json_response({"error": "invalid start_chapter"}, status=400, headers=CORS_HEADERS)
        if start_chapter_int < 0:
            return aiohttp.web.json_response({"error": "invalid start_chapter"}, status=400, headers=CORS_HEADERS)

        info = _get_table_info(series_id, volume)
        if not info:
            return aiohttp.web.json_response({"error": "unknown series"}, status=400, headers=CORS_HEADERS)

        table, chapter_col, _, _ = info
        if series_id.startswith("ranobe_"):
            lang = series_id.split("_", 1)[1] if "_" in series_id else "ru"
            where_clause = "lang = ? AND volume = ?"
            where_params = (lang, _volume_int(volume))
        elif series_id.startswith("manga_"):
            where_clause = "lang = ? AND volume = ?"
            where_params = (series_id.split("_", 1)[1], _volume_int(volume))
        else:
            where_clause = "volume = ?"
            where_params = (str(volume),)

        existing_chapters: set[str] = set()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(f"SELECT {chapter_col} FROM {table} WHERE {where_clause}", where_params) as cursor:
                existing_chapters = {str(row[0]) for row in await cursor.fetchall()}

        items = []
        invalid = []
        duplicates = []
        warnings = []
        seen_in_request: set[str] = set()
        next_order = len(existing_chapters)

        for idx, raw_url in enumerate(urls, start=1):
            chapter = str(start_chapter_int + idx - 1)
            normalized = _normalize_external_url(str(raw_url or "").strip())
            if not normalized:
                invalid.append({"index": idx, "chapter": chapter, "url": str(raw_url or ""), "reason": "invalid_url"})
                warnings.append(f"Глава {chapter}: невалидная ссылка")
                continue

            status = "new"
            if chapter in existing_chapters:
                status = "duplicate"
                duplicates.append({"index": idx, "chapter": chapter, "url": normalized})
                warnings.append(f"Глава {chapter}: уже есть в БД")
            elif chapter in seen_in_request:
                status = "duplicate"
                duplicates.append({"index": idx, "chapter": chapter, "url": normalized, "source": "request"})
                warnings.append(f"Глава {chapter}: дубль в текущей загрузке")

            seen_in_request.add(chapter)
            next_order += 1
            items.append(
                {
                    "index": idx,
                    "chapter": chapter,
                    "url": normalized,
                    "status": status,
                    "sort_order": next_order,
                }
            )

        return aiohttp.web.json_response(
            {
                "ok": not invalid,
                "items": items,
                "duplicates": duplicates,
                "invalid": invalid,
                "warnings": warnings,
                "summary": {
                    "total": len(urls),
                    "valid": len(items),
                    "new": len([item for item in items if item["status"] == "new"]),
                    "duplicates": len(duplicates),
                    "invalid": len(invalid),
                },
            },
            headers=CORS_HEADERS,
        )
    except Exception as e:  # noqa: BLE001
        logging.error(f"Bulk Preview API Error: {e}")
        await _audit_admin_action(
            action="chapter_bulk_preview",
            actor_user_id=user_id,
            payload={"path": request.path},
            result="error",
            error=str(e),
        )
        return _api_error_response(e, context=request.path)


async def handle_chapter_bulk(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST: массовое добавление глав с URL. Только для админов."""
    from bot import DB_PATH, invalidate_reader_cache, run_git_sync, spawn_bg

    user_id = ""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        limited = await _enforce_rate_limit(request, "admin_chapter_bulk", user_id=user_id)
        if limited:
            return limited
        forbidden = await _check_admin(request, user_id)
        if forbidden is not None:
            return forbidden

        data = await request.json()
        series_id = str(data.get("series_id", "")).strip()
        volume = data.get("volume")
        start_chapter = data.get("start_chapter", 1)
        urls = data.get("urls", [])

        if not series_id or not urls:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)
        if not _is_valid_series_id(series_id):
            return aiohttp.web.json_response({"error": "invalid series_id"}, status=400, headers=CORS_HEADERS)
        if series_id in ("akashic_records", "british_belle") and volume in (None, "", "null"):
            return aiohttp.web.json_response({"error": "missing volume"}, status=400, headers=CORS_HEADERS)
        if not isinstance(urls, list):
            return aiohttp.web.json_response({"error": "urls must be array"}, status=400, headers=CORS_HEADERS)
        if len(urls) > MAX_BULK_URLS_PER_REQUEST:
            return aiohttp.web.json_response({"error": "too many urls"}, status=400, headers=CORS_HEADERS)
        try:
            start_chapter_int = int(str(start_chapter))
        except Exception:  # noqa: BLE001 — int() может бросить разное.
            return aiohttp.web.json_response({"error": "invalid start_chapter"}, status=400, headers=CORS_HEADERS)
        if start_chapter_int < 0:
            return aiohttp.web.json_response({"error": "invalid start_chapter"}, status=400, headers=CORS_HEADERS)
        normalized_urls: list[str] = []
        for idx, raw_url in enumerate(urls, start=1):
            normalized = _normalize_external_url(str(raw_url or "").strip())
            if not normalized:
                return aiohttp.web.json_response({"error": f"invalid url at index {idx}"}, status=400, headers=CORS_HEADERS)
            normalized_urls.append(normalized)

        info = _get_table_info(series_id, volume)
        if not info:
            return aiohttp.web.json_response({"error": "unknown series"}, status=400, headers=CORS_HEADERS)

        table, _, _, _ = info
        added = 0

        if series_id.startswith("ranobe_"):
            lang = series_id.split("_", 1)[1] if "_" in series_id else "ru"
            volume_int = _volume_int(volume)
            where_clause = "lang = ? AND volume = ?"
            where_params = (lang, volume_int)
        elif series_id.startswith("manga_"):
            lang = series_id.split("_", 1)[1] if "_" in series_id else "ru"
            volume_int = _volume_int(volume)
            where_clause = "lang = ? AND volume = ?"
            where_params = (lang, volume_int)
        else:
            lang = ""
            volume_int = volume
            where_clause = "volume = ?"
            where_params = (str(volume),)

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(f"SELECT MAX(sort_order) FROM {table} WHERE {where_clause}", where_params) as cursor:
                row = await cursor.fetchone()
                current_max = row[0] or 0

            for i, url in enumerate(normalized_urls):
                ch_num = str(start_chapter_int + i)
                if not url:
                    continue

                next_order = current_max + added + 1

                if series_id in ("akashic_records", "british_belle"):
                    await db.execute(
                        f"INSERT INTO {table} (volume, chapter, url, sort_order) VALUES (?, ?, ?, ?) "
                        f"ON CONFLICT(volume, chapter) DO UPDATE SET url=excluded.url",
                        (volume, ch_num, url, next_order),
                    )
                elif series_id.startswith("ranobe_"):
                    await db.execute(
                        f"INSERT INTO {table} (chapter_number, lang, volume, url, sort_order) VALUES (?, ?, ?, ?, ?) "
                        f"ON CONFLICT(chapter_number, lang, volume) DO UPDATE SET url=excluded.url",
                        (ch_num, lang, volume_int, url, next_order),
                    )
                else:
                    await db.execute(
                        f"INSERT INTO {table} (chapter_number, lang, volume, url, sort_order) VALUES (?, ?, ?, ?, ?) "
                        f"ON CONFLICT(chapter_number, lang, volume) DO UPDATE SET url=excluded.url",
                        (ch_num, lang, volume_int, url, next_order),
                    )
                added += 1
            await db.commit()
        invalidate_reader_cache("chapters_bulk_uploaded")

        await _sync_reader_json()
        spawn_bg(run_git_sync(f"bulk upload {added} chapters via webapp"), name="run_git_sync:bulk_upload")
        await _audit_admin_action(
            action="chapter_bulk_upload",
            actor_user_id=user_id,
            target=series_id,
            payload={
                "series_id": series_id,
                "volume": volume,
                "start_chapter": start_chapter_int,
                "urls_count": len(normalized_urls),
                "added": added,
            },
            result="ok",
        )

        return aiohttp.web.json_response({"ok": True, "added": added}, headers=CORS_HEADERS)
    except Exception as e:  # noqa: BLE001
        logging.error(f"Bulk Upload API Error: {e}")
        await _audit_admin_action(
            action="chapter_bulk_upload",
            actor_user_id=user_id,
            payload={"path": request.path},
            result="error",
            error=str(e),
        )
        return _api_error_response(e, context=request.path)


async def handle_chapter_add(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST: добавить одну главу. Только для админов. 409 если уже существует."""
    from bot import DB_PATH, get_custom_name, invalidate_reader_cache, run_git_sync, spawn_bg, upload_to_telegraph

    user_id = ""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        limited = await _enforce_rate_limit(request, "admin_chapter_add", user_id=user_id)
        if limited:
            return limited
        forbidden = await _check_admin(request, user_id)
        if forbidden is not None:
            return forbidden

        data = await request.json()
        series_id = str(data.get("series_id", "")).strip()
        volume = data.get("volume")
        chapter = str(data.get("chapter", "")).strip()
        name = str(data.get("name", "") or "").strip()
        url_raw = str(data.get("url", "") or "").strip()
        content_html = str(data.get("content_html", "") or "").strip()
        raw_content = content_html or url_raw

        if not series_id or not chapter or not raw_content:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)
        if not _is_valid_series_id(series_id):
            return aiohttp.web.json_response({"error": "invalid series_id"}, status=400, headers=CORS_HEADERS)
        if not _is_valid_chapter_token(chapter):
            return aiohttp.web.json_response({"error": "invalid chapter"}, status=400, headers=CORS_HEADERS)
        if len(raw_content) > MAX_CHAPTER_EDIT_RAW_TEXT_LENGTH:
            return aiohttp.web.json_response({"error": "payload too large"}, status=400, headers=CORS_HEADERS)
        if series_id in ("akashic_records", "british_belle") and volume in (None, "", "null"):
            return aiohttp.web.json_response({"error": "missing volume"}, status=400, headers=CORS_HEADERS)

        info = _get_table_info(series_id, volume)
        if not info:
            return aiohttp.web.json_response({"error": "unknown series"}, status=400, headers=CORS_HEADERS)

        links = [] if content_html else _clean_urls(url_raw)
        if not links and len(raw_content) > 30:
            s_name = await get_custom_name(f"series_{series_id}") or series_id
            title = f"{s_name} — Глава {chapter}"
            telegraph_url = await upload_to_telegraph(title, raw_content)
            if telegraph_url:
                links = [telegraph_url]
        if not links:
            return aiohttp.web.json_response({"error": "invalid or unsupported URL"}, status=400, headers=CORS_HEADERS)
        if len(links) > MAX_BULK_URLS_PER_REQUEST:
            return aiohttp.web.json_response({"error": "too many urls"}, status=400, headers=CORS_HEADERS)
        new_url = " ".join(links)

        table, _, _, _ = info

        async with aiosqlite.connect(DB_PATH) as db:
            # Reject if chapter already exists — вызывающая сторона должна использовать PUT.
            if series_id in ("akashic_records", "british_belle"):
                async with db.execute(f"SELECT 1 FROM {table} WHERE volume=? AND chapter=?", (volume, chapter)) as cur:
                    exists_row = await cur.fetchone()
                if exists_row:
                    return aiohttp.web.json_response({"error": "chapter already exists"}, status=409, headers=CORS_HEADERS)

                async with db.execute(f"SELECT MAX(sort_order) FROM {table} WHERE volume=?", (volume,)) as cur:
                    row = await cur.fetchone()
                    next_order = (row[0] or 0) + 1
                await db.execute(
                    f"INSERT INTO {table} (volume, chapter, url, sort_order) VALUES (?, ?, ?, ?)",
                    (volume, chapter, new_url, next_order),
                )
            elif series_id.startswith("ranobe_"):
                lang = series_id.split("_", 1)[1] if "_" in series_id else "ru"
                volume_int = _volume_int(volume)
                async with db.execute(
                    f"SELECT 1 FROM {table} WHERE chapter_number=? AND lang=? AND volume=?",
                    (chapter, lang, volume_int),
                ) as cur:
                    exists_row = await cur.fetchone()
                if exists_row:
                    return aiohttp.web.json_response({"error": "chapter already exists"}, status=409, headers=CORS_HEADERS)

                async with db.execute(f"SELECT MAX(sort_order) FROM {table} WHERE lang=? AND volume=?", (lang, volume_int)) as cur:
                    row = await cur.fetchone()
                    next_order = (row[0] or 0) + 1
                await db.execute(
                    f"INSERT INTO {table} (chapter_number, lang, volume, url, sort_order) VALUES (?, ?, ?, ?, ?)",
                    (chapter, lang, volume_int, new_url, next_order),
                )
            else:
                lang = series_id.split("_", 1)[1] if "_" in series_id else "ru"
                volume_int = _volume_int(volume)
                async with db.execute(
                    f"SELECT 1 FROM {table} WHERE chapter_number=? AND lang=? AND volume=?",
                    (chapter, lang, volume_int),
                ) as cur:
                    exists_row = await cur.fetchone()
                if exists_row:
                    return aiohttp.web.json_response({"error": "chapter already exists"}, status=409, headers=CORS_HEADERS)

                async with db.execute(f"SELECT MAX(sort_order) FROM {table} WHERE lang=? AND volume=?", (lang, volume_int)) as cur:
                    row = await cur.fetchone()
                    next_order = (row[0] or 0) + 1
                await db.execute(
                    f"INSERT INTO {table} (chapter_number, lang, volume, url, sort_order) VALUES (?, ?, ?, ?, ?)",
                    (chapter, lang, volume_int, new_url, next_order),
                )

            # Сохраняем кастомное имя главы, если указано.
            if name:
                vol_token = volume if series_id in ("akashic_records", "british_belle") else _volume_int(volume)
                name_clean = name[:MAX_RENAME_OBJECT_ID_LENGTH]
                await db.execute(
                    "INSERT OR REPLACE INTO custom_names (id, name) VALUES (?, ?)",
                    (f"chap_{series_id}_{vol_token}_{chapter}", name_clean),
                )
            await db.commit()
        invalidate_reader_cache("chapter_added")

        await _sync_reader_json()
        spawn_bg(run_git_sync(f"add chapter {chapter} via webapp"), name="run_git_sync:add_chapter")
        await _audit_admin_action(
            action="chapter_add",
            actor_user_id=user_id,
            target=f"{series_id}:{chapter}",
            payload={"series_id": series_id, "volume": volume, "chapter": chapter, "url_count": len(links)},
            result="ok",
        )

        return aiohttp.web.json_response({"ok": True, "chapter": chapter}, headers=CORS_HEADERS)
    except Exception as e:  # noqa: BLE001
        logging.error(f"Chapter Add API Error: {e}")
        await _audit_admin_action(
            action="chapter_add",
            actor_user_id=user_id,
            payload={"path": request.path},
            result="error",
            error=str(e),
        )
        return _api_error_response(e, context=request.path)


async def handle_chapter_delete(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """DELETE: удалить главу + её custom_name. Только для админов. 404 если не найдена."""
    from bot import DB_PATH, invalidate_reader_cache, run_git_sync, spawn_bg

    user_id = ""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        limited = await _enforce_rate_limit(request, "admin_chapter_delete", user_id=user_id)
        if limited:
            return limited
        forbidden = await _check_admin(request, user_id)
        if forbidden is not None:
            return forbidden

        data = await request.json()
        series_id = str(data.get("series_id", "")).strip()
        volume = data.get("volume")
        chapter = str(data.get("chapter", "")).strip()

        if not series_id or not chapter:
            return aiohttp.web.json_response({"error": "missing fields"}, status=400, headers=CORS_HEADERS)
        if not _is_valid_series_id(series_id):
            return aiohttp.web.json_response({"error": "invalid series_id"}, status=400, headers=CORS_HEADERS)
        if not _is_valid_chapter_token(chapter):
            return aiohttp.web.json_response({"error": "invalid chapter"}, status=400, headers=CORS_HEADERS)
        if series_id in ("akashic_records", "british_belle") and volume in (None, "", "null"):
            return aiohttp.web.json_response({"error": "missing volume"}, status=400, headers=CORS_HEADERS)

        info = _get_table_info(series_id, volume)
        if not info:
            return aiohttp.web.json_response({"error": "unknown series"}, status=400, headers=CORS_HEADERS)

        table, _, _, _ = info
        deleted = 0

        async with aiosqlite.connect(DB_PATH) as db:
            if series_id in ("akashic_records", "british_belle"):
                cursor = await db.execute(f"DELETE FROM {table} WHERE volume=? AND chapter=?", (volume, chapter))
                deleted = cursor.rowcount or 0
                await cursor.close()
                vol_token = volume
            elif series_id.startswith("ranobe_"):
                lang = series_id.split("_", 1)[1] if "_" in series_id else "ru"
                volume_int = _volume_int(volume)
                cursor = await db.execute(
                    f"DELETE FROM {table} WHERE chapter_number=? AND lang=? AND volume=?",
                    (chapter, lang, volume_int),
                )
                deleted = cursor.rowcount or 0
                await cursor.close()
                vol_token = volume_int
            else:
                lang = series_id.split("_", 1)[1] if "_" in series_id else "ru"
                volume_int = _volume_int(volume)
                cursor = await db.execute(
                    f"DELETE FROM {table} WHERE chapter_number=? AND lang=? AND volume=?",
                    (chapter, lang, volume_int),
                )
                deleted = cursor.rowcount or 0
                await cursor.close()
                vol_token = volume_int

            if deleted == 0:
                await db.rollback()
                return aiohttp.web.json_response({"error": "chapter not found"}, status=404, headers=CORS_HEADERS)

            # Убираем связанное кастомное имя главы, если было.
            await db.execute("DELETE FROM custom_names WHERE id = ?", (f"chap_{series_id}_{vol_token}_{chapter}",))
            await db.commit()
        invalidate_reader_cache("chapter_deleted")

        await _sync_reader_json()
        spawn_bg(run_git_sync(f"delete chapter {chapter} via webapp"), name="run_git_sync:delete_chapter")
        await _audit_admin_action(
            action="chapter_delete",
            actor_user_id=user_id,
            target=f"{series_id}:{chapter}",
            payload={"series_id": series_id, "volume": volume, "chapter": chapter},
            result="ok",
        )

        return aiohttp.web.json_response({"ok": True, "deleted": deleted}, headers=CORS_HEADERS)
    except Exception as e:  # noqa: BLE001
        logging.error(f"Chapter Delete API Error: {e}")
        await _audit_admin_action(
            action="chapter_delete",
            actor_user_id=user_id,
            payload={"path": request.path},
            result="error",
            error=str(e),
        )
        return _api_error_response(e, context=request.path)


async def handle_series_update(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """PUT: обновить мета-данные серии (обложка и/или название). Только для админов.

    Обновляются только поля, присутствующие в payload:
    - `cover_url` — обложка (пустая строка = сброс);
    - `title` — кастомное название тайтла (пустая строка = сброс на дефолт).
    """
    from bot import DB_PATH, invalidate_reader_cache, run_git_sync, spawn_bg

    user_id = ""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        limited = await _enforce_rate_limit(request, "admin_series_update", user_id=user_id)
        if limited:
            return limited
        forbidden = await _check_admin(request, user_id)
        if forbidden is not None:
            return forbidden

        data = await request.json()
        series_id = str(data.get("series_id", "")).strip()
        has_cover_field = "cover_url" in data
        has_title_field = "title" in data
        cover_url_raw = str(data.get("cover_url", "") or "").strip()
        title_raw = str(data.get("title", "") or "").strip()

        if not series_id:
            return aiohttp.web.json_response({"error": "missing series_id"}, status=400, headers=CORS_HEADERS)
        if not _is_valid_series_id(series_id):
            return aiohttp.web.json_response({"error": "invalid series_id"}, status=400, headers=CORS_HEADERS)
        if not has_cover_field and not has_title_field:
            return aiohttp.web.json_response({"error": "nothing to update"}, status=400, headers=CORS_HEADERS)
        if has_title_field and len(title_raw) > 120:
            return aiohttp.web.json_response({"error": "title too long"}, status=400, headers=CORS_HEADERS)

        cover_url_clean: str | None = None
        if has_cover_field and cover_url_raw:
            cover_url_clean = _normalize_external_url(cover_url_raw)
            if not cover_url_clean:
                return aiohttp.web.json_response({"error": "invalid cover_url"}, status=400, headers=CORS_HEADERS)

        cover_key = f"cover_{series_id}"
        title_key = f"series_{series_id}"
        async with aiosqlite.connect(DB_PATH) as db:
            if has_cover_field:
                if cover_url_clean is None:
                    await db.execute("DELETE FROM custom_names WHERE id = ?", (cover_key,))
                else:
                    await db.execute("INSERT OR REPLACE INTO custom_names (id, name) VALUES (?, ?)", (cover_key, cover_url_clean))
            if has_title_field:
                if title_raw:
                    await db.execute("INSERT OR REPLACE INTO custom_names (id, name) VALUES (?, ?)", (title_key, title_raw))
                else:
                    await db.execute("DELETE FROM custom_names WHERE id = ?", (title_key,))
            await db.commit()
        invalidate_reader_cache("series_meta_updated")

        await _sync_reader_json()
        spawn_bg(run_git_sync(f"update cover for {series_id} via webapp"), name="run_git_sync:update_cover")
        await _audit_admin_action(
            action="series_update",
            actor_user_id=user_id,
            target=series_id,
            payload={"series_id": series_id, "has_cover": bool(cover_url_clean), "has_title": bool(title_raw)},
            result="ok",
        )

        return aiohttp.web.json_response(
            {"ok": True, "cover_url": cover_url_clean or "", "title": title_raw},
            headers=CORS_HEADERS,
        )
    except Exception as e:  # noqa: BLE001
        logging.error(f"Series Update API Error: {e}")
        await _audit_admin_action(
            action="series_update",
            actor_user_id=user_id,
            payload={"path": request.path},
            result="error",
            error=str(e),
        )
        return _api_error_response(e, context=request.path)


_SERIES_CODE_RE = re.compile(r"[a-z0-9][a-z0-9_]{0,19}")


async def handle_series_create(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST: создать новый тайтл (ranobe/manga). Только для админов.

    Payload: `{"type": "ranobe"|"manga", "code": "<lat_id>", "title": "..."}`.
    Тайтл = новая lang-секция в ranobe_urls/chapters_urls + запись
    `series_<id>` в custom_names. Пустой тайтл сразу появляется в читалке
    (build_reader_data инъектит серии из custom_names), главы добавляются
    через админ-модалку WebApp или /admin в боте (код = пункт языка).
    """
    from bot import DB_PATH, invalidate_reader_cache, run_git_sync, spawn_bg

    user_id = ""
    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)
        user_id = str(user.get("id", ""))
        limited = await _enforce_rate_limit(request, "admin_series_create", user_id=user_id)
        if limited:
            return limited
        forbidden = await _check_admin(request, user_id)
        if forbidden is not None:
            return forbidden

        data = await request.json()
        kind = str(data.get("type", "")).strip().lower()
        code = str(data.get("code", "")).strip().lower()
        title = str(data.get("title", "") or "").strip()

        if kind not in ("ranobe", "manga"):
            return aiohttp.web.json_response({"error": "invalid type"}, status=400, headers=CORS_HEADERS)
        if not _SERIES_CODE_RE.fullmatch(code):
            return aiohttp.web.json_response({"error": "invalid code"}, status=400, headers=CORS_HEADERS)
        if not title or len(title) > 120:
            return aiohttp.web.json_response({"error": "invalid title"}, status=400, headers=CORS_HEADERS)

        series_id = f"{kind}_{code}"
        if not _is_valid_series_id(series_id):
            return aiohttp.web.json_response({"error": "invalid series_id"}, status=400, headers=CORS_HEADERS)
        table = "ranobe_urls" if kind == "ranobe" else "chapters_urls"

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(f"SELECT 1 FROM {table} WHERE lang = ? LIMIT 1", (code,)) as cur:
                exists_rows = await cur.fetchone()
            async with db.execute("SELECT 1 FROM custom_names WHERE id = ?", (f"series_{series_id}",)) as cur:
                exists_name = await cur.fetchone()
            if exists_rows or exists_name:
                return aiohttp.web.json_response({"error": "series already exists"}, status=409, headers=CORS_HEADERS)
            await db.execute(
                "INSERT OR REPLACE INTO custom_names (id, name) VALUES (?, ?)",
                (f"series_{series_id}", title),
            )
            await db.commit()
        invalidate_reader_cache("series_created")

        await _sync_reader_json()
        spawn_bg(run_git_sync(f"create series {series_id} via webapp"), name="run_git_sync:create_series")
        await _audit_admin_action(
            action="series_create",
            actor_user_id=user_id,
            target=series_id,
            payload={"series_id": series_id, "type": kind, "code": code, "title": title},
            result="ok",
        )

        return aiohttp.web.json_response({"ok": True, "series_id": series_id, "title": title}, headers=CORS_HEADERS)
    except Exception as e:  # noqa: BLE001
        logging.error(f"Series Create API Error: {e}")
        await _audit_admin_action(
            action="series_create",
            actor_user_id=user_id,
            payload={"path": request.path},
            result="error",
            error=str(e),
        )
        return _api_error_response(e, context=request.path)
