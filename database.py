# -*- coding: utf-8 -*-
import aiosqlite
import sqlite3
from datetime import datetime

# Белый список допустимых колонок для update_rp_stat
_VALID_STAT_COLUMNS = frozenset({"hugs", "kisses", "bites", "slaps", "pats"})

async def init_db():
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('PRAGMA journal_mode=WAL;')
        await db.execute('PRAGMA synchronous=NORMAL;')
        await db.execute('CREATE TABLE IF NOT EXISTS chapters_urls (chapter_number TEXT, lang TEXT, url TEXT, PRIMARY KEY (chapter_number, lang))')
        await db.execute('CREATE TABLE IF NOT EXISTS ranobe_urls (chapter_number TEXT, lang TEXT, url TEXT, PRIMARY KEY (chapter_number, lang))')
        await db.execute('CREATE TABLE IF NOT EXISTS akashic_ranobe (volume INTEGER, chapter TEXT, url TEXT, PRIMARY KEY (volume, chapter))')
        await db.execute('CREATE TABLE IF NOT EXISTS british_ranobe (volume INTEGER, chapter TEXT, url TEXT, PRIMARY KEY (volume, chapter))')
        await db.execute('CREATE TABLE IF NOT EXISTS arts (id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT)')
        await db.execute('CREATE TABLE IF NOT EXISTS suggested_arts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, file_id TEXT)')
        await db.execute('CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)')
        await db.execute('CREATE TABLE IF NOT EXISTS marriages (chat_id INTEGER, user1_id INTEGER, user1_name TEXT, user2_id INTEGER, user2_name TEXT, date TEXT)')
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
            
        await db.execute('CREATE TABLE IF NOT EXISTS harems (owner_id INTEGER, member_id INTEGER, member_name TEXT, PRIMARY KEY (owner_id, member_id))')
        try:
            await db.execute('ALTER TABLE harems ADD COLUMN loyalty_level INTEGER DEFAULT 0')
        except Exception:
            pass
        await db.execute('CREATE TABLE IF NOT EXISTS user_inventory (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, item_type TEXT, item_data TEXT)')

        await db.execute('CREATE TABLE IF NOT EXISTS ai_disabled_groups (chat_id INTEGER PRIMARY KEY)')
        await db.execute('CREATE TABLE IF NOT EXISTS alya_settings (bot_id INTEGER PRIMARY KEY, mode TEXT DEFAULT "normal")')
        await db.execute('CREATE TABLE IF NOT EXISTS ai_blacklist (user_id INTEGER PRIMARY KEY)')
        await db.execute('CREATE TABLE IF NOT EXISTS bot_settings (key TEXT PRIMARY KEY, value TEXT)')
        # Таблица для выбора провайдера ИИ (groq / gemma) для каждого чата
        await db.execute('CREATE TABLE IF NOT EXISTS chat_ai_provider (chat_id INTEGER PRIMARY KEY, provider TEXT DEFAULT "groq")')
        
        # Миграция: добавляем колонку для Drag-and-Drop сортировки
        for tbl in ['chapters_urls', 'ranobe_urls', 'akashic_ranobe', 'british_ranobe']:
            async with db.execute(f"PRAGMA table_info({tbl})") as cursor:
                columns = [row[1] for row in await cursor.fetchall()]
                if 'sort_order' not in columns:
                    await db.execute(f'ALTER TABLE {tbl} ADD COLUMN sort_order INTEGER DEFAULT 0')
        
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
            pass # Колонка уже существует

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

        # Инициализация режима Али по умолчанию (если пусто)
        await db.execute('INSERT OR IGNORE INTO alya_settings (bot_id, mode) VALUES (1, "normal")')
        
        # Создание индексов для ускорения поиска (WebApp)
        await db.execute('CREATE INDEX IF NOT EXISTS idx_comments_chapter ON chapter_comments(chapter_key)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_likes_chapter ON chapter_likes(chapter_key)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON user_bookmarks(user_id)')
            
        await db.commit()

async def get_custom_name(obj_id: str) -> str:
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT name FROM custom_names WHERE id = ?', (obj_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def set_custom_name(obj_id: str, name: str):
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('INSERT OR REPLACE INTO custom_names (id, name) VALUES (?, ?)', (obj_id, name))
        await db.commit()

async def get_alya_mode() -> str:
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT mode FROM alya_settings WHERE bot_id = 1') as cursor:
            row = await cursor.fetchone()
            return row[0] if row else "normal"

