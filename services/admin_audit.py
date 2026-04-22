"""Admin audit-лог + generic API error response.

Два небольших но широко используемых helper'а:

- `_audit_admin_action(...)` — обёртка над `db_admin_audit.write_admin_audit_log`:
  ловит exceptions (чтобы аудит не ломал основной запрос), truncate'ит error-text.
  Вызывается из всех админ-handler'ов (rename, reorder, edit_url, etc.).

- `_api_error_response(exc, context, status)` — единая точка формирования 500-ответов:
  логирует полный stack в лог сервера, возвращает generic JSON клиенту
  (без утечки stack'а/секретов).

Вынесено из `bot.py` как шаг Фазы 3 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import logging

import aiohttp.web

from services.webapp_cors import CORS_HEADERS

# Лимит длины error-текста в admin audit (чтобы не раздувать БД).
MAX_API_ERROR_TEXT = 250


async def _audit_admin_action(
    action: str,
    actor_user_id: str,
    target: str = "",
    payload: object = None,
    result: str = "ok",
    error: str = "",
) -> None:
    """Пишет запись в `admin_audit_log` (best-effort, ошибки подавляются).

    Lazy-импорты `write_admin_audit_log` и `_safe_json_dumps` из bot.py
    избегают цикла `bot.py ↔ services/`.
    """
    # Lazy-import (bot.py ↔ services/).
    from bot import _safe_json_dumps, write_admin_audit_log

    try:
        await write_admin_audit_log(
            action=action,
            actor_user_id=str(actor_user_id or ""),
            target=str(target or ""),
            payload_json=_safe_json_dumps(payload if payload is not None else {}),
            result=str(result or "ok"),
            error=str(error or "")[:MAX_API_ERROR_TEXT],
        )
    except Exception as audit_error:  # noqa: BLE001 — audit best-effort, не ломаем основной handler.
        logging.error(f"Admin audit log error: {audit_error}")


def _api_error_response(exc: Exception, *, context: str = "api", status: int = 500) -> aiohttp.web.Response:
    """Generic JSON-ответ при ошибке API.

    Логирует полный stack через `logging.exception(...)`, но клиенту отдаёт
    только `{"error": "Internal error", "code": <status>}` — без утечки
    stack'а или секретов.
    """
    logging.exception("API error in %s", context, exc_info=exc)
    return aiohttp.web.json_response(
        {"error": "Internal error", "code": status},
        status=status,
        headers=CORS_HEADERS,
    )
