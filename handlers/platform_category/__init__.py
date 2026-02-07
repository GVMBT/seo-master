"""
Platform Category Menu - модульная структура

Модули:
1. main_menu - главное меню и основные действия
2. scheduler_media - планировщик и медиа библиотека
3. images_menu - подменю настроек изображений
4. quality_tone - качество и тональность
5. text_menu - подменю настроек текста
6. platform_utils - вспомогательные функции

Старые модули (deprecated):
- menu, toggle, post_manual, post_ai, etc.
"""

# Импортируем все модули в правильном порядке
from . import main_menu
from . import scheduler_media
from . import images_menu
from . import quality_tone
from . import text_menu
from . import platform_utils

