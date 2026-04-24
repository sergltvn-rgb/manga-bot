# -*- coding: utf-8 -*-
import aiosqlite
import sqlite3
import os
from datetime import datetime, timezone
from config import ADMIN_IDS

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'manga.db')

# Белый список допустимых колонок для update_rp_stat
_VALID_STAT_COLUMNS = frozenset({"hugs", "kisses", "bites", "slaps", "pats"})

AKASHIC_VOLUME_11_REPAIR_KEY = "repair_akashic_v11_illustrations_done"
AKASHIC_VOLUME_11_ORDER = ["0", "Эпилог", "Послесловие", "Иллюстрации", "1", "2", "3", "4", "5", "6"]


async def repair_akashic_volume_11_illustrations(db):
    """One-time repair for the Akashic volume 11 chapter list."""
    async with db.execute(
        "SELECT 1 FROM akashic_ranobe WHERE volume = ? AND chapter = ?",
        (11, "Иллюстрации"),
    ) as cursor:
        illustration_exists = await cursor.fetchone() is not None
    async with db.execute(
        "SELECT value FROM bot_settings WHERE key = ?",
        (AKASHIC_VOLUME_11_REPAIR_KEY,),
    ) as cursor:
        repair_done = await cursor.fetchone() is not None

    if illustration_exists and repair_done:
        return

    await db.execute(
        """
        INSERT OR IGNORE INTO akashic_ranobe (volume, chapter, url, sort_order)
        VALUES (?, ?, ?, ?)
        """,
        (11, "Иллюстрации", "", AKASHIC_VOLUME_11_ORDER.index("Иллюстрации")),
    )
    for sort_order, chapter in enumerate(AKASHIC_VOLUME_11_ORDER):
        await db.execute(
            "UPDATE akashic_ranobe SET sort_order = ? WHERE volume = ? AND chapter = ?",
            (sort_order, 11, chapter),
        )
    await db.execute(
        "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
        (AKASHIC_VOLUME_11_REPAIR_KEY, "1"),
    )


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('PRAGMA journal_mode=WAL;')
        await db.execute('PRAGMA synchronous=NORMAL;')
        await db.execute(
            'CREATE TABLE IF NOT EXISTS chapters_urls (chapter_number TEXT, lang TEXT, url TEXT, PRIMARY KEY (chapter_number, lang))'
        )
        await db.execute(
            'CREATE TABLE IF NOT EXISTS ranobe_urls (chapter_number TEXT, lang TEXT, url TEXT, PRIMARY KEY (chapter_number, lang))'
        )
        await db.execute(
            'CREATE TABLE IF NOT EXISTS akashic_ranobe (volume INTEGER, chapter TEXT, url TEXT, PRIMARY KEY (volume, chapter))'
        )
        await db.execute(
            'CREATE TABLE IF NOT EXISTS british_ranobe (volume INTEGER, chapter TEXT, url TEXT, PRIMARY KEY (volume, chapter))'
        )
        await db.execute('CREATE TABLE IF NOT EXISTS arts (id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT)')
        await db.execute('CREATE TABLE IF NOT EXISTS suggested_arts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, file_id TEXT)')
        await db.execute('CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)')
        await db.execute(
            'CREATE TABLE IF NOT EXISTS marriages (chat_id INTEGER, user1_id INTEGER, user1_name TEXT, user2_id INTEGER, user2_name TEXT, date TEXT)'
        )
        await db.execute('''CREATE TABLE IF NOT EXISTS users_stats
                     (user_id INTEGER PRIMARY KEY, hugs INTEGER DEFAULT 0, kisses INTEGER DEFAULT 0,
                      bites INTEGER DEFAULT 0, slaps INTEGER DEFAULT 0, pats INTEGER DEFAULT 0)''')

        # Миграция: добавляем новые колонки, если их нет
        try:
            await db.execute('ALTER TABLE users_stats ADD COLUMN messages_count INTEGER DEFAULT 0')
            await db.execute('ALTER TABLE users_stats ADD COLUMN stickers_count INTEGER DEFAULT 0')
        except Exception:
            pass

        try:
            await db.execute('ALTER TABLE users_stats ADD COLUMN balance INTEGER DEFAULT 0')
            await db.execute('ALTER TABLE users_stats ADD COLUMN custom_title TEXT DEFAULT NULL')
            await db.execute('ALTER TABLE users_stats ADD COLUMN is_hidden INTEGER DEFAULT 0')
            await db.execute('ALTER TABLE marriages ADD COLUMN love_level INTEGER DEFAULT 0')
        except Exception:
            pass

        try:
            await db.execute('ALTER TABLE users_stats ADD COLUMN casino_played INTEGER DEFAULT 0')
            await db.execute('ALTER TABLE users_stats ADD COLUMN divorces_count INTEGER DEFAULT 0')
        except Exception:
            pass

        try:
            await db.execute('ALTER TABLE users_stats ADD COLUMN xp INTEGER DEFAULT 0')
            await db.execute('ALTER TABLE users_stats ADD COLUMN level INTEGER DEFAULT 1')
        except Exception:
            pass

        try:
            await db.execute('ALTER TABLE users_stats ADD COLUMN last_daily TEXT DEFAULT NULL')
            await db.execute('ALTER TABLE users_stats ADD COLUMN daily_streak INTEGER DEFAULT 0')
        except Exception:
            pass

        try:
            await db.execute('ALTER TABLE users_stats ADD COLUMN referred_by INTEGER DEFAULT 0')
        except Exception:
            pass

        await db.execute('''CREATE TABLE IF NOT EXISTS referrals
                         (referrer_id INTEGER, referred_id INTEGER, timestamp TEXT)''')

        await db.execute(
            'CREATE TABLE IF NOT EXISTS harems (owner_id INTEGER, member_id INTEGER, member_name TEXT, PRIMARY KEY (owner_id, member_id))'
        )
        try:
            await db.execute('ALTER TABLE harems ADD COLUMN loyalty_level INTEGER DEFAULT 0')
        except Exception:
            pass
        await db.execute(
            'CREATE TABLE IF NOT EXISTS user_inventory (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, item_type TEXT, item_data TEXT)'
        )

        await db.execute('CREATE TABLE IF NOT EXISTS ai_disabled_groups (chat_id INTEGER PRIMARY KEY)')
        await db.execute('CREATE TABLE IF NOT EXISTS alya_settings (bot_id INTEGER PRIMARY KEY, mode TEXT DEFAULT "normal")')
        await db.execute('CREATE TABLE IF NOT EXISTS ai_blacklist (user_id INTEGER PRIMARY KEY)')
        await db.execute('CREATE TABLE IF NOT EXISTS bot_settings (key TEXT PRIMARY KEY, value TEXT)')
        await db.execute('''CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS web_sessions (
            session_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            user_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )''')
        # Таблица для выбора провайдера ИИ (gemma / groq) для каждого чата.
        # Default = gemma (локальная без цензуры). Groq используется как
        # автофоллбек в `ask_ai`, если Gemma недоступна.
        await db.execute('CREATE TABLE IF NOT EXISTS chat_ai_provider (chat_id INTEGER PRIMARY KEY, provider TEXT DEFAULT "gemma")')

        # Персистентная память ИИ-диалогов. Сохраняется между рестартами бота.
        # Ключ хранения — (chat_id, user_id, char_id), т.е. у каждого юзера
        # своя отдельная память по каждому персонажу в каждом чате.
        # Role: "user" | "assistant". ts — unix timestamp.
        await db.execute(
            '''CREATE TABLE IF NOT EXISTS ai_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                char_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                ts INTEGER NOT NULL)'''
        )
        await db.execute('CREATE INDEX IF NOT EXISTS idx_ai_memory_lookup ON ai_memory(chat_id, user_id, char_id, ts)')

        # Миграция: добавляем колонку для Drag-and-Drop сортировки
        for tbl in ['chapters_urls', 'ranobe_urls', 'akashic_ranobe', 'british_ranobe']:
            async with db.execute(f"PRAGMA table_info({tbl})") as cursor:
                columns = [row[1] for row in await cursor.fetchall()]
                if 'sort_order' not in columns:
                    await db.execute(f'ALTER TABLE {tbl} ADD COLUMN sort_order INTEGER DEFAULT 0')

        await repair_akashic_volume_11_illustrations(db)

        # Таблица для кастомных названий тайтлов/томов/глав в WebApp
        await db.execute('CREATE TABLE IF NOT EXISTS custom_names (id TEXT PRIMARY KEY, name TEXT)')

        # Таблица лайков глав (WebApp)
        await db.execute('''CREATE TABLE IF NOT EXISTS chapter_likes (
            chapter_key TEXT, user_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (chapter_key, user_id))''')

        # Таблица комментариев глав (WebApp)
        await db.execute('''CREATE TABLE IF NOT EXISTS chapter_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_key TEXT NOT NULL,
            user_id TEXT NOT NULL,
            user_name TEXT DEFAULT '',
            text TEXT NOT NULL,
            parent_id INTEGER DEFAULT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

        # Миграция: добавление parent_id, если его нет
        try:
            await db.execute('ALTER TABLE chapter_comments ADD COLUMN parent_id INTEGER DEFAULT NULL')
        except sqlite3.OperationalError:
            pass  # Колонка уже существует

        # Миграция: добавление updated_at для поддержки редактирования комментариев
        try:
            await db.execute('ALTER TABLE chapter_comments ADD COLUMN updated_at TEXT DEFAULT NULL')
        except sqlite3.OperationalError:
            pass  # Колонка уже существует

        # Таблица прогресса чтения (WebApp)
        await db.execute('''CREATE TABLE IF NOT EXISTS user_bookmarks (
            user_id TEXT NOT NULL,
            series_id TEXT NOT NULL,
            volume_id TEXT NOT NULL,
            chapter_key TEXT NOT NULL,
            scroll_pos REAL DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, series_id))''')

        # Таблица репортов об опечатках (WebApp)
        await db.execute('''CREATE TABLE IF NOT EXISTS chapter_typos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_key TEXT NOT NULL,
            user_id TEXT NOT NULL,
            user_name TEXT DEFAULT '',
            selected_text TEXT NOT NULL,
            context_text TEXT NOT NULL,
            comment TEXT DEFAULT '',
            status TEXT DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

        # Таблица реакций (WebApp Phase 3)
        await db.execute('''CREATE TABLE IF NOT EXISTS chapter_reactions (
            chapter_key TEXT NOT NULL,
            user_id TEXT NOT NULL,
            reaction TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (chapter_key, user_id))''')

        # Таблица реакций на комментарии (WebApp MangaLib Style)
        await db.execute('''CREATE TABLE IF NOT EXISTS comment_reactions (
            comment_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            type TEXT NOT NULL, -- 'like' or 'dislike'
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (comment_id, user_id))''')

        await db.execute('''CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL DEFAULT 'draft',
            channel_id TEXT NOT NULL,
            message_id INTEGER DEFAULT NULL,
            prize TEXT NOT NULL,
            post_text TEXT NOT NULL,
            media_type TEXT DEFAULT NULL,
            media_file_id TEXT DEFAULT NULL,
            winners_count INTEGER NOT NULL DEFAULT 1,
            ends_at_utc TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            published_at TEXT DEFAULT NULL,
            finished_at TEXT DEFAULT NULL,
            replacements_count INTEGER NOT NULL DEFAULT 0
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS giveaway_entries (
            giveaway_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT DEFAULT NULL,
            first_name TEXT DEFAULT NULL,
            joined_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'joined',
            is_winner INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (giveaway_id, user_id)
        )''')

        await db.execute('''CREATE TABLE IF NOT EXISTS webapp_telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            user_id TEXT DEFAULT '',
            source_module TEXT DEFAULT '',
            message TEXT DEFAULT '',
            stack TEXT DEFAULT '',
            page_url TEXT DEFAULT '',
            user_agent TEXT DEFAULT '',
            payload_json TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS admin_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            actor_user_id TEXT NOT NULL,
            target TEXT DEFAULT '',
            payload_json TEXT DEFAULT '',
            result TEXT NOT NULL,
            error TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

        # Инициализация режима Али по умолчанию (если пусто)
        await db.execute('INSERT OR IGNORE INTO alya_settings (bot_id, mode) VALUES (1, "normal")')

        # Создание индексов для ускорения поиска (WebApp)
        await db.execute('CREATE INDEX IF NOT EXISTS idx_comments_chapter ON chapter_comments(chapter_key)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_likes_chapter ON chapter_likes(chapter_key)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON user_bookmarks(user_id)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_reactions_chapter ON chapter_reactions(chapter_key)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_user_profiles_username ON user_profiles(username)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_web_sessions_user ON web_sessions(user_id)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_web_sessions_expires ON web_sessions(expires_at)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_giveaways_status_ends ON giveaways(status, ends_at_utc)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_giveaway_entries_giveaway ON giveaway_entries(giveaway_id)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_webapp_telemetry_event_time ON webapp_telemetry(event_type, created_at)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_admin_audit_actor_time ON admin_audit_log(actor_user_id, created_at)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_admin_audit_action_time ON admin_audit_log(action, created_at)')

        await db.commit()


async def get_custom_name(obj_id: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT name FROM custom_names WHERE id = ?', (obj_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def set_custom_name(obj_id: str, name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO custom_names (id, name) VALUES (?, ?)', (obj_id, name))
        await db.commit()


async def get_alya_mode() -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT mode FROM alya_settings WHERE bot_id = 1') as cursor:
            row = await cursor.fetchone()
            return row[0] if row else "normal"


async def toggle_alya_mode() -> str:
    current_mode = await get_alya_mode()
    new_mode = "gopnik" if current_mode == "normal" else "normal"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE alya_settings SET mode = ? WHERE bot_id = 1', (new_mode,))
        await db.commit()
    return new_mode


async def get_chat_ai_provider(chat_id: int) -> str:
    """Возвращает провайдера ИИ для чата: 'gemma' или 'groq'. Default: 'gemma'."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT provider FROM chat_ai_provider WHERE chat_id = ?', (chat_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else "gemma"


async def get_users_with_bookmark(series_id: str):
    """Возвращает список user_id, у которых этот тайтл в закладках."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT user_id FROM user_bookmarks WHERE series_id = ?', (series_id,)) as cursor:
            rows = await cursor.fetchall()
            return [int(row[0]) for row in rows]


async def set_chat_ai_provider(chat_id: int, provider: str):
    """Устанавливает провайдера ИИ для чата."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO chat_ai_provider (chat_id, provider) VALUES (?, ?)', (chat_id, provider))
        await db.commit()


# --- Персистентная память ИИ-диалогов ---

# Максимальная длина сообщения, которое сохраняем в память. Защита от аномально
# больших payload'ов (напр., юзер вставил портянку текста). Обрезаем перед записью.
_AI_MEMORY_MAX_CONTENT_LEN = 2000


async def get_ai_memory(chat_id: int, user_id: int, char_id: str, limit: int = 20) -> list:
    """Возвращает последние `limit` сообщений диалога в хронологическом порядке
    как список {"role": "user"|"assistant", "content": "..."}.

    Ключ памяти — (chat_id, user_id, char_id). У каждого юзера своя отдельная
    память с каждым персонажем в каждом чате.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # Берём последние `limit` по ts DESC, затем разворачиваем в ASC
        # чтобы на выходе был хронологический порядок.
        async with db.execute(
            'SELECT role, content FROM ai_memory ' 'WHERE chat_id = ? AND user_id = ? AND char_id = ? ' 'ORDER BY ts DESC, id DESC LIMIT ?',
            (chat_id, user_id, char_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
    # rows сейчас в обратном порядке (свежие сверху) — разворачиваем
    return [{"role": role, "content": content} for role, content in reversed(rows)]


async def append_ai_memory(chat_id: int, user_id: int, char_id: str, role: str, content: str) -> None:
    """Добавляет одно сообщение в память. Обрезает content до `_AI_MEMORY_MAX_CONTENT_LEN`."""
    if role not in ("user", "assistant"):
        # защита от опечаток в коде — молча игнорим некорректную роль
        return
    if not content:
        return
    if len(content) > _AI_MEMORY_MAX_CONTENT_LEN:
        content = content[:_AI_MEMORY_MAX_CONTENT_LEN]
    ts = int(datetime.now(timezone.utc).timestamp())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT INTO ai_memory (chat_id, user_id, char_id, role, content, ts) ' 'VALUES (?, ?, ?, ?, ?, ?)',
            (chat_id, user_id, char_id, role, content, ts),
        )
        await db.commit()


async def clear_ai_memory(chat_id: int, user_id: int, char_id: str | None = None) -> int:
    """Удаляет память юзера. Если `char_id=None` — удаляет по всем персонажам
    (полное забывание). Возвращает количество удалённых строк."""
    async with aiosqlite.connect(DB_PATH) as db:
        if char_id is None:
            cursor = await db.execute(
                'DELETE FROM ai_memory WHERE chat_id = ? AND user_id = ?',
                (chat_id, user_id),
            )
        else:
            cursor = await db.execute(
                'DELETE FROM ai_memory WHERE chat_id = ? AND user_id = ? AND char_id = ?',
                (chat_id, user_id, char_id),
            )
        deleted = cursor.rowcount or 0
        await db.commit()
        return deleted


async def get_all_arts() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT id, file_id FROM arts') as cursor:
            return await cursor.fetchall() or []


async def delete_art_by_id(art_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT 1 FROM arts WHERE id = ?', (art_id,)) as cursor:
            if not await cursor.fetchone():
                return False
        await db.execute('DELETE FROM arts WHERE id = ?', (art_id,))
        await db.commit()
        return True


async def get_commands_link() -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT value FROM bot_settings WHERE key = "commands_link"') as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def set_commands_link(url: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO bot_settings (key, value) VALUES ("commands_link", ?)', (url,))
        await db.commit()


async def delete_commands_link():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM bot_settings WHERE key = "commands_link"')
        await db.commit()


async def get_setting(key: str, default: str = None) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT value FROM bot_settings WHERE key = ?', (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else default


async def upsert_user_profile(user_id: int, username: str | None, first_name: str | None):
    """Upsert user profile for @username resolution in commands."""
    normalized = username.lower() if username else None
    safe_name = first_name or ""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            '''
            INSERT INTO user_profiles (user_id, username, first_name, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                username = COALESCE(excluded.username, user_profiles.username),
                first_name = excluded.first_name,
                updated_at = CURRENT_TIMESTAMP
            ''',
            (user_id, normalized, safe_name),
        )
        await db.commit()


async def get_user_profile_by_username(username: str):
    """Return tuple (user_id, username, first_name) by @username (case-insensitive)."""
    if not username:
        return None
    normalized = username.lower().lstrip("@")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            '''
            SELECT user_id, username, first_name
            FROM user_profiles
            WHERE username = ?
            ORDER BY updated_at DESC
            LIMIT 1
            ''',
            (normalized,),
        ) as cursor:
            return await cursor.fetchone()


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)', (key, value))
        await db.commit()


async def add_to_blacklist(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute('INSERT INTO ai_blacklist (user_id) VALUES (?)', (user_id,))
            await db.commit()
            return True
        except sqlite3.IntegrityError:
            return False


async def remove_from_blacklist(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT 1 FROM ai_blacklist WHERE user_id = ?', (user_id,)) as cursor:
            if not await cursor.fetchone():
                return False
        await db.execute('DELETE FROM ai_blacklist WHERE user_id = ?', (user_id,))
        await db.commit()
        return True


async def is_blacklisted(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT 1 FROM ai_blacklist WHERE user_id = ?', (user_id,)) as cursor:
            return bool(await cursor.fetchone())


async def get_blacklist() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT user_id FROM ai_blacklist') as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def toggle_group_ai(chat_id: int) -> bool:
    '''Toggles AI for a group. Returns True if enabled, False if disabled.'''
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT 1 FROM ai_disabled_groups WHERE chat_id = ?', (chat_id,)) as cursor:
            is_disabled = await cursor.fetchone()

        if is_disabled:
            await db.execute('DELETE FROM ai_disabled_groups WHERE chat_id = ?', (chat_id,))
            await db.commit()
            return True
        await db.execute('INSERT INTO ai_disabled_groups (chat_id) VALUES (?)', (chat_id,))
        await db.commit()
        return False


async def is_ai_enabled(chat_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT 1 FROM ai_disabled_groups WHERE chat_id = ?', (chat_id,)) as cursor:
            return not bool(await cursor.fetchone())


async def update_rp_stat(user_id: int, stat_name: str):
    # Защита от SQL-инъекции: проверяем по белому списку
    if stat_name not in _VALID_STAT_COLUMNS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (user_id,))
        await db.execute(f'UPDATE users_stats SET {stat_name} = {stat_name} + 1 WHERE user_id = ?', (user_id,))
        await db.commit()


async def get_user_stats(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            '''SELECT
            hugs, kisses, bites, slaps, pats,
            messages_count, stickers_count, balance,
            custom_title, is_hidden, casino_played,
            divorces_count, last_daily, daily_streak,
            referred_by, xp, level
            FROM users_stats WHERE user_id = ?''',
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                # user_id, hugs, kisses, bites, slaps, pats, msg, stick, bal, title, hidden, casino, divorce, daily, streak, ref, xp, level
                return (0, 0, 0, 0, 0, 0, 0, 0, None, 0, 0, 0, None, 0, 0, 0, 1)

            res = list(row)
            for i in range(len(res)):
                if res[i] is None:
                    if i in (8, 12):
                        res[i] = None
                    elif i == 16:  # level
                        res[i] = 1
                    else:
                        res[i] = 0
            return tuple(res)


# ---------------------------------------------------------------
# TTL-кэш списка админов. Админы читаются на горячих путях
# (antispam middleware, /admin callbacks, API-хендлеры), и каждый
# вызов без кэша открывал aiosqlite.connect + SELECT — сотни
# round-trip'ов в минуту. Кэш 5 сек + invalidate на add/remove.
# ---------------------------------------------------------------
import time as _admins_time

_ADMINS_CACHE: tuple[float, list[int]] | None = None
_ADMINS_CACHE_TTL = 5.0  # секунд


def _invalidate_admins_cache() -> None:
    global _ADMINS_CACHE
    _ADMINS_CACHE = None


async def get_admins():
    global _ADMINS_CACHE
    now = _admins_time.monotonic()
    cached = _ADMINS_CACHE
    if cached and now - cached[0] < _ADMINS_CACHE_TTL:
        return list(cached[1])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT user_id FROM admins') as cursor:
            rows = await cursor.fetchall()
    result = [row[0] for row in rows] + ADMIN_IDS
    _ADMINS_CACHE = (now, result)
    return list(result)


async def add_admin(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (user_id,))
        await db.commit()
    _invalidate_admins_cache()


async def remove_admin(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
        await db.commit()
    _invalidate_admins_cache()


async def get_chapters(lang: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT chapter_number FROM chapters_urls WHERE lang = ? ORDER BY sort_order, CAST(chapter_number AS REAL)', (lang,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def get_chapter_link(lang: str, chapter_number: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT url FROM chapters_urls WHERE chapter_number = ? AND lang = ?', (chapter_number, lang)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def get_ranobe_chapters(lang: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT chapter_number FROM ranobe_urls WHERE lang = ? ORDER BY sort_order, CAST(chapter_number AS REAL)', (lang,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def get_ranobe_chapter_link(lang: str, chapter_number: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT url FROM ranobe_urls WHERE chapter_number = ? AND lang = ?', (chapter_number, lang)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT user_id FROM users_stats') as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def get_user_marriage(chat_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT user1_id, user1_name, user2_id, user2_name, date, love_level FROM marriages WHERE chat_id = ? AND (user1_id = ? OR user2_id = ?)',
            (chat_id, user_id, user_id),
        ) as cursor:
            return await cursor.fetchone()


async def get_akashic_volumes():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT DISTINCT volume FROM akashic_ranobe ORDER BY volume') as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def get_akashic_chapters(volume: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT chapter FROM akashic_ranobe WHERE volume = ? ORDER BY sort_order, CAST(chapter AS REAL)', (volume,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def get_akashic_chapter_link(volume: int, chapter: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT url FROM akashic_ranobe WHERE volume = ? AND chapter = ?', (volume, chapter)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def get_british_volumes():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT DISTINCT volume FROM british_ranobe ORDER BY volume') as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows] if rows else []


async def get_british_chapters(volume: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT chapter FROM british_ranobe WHERE volume = ? ORDER BY sort_order, CAST(chapter AS REAL)', (volume,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def get_british_chapter_link(volume: int, chapter: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT url FROM british_ranobe WHERE volume = ? AND chapter = ?', (volume, chapter)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


# --- Harem Functions ---
async def add_to_harem(owner_id: int, member_id: int, member_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT OR REPLACE INTO harems (owner_id, member_id, member_name) VALUES (?, ?, ?)', (owner_id, member_id, member_name)
        )
        await db.commit()


async def remove_from_harem(owner_id: int, member_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM harems WHERE owner_id = ? AND member_id = ?', (owner_id, member_id))
        await db.commit()


async def get_user_harem(owner_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT member_id, member_name, loyalty_level FROM harems WHERE owner_id = ?', (owner_id,)) as cursor:
            return await cursor.fetchall()


async def update_loyalty_level(owner_id: int, member_id: int, amount: int = 1):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'UPDATE harems SET loyalty_level = loyalty_level + ? WHERE owner_id = ? AND member_id = ?', (amount, owner_id, member_id)
        )
        await db.commit()


# --- Inventory Functions ---
async def add_to_inventory(user_id: int, item_type: str, item_data: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO user_inventory (user_id, item_type, item_data) VALUES (?, ?, ?)', (user_id, item_type, item_data))
        await db.commit()


async def get_user_inventory(user_id: int, item_type: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        query = 'SELECT item_type, item_data FROM user_inventory WHERE user_id = ?'
        params = [user_id]
        if item_type:
            query += ' AND item_type = ?'
            params.append(item_type)

        async with db.execute(query, tuple(params)) as cursor:
            return await cursor.fetchall()


# --- Referral Functions ---
async def add_referral(referrer_id: int, referred_id: int) -> bool:
    if referrer_id == referred_id:
        return False

    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await db.execute('BEGIN IMMEDIATE')

        # Гарантируем наличие записей в users_stats
        await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (referred_id,))
        await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (referrer_id,))

        # Защита от повторной выдачи бонусов: награда только при первом реферале пользователя
        cursor = await db.execute(
            'UPDATE users_stats SET referred_by = ? WHERE user_id = ? AND COALESCE(referred_by, 0) = 0', (referrer_id, referred_id)
        )
        if cursor.rowcount == 0:
            await db.rollback()
            return False

        await db.execute('INSERT INTO referrals (referrer_id, referred_id, timestamp) VALUES (?, ?, ?)', (referrer_id, referred_id, now))
        await db.execute('UPDATE users_stats SET balance = balance + 1000, xp = xp + 3 WHERE user_id = ?', (referrer_id,))
        await db.execute('UPDATE users_stats SET balance = balance + 500 WHERE user_id = ?', (referred_id,))
        await db.commit()
        return True


async def get_referral_stats(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,)) as cursor:
            count = (await cursor.fetchone())[0]
            return count


# --- Comment Reactions ---
async def add_comment_reaction(comment_id: int, user_id: str, reaction_type: str):
    """Добавляет или переключает реакцию (like/dislike) на комментарий."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT type FROM comment_reactions WHERE comment_id = ? AND user_id = ?', (comment_id, user_id)) as cursor:
            row = await cursor.fetchone()

        if row:
            if row[0] == reaction_type:
                # Убираем, если нажали то же самое
                await db.execute('DELETE FROM comment_reactions WHERE comment_id = ? AND user_id = ?', (comment_id, user_id))
            else:
                # Переключаем
                await db.execute(
                    'UPDATE comment_reactions SET type = ? WHERE comment_id = ? AND user_id = ?', (reaction_type, comment_id, user_id)
                )
        else:
            await db.execute(
                'INSERT INTO comment_reactions (comment_id, user_id, type) VALUES (?, ?, ?)', (comment_id, user_id, reaction_type)
            )
        await db.commit()


async def get_user_referred_by(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT referred_by FROM users_stats WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def write_admin_audit_log(
    action: str,
    actor_user_id: str,
    target: str = "",
    payload_json: str = "",
    result: str = "ok",
    error: str = "",
):
    """Пишет запись об admin-действии в аудит-лог."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            '''
            INSERT INTO admin_audit_log
            (action, actor_user_id, target, payload_json, result, error)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (
                str(action),
                str(actor_user_id),
                str(target or ""),
                str(payload_json or ""),
                str(result or "ok"),
                str(error or ""),
            ),
        )
        await db.commit()
