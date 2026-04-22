"""WebApp API-прокси для ИИ-чата через Groq.

`handle_ai_chat(request)` — POST `/api/ai-chat` с `{messages: [{role, content}, ...]}`.
Клиент шлёт историю; сервер сам обращается к Groq и возвращает `{reply}`.

Ключ `GROQ_API_KEY` НИКОГДА не покидает сервер (проксируется через
`bot.ask_ai`, который читает ключ из `config`).

Ограничения:
- `messages` — array, max 20 последних (защита от абьюза).
- Первый элемент с `role=system` → system_prompt.
- Последний элемент с `role=user` → текущий `prompt`, всё остальное → `history`.
- Сообщения `role=assistant` без последующего user — обрезаются (некорректная история).

Auth-required: без валидного initData → 401.

Вынесено из `bot.py` как шаг Фазы 3 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import logging

import aiohttp.web

from services.auth import get_auth_user
from services.webapp_cors import CORS_HEADERS


async def handle_ai_chat(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST `/api/ai-chat` → `{reply}` от Groq.

    Полная обработка истории: system prompt + user/assistant chain →
    prompt (последний user) + history (всё предыдущее). Lazy-импорт `ask_ai`
    из bot.py для избежания цикла.
    """
    from bot import ask_ai

    try:
        user = get_auth_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Unauthorized"}, status=401, headers=CORS_HEADERS)

        data = await request.json()
        messages = data.get("messages", [])
        if not messages or not isinstance(messages, list):
            return aiohttp.web.json_response({"error": "messages array is required"}, status=400, headers=CORS_HEADERS)
        # Ограничиваем длину истории (макс. 20 сообщений) для защиты от абьюза.
        messages = messages[-20:]
        # Извлекаем system prompt (первый элемент) и остальную историю.
        system_prompt = ""
        history: list[dict[str, str]] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                system_prompt = content
            elif role in ("user", "assistant"):
                history.append({"role": role, "content": content})
        # Последнее сообщение пользователя — prompt, остальное — history.
        prompt = ""
        while history and history[-1]["role"] != "user":
            history.pop()  # Убираем ассистента в конце, если нет user.

        if history and history[-1]["role"] == "user":
            prompt = history.pop()["content"]

        if not prompt or not prompt.strip():
            return aiohttp.web.json_response({"error": "no user message found"}, status=400, headers=CORS_HEADERS)
        reply = await ask_ai(prompt, system_prompt, history=history if history else None)
        return aiohttp.web.json_response({"reply": reply}, headers=CORS_HEADERS)
    except Exception as e:  # noqa: BLE001 — ловим и logging.exception'им всё.
        logging.exception("API error in %s", request.path, exc_info=e)
        return aiohttp.web.json_response({"error": "Internal error", "code": 500}, status=500, headers=CORS_HEADERS)
