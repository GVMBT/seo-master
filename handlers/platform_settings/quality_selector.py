"""
Quality Selector - Выбор уровня детализации и качества
Опциональные настройки для детальной настройки изображений
"""
from telebot import types
from loader import bot
from database.database import db
from .constants import QUALITY_PRESETS, PLATFORM_NAMES
from .utils import get_platform_settings, save_platform_settings


# ═══════════════════════════════════════════════════════════════
# КАЧЕСТВО И ДЕТАЛИЗАЦИЯ
# ═══════════════════════════════════════════════════════════════

def show_quality_selector(call, platform_type, category_id, bot_id, platform_id='main'):
    """
    Показать интерфейс выбора качества и детализации
    """
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    category_name = category.get('name', 'Без названия')
    settings = get_platform_settings(category, platform_type)
    current_quality = settings['quality']
    platform_name = PLATFORM_NAMES.get(platform_type, platform_type.upper())
    
    # Фильтруем только валидные параметры качества (которые есть в QUALITY_PRESETS)
    valid_quality = [q for q in current_quality if q in QUALITY_PRESETS]
    
    # Если после фильтрации список изменился - сохраняем
    if len(valid_quality) != len(current_quality):
        print(f"⚠️  Найдены невалидные параметры качества! Было: {current_quality}, стало: {valid_quality}")
        current_quality = valid_quality
        save_platform_settings(db, category_id, platform_type, quality=current_quality)
    else:
        current_quality = valid_quality
    
    # Текст
    if len(current_quality) == 0:
        selected_text = "Выберите уровни качества (можно несколько):"
    else:
        selected_text = f"Выбрано: {len(current_quality)}"
    
    text = (
        f"💎 <b>КАЧЕСТВО</b>\n\n"
        f"{selected_text}\n"
        f"⚠️ <i>ВСЕ выбранные параметры будут применены одновременно</i>"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Кнопки качества по 2 в ряд
    buttons = []
    for quality_code, quality_data in QUALITY_PRESETS.items():
        is_selected = quality_code in current_quality
        # Название уже содержит эмодзи
        button_text = quality_data['name']
        if is_selected:
            button_text += " ✅"
        
        buttons.append(
            types.InlineKeyboardButton(
                button_text,
                callback_data=f"toggle_quality_{platform_type}_{category_id}_{bot_id}_{quality_code}"
            )
        )
    
    # Добавляем кнопки по 2 в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])
    
    # Только кнопка "Назад"
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_images_menu_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        )
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                            reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


def handle_toggle_quality(call, platform_type, category_id, bot_id, quality_code):
    """Переключить уровень качества"""
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    settings = get_platform_settings(category, platform_type)
    current_quality = settings['quality'].copy() if settings['quality'] else []
    
    # Переключаем
    if quality_code in current_quality:
        current_quality.remove(quality_code)
    else:
        current_quality.append(quality_code)
    
    # Сохраняем
    save_platform_settings(db, category_id, platform_type, quality=current_quality)
    
    # Обновляем интерфейс
    show_quality_selector(call, platform_type, category_id, bot_id)


def handle_quality_all(call, platform_type, category_id, bot_id):
    """Выбрать все уровни качества"""
    all_quality = list(QUALITY_PRESETS.keys())
    save_platform_settings(db, category_id, platform_type, quality=all_quality)
    show_quality_selector(call, platform_type, category_id, bot_id)


def handle_quality_clear(call, platform_type, category_id, bot_id):
    """Очистить выбор качества"""
    save_platform_settings(db, category_id, platform_type, quality=[])
    show_quality_selector(call, platform_type, category_id, bot_id)


def register_quality_handlers(bot_instance):
    """Регистрация обработчиков для выбора качества"""
    
    @bot_instance.callback_query_handler(func=lambda call: call.data.startswith('next_quality_'))
    def handle_next_quality(call):
        parts = call.data.split('_')
        platform_type = parts[2]
        category_id = int(parts[3])
        bot_id = int(parts[4])
        show_quality_selector(call, platform_type, category_id, bot_id)
    
    @bot_instance.callback_query_handler(func=lambda call: call.data.startswith('toggle_quality_'))
    def handle_toggle(call):
        parts = call.data.split('_')
        # toggle_quality_pinterest_123_456_ultra_quality
        # Собираем quality_code из всех частей после bot_id
        platform_type = parts[2]
        category_id = int(parts[3])
        bot_id = int(parts[4])
        quality_code = "_".join(parts[5:])  # Собираем всё что после bot_id
        handle_toggle_quality(call, platform_type, category_id, bot_id, quality_code)
    
    @bot_instance.callback_query_handler(func=lambda call: call.data.startswith('quality_all_'))
    def handle_all(call):
        parts = call.data.split('_')
        platform_type = parts[2]
        category_id = int(parts[3])
        bot_id = int(parts[4])
        handle_quality_all(call, platform_type, category_id, bot_id)
    
    @bot_instance.callback_query_handler(func=lambda call: call.data.startswith('quality_clear_'))
    def handle_clear(call):
        parts = call.data.split('_')
        platform_type = parts[2]
        category_id = int(parts[3])
        bot_id = int(parts[4])
        handle_quality_clear(call, platform_type, category_id, bot_id)
    
    print("  ├─ quality_selector.py загружен")


print("✅ platform_settings/quality_selector.py загружен")
