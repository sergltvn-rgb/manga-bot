import os
from dotenv import load_dotenv

load_dotenv("codes.env")  # Загружаем данные из codes.env

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://sergltvn-rgb.github.io/manga-bot/")
API_HOST = os.getenv("API_HOST", "")  # Публичный URL aiohttp-сервера, например https://api.yourdomain.com
ADMIN_IDS = [6210312655]  # Можно оставить тут
GIVEAWAY_CHANNEL_ID = os.getenv("GIVEAWAY_CHANNEL_ID", "@alya_novel")
GIVEAWAY_CHANNEL_URL = os.getenv("GIVEAWAY_CHANNEL_URL", "https://t.me/alya_novel")

# --- Локальный inference-сервер (Ollama через Cloudflare Tunnel) ---
# Если GEMMA_URL пустой — бот использует только Groq (старое поведение).
# Пример: GEMMA_URL=https://smooth-camera-xxx.trycloudflare.com
GEMMA_URL = os.getenv("GEMMA_URL", "").rstrip("/")
GEMMA_MODEL = os.getenv("GEMMA_MODEL", "huihui_ai/gemma3-abliterated:4b")
GEMMA_TIMEOUT = int(os.getenv("GEMMA_TIMEOUT", "30"))  # сек; при превышении → fallback Groq
