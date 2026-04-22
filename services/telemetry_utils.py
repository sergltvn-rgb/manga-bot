"""Утилиты для санации telemetry-payload'ов.

Используются в ~15 местах WebApp API хендлеров для:
- обрезания клиентских строк до безопасной длины (protection от огромных payload'ов);
- валидации числовых метрик (`duration_ms`, `chapter_idx` и т. п.).

Вынесено из `bot.py` как микро-шаг Фазы 3 (см.
`C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`).
"""

from __future__ import annotations

import math

# Верхняя граница для `duration_ms`-метрик. Больше 2 минут на один reader-event —
# это либо заснувшая вкладка, либо баг клиента, игнорируем.
MAX_TELEMETRY_METRIC_MS: float = 120000.0


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
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _sanitize_client_chapter_open_payload(payload: dict) -> dict | None:
    """Валидирует и нормализует payload события `client_chapter_open_ms`.

    Возвращает `None` если payload невалиден (неправильный `duration_ms`).
    Иначе — dict с приведёнными к безопасным типам/длинам полями:
    `duration_ms`, `series_id`, `volume`, `chapter`, `chapter_idx`,
    `source`, `used_prefetch`.

    Используется хендлером `/api/telemetry` для защиты `chapter_reader_events`
    от мусора из клиента.
    """
    duration = _to_finite_float(payload.get("duration_ms"))
    if duration is None or duration < 0 or duration > MAX_TELEMETRY_METRIC_MS:
        return None

    chapter_idx: int | None = None
    raw_idx = payload.get("chapter_idx")
    if raw_idx is not None and raw_idx != "":
        try:
            parsed_idx = int(raw_idx)
            if 0 <= parsed_idx <= 10000:
                chapter_idx = parsed_idx
        except (TypeError, ValueError):
            chapter_idx = None

    return {
        "duration_ms": round(duration, 2),
        "series_id": _clip_telemetry_text(payload.get("series_id"), 64),
        "volume": _clip_telemetry_text(payload.get("volume"), 32),
        "chapter": _clip_telemetry_text(payload.get("chapter"), 32),
        "chapter_idx": chapter_idx,
        "source": _clip_telemetry_text(payload.get("source"), 64),
        "used_prefetch": bool(payload.get("used_prefetch")),
    }
