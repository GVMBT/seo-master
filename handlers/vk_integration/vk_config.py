# -*- coding: utf-8 -*-
"""
Конфигурация VK OAuth авторизации (VK ID с PKCE)
"""
import os
import hashlib
import base64
import secrets

# VK Application credentials
VK_APP_ID = os.getenv("VK_APP_ID", "5354809")  # Standalone приложение "Хроники героя"
VK_APP_SECRET = os.getenv("VK_APP_SECRET", "")  # Сервисный ключ из настроек
VK_ACCESS_TOKEN = os.getenv("VK_ACCESS_TOKEN", "")  # Прямой токен (если OAuth недоступен)

# Redirect URI для OAuth callback
VK_REDIRECT_URI = "https://alexshylman-sudo-project.onrender.com/vk_callback"

# VK API версия
VK_API_VERSION = "5.131"

# Права доступа (scope) для VK ID OAuth 2.1
# VK ID использует специальные scope
VK_OAUTH_SCOPE = "vkid.personal_info"  # Базовая информация о пользователе

# URLs - VK ID OAuth 2.1 (новый протокол)
VK_OAUTH_AUTHORIZE_URL = "https://id.vk.com/authorize"
VK_OAUTH_TOKEN_URL = "https://id.vk.com/oauth2/auth"
VK_API_BASE_URL = "https://api.vk.com/method"

# Временное хранилище для PKCE verifiers
_pkce_storage = {}


def generate_pkce_pair():
    """
    Генерирует PKCE code_verifier и code_challenge
    
    Returns:
        tuple: (code_verifier, code_challenge)
    """
    # Генерируем случайный code_verifier (43-128 символов)
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
    
    # Генерируем code_challenge (SHA256 хеш от verifier)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode('utf-8')).digest()
    ).decode('utf-8').rstrip('=')
    
    return code_verifier, code_challenge


def get_vk_auth_url(telegram_user_id: int) -> str:
    """
    Генерирует URL для авторизации через VK OAuth (старый API)
    
    Args:
        telegram_user_id: ID пользователя в Telegram
        
    Returns:
        str: URL для авторизации
    """
    state = f"tg_{telegram_user_id}"
    
    # Старый OAuth не требует PKCE - просто возвращаем URL
    return (
        f"{VK_OAUTH_AUTHORIZE_URL}"
        f"?client_id={VK_APP_ID}"
        f"&redirect_uri={VK_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={VK_OAUTH_SCOPE}"
        f"&state={state}"
        f"&v={VK_API_VERSION}"
        f"&display=page"
    )


def get_pkce_verifier(telegram_user_id: int) -> str:
    """
    Получает сохраненный PKCE verifier для пользователя
    
    Args:
        telegram_user_id: ID пользователя в Telegram
        
    Returns:
        str: code_verifier или None
    """
    # Сначала пробуем получить из БД
    try:
        from database.database import Database
        db = Database()
        
        db.cursor.execute("""
            SELECT code_verifier FROM vk_pkce_sessions
            WHERE telegram_user_id = %s
            AND created_at > NOW() - INTERVAL '10 minutes'
        """, (telegram_user_id,))
        result = db.cursor.fetchone()
        
        if result:
            code_verifier = result['code_verifier']
            # Удаляем использованный verifier
            db.cursor.execute("""
                DELETE FROM vk_pkce_sessions WHERE telegram_user_id = %s
            """, (telegram_user_id,))
            db.conn.commit()
            
            # Закрываем подключение
            db.cursor.close()
            db.conn.close()
            
            return code_verifier
            
        # Закрываем подключение если нет результата
        db.cursor.close()
        db.conn.close()
        
    except Exception as e:
        print(f"⚠️ Ошибка получения PKCE из БД: {e}")
    
    # Fallback на in-memory storage
    return _pkce_storage.pop(telegram_user_id, None)


print("✅ VK Config загружен (VK ID + PKCE)")
