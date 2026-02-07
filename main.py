"""
Главный файл запуска Telegram бота
"""
import sys
import logging
import importlib
from pathlib import Path
from dotenv import load_dotenv
import os
from telebot.types import BotCommand

# Настройка логирования (только критичное)
logging.basicConfig(
    level=logging.WARNING,  # Только WARNING и выше
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)

# Тихий режим (без лишних ✅)
QUIET_MODE = os.getenv('QUIET_MODE', 'true').lower() == 'true'

# Проверка .env файла
env_path = Path(".env")
if env_path.exists():
    load_dotenv()
    if not QUIET_MODE:
        print("✅ .env загружен")
else:
    print("⚠️ .env не найден")

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN or BOT_TOKEN.startswith("your_"):
    print("❌ BOT_TOKEN не указан!")
    sys.exit(1)

ADMIN_ID = os.getenv("ADMIN_ID")
if not ADMIN_ID and not QUIET_MODE:
    print("⚠️ ADMIN_ID не найден")

print("\n🤖 AI Bot Creator")
print("="*50)

# Выполняем миграции БД (тихо)
try:
    from database.migrations.migration_manager import MigrationManager
    MigrationManager().run_migrations()
    if not QUIET_MODE:
        print("✅ БД готова")
except Exception as e:
    print(f"⚠️ Миграции: {e}")

try:
    from loader import bot
except Exception as e:
    print(f"❌ Ошибка загрузки: {e}")
    sys.exit(1)

# Обновляем loader с БД
from database.database import db as database
import loader
loader.db = database

if not QUIET_MODE:
    print("⏳ Загрузка...")

try:
    # Импортируем обработчики
    from handlers import (start, projects, bot_creation, bot_card, profile, 
                         tariffs, settings, categories, keywords, category_sections,
                         connections, site_analysis, media_upload,
                         reviews_generator, pinterest_settings, 
                         text_style_settings, universal_platform_settings, telegram_topics,
                         global_scheduler, auto_notifications,
                         notification_scheduler)
    
    # НОВАЯ МОДУЛЬНАЯ СТРУКТУРА: Импортируем auto_publish
    from handlers.auto_publish import auto_publish_scheduler
    
    # Импортируем настройки платформ
    from handlers import platform_settings
    
    # КРИТИЧНО: Импортируем подключения платформ (Мои подключения)
    from handlers import platform_connections
    
    # КРИТИЧНО: Импортируем все модули website (настройки изображений, генерация статей)
    from handlers.website import (
        images_settings,
        image_settings_handlers,
        image_advanced_settings,
        words_settings,
        article_generation,
        article_preview,
        article_publishing,
        article_analyzer,
        wordpress_api
    )
    
    # КРИТИЧНО: Регистрируем хендлер админки ДО text_input_handler!
    try:
        from handlers.admin import admin_main
    except Exception as admin_error:
        logger.error(f"Ошибка загрузки админки: {admin_error}")
    
    
    # ВАЖНО: text_input_handler загружается ПОСЛЕ админки!
    from handlers import text_input_handler
    
    logger.info("✅ Все модули загружены")
    
    # ═══════════════════════════════════════════════════════════════
    # Callback tracker был удалён (служебный файл для разработки)
    # ═══════════════════════════════════════════════════════════════
    
except Exception as e:
    logger.error(f"Ошибка загрузки модулей: {e}", exc_info=True)
    sys.exit(1)


