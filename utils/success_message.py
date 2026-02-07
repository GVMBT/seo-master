# -*- coding: utf-8 -*-
"""
Универсальное сообщение успеха для всех платформ
"""
from telebot import types
from utils import escape_html


def send_unified_success_message(
    bot,
    chat_id: int,
    message_id: int,
    platform_type: str,
    category_name: str,
    cost: int,
    new_balance: int,
    word_count: int = 0,
    post_url: str = None,
    platform_detail: str = None,  # Топик/Доска/Страница
    category_id: int = None,
    bot_id: int = None,
    platform_id: str = None
):
    """
    Отправляет единое сообщение об успешной публикации
    
    Args:
        bot: Телеграм бот
        chat_id: ID чата
        message_id: ID сообщения для редактирования
        platform_type: Тип платформы (telegram, pinterest, vk, website)
        category_name: Название категории
        cost: Списано токенов
        new_balance: Новый баланс
        word_count: Количество слов
        post_url: URL поста
        platform_detail: Детали (Топик "Название" / Доска "Название" / и т.д.)
        category_id: ID категории (для кнопок)
        bot_id: ID бота (для кнопок)
        platform_id: ID платформы (для кнопок)
    """
    # Логируем публикацию в БД
    if category_id and bot_id:
        from database.database import db
        
        # Получаем user_id из chat_id (предполагаем что chat_id = user_id в личных сообщениях)
        user_id = chat_id
        
        db.log_publication(
            user_id=user_id,
            bot_id=bot_id,
            category_id=category_id,
            platform_type=platform_type.lower(),
            platform_id=platform_id,
            post_url=post_url,
            word_count=word_count,
            tokens_spent=cost,
            status='success'
        )
    
    # Названия платформ
    platform_names = {
        'telegram': 'TELEGRAM',
        'pinterest': 'PINTEREST',
        'vk': 'ВКОНТАКТЕ',
        'website': 'САЙТ'
    }
    
    platform_name = platform_names.get(platform_type.lower(), platform_type.upper())
    
    # Формируем текст
    text = (
        f"✅ <b>ПОСТ ОПУБЛИКОВАН В {platform_name}!</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📂 Категория: {escape_html(category_name)}\n"
        f"💳 Списано: {cost} токенов\n"
        f"💰 Баланс: {new_balance:,} токенов\n"
    )
    
    # Добавляем количество слов если есть
    if word_count > 0:
        text += f"\n📊 Слов: {word_count}\n"
    
    # Добавляем детали платформы если есть
    if platform_detail:
        text += f"📌 {platform_detail}\n"
    
    # Кнопки
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    # Кнопка "Открыть"
    if post_url:
        button_texts = {
            'telegram': '📱 Открыть пост',
            'pinterest': '📌 Открыть пин',
            'vk': '🔵 Открыть публикацию',
            'website': '🌐 Открыть статью'
        }
        button_text = button_texts.get(platform_type.lower(), '🔗 Открыть')
        markup.add(
            types.InlineKeyboardButton(
                button_text,
                url=post_url
            )
        )
    
    # Кнопка "Опубликовать ещё"
    if category_id and bot_id and platform_id:
        markup.add(
            types.InlineKeyboardButton(
                "🔄 Опубликовать ещё",
                callback_data=f"quick_publish_{platform_type}_{bot_id}_{category_id}_{platform_id}"
            )
        )
    
    # Кнопка "Назад" - возврат в "БЫСТРЫЙ ДОСТУП К ПУБЛИКАЦИЯМ"
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data="quick_publish_menu"
        )
    )
    
    # Отправляем/редактируем сообщение
    try:
        bot.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=markup,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    except Exception:
        bot.send_message(
            chat_id,
            text,
            reply_markup=markup,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
