import os
from dotenv import load_dotenv

load_dotenv("codes.env") # Загружаем данные из codes.env

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LOCAL_API_URL = os.getenv("LOCAL_API_URL", "http://127.0.0.1:1234/v1")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://sergltvn-rgb.github.io/manga-bot/")
ADMIN_IDS = [6210312655] # Можно оставить тут