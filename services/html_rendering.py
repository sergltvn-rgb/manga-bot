"""Рендеринг и санитизация HTML-контента глав.

Шесть связанных функций/классов для преобразования сырого контента (Telegraph
JSON-nodes или HTML-страницы Teletype) в безопасный HTML-фрагмент для
WebApp-читалки.

Pipeline:
1. Telegraph → `_render_telegraph_nodes_server(nodes)` — JSON-nodes → HTML.
2. Teletype → `_extract_teletype_article_fragment(page_html)` → вырезка `<article>`.
3. `_normalize_teletype_article_fragment(fragment, source_url)` — разворачивает
   lazy-load `<noscript><img></noscript>` в обычный `<img>`.
4. `_sanitize_html_fragment(fragment, base_url)` — финальная санитизация через
   `_SafeHtmlFragmentParser` (whitelist-теги, whitelist-атрибуты, абсолютные URL).

Зависимости: `html`, `re`, `html.parser.HTMLParser`, `urllib.parse.urljoin`
из stdlib + `_normalize_external_url` из `services/validators.py`.

Вынесено из `bot.py` как шаг Фазы 3 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from services.validators import _normalize_external_url


# =============================================================================
# Telegraph-рендеринг: JSON nodes → HTML
# =============================================================================


def _render_telegraph_nodes_server(nodes: list) -> str:
    """Сериализует Telegraph content-nodes (список dict'ов и строк) в безопасный HTML.

    Whitelist-теги — `{p, strong, em, a, img, ...}`. Атрибуты — только `href` у `<a>`
    и `src/alt` у `<img>`. Все URL проходят через `_normalize_external_url`
    (без `javascript:`, без credentials). Относительные пути в `<img src>` привязываются
    к `telegra.ph`.

    Используется `bot.py:_fetch_telegra_ph_html` при получении main-payload'а главы.
    """
    if not isinstance(nodes, list):
        return ""

    allowed_tags = {
        "p",
        "br",
        "strong",
        "em",
        "b",
        "i",
        "u",
        "s",
        "blockquote",
        "code",
        "pre",
        "a",
        "h3",
        "h4",
        "figure",
        "figcaption",
        "img",
        "ul",
        "ol",
        "li",
        "hr",
    }
    void_tags = {"br", "img", "hr"}
    attr_allowlist = {
        "a": {"href"},
        "img": {"src", "alt"},
    }

    def render(node: object) -> str:
        if isinstance(node, str):
            return html.escape(node, quote=False)
        if not isinstance(node, dict):
            return ""

        tag = str(node.get("tag") or "").lower().strip()
        if not tag:
            return ""
        if tag not in allowed_tags:
            return "".join(render(child) for child in (node.get("children") or []))

        attrs = []
        for key, value in (node.get("attrs") or {}).items():
            attr_name = str(key or "").lower().strip()
            if attr_name not in attr_allowlist.get(tag, set()):
                continue
            attr_value = str(value or "").strip()
            if tag == "img" and attr_name == "src" and attr_value.startswith("/"):
                attr_value = urljoin("https://telegra.ph", attr_value)
            if tag == "a" and attr_name == "href":
                normalized = _normalize_external_url(attr_value, max_len=2048)
                if not normalized:
                    continue
                attr_value = normalized
            if not attr_value:
                continue
            attrs.append(f'{attr_name}="{html.escape(attr_value, quote=True)}"')

        attrs_text = f" {' '.join(attrs)}" if attrs else ""
        children_html = "".join(render(child) for child in (node.get("children") or []))
        if tag == "img":
            if 'src="' not in attrs_text:
                return ""
            attrs_text += ' loading="lazy"'
        if tag in void_tags:
            return f"<{tag}{attrs_text}>"
        return f"<{tag}{attrs_text}>{children_html}</{tag}>"

    return "".join(render(item) for item in nodes)


# =============================================================================
# Универсальный санитайзер HTML-фрагмента (whitelist-парсер)
# =============================================================================


class _SafeHtmlFragmentParser(HTMLParser):
    """HTMLParser-санитайзер: whitelist-теги/атрибуты + абсолютные URL.

    Поведение:
    - `<script>/<style>/<noscript>/<iframe>` и их содержимое выкидываются.
    - Не-whitelist теги удаляются (содержимое сохраняется только если текст).
    - `<a href>` и `<img src>` нормализуются через `_normalize_external_url`.
    - `<img>` без `src` выкидывается, с `src` получает `loading="lazy"`.

    Не вызывать напрямую — используйте `_sanitize_html_fragment`.
    """

    _ALLOWED_TAGS = {
        "article",
        "section",
        "div",
        "p",
        "br",
        "strong",
        "em",
        "b",
        "i",
        "u",
        "s",
        "blockquote",
        "code",
        "pre",
        "a",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "figure",
        "figcaption",
        "img",
        "ul",
        "ol",
        "li",
        "hr",
        "span",
    }
    _VOID_TAGS = {"br", "img", "hr"}
    _ATTR_ALLOWLIST = {
        "a": {"href"},
        "img": {"src", "alt"},
    }

    def __init__(self, base_url: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.result: list[str] = []
        self._tag_stack: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = str(tag or "").lower()
        if name in {"script", "style", "noscript", "iframe"}:
            self._skip_depth += 1
            self._tag_stack.append("__skip__")
            return
        if self._skip_depth:
            self._tag_stack.append("__skip__")
            return
        if name not in self._ALLOWED_TAGS:
            self._tag_stack.append("__drop__")
            return

        clean_attrs = []
        allowed_attrs = self._ATTR_ALLOWLIST.get(name, set())
        for key, value in attrs:
            attr_name = str(key or "").lower()
            if attr_name not in allowed_attrs:
                continue
            raw_value = str(value or "").strip()
            if name == "a" and attr_name == "href":
                normalized = _normalize_external_url(raw_value, max_len=2048)
                if not normalized:
                    continue
                raw_value = normalized
            elif name == "img" and attr_name == "src":
                raw_value = urljoin(self.base_url or "", raw_value)
                normalized = _normalize_external_url(raw_value, max_len=2048)
                if not normalized:
                    continue
                raw_value = normalized
            if not raw_value:
                continue
            clean_attrs.append(f'{attr_name}="{html.escape(raw_value, quote=True)}"')

        attrs_text = f" {' '.join(clean_attrs)}" if clean_attrs else ""
        if name == "img" and 'src="' not in attrs_text:
            self._tag_stack.append("__drop__")
            return
        if name == "img":
            attrs_text += ' loading="lazy"'
        self.result.append(f"<{name}{attrs_text}>")
        self._tag_stack.append(name)

    def handle_endtag(self, tag: str) -> None:
        if not self._tag_stack:
            return
        marker = self._tag_stack.pop()
        if marker == "__skip__":
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if marker == "__drop__" or marker in self._VOID_TAGS:
            return
        self.result.append(f"</{marker}>")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = str(data or "")
        if not text:
            return
        self.result.append(html.escape(text, quote=False))

    def handle_entityref(self, name: str) -> None:
        if self._skip_depth:
            return
        self.result.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._skip_depth:
            return
        self.result.append(f"&#{name};")


def _sanitize_html_fragment(fragment: str, base_url: str = "") -> str:
    """Публичная обёртка над `_SafeHtmlFragmentParser`: санитизирует HTML-фрагмент.

    `base_url` используется для резолва относительных `<img src>`.
    Дополнительно свёртывает 3+ подряд `<br>` в `<br><br>`.
    """
    parser = _SafeHtmlFragmentParser(base_url=base_url)
    parser.feed(str(fragment or ""))
    parser.close()
    cleaned = "".join(parser.result)
    cleaned = re.sub(r"(?:\s*<br>\s*){3,}", "<br><br>", cleaned)
    return cleaned.strip()


# =============================================================================
# Teletype-специфичные утилиты
# =============================================================================


def _extract_teletype_article_fragment(page_html: str) -> str:
    """Вырезает тело статьи из HTML-страницы Teletype.

    Приоритет: `<article itemprop="articleBody">`, fallback — любой `<article>`.
    Убирает HTML-комментарии и named-anchor'ы (`<a name="..."></a>`), т. к. они
    ломают реading-flow в WebApp.
    """
    if not page_html:
        return ""
    match = re.search(
        r'<article[^>]*itemprop=["\']articleBody["\'][^>]*>(.*?)</article>',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        match = re.search(r"<article\b[^>]*>(.*?)</article>", page_html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    fragment = match.group(1)
    fragment = re.sub(r"<!--.*?-->", "", fragment, flags=re.DOTALL)
    fragment = re.sub(r"<a[^>]*name=[\"'][^\"']+[\"'][^>]*>\s*</a>", "", fragment, flags=re.IGNORECASE)
    return fragment.strip()


def _extract_img_attrs_from_tag(img_tag: str, source_url: str = "") -> tuple[str, str]:
    """Парсит `<img>`-тег regex'ом → `(normalized_src, alt_text)`.

    Используется для обработки `<noscript><img ...></noscript>` lazy-load
    конструкций, где img нужно извлечь и нормализовать src.
    """
    if not img_tag:
        return "", ""
    src_match = re.search(r'\bsrc\s*=\s*(["\'])(.*?)\1', img_tag, flags=re.IGNORECASE | re.DOTALL)
    if not src_match:
        return "", ""
    raw_src = html.unescape(str(src_match.group(2) or "").strip())
    normalized_src = _normalize_external_url(urljoin(source_url or "", raw_src), max_len=2048)
    if not normalized_src:
        return "", ""

    alt_match = re.search(r'\balt\s*=\s*(["\'])(.*?)\1', img_tag, flags=re.IGNORECASE | re.DOTALL)
    alt_text = html.unescape(str(alt_match.group(2) or "").strip()) if alt_match else ""
    return normalized_src, alt_text


def _normalize_teletype_article_fragment(fragment: str, source_url: str = "") -> str:
    """Нормализует Teletype-article перед санитизацией.

    Основная задача — развернуть lazy-load конструкции:
    - `<figure>...<noscript><img></noscript>...</figure>` → `<figure><img src="..." loading="lazy">...</figure>`
    - Одиночные `<noscript><img></noscript>` → `<img>`

    Без этой нормализации санитайзер выкидывает `<noscript>` целиком и мы
    теряем все картинки статьи.
    """
    if not fragment:
        return ""

    def replace_figure(match: re.Match[str]) -> str:
        figure_html = match.group(0)
        noscript_img = re.search(r"<noscript\b[^>]*>\s*(<img\b.*?>)\s*</noscript>", figure_html, flags=re.IGNORECASE | re.DOTALL)
        if not noscript_img:
            return figure_html

        src, alt = _extract_img_attrs_from_tag(noscript_img.group(1), source_url=source_url)
        if not src:
            return figure_html

        alt_attr = f' alt="{html.escape(alt, quote=True)}"' if alt else ""
        caption_match = re.search(r"<figcaption\b[^>]*>(.*?)</figcaption>", figure_html, flags=re.IGNORECASE | re.DOTALL)
        caption_html = caption_match.group(0) if caption_match else ""
        return f'<figure><img src="{html.escape(src, quote=True)}"{alt_attr} loading="lazy">{caption_html}</figure>'

    normalized = re.sub(r"<figure\b.*?</figure>", replace_figure, fragment, flags=re.IGNORECASE | re.DOTALL)

    def replace_noscript_img(match: re.Match[str]) -> str:
        src, alt = _extract_img_attrs_from_tag(match.group(1), source_url=source_url)
        if not src:
            return ""
        alt_attr = f' alt="{html.escape(alt, quote=True)}"' if alt else ""
        return f'<img src="{html.escape(src, quote=True)}"{alt_attr} loading="lazy">'

    normalized = re.sub(
        r"<noscript\b[^>]*>\s*(<img\b.*?>)\s*</noscript>",
        replace_noscript_img,
        normalized,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return normalized.strip()
