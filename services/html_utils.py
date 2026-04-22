"""HTML-утилиты: анализ и скоринг фрагментов глав.

Используются в reader-pipeline (см. `bot.py:build_chapter_content`) для:
- определения, содержит ли фрагмент visible-контент (текст или изображение);
- оценки «богатства» контента (image_count / text_len / block_count);
- выбора лучшего кандидата главы, когда есть несколько URL.

Чистые функции без зависимостей (только `html` и `re` из stdlib).
Вынесено из `bot.py` как микро-шаг Фазы 3.
"""

from __future__ import annotations

import html
import re


def _html_fragment_has_visible_content(fragment: str) -> bool:
    """True если фрагмент содержит `<img>` или непустой текст после снятия тегов.
    Используется при санации Telegraph-контента перед вставкой в читалку.
    """
    if not fragment:
        return False
    if re.search(r"<img\b", fragment, flags=re.IGNORECASE):
        return True
    text_only = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    text_only = re.sub(r"\s+", " ", text_only).strip()
    return bool(text_only)


def _analyze_html_fragment(fragment: str) -> dict[str, int]:
    """Статистика по фрагменту: длина текста, число якорей/картинок/блоков.
    Результат — dict со строго-int значениями, легко сериализуется в JSON.
    """
    raw_fragment = str(fragment or "")
    text_only = html.unescape(re.sub(r"<[^>]+>", " ", raw_fragment))
    text_only = re.sub(r"\s+", " ", text_only).strip()
    return {
        "text_len": len(text_only),
        "anchor_count": len(re.findall(r"<a\b", raw_fragment, flags=re.IGNORECASE)),
        "image_count": len(re.findall(r"<img\b", raw_fragment, flags=re.IGNORECASE)),
        "block_count": len(
            re.findall(
                r"<(?:p|li|blockquote|figure|figcaption|h[1-6]|pre)\b",
                raw_fragment,
                flags=re.IGNORECASE,
            )
        ),
    }


def _is_low_value_html_fragment(fragment: str) -> bool:
    """True если фрагмент слишком «беден» для показа в читалке:
    - нет изображений;
    - текст короткий (<180 символов) и мало блоков;
    - или только anchor-линки с коротким текстом.

    Используется для фильтрации Telegraph-«заглушек» (типа «См. оригинал → link»).
    """
    stats = _analyze_html_fragment(fragment)
    if stats["image_count"] > 0:
        return False
    if stats["text_len"] >= 180:
        return False
    if stats["block_count"] >= 3 and stats["text_len"] >= 90:
        return False
    if stats["anchor_count"] > 0 and stats["text_len"] <= 120:
        return True
    return stats["text_len"] < 60 and stats["block_count"] <= 1


def _score_html_fragment(fragment: str) -> tuple[int, int, int, int]:
    """Скоринг фрагмента по tuple-порядку для Python-сравнения:
    1. Есть ли изображения (приоритет картинкам для манги).
    2. Количество блоков, capped на 12.
    3. Длина текста, capped на 4000.
    4. ОТРИЦАТЕЛЬНОЕ количество anchor'ов — меньше ссылок-«выходов» лучше.

    Больший tuple = лучший фрагмент. Используется в `build_chapter_content`,
    когда для одной главы есть несколько URL и надо выбрать самый информативный.
    """
    stats = _analyze_html_fragment(fragment)
    return (
        1 if stats["image_count"] > 0 else 0,
        min(stats["block_count"], 12),
        min(stats["text_len"], 4000),
        -min(stats["anchor_count"], 32),
    )