def main():
    """Главная функция запуска бота"""
    print("=" * 60)
    print("🚀 AI BOT CREATOR v1.0")
    print("=" * 60)
    
    # Проверка подключения к Telegram
    try:
        bot_info = bot.get_me()
        logger.info(f"Бот: @{bot_info.username} (ID: {bot_info.id})")
        print(f"✅ Бот: @{bot_info.username}")
    except Exception as e:
        logger.error(f"Ошибка подключения к Telegram: {e}")
        sys.exit(1)
    
    # Установка команд бота
    try:
        commands = [
            BotCommand("start", "🏠 Главное меню"),
            BotCommand("help", "🆘 Помощь"),
        ]
        bot.set_my_commands(commands)
        logger.info("Команды установлены")
    except Exception as e:
        logger.warning(f"Не удалось установить команды: {e}")
    
    # Удаление webhook (для polling режима)
    try:
        bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook очищен")
    except Exception as e:
        logger.warning(f"Ошибка очистки webhook: {e}")
    
    # Запускаем планировщики
    try:
        from handlers.notification_scheduler import start_notification_scheduler
        start_notification_scheduler()
        if not QUIET_MODE:
            print("✅ Уведомления")
    except Exception as e:
        print(f"⚠️ Уведомления: {e}")
    
    try:
        print("\n" + "="*60)
        print("🔄 ЗАПУСК ПЛАНИРОВЩИКА АВТОПУБЛИКАЦИЙ")
        print("="*60)
        
        # Проверяем наличие APScheduler
        try:
            import apscheduler
            print(f"✅ APScheduler установлен (версия: {apscheduler.__version__})")
        except ImportError:
            print("❌ APScheduler НЕ установлен!")
            print("💡 Установите: pip install apscheduler")
            raise ImportError("APScheduler не установлен")
        
        if 'handlers.auto_publish.utils.token_manager' in sys.modules:
            importlib.reload(sys.modules['handlers.auto_publish.utils.token_manager'])
        
        # Проверяем что планировщик существует
        if auto_publish_scheduler is None:
            raise Exception("auto_publish_scheduler is None!")
        
        print("✅ Экземпляр планировщика создан")
        
        # Запускаем
        print("\n🚀 Вызываю auto_publish_scheduler.start()...")
        auto_publish_scheduler.start()
        
        # Проверяем что запустился
        if hasattr(auto_publish_scheduler, 'scheduler'):
            if auto_publish_scheduler.scheduler.running:
                jobs_count = len(auto_publish_scheduler.scheduler.get_jobs())
                print("\n" + "="*60)
                print(f"✅ ПЛАНИРОВЩИК ЗАПУЩЕН ({jobs_count} задач)")
                print("="*60 + "\n")
                
                # Показываем детали задач
                if jobs_count > 0:
                    print("📋 Зарегистрированные задачи:")
                    for job in auto_publish_scheduler.scheduler.get_jobs():
                        print(f"   • {job.name} (следующий запуск: {job.next_run_time})")
                    print()
            else:
                print("⚠️ Автопубликация: планировщик не запущен после start()")
        else:
            print("⚠️ Автопубликация: нет атрибута scheduler")
            
    except Exception as e:
        print(f"\n❌ ОШИБКА АВТОПУБЛИКАЦИИ: {e}")
        import traceback
        traceback.print_exc()
        print()
    
    # Запуск
    print("\n" + "="*50)
    print("✅ БОТ ЗАПУЩЕН")
    print("="*50)
    print("💡 Ctrl+C для остановки\n")
    
    try:
        bot.infinity_polling(
            timeout=60,
            long_polling_timeout=30,
            skip_pending=True,
            allowed_updates=['message', 'callback_query']
        )
    except KeyboardInterrupt:
        logger.info("Остановка бота по Ctrl+C")
        print("\n👋 Бот остановлен")
        
        # Останавливаем планировщик уведомлений
        try:
            from handlers.notification_scheduler import stop_notification_scheduler
            stop_notification_scheduler()
        except Exception:
            pass
        
        # Останавливаем планировщик публикаций (НОВАЯ МОДУЛЬНАЯ СТРУКТУРА)
        try:
            auto_publish_scheduler.stop()
        except Exception:
            pass
        
        # Callback tracker был удалён (служебный файл)
            
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
    finally:
        print("✅ Выход")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен")
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
