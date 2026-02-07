# -*- coding: utf-8 -*-
"""
Reporter для автопостинга
Отправка отчетов пользователям об успешных публикациях и ошибках
"""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def send_success_report(
    user_id: int,
    category_id: int,
    platform_type: str,
    platform_id: str,
    post_url: Optional[str] = None
) -> bool:
    """
    Отправляет отчет об успешной публикации
    
    Args:
        user_id: ID пользователя
        category_id: ID категории
        platform_type: Тип платформы (website, telegram, pinterest, vk)
        platform_id: ID платформы
        post_url: URL опубликованного поста (опционально)
        
    Returns:
        bool: True если отчет отправлен успешно
    """
    try:
        from loader import bot
        from database.database import db
        
        # Получаем данные категории
        category = db.get_category(category_id)
        category_name = category.get('name', 'Unknown') if category else 'Unknown'
        
        # Названия платформ с эмодзи
        platform_names = {
            'website': '🌐 Website',
            'telegram': '📱 Telegram',
            'pinterest': '📌 Pinterest',
            'vk': '🔵 VK'
        }
        platform_display = platform_names.get(platform_type, platform_type)
        
        current_time = datetime.now().strftime("%H:%M:%S")
        
        # Формируем сообщение
        text = (
            f"✅ <b>ПУБЛИКАЦИЯ УСПЕШНА</b>\n\n"
            f"🕐 Время: {current_time}\n"
            f"📂 Категория: <b>{category_name}</b>\n"
            f"📱 Платформа: {platform_display}\n"
        )
        
        if post_url:
            text += f"\n🔗 <a href='{post_url}'>Открыть публикацию</a>"
        
        text += "\n\n💰 Токены списаны успешно"
        
        # Добавляем кнопки
        from telebot import types
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "📅 Планировщик",
                callback_data=f"global_scheduler_{category_id}"
            )
        )
        
        # Отправляем сообщение
        bot.send_message(
            user_id,
            text,
            parse_mode='HTML',
            reply_markup=markup,
            disable_web_page_preview=True
        )
        
        logger.info(f"📧 Отчет об успехе отправлен user_id={user_id}, platform={platform_type}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки отчета об успехе: {e}")
        import traceback
        traceback.print_exc()
        return False


def send_error_report(
    user_id: int,
    category_id: int,
    platform_type: str,
    platform_id: str,
    error_message: str,
    tokens_refunded: bool = True
) -> bool:
    """
    Отправляет отчет об ошибке публикации
    
    Args:
        user_id: ID пользователя
        category_id: ID категории
        platform_type: Тип платформы
        platform_id: ID платформы
        error_message: Текст ошибки
        tokens_refunded: Были ли возвращены токены
        
    Returns:
        bool: True если отчет отправлен успешно
    """
    try:
        from loader import bot
        from database.database import db
        
        # Получаем данные категории
        category = db.get_category(category_id)
        category_name = category.get('name', 'Unknown') if category else 'Unknown'
        
        # Названия платформ с эмодзи
        platform_names = {
            'website': '🌐 Website',
            'telegram': '📱 Telegram',
            'pinterest': '📌 Pinterest',
            'vk': '🔵 VK'
        }
        platform_display = platform_names.get(platform_type, platform_type)
        
        current_time = datetime.now().strftime("%H:%M:%S")
        
        # Формируем сообщение
        text = (
            f"❌ <b>ОШИБКА АВТОПУБЛИКАЦИИ</b>\n\n"
            f"🕐 Время: {current_time}\n"
            f"📂 Категория: <b>{category_name}</b>\n"
            f"📱 Платформа: {platform_display}\n\n"
            f"⚠️ <b>Причина:</b>\n"
            f"<code>{error_message}</code>\n\n"
        )
        
        if tokens_refunded:
            text += f"💰 <b>Токены возвращены</b> - списания не произошло\n\n"
        else:
            text += f"⚠️ <b>Внимание:</b> токены могли быть списаны\n\n"
        
        text += (
            f"💡 <b>Что делать:</b>\n"
            f"• Проверьте настройки подключения платформы\n"
            f"• Убедитесь что токены доступа актуальны\n"
            f"• Проверьте ваш баланс токенов\n"
            f"• Попробуйте опубликовать вручную"
        )
        
        # Добавляем кнопки
        from telebot import types
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(
                "📅 Планировщик",
                callback_data=f"global_scheduler_{category_id}"
            ),
            types.InlineKeyboardButton(
                "⚙️ Настройки",
                callback_data="settings_main"
            )
        )
        
        # Отправляем сообщение
        bot.send_message(
            user_id,
            text,
            parse_mode='HTML',
            reply_markup=markup,
            disable_web_page_preview=True
        )
        
        logger.info(f"📧 Отчет об ошибке отправлен user_id={user_id}, platform={platform_type}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки отчета об ошибке: {e}")
        import traceback
        traceback.print_exc()
        return False


# Экспортируем функции
__all__ = [
    'send_success_report',
    'send_error_report'
]
