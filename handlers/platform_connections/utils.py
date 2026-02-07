"""
Управление подключениями к внешним площадкам (VK, Pinterest, Telegram, сайты)
"""
from telebot import types
from loader import bot
from database.database import db
from config import ADMIN_ID
from utils import escape_html
import json
import sys
import os
from datetime import datetime

# Импортируем cms_platforms из корня проекта
from cms_platforms import SUPPORTED_CMS, get_cms_list, get_cms_info, get_cms_instruction


# Временное хранилище для процесса подключения
user_adding_platform = {}


# ═══════════════════════════════════════════════════════════════
# ПРОВЕРКА УНИКАЛЬНОСТИ ПОДКЛЮЧЕНИЙ
# ═══════════════════════════════════════════════════════════════

def check_global_platform_uniqueness(platform_type, identifier):
    """
    Проверяет, что данная платформа еще не подключена ни у кого из пользователей
    
    Args:
        platform_type: тип платформы ('website', 'vk', 'pinterest', 'telegram')
        identifier: уникальный идентификатор (url, username, channel, group_id и т.д.)
    
    Returns:
        dict: {'is_unique': bool, 'owner_id': int/None, 'owner_username': str/None}
    """
    try:
        # Получаем всех пользователей
        db.cursor.execute("SELECT id, username, platform_connections FROM users")
        all_users = db.cursor.fetchall()
        
        # Нормализуем идентификатор для сравнения
        identifier_normalized = identifier.lower().strip()
        if identifier_normalized.startswith('http'):
            # Для URL убираем протокол и www
            identifier_normalized = identifier_normalized.replace('https://', '').replace('http://', '').replace('www.', '')
            identifier_normalized = identifier_normalized.rstrip('/')
        if identifier_normalized.startswith('@'):
            identifier_normalized = identifier_normalized[1:]
        
        # Проверяем каждого пользователя
        for user in all_users:
            connections = user.get('platform_connections', {})
            if not isinstance(connections, dict):
                continue
            
            # В зависимости от типа платформы проверяем соответствующий массив
            if platform_type == 'website':
                websites = connections.get('websites', [])
                for site in websites:
                    site_url = site.get('url', '')
                    # Нормализуем URL сайта
                    site_url_normalized = site_url.lower().strip()
                    if site_url_normalized.startswith('http'):
                        site_url_normalized = site_url_normalized.replace('https://', '').replace('http://', '').replace('www.', '')
                        site_url_normalized = site_url_normalized.rstrip('/')
                    
                    if site_url_normalized == identifier_normalized:
                        return {
                            'is_unique': False,
                            'owner_id': user['id'],
                            'owner_username': user.get('username', 'Unknown')
                        }
            
            elif platform_type == 'vk':
                vks = connections.get('vks', [])
                for vk in vks:
                    vk_group = vk.get('group_id', '').lower().strip()
                    vk_group = vk_group.replace('https://vk.com/', '').replace('http://vk.com/', '')
                    if vk_group == identifier_normalized:
                        return {
                            'is_unique': False,
                            'owner_id': user['id'],
                            'owner_username': user.get('username', 'Unknown')
                        }
            
            elif platform_type == 'pinterest':
                pinterests = connections.get('pinterests', [])
                for pin in pinterests:
                    pin_username = pin.get('username', '').lower().strip().replace('@', '')
                    if pin_username == identifier_normalized:
                        return {
                            'is_unique': False,
                            'owner_id': user['id'],
                            'owner_username': user.get('username', 'Unknown')
                        }
            
            elif platform_type == 'telegram':
                telegrams = connections.get('telegrams', [])
                for tg in telegrams:
                    tg_channel = tg.get('channel', '').lower().strip().replace('@', '')
                    tg_channel_id = tg.get('channel_id', '').lower().strip().replace('@', '')
                    
                    # Проверяем и по channel и по channel_id
                    if tg_channel == identifier_normalized or tg_channel_id == identifier_normalized:
                        return {
                            'is_unique': False,
                            'owner_id': user['id'],
                            'owner_username': user.get('username', 'Unknown')
                        }
        
        # Платформа уникальна - никто не использует
        return {
            'is_unique': True,
            'owner_id': None,
            'owner_username': None
        }
    
    except Exception as e:
        print(f"❌ Ошибка проверки уникальности: {e}")
        # В случае ошибки считаем платформу уникальной (не блокируем процесс)
        return {
            'is_unique': True,
            'owner_id': None,
            'owner_username': None
        }


# ═══════════════════════════════════════════════════════════════
# СПИСОК ПОДКЛЮЧЕНИЙ
# ═══════════════════════════════════════════════════════════════


print("✅ handlers/platform_connections/utils.py загружен")
