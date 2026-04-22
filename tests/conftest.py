"""Pytest fixtures/bootstrap. Сейчас единственная задача — дать `bot.py`
валидный fake-токен до его импорта, чтобы smoke-тесты регистрации
хендлеров работали без боевого `codes.env`.
"""
import os

# aiogram 3.x требует формат `<digits>:<secret>` у Bot-токена.
# Проверяется только при реальном API-вызове, но на всякий случай
# даём синтаксически корректный.
os.environ.setdefault("BOT_TOKEN", "1234567890:TEST_TOKEN_FOR_UNIT_TESTS_ONLY")
os.environ.setdefault("GROQ_API_KEY", "test-key-not-used")
os.environ.setdefault("WEBAPP_URL", "https://example.com/")
