"""Общее мутабельное состояние, которое должно переживать отдельные FSM-шаги.

Цель существования модуля — разорвать циклическую зависимость:
`services/*` не должны делать `from bot import ART_CACHE`. Если они это
делают и bot.py был запущен как `python bot.py` (т.е. sys.modules='__main__'),
то `from bot import X` триггерит **повторный импорт** bot.py как модуля `bot`
(дубликат в памяти), и если в top-level есть aiogram-специфичные side-effects
типа `dp.include_router(...)` — падает с `RuntimeError: Router is already
attached`.

Решение: хранить общие dict'ы здесь. Импортируется и `bot.py`, и services/.

Текущие обитатели:
- `ART_CACHE` — кэш фото, собираемых админом через `/add_art`. Ключ — user_id,
  значение — `{message_id: file_id}`. Очищается в `/finish` (FSM commit)
  и в `/cancel` / `process_cancel_state` (FSM abort).
"""

from __future__ import annotations

ART_CACHE: dict = {}
