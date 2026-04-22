# `bot.py` — аудит (Фаза 0)

Статический отчёт по состоянию на коммит с фиксом `_is_bot_admin` shadowing.
Живой план работ — `C:/Users/litvi/.windsurf/plans/bot-py-hardening-roadmap-c8a805.md`.

## Снимок

- **LOC**: 8444
- **Top-level функций**: 305
- **Уникальных `@dp.message(Command(...))`**: 36
- **Дублей имён функций**: 0 (после фикса `_is_bot_admin` → `_bot_is_chat_admin`)
- **Дублей `Command()` декораторов**: 0
- **Блоков (по комментариям `# БЛОК N`)**: 10
- **`aiosqlite.connect(` прямо в `bot.py`**: 56
- **`except Exception: pass`**: 19

## A. Тихие `except Exception: pass`

Классификация каждого вхождения:

| Line | Функция / контекст | Вердикт | Действие |
|---|---|---|---|
| 71 | `_resolve_webapp_cache_buster` — fallback git-sha | осознанный fallback | оставить |
| 149 | `CallbackAntiSpamMiddleware.__call__` — extract ctx | тихая потеря | `logging.debug` |
| 162 | то же, иная ветка | тихая потеря | `logging.debug` |
| 211 | `errors_handler` — extract context | внутри error-handler'а | оставить |
| 2090 | `roast_profile` — delete `wait_msg` | delete уже-удалённого | оставить |
| 3800 | `_fetch_admin_metrics` — events count | тихая потеря метрики | `logging.debug` |
| 3832 | то же — `akashic_ranobe` | таблицы может не быть | оставить |
| 3838 | то же — `british_ranobe` | таблицы может не быть | оставить |
| 3844 | то же — `marriages` | таблицы может не быть | оставить |
| 3853 | то же — cmt_24h | таблицы `comments` может не быть | `logging.debug` |
| 4080 | `_render_admins_section` — user_profile lookup | отсутствие профиля ок | `logging.debug` |
| 4170 | `_build_settings_text_and_kb` — `sync_locked` | тихая подмена дефолтом | `logging.debug` |
| 4175 | то же — `cleanup_service` | тихая подмена дефолтом | `logging.debug` |
| 4181 | то же — `alya_mode` | тихая подмена дефолтом | `logging.debug` |
| 4307 | `_exec_admin_action` — delete message | delete уже-удалённого | оставить |
| 6125 | `apply_webapp_response_headers` — enable_compression | неподдерживаемый тип | `logging.debug` |
| 8021 | `cmd_clean` — delete own command | delete уже-удалённого | оставить |
| 8043 | `cmd_clean` — send autodelete note | некритично | оставить |
| 8189 | `_guard_mod_command` — `is_moderator` check | fail-safe для /ban | `logging.warning` |

**Итого в Фазе 1 трогаем 10 мест**. Остальные — умышленные no-op'ы.

## B. FSM message-хендлеры и перехват команд

Все хендлеры, которые матчатся по FSM-состоянию:

| Line | Хендлер | Защита от `/command` |
|---|---|---|
| 743 | `process_ai_chat` (AIChat.chatting) | ✅ `if text.startswith('/'): return` |
| 817 | `process_group_ai_chat` | ✅ `StateFilter(None)` + `is_ai_trigger` фильтрует `/` |
| 1347 | `process_rename_name` (AdminRename) | ✅ `if text.startswith('/'): state.clear()` |
| 1446 | `handle_tech_support_message` (TechSupport) | ✅ то же |
| **2797** | **`shop_process_title` (ShopBuyTitle)** | ❌ **нет** — команда станет новым титулом |
| 3455 | `handle_manga_jump` (ChapterJump) | ✅ `F.text.isdigit()` |
| 3478 | `handle_ranobe_jump` (ChapterJump) | ✅ `F.text.isdigit()` |
| 3602 | `handle_art_number_input` (ArtView) | ✅ `F.text.isdigit()` |
| 3701 | `handle_grid_page_input` (ArtView) | ✅ `F.text.isdigit()` |
| 3754 | `handle_grid_art_number_input` (ArtView) | ✅ `F.text.isdigit()` |
| **4138** | **`admin_manage_new_id` (AdminManage)** | ⚠️ частичная — команда отклоняется как "не число", но state не очищается → юзер застрянет |

