"""
Подключение VK (ВКонтакте)
Поддерживает как группы, так и личные страницы
ВАЖНО: Старый handler закомментирован, используется OAuth через vk_integration
"""
from telebot import types
from loader import bot, db
from utils import escape_html
from .utils import check_global_platform_uniqueness, user_adding_platform
import re
import json


# Экспортируем для использования в других модулях
__all__ = ['extract_vk_id', 'extract_vk_token']


# ============================================================================
# СТАРЫЙ HANDLER ЗАКОММЕНТИРОВАН - ИСПОЛЬЗУЕТСЯ VK OAUTH
# ============================================================================
# 
# Старый handler add_platform_vk_start() был здесь, но теперь OAuth 
# обрабатывается в handlers/vk_integration/vk_telegram_handler.py
#
# Причина: OAuth flow через ngrok требует автоматической обработки callback
# 
# ============================================================================


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (экспортируются для других модулей)
# ============================================================================

def extract_vk_id(input_text: str, vk_type: str) -> str:
    """
    Извлекает VK ID из различных форматов

    Примеры:
    - mycompany → mycompany
    - https://vk.com/mycompany → mycompany
    - club123456 → club123456
    - id123456789 → id123456789
    """
    input_text = input_text.strip()

    # Удаляем пробелы и лишние символы
    input_text = input_text.replace(' ', '')

    # Если это полная ссылка
    if 'vk.com/' in input_text:
        # Извлекаем часть после vk.com/
        match = re.search(r'vk\.com/([^/?#]+)', input_text)
        if match:
            vk_id = match.group(1)
            return vk_id

    # Если это просто ID
    # Для групп: может быть club123, public123, event123, или короткое имя
    # Для пользователей: может быть id123 или короткое имя
    if vk_type == 'group':
        # Принимаем club, public, event, или любое короткое имя
        if re.match(r'^(club|public|event)\d+$', input_text) or re.match(r'^[a-zA-Z0-9_]+$', input_text):
            return input_text
    else:  # user
        # Принимаем id123456 или короткое имя
        if re.match(r'^id\d+$', input_text) or re.match(r'^[a-zA-Z0-9_]+$', input_text):
            return input_text

    return None


def extract_vk_token(input_text: str) -> str:
    """
    Извлекает VK токен из различных форматов

    Примеры:
    - vk1.a.xxxxx → vk1.a.xxxxx
    - https://oauth.vk.com/blank.html#access_token=vk1.a.xxxxx&... → vk1.a.xxxxx
    - длинная строка символов → длинная строка
    """
    input_text = input_text.strip()

    # Если это URL с токеном
    if 'access_token=' in input_text:
        match = re.search(r'access_token=([^&]+)', input_text)
        if match:
            return match.group(1)

    # Если это просто токен
    # Токен VK обычно начинается с vk1.a. или длинная строка букв и цифр
    if re.match(r'^vk1\.[a-zA-Z]\.[a-zA-Z0-9_-]+$', input_text):
        return input_text

    # Старый формат токенов (длинная строка)
    if len(input_text) > 50 and re.match(r'^[a-zA-Z0-9]+$', input_text):
        return input_text

    return None


print("✅ handlers/platform_connections/vk.py загружен")
print(f"   📤 Экспортировано: extract_vk_id, extract_vk_token")
