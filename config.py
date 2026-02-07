import os
import urllib.parse
from dotenv import load_dotenv

# Определяем базовую директорию проекта
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Загружаем переменные из .env файла
load_dotenv()

# --- Telegram & API Tokens ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "ai_bot_creator_bot")  # Username бота (без @)
ADMIN_ID = os.getenv("ADMIN_ID")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")  # Claude AI
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")  # Nano Banana Pro (Imagen)

# --- Pinterest OAuth ---
PINTEREST_APP_ID = os.getenv("PINTEREST_APP_ID", "")
PINTEREST_APP_SECRET = os.getenv("PINTEREST_APP_SECRET", "")
PINTEREST_REDIRECT_URI = os.getenv("PINTEREST_REDIRECT_URI", "https://yourdomain.com/pinterest/callback")

# --- Database Config ---
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_PORT = os.getenv("DB_PORT")

# Безопасная сборка URL
if DB_USER and DB_PASS and DB_HOST and DB_PORT and DB_NAME:
    encoded_pass = urllib.parse.quote_plus(DB_PASS)
    DATABASE_URL = f"postgresql://{DB_USER}:{encoded_pass}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
else:
    print("⚠️ ВНИМАНИЕ: Не все переменные БД заданы в .env")
    DATABASE_URL = None

# ═══════════════════════════════════════════════════════════════
# ТОКЕН-СИСТЕМА
# ═══════════════════════════════════════════════════════════════

# СТАРТОВЫЙ БАЛАНС ДЛЯ НОВЫХ ПОЛЬЗОВАТЕЛЕЙ
WELCOME_BONUS = 1500  # 🎁 1500 токенов при первом входе!

# --- Стоимость операций в токенах ---
TOKEN_PRICES = {
    # Генерация текста (100 слов = 10 токенов)
    "text_generation": {
        "cost": 10,
        "cost_per_100_words": 10,
        "name": "Генерация текста",
        "emoji": "✍️",
        "description": "100 слов AI-текста"
    },
    
    # Генерация изображений
    "image_generation": {
        "cost": 30,
        "name": "AI-изображение",
        "emoji": "🎨",
        "description": "Одно уникальное AI-изображение"
    },
    
    # Подбор ключевых фраз
    "keywords_collection": {
        "cost_per_50": 50,
        "cost_per_100": 100,
        "cost_per_150": 150,
        "cost_per_200": 200,
        "name": "Подбор ключевых фраз",
        "emoji": "🔑",
        "description": "Сбор и анализ ключевых фраз"
    }
}

print("✅ Config загружен")
