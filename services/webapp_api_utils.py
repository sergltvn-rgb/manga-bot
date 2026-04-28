from __future__ import annotations

import uuid
from typing import Any

import aiohttp.web

from services.webapp_cors import CORS_HEADERS


ERROR_MESSAGES: dict[str, tuple[str, str]] = {
    "unauthorized": ("Нужна авторизация.", "Откройте WebApp из Telegram или войдите через Telegram."),
    "forbidden": ("Нет доступа.", "Откройте WebApp из Telegram под аккаунтом с нужными правами."),
    "bad_request": ("Запрос не прошел проверку.", "Проверьте введенные данные и повторите действие."),
    "not_found": ("Данные не найдены.", "Обновите страницу или вернитесь к списку."),
    "timeout": ("Сервер не успел ответить.", "Проверьте соединение и повторите действие."),
    "internal": ("Внутренняя ошибка.", "Повторите действие позже или сообщите админу."),
    "sync_failed": ("Не удалось обновить данные читалки.", "Проверьте журнал действий и повторите синхронизацию."),
}


def request_id() -> str:
    return uuid.uuid4().hex[:12]


def error_details(code: str, *, message: str | None = None, recovery: str | None = None) -> dict[str, str]:
    default_message, default_recovery = ERROR_MESSAGES.get(str(code), ERROR_MESSAGES["internal"])
    return {
        "code": str(code),
        "message": message or default_message,
        "recovery": recovery or default_recovery,
    }


def webapp_json(payload: dict[str, Any], *, status: int = 200) -> aiohttp.web.Response:
    body = {"ok": True, **payload}
    body.setdefault("request_id", request_id())
    return aiohttp.web.json_response(body, status=status, headers=CORS_HEADERS)


def webapp_error(
    code: str,
    *,
    status: int = 400,
    message: str | None = None,
    recovery: str | None = None,
    extra: dict[str, Any] | None = None,
) -> aiohttp.web.Response:
    body: dict[str, Any] = {
        "ok": False,
        "error": error_details(code, message=message, recovery=recovery),
        "request_id": request_id(),
    }
    if extra:
        body.update(extra)
    return aiohttp.web.json_response(body, status=status, headers=CORS_HEADERS)
