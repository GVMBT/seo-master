import telebot
from telebot import apihelper
import os
import time
from config import BOT_TOKEN

# Проверяем что токен указан
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не указан в .env")

# ═══════════════════════════════════════════════════════════════
# НАСТРОЙКА ПРОКСИ
# ═══════════════════════════════════════════════════════════════

PROXY_HOST = "172.120.82.109"
PROXY_PORT = "62394"
PROXY_USER = "uhXXpPFB"
PROXY_PASS = "N7HhCVBY"

# Формируем URL прокси
PROXY_URL = f'http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}'

# ПРИНУДИТЕЛЬНО устанавливаем переменные окружения
os.environ['HTTP_PROXY'] = PROXY_URL
os.environ['HTTPS_PROXY'] = PROXY_URL
os.environ['http_proxy'] = PROXY_URL
os.environ['https_proxy'] = PROXY_URL

# Устанавливаем прокси для telebot
apihelper.proxy = {
    'http': PROXY_URL,
    'https': PROXY_URL
}

print(f"🔐 Прокси настроен: {PROXY_HOST}:{PROXY_PORT}")

# Увеличиваем таймауты для стабильной работы
apihelper.CONNECT_TIMEOUT = 60
apihelper.READ_TIMEOUT = 120
apihelper.RETRY_ON_ERROR = True
apihelper.RETRY_TIMEOUT = 10
apihelper.MAX_RETRIES = 5

print(f"⚙️ Настройки: Connect={apihelper.CONNECT_TIMEOUT}s, Read={apihelper.READ_TIMEOUT}s, Retries={apihelper.MAX_RETRIES}")

# ═══════════════════════════════════════════════════════════════
# СОЗДАНИЕ БОТА С ПРОВЕРКОЙ ПОДКЛЮЧЕНИЯ
# ═══════════════════════════════════════════════════════════════

def create_bot_with_connection_check():
    """Создаёт бота и проверяет подключение к Telegram API"""
    print("\n🔄 Подключение к Telegram API...")
    
    bot_instance = telebot.TeleBot(BOT_TOKEN, threaded=True)
    
    # Пытаемся подключиться с повторами
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            print(f"   Попытка {attempt + 1}/{max_attempts}...", end=" ")
            bot_info = bot_instance.get_me()
            print(f"✅ Успешно!")
            print(f"   Бот: @{bot_info.username}")
            print(f"   ID: {bot_info.id}")
            return bot_instance
            
        except Exception as e:
            error_msg = str(e)
            if "Read timed out" in error_msg:
                print(f"❌ Таймаут")
                if attempt < max_attempts - 1:
                    wait_time = 15 * (attempt + 1)
                    print(f"   ⏳ Повтор через {wait_time} секунд...")
                    time.sleep(wait_time)
            else:
                print(f"❌ Ошибка: {error_msg}")
                if attempt < max_attempts - 1:
                    print(f"   ⏳ Повтор через 10 секунд...")
                    time.sleep(10)
    
    # Если все попытки провалились
    print("\n❌ НЕ УДАЛОСЬ ПОДКЛЮЧИТЬСЯ К TELEGRAM API")
    print("\n💡 Возможные решения:")
    print("   1. Проверьте интернет-соединение")
    print("   2. Проверьте прокси-сервер")
    print("   3. Попробуйте перезапустить бота")
    raise ConnectionError("Не удалось подключиться к Telegram API")

# Создаем бота
bot = create_bot_with_connection_check()

# Инициализация базы данных (будет создана позже)
db = None

print("✅ Loader инициализирован")
