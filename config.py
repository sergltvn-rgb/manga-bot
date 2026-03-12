import os
from dotenv import load_dotenv

load_dotenv("codes.env") # Загружаем данные из codes.env

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_IDS = [6210312655] # Можно оставить тут