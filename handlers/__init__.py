# -*- coding: utf-8 -*-
"""
Handlers Package
Загружает все обработчики для Telegram бота
"""

# Website handlers
try:
    from handlers.website import *
except Exception as e:
    print(f"⚠️ handlers/website/ не загружен: {e}")

# Reviews handlers
try:
    from handlers.reviews import *
except Exception as e:
    print(f"⚠️ handlers/reviews/ не загружен: {e}")

# Platform connections
try:
    from handlers.platform_connections import *
except Exception as e:
    print(f"⚠️ handlers/platform_connections/ не загружен: {e}")

# Platform category
try:
    from handlers.platform_category import *
except Exception as e:
    print(f"⚠️ handlers/platform_category/ не загружен: {e}")

# Platform settings
try:
    from handlers.platform_settings import *
except Exception as e:
    print(f"⚠️ handlers/platform_settings/ не загружен: {e}")

# Admin handlers
try:
    from handlers.admin import *
except Exception as e:
    print(f"⚠️ handlers/admin/ не загружен: {e}")

# Main handlers
try:
    from handlers.start import *
except Exception as e:
    print(f"⚠️ handlers/start.py не загружен: {e}")

try:
    from handlers.projects import *
except Exception as e:
    print(f"⚠️ handlers/projects.py не загружен: {e}")

try:
    from handlers.bot_creation import *
except Exception as e:
    print(f"⚠️ handlers/bot_creation.py не загружен: {e}")

try:
    from handlers.bot_card import *
except Exception as e:
    print(f"⚠️ handlers/bot_card.py не загружен: {e}")

try:
    from handlers.profile import *
except Exception as e:
    print(f"⚠️ handlers/profile.py не загружен: {e}")

try:
    from handlers.tariffs import *
except Exception as e:
    print(f"⚠️ handlers/tariffs.py не загружен: {e}")

try:
    from handlers.settings import *
except Exception as e:
    print(f"⚠️ handlers/settings.py не загружен: {e}")

try:
    from handlers.categories import *
except Exception as e:
    print(f"⚠️ handlers/categories.py не загружен: {e}")

try:
    from handlers.keywords import *
except Exception as e:
    print(f"⚠️ handlers/keywords.py не загружен: {e}")

try:
    from handlers.category_sections import *
except Exception as e:
    print(f"⚠️ handlers/category_sections.py не загружен: {e}")

try:
    from handlers.connection_instructions import *
except Exception as e:
    print(f"⚠️ handlers/connection_instructions.py не загружен: {e}")

try:
    from handlers.site_analysis import *
except Exception as e:
    print(f"⚠️ handlers/site_analysis.py не загружен: {e}")

try:
    from handlers.site_colors_detector import *
except Exception as e:
    print(f"⚠️ handlers/site_colors_detector.py не загружен: {e}")

try:
    from handlers.media_upload import *
except Exception as e:
    print(f"⚠️ handlers/media_upload.py не загружен: {e}")

try:
    from handlers.pinterest_settings import *
except Exception as e:
    print(f"⚠️ handlers/pinterest_settings.py не загружен: {e}")

try:
    from handlers.pinterest_images_settings import *
except Exception as e:
    print(f"⚠️ handlers/pinterest_images_settings.py не загружен: {e}")

try:
    from handlers.telegram_images_settings import *
except Exception as e:
    print(f"⚠️ handlers/telegram_images_settings.py не загружен: {e}")

try:
    from handlers.vk_images_settings import *
except Exception as e:
    print(f"⚠️ handlers/vk_images_settings.py не загружен: {e}")

try:
    from handlers.text_style_settings import *
except Exception as e:
    print(f"⚠️ handlers/text_style_settings.py не загружен: {e}")

try:
    from handlers.universal_platform_settings import *
except Exception as e:
    print(f"⚠️ handlers/universal_platform_settings.py не загружен: {e}")

try:
    from handlers.telegram_topics import *
except Exception as e:
    print(f"⚠️ handlers/telegram_topics.py не загружен: {e}")

try:
    from handlers.global_scheduler import *
except Exception as e:
    print(f"⚠️ handlers/global_scheduler.py не загружен: {e}")

try:
    from handlers.platform_scheduler import *
except Exception as e:
    print(f"⚠️ handlers/platform_scheduler.py не загружен: {e}")

try:
    from handlers.auto_notifications import *
except Exception as e:
    print(f"⚠️ handlers/auto_notifications.py не загружен: {e}")

try:
    from handlers.notification_scheduler import *
except Exception as e:
    print(f"⚠️ handlers/notification_scheduler.py не загружен: {e}")

try:
    # НОВАЯ МОДУЛЬНАЯ СТРУКТУРА: auto_publish импортируется отдельно в main.py
    # from handlers.auto_publish import auto_publish_scheduler
    pass  # Не импортируем здесь, только в main.py
except Exception as e:
    print(f"⚠️ handlers/auto_publish не загружен: {e}")

try:
    from handlers.reviews_generator import *
except Exception as e:
    print(f"⚠️ handlers/reviews_generator.py не загружен: {e}")

try:
    from handlers.state_manager import *
except Exception as e:
    print(f"⚠️ handlers/state_manager.py не загружен: {e}")

# ВАЖНО: text_input_handler НЕ импортируется автоматически!
# Он загружается вручную в main.py ПОСЛЕ admin handler
# try:
#     from handlers.text_input_handler import *
# except Exception as e:
#     print(f"⚠️ handlers/text_input_handler.py не загружен: {e}")

# VK Integration (OAuth)
try:
    from handlers.vk_integration import *
except Exception as e:
    print(f"⚠️ VK Integration не загружен: {e}")

print("=" * 80)
print("=" * 80)
