# -*- coding: utf-8 -*-
"""
Селектор настроек текста на изображении и коллажей
"""
from telebot import types
from loader import bot, db
from utils import escape_html
from .constants import TEXT_ON_IMAGE_PRESETS, COLLAGE_PRESETS, TEXT_STYLES_DESCRIPTION, COLLAGE_DESCRIPTION
from .utils import get_platform_settings, save_platform_settings


# ═══════════════════════════════════════════════════════════════
# ТЕКСТ НА ИЗОБРАЖЕНИИ
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("next_text_percent_"))
def handle_next_text_percent(call):
    """Обработчик для next_text_percent_ (из images_menu)"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    
    show_text_percent_menu(call, platform_type, category_id, bot_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_text_percent_"))
def handle_text_percent_selector(call):
    """
    Меню выбора процента текста на изображениях
    
    📝 Инструкция:
    1. Выберите процент изображений с текстом
    2. 0% = текст никогда не добавляется
    3. 100% = текст на всех изображениях
    4. Текст выглядит как журнальные заголовки
    """
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_type = parts[5]
    platform_id = parts[6]
    
    show_text_percent_menu(call, platform_type, category_id, bot_id, platform_id)


def show_text_percent_menu(call, platform_type, category_id, bot_id, platform_id='main'):
    """Показать меню выбора процента текста"""
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    # Получаем текущие настройки
    settings = get_platform_settings(category, platform_type)
    current_percent = settings.get('text_percent', '0')
    
    text = (
        f"📝 <b>ТЕКСТ НА ФОТО</b>\n\n"
        f"Текущее: {current_percent}%\n"
        f"Выберите процент покрытия:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=5)
    
    # Кнопки процентов в одну строку: 0%, 25%, 50%, 75%, 100%
    percents = ['0', '25', '50', '75', '100']
    buttons = []
    
    for percent in percents:
        if percent == current_percent:
            label = f"{percent}% ✅"
        else:
            label = f"{percent}%"
        
        buttons.append(
            types.InlineKeyboardButton(
                label,
                callback_data=f"set_text_percent_{platform_type}_{category_id}_{bot_id}_{percent}"
            )
        )
    
    markup.row(*buttons)
    
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_images_menu_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        )
    )
    
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='HTML'
        )
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_text_percent_"))
def handle_set_text_percent(call):
    """
    Сохранение процента текста на изображениях
    
    📝 Инструкция:
    Эта функция автоматически сохраняет выбранный процент
    и возвращает в меню настроек
    """
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    percent = parts[6]
    
    # Сохраняем настройку
    save_platform_settings(db, category_id, platform_type, text_percent=percent)
    
    bot.answer_callback_query(
        call.id,
        f"✅ Установлено: {percent}%"
    )
    
    # Возвращаемся в меню текста
    call.data = f"next_text_percent_{platform_type}_{category_id}_{bot_id}"
    handle_next_text_percent(call)


# ═══════════════════════════════════════════════════════════════
# КОЛЛАЖ ИЛИ ЦЕЛЬНОЕ ИЗОБРАЖЕНИЕ
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("next_collage_percent_"))
def handle_next_collage_percent(call):
    """Обработчик для next_collage_percent_ (из images_menu)"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    
    show_collage_percent_menu(call, platform_type, category_id, bot_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_collage_percent_"))
def handle_collage_percent_selector(call):
    """
    Меню выбора процента коллажей
    
    🎨 Инструкция:
    1. Выберите процент изображений-коллажей
    2. 0% = всегда цельное изображение
    3. 100% = всегда коллаж
    4. Коллаж = несколько элементов на одном фото
    """
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_type = parts[5]
    platform_id = parts[6]
    
    show_collage_percent_menu(call, platform_type, category_id, bot_id, platform_id)


def show_collage_percent_menu(call, platform_type, category_id, bot_id, platform_id='main'):
    """Показать меню выбора процента коллажей"""
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    # Получаем текущие настройки
    settings = get_platform_settings(category, platform_type)
    current_percent = settings.get('collage_percent', '0')
    
    text = (
        f"🖼 <b>КОЛЛАЖ ФОТО</b>\n\n"
        f"Текущее: {current_percent}%\n"
        f"Выберите процент покрытия:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=5)
    
    # Кнопки процентов в одну строку: 0%, 25%, 50%, 75%, 100%
    percents = ['0', '25', '50', '75', '100']
    buttons = []
    
    for percent in percents:
        if percent == current_percent:
            label = f"{percent}% ✅"
        else:
            label = f"{percent}%"
        
        buttons.append(
            types.InlineKeyboardButton(
                label,
                callback_data=f"set_collage_percent_{platform_type}_{category_id}_{bot_id}_{percent}"
            )
        )
    
    markup.row(*buttons)
    
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_images_menu_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        )
    )
    
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='HTML'
        )
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_collage_percent_"))
def handle_set_collage_percent(call):
    """
    Сохранение процента коллажей
    
    🎨 Инструкция:
    Эта функция автоматически сохраняет выбранный процент
    и возвращает в меню настроек
    """
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    percent = parts[6]
    
    # Сохраняем настройку
    save_platform_settings(db, category_id, platform_type, collage_percent=percent)
    
    bot.answer_callback_query(
        call.id,
        f"✅ Установлено: {percent}%"
    )
    
    # Возвращаемся в меню коллажей
    call.data = f"next_collage_percent_{platform_type}_{category_id}_{bot_id}"
    handle_next_collage_percent(call)


print("✅ platform_settings/text_collage_selector.py загружен")
