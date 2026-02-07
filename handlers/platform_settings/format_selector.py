"""
Format Selector - Выбор форматов изображений
Множественный выбор с галочками в реальном времени
"""
from telebot import types
from loader import bot
from database.database import db
from .constants import PLATFORM_FORMATS, PLATFORM_NAMES, RECOMMENDED_FORMATS
from .utils import get_platform_settings, save_platform_settings


def show_format_selector(call, platform_type, category_id, bot_id, platform_id=None):
    """
    Показать интерфейс выбора форматов
    
    Args:
        call: callback query
        platform_type: str - pinterest/telegram/website
        category_id: int
        bot_id: int
        platform_id: str (optional) - ID платформы для возврата в подменю
    """
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    category_name = category.get('name', 'Без названия')
    
    # Получаем текущие настройки
    settings = get_platform_settings(category, platform_type)
    current_formats = settings['formats']
    
    # Если форматы пустые - выбираем формат по умолчанию
    if not current_formats or len(current_formats) == 0:
        formats = PLATFORM_FORMATS.get(platform_type, PLATFORM_FORMATS['website'])
        if formats and len(formats) > 0:
            # Для VK по умолчанию 9:16
            if platform_type == 'vk':
                # Ищем 9:16 в списке форматов
                default_format = '9:16'
                for fmt_code, fmt_name in formats:
                    if fmt_code == default_format:
                        current_formats = [default_format]
                        break
                if not current_formats:
                    current_formats = [formats[0][0]]  # Если не нашли, берём первый
            else:
                current_formats = [formats[0][0]]  # Первый формат для других платформ
            
            # Сохраняем в настройки
            settings['formats'] = current_formats
            save_platform_settings(category, platform_type, settings)
            print(f"✅ Установлен формат по умолчанию: {current_formats[0]}")
    
    # Получаем форматы для платформы
    formats = PLATFORM_FORMATS.get(platform_type, PLATFORM_FORMATS['website'])
    platform_name = PLATFORM_NAMES.get(platform_type, platform_type.upper())
    recommended = RECOMMENDED_FORMATS.get(platform_type, '16:9')
    
    # Текст
    text = (
        f"🎨 <b>ФОРМАТ ИЗОБРАЖЕНИЯ</b>\n"
        f"📱 Платформа: {platform_name}\n"
        f"📂 Категория: {category_name}\n"
        "━━━━━━━━━━━━━━\n\n"
        f"✅ Выбрано: <b>{len(current_formats)}</b> формат(ов)\n"
        f"📌 Рекомендация: <b>{recommended}</b>\n\n"
        "Выберите один или несколько форматов.\n"
        "При генерации будет случайно выбран один из них."
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Кнопки форматов (по 2 в ряд)
    buttons = []
    for format_code, format_icon in formats:
        # Проверяем выбран ли формат
        is_selected = format_code in current_formats
        
        # Формат кнопки с точкой в конце (чтобы убрать треугольник)
        if is_selected:
            button_text = f"{format_icon}✅."
        else:
            button_text = f"{format_icon}."
        
        # Формируем callback_data с platform_id если он есть
        if platform_id:
            callback_data = f"toggle_format_{platform_type}_{category_id}_{bot_id}_{platform_id}_{format_code}"
        else:
            callback_data = f"toggle_format_{platform_type}_{category_id}_{bot_id}_{format_code}"
        
        buttons.append(
            types.InlineKeyboardButton(
                button_text,
                callback_data=callback_data
            )
        )
    
    # Добавляем кнопки по 2 в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])
    
    # Кнопка назад (БЕЗ кнопок управления)
    if platform_id:
        # Возвращаемся в подменю изображений
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"platform_images_menu_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            )
        )
    else:
        # Старая логика - к категории
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"open_category_{category_id}"
            )
        )
    
    # Отправляем или редактируем
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='HTML'
        )
    except Exception:
        bot.send_message(
            call.message.chat.id,
            text,
            reply_markup=markup,
            parse_mode='HTML'
        )
    
    bot.answer_callback_query(call.id)


