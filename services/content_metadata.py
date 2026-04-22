"""Константы и маппинги контента: языки, таблицы БД, UI-имена.

Этот модуль — shared-слой между `bot.py` (read-каталоги манги/ранобэ в меню
пользователя) и `services/admin_content.py` (admin FSM добавления/удаления
контента). Вынесено из `bot.py` как шаг Фазы 3 B.5, чтобы оба модуля могли
импортировать top-level без cyclic-import.

Экспортирует:

- `LANGUAGES` — языки/секции манги (ru/en/jp/color).
- `RANOBE_LANGUAGES` — тайтлы ранобэ (alya, ru).
- `CONTENT_TYPES` — маппинг типа контента → таблица БД, колонки,
  UI-имя, emoji, тип id (lang/volume/ranobe_lang), `names_map` для
  отображения id в человеческом виде.
- `get_langs_menu(prefix)` — inline-клавиатура с кнопками языков.
  Callback-data: `{prefix}_{lang_code}`. Используется для `readlang_`
  (пользовательский каталог), `ucadd_` (admin add), `ucdel_` (admin delete).
- `get_ranobe_langs_menu(prefix)` — то же для ранобэ.
"""

from __future__ import annotations

from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder

LANGUAGES = {
    "ru": "🇷🇺 Русский",
    "en": "🇬🇧 English",
    "jp": "🇯🇵 日本語",
    "color": "🎨 Цветная манга",
}

RANOBE_LANGUAGES = {
    "alya": "⚔️ Воительница-Аля",
    "ru": "🇷🇺 Русский (Ранобэ)",
}


def get_langs_menu(prefix: str = "lang") -> types.InlineKeyboardMarkup:
    """Inline-клавиатура с кнопками языков манги. Callback = `{prefix}_{code}`.

    Дополнительно добавляет кнопку "⬅️ Назад", указывающую туда, куда нужно
    вернуться в зависимости от контекста:
    - `readlang` — пользователь в каталоге чтения → `section_read`.
    - `ucadd`/`ucdel` — админ в FSM добавления/удаления → `cancel_state`.
    - иное — в главное меню.
    """
    builder = InlineKeyboardBuilder()
    for code, name in LANGUAGES.items():
        builder.row(types.InlineKeyboardButton(text=name, callback_data=f"{prefix}_{code}"))

    if prefix == "readlang":
        builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="section_read"))
    elif prefix in ("ucadd", "ucdel"):
        builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="cancel_state"))
    else:
        builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))
    return builder.as_markup()


def get_ranobe_langs_menu(prefix: str = "ranobelang") -> types.InlineKeyboardMarkup:
    """Inline-клавиатура с кнопками тайтлов ранобэ. Callback = `{prefix}_{code}`.

    Для `readranobelang` дополнительно показывает Хроники Акаши и
    Британскую красавицу (не-переводные тайтлы в том же каталоге).
    """
    builder = InlineKeyboardBuilder()
    for code, name in RANOBE_LANGUAGES.items():
        builder.row(types.InlineKeyboardButton(text=name, callback_data=f"{prefix}_{code}"))

    if prefix == "readranobelang":
        builder.row(types.InlineKeyboardButton(text="📖 Хроники Акаши", callback_data="akashic_vols"))
        builder.row(types.InlineKeyboardButton(text="👸 Британская красавица", callback_data="british_vols"))
        builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="section_read"))
    elif prefix in ("adminranobe", "ucadd", "ucdel"):
        builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="cancel_state"))
    else:
        builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))
    return builder.as_markup()


# Маппинг типов контента → таблицы/колонки БД и UI-имена.
# Используется в admin content FSM (services/admin_content.py) для добавления
# и удаления глав универсальным способом: `CONTENT_TYPES[ctype]['table']` и т.д.
CONTENT_TYPES = {
    'manga': {
        'table': 'chapters_urls',
        'id_col': 'lang',
        'chapter_col': 'chapter_number',
        'url_col': 'url',
        'name': 'Манга',
        'emoji': '📗',
        'id_type': 'lang',
        'names_map': LANGUAGES,
    },
    'ranobe': {
        'table': 'ranobe_urls',
        'id_col': 'lang',
        'chapter_col': 'chapter_number',
        'url_col': 'url',
        'name': 'Ранобэ',
        'emoji': '📘',
        'id_type': 'ranobe_lang',
        'names_map': RANOBE_LANGUAGES,
    },
    'akashic': {
        'table': 'akashic_ranobe',
        'id_col': 'volume',
        'chapter_col': 'chapter',
        'url_col': 'url',
        'name': 'Хроники Акаши',
        'emoji': '📖',
        'id_type': 'volume',
        'names_map': {},
    },
    'british': {
        'table': 'british_ranobe',
        'id_col': 'volume',
        'chapter_col': 'chapter',
        'url_col': 'url',
        'name': 'Британская красавица',
        'emoji': '👸',
        'id_type': 'volume',
        'names_map': {},
    },
}
