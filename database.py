# -*- coding: utf-8 -*-
import aiosqlite
from datetime import datetime

async def init_db():
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('CREATE TABLE IF NOT EXISTS chapters_urls (chapter_number TEXT, lang TEXT, url TEXT, PRIMARY KEY (chapter_number, lang))')
        await db.execute('CREATE TABLE IF NOT EXISTS ranobe_urls (chapter_number TEXT, lang TEXT, url TEXT, PRIMARY KEY (chapter_number, lang))')
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
        except:
            pass

        # Таблица для отключения ИИ в группах
        await db.execute('CREATE TABLE IF NOT EXISTS ai_disabled_groups (chat_id INTEGER PRIMARY KEY)')
            
        await db.commit()

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
            is_disabled = await cursor.fetchone()
            return not bool(is_disabled)

async def update_rp_stat(user_id: int, stat_name: str):
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('INSERT OR IGNORE INTO users_stats (user_id) VALUES (?)', (user_id,))
        await db.execute(f'UPDATE users_stats SET {stat_name} = {stat_name} + 1 WHERE user_id = ?', (user_id,))
        await db.commit()

async def get_user_stats(user_id: int):
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT hugs, kisses, bites, slaps, pats, messages_count, stickers_count FROM users_stats WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            return tuple(x or 0 for x in row) if row else (0, 0, 0, 0, 0, 0, 0)

async def get_admins():
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)')
        async with db.execute('SELECT user_id FROM admins') as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows] + [6210312655] 

async def add_admin(user_id: int):
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)')
        await db.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (user_id,))
        await db.commit()

async def remove_admin(user_id: int):
    async with aiosqlite.connect('manga.db') as db:
        await db.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
        await db.commit()

async def get_chapters(lang: str):
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT chapter_number FROM chapters_urls WHERE lang = ?', (lang,)) as cursor:
            rows = await cursor.fetchall()
            return sorted([row[0] for row in rows], key=float)

async def get_chapter_link(lang: str, chapter_number: str):
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT url FROM chapters_urls WHERE chapter_number = ? AND lang = ?', (chapter_number, lang)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def get_ranobe_chapters(lang: str):
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT chapter_number FROM ranobe_urls WHERE lang = ?', (lang,)) as cursor:
            rows = await cursor.fetchall()
            return sorted([row[0] for row in rows], key=float)

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
        async with db.execute('SELECT user1_id, user1_name, user2_id, user2_name, date FROM marriages WHERE chat_id = ? AND (user1_id = ? OR user2_id = ?)', (chat_id, user_id, user_id)) as cursor:
            return await cursor.fetchone()
