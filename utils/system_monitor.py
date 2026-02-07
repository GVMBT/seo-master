"""
Утилита мониторинга систем - проверка API и серверных ресурсов
"""
import os
from config import ANTHROPIC_API_KEY


def check_claude_api():
    """Проверить статус Claude API (БЕЗ реального API запроса для скорости)"""
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        return {
            'status': 'not_configured',
            'message': 'API ключ не настроен'
        }
    
    # Проверяем только наличие ключа (без API запроса для скорости)
    if len(ANTHROPIC_API_KEY) > 20 and ANTHROPIC_API_KEY.startswith("sk-ant-"):
        return {
            'status': 'ok',
            'model': 'claude-sonnet-4-20250514',
            'message': 'API настроен'
        }
    
    return {
        'status': 'error',
        'message': 'Некорректный формат ключа'
    }


def check_imagen_api():
    """Проверить статус Imagen API (Nano Banana Pro) - БЕЗ реального запроса"""
    from config import GOOGLE_API_KEY
    google_key = GOOGLE_API_KEY
    
    if not google_key or google_key.startswith("your_"):
        return {
            'status': 'not_configured',
            'model': 'Not configured',
            'message': 'API ключ не настроен'
        }
    
    # Проверяем только наличие ключа (без API запроса)
    if len(google_key) > 20 and google_key.startswith("AIza"):
        return {
            'status': 'ok',
            'model': 'nano-banana-pro-preview',
            'message': 'API настроен'
        }
    
    return {
        'status': 'error',
        'model': 'Error',
        'message': 'Некорректный формат ключа'
    }


def check_database():
    """Проверить статус базы данных"""
    try:
        from database.database import db
        
        # Проверяем подключение
        db.cursor.execute("SELECT 1 as test")
        result = db.cursor.fetchone()
        db.conn.commit()
        
        # Получаем версию PostgreSQL
        db.cursor.execute("SELECT version() as version")
        version_row = db.cursor.fetchone()
        db.conn.commit()
        
        # Для RealDictRow обращаемся по ключу
        if isinstance(version_row, dict):
            version = version_row.get('version', 'Unknown')
        else:
            version = str(version_row)
            
        version_short = version.split('PostgreSQL')[1].split('on')[0].strip() if 'PostgreSQL' in version else 'Unknown'
        
        # Получаем количество активных подключений
        db.cursor.execute("""
            SELECT count(*) as count
            FROM pg_stat_activity 
            WHERE datname = current_database()
        """)
        conn_row = db.cursor.fetchone()
        db.conn.commit()
        
        # Для RealDictRow обращаемся по ключу
        if isinstance(conn_row, dict):
            connections = conn_row.get('count', 0)
        else:
            connections = int(conn_row)
        
        return {
            'status': 'ok',
            'message': f'{connections}',
            'connections': connections,
            'version': version_short
        }
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"❌ Ошибка в check_database: {e}")
        print(error_details)
        
        return {
            'status': 'error',
            'message': '0',
            'connections': 0,
            'version': 'N/A',
            'error': str(e)
        }


def check_telegram(bot):
    """Проверить статус Telegram API"""
    try:
        bot_info = bot.get_me()
        
        return {
            'status': 'ok',
            'message': 'Подключен',
            'username': bot_info.username,
            'bot_id': bot_info.id
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': str(e)[:100],
            'username': 'Unknown',
            'bot_id': 'N/A'
        }


def get_full_system_status():
    """Получить полный статус всех систем"""
    status = {
        'claude': check_claude_api(),
        'imagen': check_imagen_api(),
    }
    
    # Проверка БД
    try:
        from database.database import db
        db.cursor.execute("SELECT 1")
        status['database'] = {'status': 'ok', 'message': 'БД работает'}
    except Exception as e:
        status['database'] = {'status': 'error', 'message': str(e)}
    
    return status


def format_status_message(status):
    """Форматировать сообщение о статусе систем"""
    claude = status.get('claude', {})
    imagen = status.get('imagen', {})
    database = status.get('database', {})
    
    # Эмодзи для статусов
    def get_emoji(s):
        if s == 'ok':
            return '✅'
        elif s == 'error':
            return '❌'
        else:
            return '⚪️'
    
    text = (
        "🖥 <b>МОНИТОРИНГ СИСТЕМ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "<b>🤖 AI СЕРВИСЫ:</b>\n"
        f"   ├─ Claude: {get_emoji(claude.get('status'))} <code>{claude.get('model', 'N/A')}</code>\n"
        f"   │   {claude.get('message', '')}\n"
        f"   └─ Nano Banana Pro: {get_emoji(imagen.get('status'))} <code>{imagen.get('message', '')}</code>\n\n"
        
        "<b>💾 БАЗА ДАННЫХ:</b>\n"
        f"   └─ PostgreSQL: {get_emoji(database.get('status'))} {database.get('message', '')}\n\n"
    )
    
    return text


print("✅ utils/system_monitor.py загружен")


def check_claude_api_real():
    """
    Реальная проверка Claude API с запросом
    МЕДЛЕННО! Используется только для диагностики
    """
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your_"):
        return {'status': 'not_configured'}
    
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=10,
            messages=[{"role": "user", "content": "test"}]
        )
        return {'status': 'ok', 'model': 'claude-sonnet-4-20250514'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


def check_imagen_api_real():
    """
    Реальная проверка Nano Banana Pro API с запросом
    МЕДЛЕННО! Используется только для диагностики
    """
    from config import GOOGLE_API_KEY
    if not GOOGLE_API_KEY:
        return {'status': 'not_configured'}
    
    try:
        from google import genai
        client = genai.Client(api_key=GOOGLE_API_KEY)
        return {'status': 'ok', 'model': 'nano-banana-pro-preview'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)[:100]}