**Итого в Фазе 1 чиним**: `shop_process_title`, `admin_manage_new_id`.

## C. Прямые `aiosqlite.connect(DB_PATH)` в `bot.py` — 56 вхождений

Это размывает абстракцию БД между `bot.py` и `database.py`. Выносим в Фазе 3 (по мере распила блоков). Предварительный разрез:

| Блок | Кол-во `aiosqlite.connect` | Куда уйдёт |
|---|---|---|
| БЛОК 4 (ИИ) | ~5 | `handlers/ai.py` → `database.get_ai_*` |
| БЛОК 5 (меню) | ~3 | `handlers/menus.py` → `database.*_profile_*` |
| БЛОК 6 (профили) | ~8 | `handlers/menus.py` → `database.*_stats_*` |
| БЛОК 7 (браки) | ~4 | `handlers/marriage.py` → `database.*_marriage_*` |
| БЛОК 8 (игры) | ~10 | `handlers/games.py` → `database.*_shop_*` |
| БЛОК 9 (читалка) | ~8 | `handlers/reader.py` → `database.*_reader_*` |
| БЛОК 10 (админ) | ~6 | `handlers/admin.py` → `database.*_admin_*` |
| БЛОК 11 (WebApp API) | ~12 | `services/webapp_api.py` → `database.*_api_*` |

**Цель**: 0 прямых `aiosqlite.connect` в `bot.py` и `handlers/*.py`. Всё через функции `database.py`.

## D. Блоки → файлы (план распила Фазы 3)

| Блок | Строки | LOC | Куда |
|---|---|---|---|
| 1 | 1–469 | 469 | остаётся в `bot.py` (bootstrap/imports/cache) |
| 2 | 472–500 | 29 | остаётся в `bot.py` (cooldowns re-export) |
| 4 | 503–864 | 362 | `handlers/ai.py` + `services/ai_providers.py` |
| 5 | 866–1680 | 815 | `handlers/menus.py` |
| 6 | 1683–2169 | 487 | `handlers/menus.py` (профили), `handlers/rp.py` уже вынесен |
| 7 | 2171–2293 | 123 | `handlers/marriage.py` |
| 7.1 | 2295–2379 | 85 | `handlers/marriage.py` |
| 8 | 2381–3142 | 762 | `handlers/games.py` |
| 9 | 3144–3762 | 619 | `handlers/reader.py` |
| 10 | 3765–5760 | 1996 | `handlers/admin.py` |
| 11 | 5763–8444 | 2682 | `services/webapp_api.py` + `handlers/moderation.py` + остаток в `bot.py` |

## E. Глобалы и риски циклических импортов

- `bot = Bot(token=...)` в `@c:\bot – копія\bot.py:100`
- `dp = Dispatcher()` в `@c:\bot – копія\bot.py:101`
- `_http_session` — ленивый глобал через `get_http_session()`

**Правило для распила**: новые модули не импортируют `bot` напрямую; получают `Bot`/`Router` через factory-функции (`register_admin_handlers(router: Router, bot: Bot) -> None`). `dp.include_router(...)` только в `main()`.

## F. Инструментальные проверки на будущее (Фаза 2)

1. **`ruff`** с правилами `F811`, `F841`, `E722`, `BLE001`, `ASYNC*` — минимум.
2. **Pre-commit hook**: `scripts/check_no_shadowing.py` — `ast.parse` + проверка, что в каждом файле нет двух top-level `def` с одинаковым именем.
3. **Smoke-тест** `tests/test_handlers_registered.py` — импорт `bot`, проверка что все 36 команд зарегистрированы ровно один раз.
4. **journalctl-алерт** раз в час: скрипт, который отдаёт главному админу в TG все новые `WARNING`/`ERROR`.