async def toggle_alya_mode() -> str:
    current_mode = await get_alya_mode()
    new_mode = "gopnik" if current_mode == "normal" else "normal"
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('UPDATE alya_settings SET mode = ? WHERE bot_id = 1', (new_mode,))
        await db.commit()
    return new_mode

async def get_chat_ai_provider(chat_id: int) -> str:
    """Возвращает провайдера ИИ для чата: 'groq' или 'gemma'."""
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT provider FROM chat_ai_provider WHERE chat_id = ?', (chat_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else "groq"

async def get_users_with_bookmark(series_id: str):
    """Возвращает список user_id, у которых этот тайтл в закладках."""
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT user_id FROM user_bookmarks WHERE series_id = ?', (series_id,)) as cursor:
            rows = await cursor.fetchall()
            return [int(row[0]) for row in rows]

async def set_chat_ai_provider(chat_id: int, provider: str):
    """Устанавливает провайдера ИИ для чата."""
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('INSERT OR REPLACE INTO chat_ai_provider (chat_id, provider) VALUES (?, ?)', (chat_id, provider))
        await db.commit()

async def get_all_arts() -> list:
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT id, file_id FROM arts') as cursor:
            return await cursor.fetchall() or []

async def delete_art_by_id(art_id: int) -> bool:
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT 1 FROM arts WHERE id = ?', (art_id,)) as cursor:
            if not await cursor.fetchone():
                return False
        await db.execute('DELETE FROM arts WHERE id = ?', (art_id,))
        await db.commit()
        return True

async def get_commands_link() -> str | None:
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT value FROM bot_settings WHERE key = "commands_link"') as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def set_commands_link(url: str):
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('INSERT OR REPLACE INTO bot_settings (key, value) VALUES ("commands_link", ?)', (url,))
        await db.commit()

async def delete_commands_link():
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('DELETE FROM bot_settings WHERE key = "commands_link"')
        await db.commit()

async def add_to_blacklist(user_id: int) -> bool:
    async with aiosqlite.connect('manga.db') as db:
        try:
            await db.execute('INSERT INTO ai_blacklist (user_id) VALUES (?)', (user_id,))
            await db.commit()
            return True
        except sqlite3.IntegrityError:
            return False

async def remove_from_blacklist(user_id: int) -> bool:
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT 1 FROM ai_blacklist WHERE user_id = ?', (user_id,)) as cursor:
            if not await cursor.fetchone():
                return False
        await db.execute('DELETE FROM ai_blacklist WHERE user_id = ?', (user_id,))
        await db.commit()
        return True

async def is_blacklisted(user_id: int) -> bool:
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT 1 FROM ai_blacklist WHERE user_id = ?', (user_id,)) as cursor:
            return bool(await cursor.fetchone())

async def get_blacklist() -> list:
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT user_id FROM ai_blacklist') as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def toggle_group_ai(chat_id: int) -> bool:
    '''Toggles AI for a group. Returns True if enabled, False if disabled.'''
    async with aiosqlite.connect('manga.db') as db:
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
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT 1 FROM ai_disabled_groups WHERE chat_id = ?', (chat_id,)) as cursor:
            return not bool(await cursor.fetchone())

async def update_rp_stat(user_id: int, stat_name: str):
    # Защита от SQL-инъекции: проверяем по белому списку
    if stat_name not in _VALID_STAT_COLUMNS:
        return
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (user_id,))
        await db.execute(f'UPDATE users_stats SET {stat_name} = {stat_name} + 1 WHERE user_id = ?', (user_id,))
        await db.commit()

async def get_user_stats(user_id: int):
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('''SELECT 
            hugs, kisses, bites, slaps, pats, 
            messages_count, stickers_count, balance, 
            custom_title, is_hidden, casino_played, 
            divorces_count, last_daily, daily_streak, 
            referred_by, xp, level 
            FROM users_stats WHERE user_id = ?''', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                # user_id, hugs, kisses, bites, slaps, pats, msg, stick, bal, title, hidden, casino, divorce, daily, streak, ref, xp, level
                return (0, 0, 0, 0, 0, 0, 0, 0, None, 0, 0, 0, None, 0, 0, 0, 1)
            
            res = list(row)
            for i in range(len(res)):
                if res[i] is None:
                    if i in (8, 12):
                        res[i] = None
                    elif i == 16: # level
                        res[i] = 1
                    else:
                        res[i] = 0
            return tuple(res)

async def get_admins():
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT user_id FROM admins') as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows] + [6210312655] 

async def add_admin(user_id: int):
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (user_id,))
        await db.commit()

async def remove_admin(user_id: int):
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
        await db.commit()

