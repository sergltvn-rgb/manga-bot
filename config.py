import os
from dotenv import load_dotenv

load_dotenv("codes.env") # Загружаем данные из codes.env

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://sergltvn-rgb.github.io/manga-bot/webapp/index.html")
ADMIN_IDS = [6210312655] # Можно оставить тут