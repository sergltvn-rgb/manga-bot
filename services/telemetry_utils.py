"""Утилиты для санации telemetry-payload'ов.

Используются в ~15 местах WebApp API хендлеров для:
- обрезания клиентских строк до безопасной длины (protection от огромных payload'ов);
- валидации числовых метрик (`duration_ms`, `chapter_idx` и т. п.).

Вынесено из `bot.py` как микро-шаг Фазы 3 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import math


def _clip_telemetry_text(value: object, max_len: int) -> str:
    """Приводит любое значение к строке, обрезает пробелы и длину.
    Для `None` возвращает `""`. Используется для безопасного логирования
    клиентских payload'ов в `chapter_reader_events` / `webapp_telemetry`.
    """
    if value is None:
        return ""
    text = str(value).strip()
    return text[:max_len] if len(text) > max_len else text


def _to_finite_float(value: object) -> float | None:
    """Безопасный float-cast. Возвращает `None` для NaN/Infinity/нечислового ввода.
    Нужен для отсева battles-payload'ов, где клиент может прислать мусор.
    """
    try:
        number = float(value)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number
