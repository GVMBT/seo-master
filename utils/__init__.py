"""
Вспомогательные функции для бота
"""
import logging

logger = logging.getLogger(__name__)


def escape_html(text):
    """Экранирование HTML символов"""
    if not text:
        return ""
    text = str(text)
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def bold_html(text):
    """Обернуть текст в жирный HTML"""
    return f"<b>{escape_html(text)}</b>"


def safe_answer_callback(bot, call_id, text="", show_alert=False):
    """
    Безопасный ответ на callback query
    Обрабатывает ошибку "query is too old"
    
    Args:
        bot: Объект бота
        call_id: ID callback query
        text: Текст ответа
        show_alert: Показывать как alert
        
    Returns:
        bool: True если успешно, False если ошибка
    """
    try:
        bot.answer_callback_query(call_id, text, show_alert=show_alert)
        return True
    except Exception as e:
        # Игнорируем ошибку "query is too old" - это нормально для долгих операций
        error_str = str(e).lower()
        if "query is too old" in error_str or "query id is invalid" in error_str:
            logger.debug(f"Callback query устарел (это нормально для долгих операций)")
            return False
        else:
            logger.error(f"Ошибка answer_callback_query: {e}")
            return False


print("  ├─ utils/__init__.py загружен")
