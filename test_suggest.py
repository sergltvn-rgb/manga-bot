import asyncio
from aiogram import Bot, Dispatcher, types
import os
from dotenv import load_dotenv

load_dotenv("codes.env")
BOT_TOKEN = os.getenv("BOT_TOKEN")

async def test_suggest_art():
    bot = Bot(token=BOT_TOKEN)
    print("Test script ready! However, interacting as a user via API requires Pyrogram/Telethon.")
    print("Manual testing is required for testing the bot.")
    await bot.session.close()

if __name__ == "__main__":
    asyncio.run(test_suggest_art())
