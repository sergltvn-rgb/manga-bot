"""Клиент Telegraph API.

Загружает главы-тексты как Telegraph-страницы. Используется при
добавлении главы через `/add_chapter` и при нормализации URL глав
через WebApp API (handle_chapter_edit).

Вынесено из `bot.py` как шаг 5 Фазы 3 распила монолита (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import json
import logging
from html.parser import HTMLParser

from database import get_setting, set_setting
from services.validators import _normalize_external_url

# Теги, которые Telegraph принимает в content-nodes.
# Полный список: https://telegra.ph/api#NodeElement
_TELEGRAPH_ALLOWED_TAGS: set[str] = {
    "a",
    "aside",
    "b",
    "blockquote",
    "br",
    "code",
    "em",
    "figcaption",
    "figure",
    "h3",
    "h4",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "s",
    "strong",
    "u",
    "ul",
}

# Теги, чей контент нужно молча выкидывать (script/style-инъекции и embed-ресурсы).
_TELEGRAPH_DROP_TAGS: set[str] = {"script", "style", "iframe", "object", "embed"}

# Void-теги: они не могут быть parent'ами (не кладём на stack).
_TELEGRAPH_VOID_TAGS: set[str] = {"br", "img", "hr"}

# Block-level теги, в которые Telegraph НЕ оборачивает дополнительно в <p>.
_TELEGRAPH_BLOCK_TAGS: set[str] = {
    "p",
    "h3",
    "h4",
    "ol",
    "ul",
    "blockquote",
    "aside",
    "figure",
    "img",
    "pre",
    "hr",
}


class _TelegraphHTMLParser(HTMLParser):
    """Парсит произвольный HTML → список Telegraph content-nodes.

    Незнакомые теги прозрачно пропускаются (содержимое сохраняется),
    опасные теги (`_TELEGRAPH_DROP_TAGS`) полностью выкидываются вместе с контентом.
    `href`/`src` нормализуются через `_normalize_external_url`.
    """

    def __init__(self) -> None:
        super().__init__()
        self.nodes: list = []
        self.stack: list = []
        self.drop_depth: int = 0

    def _nearest_parent(self) -> dict | None:
        for item in reversed(self.stack):
            if isinstance(item, dict):
                return item
        return None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = str(tag or "").lower()
        if tag in _TELEGRAPH_DROP_TAGS:
            self.drop_depth += 1
            self.stack.append(None)
            return
        if tag not in _TELEGRAPH_ALLOWED_TAGS:
            self.stack.append(None)
            return

        node: dict = {"tag": tag, "children": []}
        attr_dict = {k: v for k, v in attrs}
        if tag == "a" and "href" in attr_dict:
            href = _normalize_external_url(attr_dict["href"] or "", max_len=2048)
            if href:
                node["attrs"] = {"href": href}
        elif tag == "img" and "src" in attr_dict:
            src = _normalize_external_url(attr_dict["src"] or "", max_len=2048)
            if src:
                node["attrs"] = {"src": src}

        parent = self._nearest_parent()
        if parent is not None:
            parent["children"].append(node)
        else:
            self.nodes.append(node)

        if tag not in _TELEGRAPH_VOID_TAGS:
            self.stack.append(node)
        else:
            self.stack.append(None)

    def handle_endtag(self, tag: str) -> None:
        tag = str(tag or "").lower()
        if self.stack:
            self.stack.pop()
        if tag in _TELEGRAPH_DROP_TAGS and self.drop_depth > 0:
            self.drop_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.drop_depth > 0:
            return
        if not data.strip() and not self.stack:
            return
        parent = self._nearest_parent()
        if parent is not None:
            parent["children"].append(data)
        else:
            self.nodes.append(data)


def _html_to_nodes(html_text: str) -> list:
    """Переводит HTML → Telegraph content-nodes (JSON-сериализуемая структура).
    Оборачивает inline-текст/элементы в <p>, оставляя block-level теги как есть.
    """
    parser = _TelegraphHTMLParser()
    parser.feed(html_text)

    wrapped_nodes: list = []
    for n in parser.nodes:
        if isinstance(n, str):
            if n.strip():
                wrapped_nodes.append({"tag": "p", "children": [n]})
        elif isinstance(n, dict) and n.get("tag") not in _TELEGRAPH_BLOCK_TAGS:
            wrapped_nodes.append({"tag": "p", "children": [n]})
        else:
            wrapped_nodes.append(n)
    return wrapped_nodes


async def get_telegraph_token() -> str | None:
    """Возвращает access_token аккаунта Telegraph.

    При первом вызове создаёт новый аккаунт `AlyaBot` и сохраняет токен
    в `bot_settings` (key=`telegraph_token`). Последующие вызовы берут
    токен из БД без сетевого запроса.
    """
    token = await get_setting("telegraph_token")
    if token:
        return token

    # Lazy-import, чтобы избежать циклического импорта bot.py <-> services/telegraph.py.
    # `get_http_session` живёт в bot.py (глобальная aiohttp-сессия).
    from bot import get_http_session

    url = "https://api.telegra.ph/createAccount?short_name=AlyaBot&author_name=AlyaBot"
    try:
        session = await get_http_session()
        async with session.get(url) as resp:
            data = await resp.json()
            if data.get("ok"):
                token = data["result"]["access_token"]
                await set_setting("telegraph_token", token)
                return token
    except Exception as e:
        logging.error(f"Telegraph Token Error: {e}")
    return None


async def upload_to_telegraph(title: str, html_content: str) -> str | None:
    """Создаёт Telegraph-страницу с указанным заголовком и HTML-контентом.
    Возвращает URL страницы или None при ошибке.
    """
    token = await get_telegraph_token()
    if not token:
        return None

    nodes = _html_to_nodes(html_content)
    if not nodes:
        nodes = [{"tag": "p", "children": ["(Пустая глава)"]}]

    payload = {
        "access_token": token,
        "title": title,
        "author_name": "AlyaBot",
        "content": json.dumps(nodes),
        "return_content": "false",
    }
    # Lazy-import, см. комментарий в get_telegraph_token.
    from bot import get_http_session

    try:
        session = await get_http_session()
        async with session.post("https://api.telegra.ph/createPage", data=payload) as resp:
            data = await resp.json()
            if data.get("ok"):
                return data["result"]["url"]
            logging.error(f"Telegraph API Error: {data}")
    except Exception as e:
        logging.error(f"Telegraph Upload Error: {e}")
    return None