async def get_chapters(lang: str):
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT chapter_number FROM chapters_urls WHERE lang = ? ORDER BY sort_order, CAST(chapter_number AS REAL)', (lang,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def get_chapter_link(lang: str, chapter_number: str):
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT url FROM chapters_urls WHERE chapter_number = ? AND lang = ?', (chapter_number, lang)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def get_ranobe_chapters(lang: str):
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT chapter_number FROM ranobe_urls WHERE lang = ? ORDER BY sort_order, CAST(chapter_number AS REAL)', (lang,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def get_ranobe_chapter_link(lang: str, chapter_number: str):
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT url FROM ranobe_urls WHERE chapter_number = ? AND lang = ?', (chapter_number, lang)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def get_all_users():
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT user_id FROM users_stats') as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def get_user_marriage(chat_id: int, user_id: int):
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT user1_id, user1_name, user2_id, user2_name, date, love_level FROM marriages WHERE chat_id = ? AND (user1_id = ? OR user2_id = ?)', (chat_id, user_id, user_id)) as cursor:
            return await cursor.fetchone()

async def get_akashic_volumes():
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT DISTINCT volume FROM akashic_ranobe ORDER BY volume') as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def get_akashic_chapters(volume: int):
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT chapter FROM akashic_ranobe WHERE volume = ? ORDER BY sort_order, CAST(chapter AS REAL)', (volume,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def get_akashic_chapter_link(volume: int, chapter: str):
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT url FROM akashic_ranobe WHERE volume = ? AND chapter = ?', (volume, chapter)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def get_british_volumes():
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT DISTINCT volume FROM british_ranobe ORDER BY volume') as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows] if rows else []

async def get_british_chapters(volume: int):
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT chapter FROM british_ranobe WHERE volume = ? ORDER BY sort_order, CAST(chapter AS REAL)', (volume,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def get_british_chapter_link(volume: int, chapter: str):
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT url FROM british_ranobe WHERE volume = ? AND chapter = ?', (volume, chapter)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

# --- Harem Functions ---
async def add_to_harem(owner_id: int, member_id: int, member_name: str):
    async with aiosqlite.connect('manga.db') as db:
        await db.execute(
            'INSERT OR REPLACE INTO harems (owner_id, member_id, member_name) VALUES (?, ?, ?)',
            (owner_id, member_id, member_name)
        )
        await db.commit()

async def remove_from_harem(owner_id: int, member_id: int):
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('DELETE FROM harems WHERE owner_id = ? AND member_id = ?', (owner_id, member_id))
        await db.commit()

async def get_user_harem(owner_id: int):
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT member_id, member_name, loyalty_level FROM harems WHERE owner_id = ?', (owner_id,)) as cursor:
            return await cursor.fetchall()

async def update_loyalty_level(owner_id: int, member_id: int, amount: int = 1):
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('UPDATE harems SET loyalty_level = loyalty_level + ? WHERE owner_id = ? AND member_id = ?', (amount, owner_id, member_id))
        await db.commit()

# --- Inventory Functions ---
async def add_to_inventory(user_id: int, item_type: str, item_data: str):
    async with aiosqlite.connect('manga.db') as db:
        await db.execute(
            'INSERT INTO user_inventory (user_id, item_type, item_data) VALUES (?, ?, ?)',
            (user_id, item_type, item_data)
        )
        await db.commit()

async def get_user_inventory(user_id: int, item_type: str = None):
    async with aiosqlite.connect('manga.db') as db:
        query = 'SELECT item_type, item_data FROM user_inventory WHERE user_id = ?'
        params = [user_id]
        if item_type:
            query += ' AND item_type = ?'
            params.append(item_type)
            
        async with db.execute(query, tuple(params)) as cursor:
            return await cursor.fetchall()

# --- Referral Functions ---
async def add_referral(referrer_id: int, referred_id: int):
    async with aiosqlite.connect('manga.db') as db:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await db.execute('INSERT INTO referrals (referrer_id, referred_id, timestamp) VALUES (?, ?, ?)',
                         (referrer_id, referred_id, now))
        await db.execute('UPDATE users_stats SET referred_by = ? WHERE user_id = ?', (referrer_id, referred_id))
        await db.execute('UPDATE users_stats SET balance = balance + 1000, xp = xp + 3 WHERE user_id = ?', (referrer_id,))
        await db.execute('UPDATE users_stats SET balance = balance + 500 WHERE user_id = ?', (referred_id,))
        await db.commit()

async def get_referral_stats(user_id: int):
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,)) as cursor:
            count = (await cursor.fetchone())[0]
            return count

async def get_user_referred_by(user_id: int):
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT referred_by FROM users_stats WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0
