from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, types

from database import is_rp_only_group
from handlers.rp import REGEX_RP

RP_ONLY_CONTROL_RE = re.compile(r"(?i)^[/*\s]*(?:rp_only|rponly)(?:@[A-Za-z0-9_]{3,})?(?:\s|$)")


def is_allowed_in_rp_only_mode(text: str | None) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    return bool(RP_ONLY_CONTROL_RE.match(value) or REGEX_RP.match(value))


def should_block_message_in_rp_only_mode(chat_type: str, enabled: bool, text: str | None) -> bool:
    if chat_type not in {"group", "supergroup"}:
        return False
    if not enabled:
        return False
    return not is_allowed_in_rp_only_mode(text)


class GroupRpOnlyMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[types.Message, dict[str, Any]], Awaitable[Any]],
        event: types.Message,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, types.Message):
            return await handler(event, data)

        enabled = await is_rp_only_group(event.chat.id)
        if should_block_message_in_rp_only_mode(event.chat.type, enabled, event.text or event.caption):
            return None
        return await handler(event, data)