def handle_toggle_format(call, platform_type, category_id, bot_id, format_code, platform_id=None):
    """
    Переключить формат (добавить/удалить из списка)
    
    Args:
        call: callback query
        platform_type: str
        category_id: int
        bot_id: int
        format_code: str - например '2:3'
        platform_id: str (optional) - ID платформы
    """
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    # Получаем текущие форматы
    settings = get_platform_settings(category, platform_type)
    current_formats = settings['formats'].copy()
    
    # Переключаем формат
    if format_code in current_formats:
        current_formats.remove(format_code)
    else:
        current_formats.append(format_code)
    
    # Минимум 1 формат должен быть выбран
    if len(current_formats) == 0:
        recommended = RECOMMENDED_FORMATS.get(platform_type, '16:9')
        current_formats = [recommended]
        bot.answer_callback_query(call.id, "⚠️ Минимум 1 формат", show_alert=True)
    else:
        bot.answer_callback_query(call.id)
    
    # Сохраняем
    save_platform_settings(db, category_id, platform_type, formats=current_formats)
    
    # Обновляем интерфейс
    show_format_selector(call, platform_type, category_id, bot_id, platform_id)


def handle_formats_all(call, platform_type, category_id, bot_id, platform_id=None):
    """Выбрать все форматы"""
    formats = PLATFORM_FORMATS.get(platform_type, PLATFORM_FORMATS['website'])
    all_formats = [f[0] for f in formats]
    
    # Сохраняем
    save_platform_settings(db, category_id, platform_type, formats=all_formats)
    
    bot.answer_callback_query(call.id, "✅ Все форматы выбраны")
    
    # Обновляем интерфейс
    show_format_selector(call, platform_type, category_id, bot_id, platform_id)


def handle_formats_reset(call, platform_type, category_id, bot_id, platform_id=None):
    """Сбросить к рекомендованному"""
    recommended = RECOMMENDED_FORMATS.get(platform_type, '16:9')
    
    # Сохраняем
    save_platform_settings(db, category_id, platform_type, formats=[recommended])
    
    bot.answer_callback_query(call.id, f"✅ Сброшено к {recommended}")
    
    # Обновляем интерфейс
    show_format_selector(call, platform_type, category_id, bot_id, platform_id)


# ═══════════════════════════════════════════════════════════════
# РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_format_"))
def handle_platform_format(call):
    """Вход в выбор форматов"""
    parts = call.data.split("_")
    platform_type = parts[2]
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = "_".join(parts[5:]) if len(parts) > 5 else None
    
    show_format_selector(call, platform_type, category_id, bot_id, platform_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("toggle_format_"))
def callback_toggle_format(call):
    """Переключение формата"""
    parts = call.data.split("_")
    # toggle_format_pinterest_123_456_16:9 (без platform_id)
    # toggle_format_pinterest_123_456_https://site.com_16:9 (с platform_id)
    platform_type = parts[2]
    category_id = int(parts[3])
    bot_id = int(parts[4])
    
    # Определяем где format_code - он всегда последний
    # Форматы типа "16:9", "1:1", "2:3" и т.д.
    format_code = None
    platform_id = None
    
    # Ищем format_code в конце (содержит :)
    if len(parts) > 5:
        # Проверяем последний элемент
        last_part = parts[-1]
        if ':' in last_part or last_part in ['square', 'portrait', 'landscape']:
            format_code = last_part
            # Все что между bot_id и format_code - это platform_id
            if len(parts) > 6:
                platform_id = "_".join(parts[5:-1])
        else:
            # Нет формата в конце - значит весь остаток это format_code
            format_code = "_".join(parts[5:])
    
    handle_toggle_format(call, platform_type, category_id, bot_id, format_code, platform_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("formats_all_"))
def callback_formats_all(call):
    """Выбрать все форматы"""
    parts = call.data.split("_")
    platform_type = parts[2]
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = "_".join(parts[5:]) if len(parts) > 5 else None
    
    handle_formats_all(call, platform_type, category_id, bot_id, platform_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("formats_reset_"))
def callback_formats_reset(call):
    """Сбросить форматы"""
    parts = call.data.split("_")
    platform_type = parts[2]
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = "_".join(parts[5:]) if len(parts) > 5 else None
    
    handle_formats_reset(call, platform_type, category_id, bot_id, platform_id)


print("✅ platform_settings/format_selector.py загружен")
