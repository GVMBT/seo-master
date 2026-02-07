"""
Angle Selector - Выбор ракурса/угла обзора
Опциональные настройки для детальной настройки изображений
"""
from telebot import types
from loader import bot
from database.database import db
from .constants import ANGLE_PRESETS, PLATFORM_NAMES
from .utils import get_platform_settings, save_platform_settings


# ═══════════════════════════════════════════════════════════════
# РАКУРСЫ
# ═══════════════════════════════════════════════════════════════

def show_angle_selector(call, platform_type, category_id, bot_id, platform_id='main'):
    """
    Показать интерфейс выбора ракурса
    """
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    category_name = category.get('name', 'Без названия')
    settings = get_platform_settings(category, platform_type)
    current_angles = settings['angles']
    platform_name = PLATFORM_NAMES.get(platform_type, platform_type.upper())
    
    # Фильтруем только валидные ракурсы (которые есть в ANGLE_PRESETS)
    valid_angles = [angle for angle in current_angles if angle in ANGLE_PRESETS]
    
    # Если после фильтрации список изменился - сохраняем
    if len(valid_angles) != len(current_angles):
        print(f"⚠️  Найдены невалидные ракурсы! Было: {current_angles}, стало: {valid_angles}")
        current_angles = valid_angles
        save_platform_settings(db, category_id, platform_type, angles=current_angles)
    else:
        current_angles = valid_angles
    
    # Текст
    if len(current_angles) == 0:
        selected_text = "Выберите ракурсы (можно несколько):"
    else:
        selected_text = f"Выбрано: {len(current_angles)}"
    
    text = (
        f"📐 <b>РАКУРС</b>\n\n"
        f"{selected_text}"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Кнопки ракурсов по 2 в ряд
    buttons = []
    for angle_code, angle_data in ANGLE_PRESETS.items():
        is_selected = angle_code in current_angles
        # Название уже содержит эмодзи
        button_text = angle_data['name']
        if is_selected:
            button_text += " ✅"
        
        buttons.append(
            types.InlineKeyboardButton(
                button_text,
                callback_data=f"toggle_angle_{platform_type}_{category_id}_{bot_id}_{angle_code}"
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


def handle_toggle_angle(call, platform_type, category_id, bot_id, angle_code):
    """Переключить ракурс"""
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    settings = get_platform_settings(category, platform_type)
    current_angles = settings['angles'].copy() if settings['angles'] else []
    
    # Переключаем
    if angle_code in current_angles:
        current_angles.remove(angle_code)
    else:
        current_angles.append(angle_code)
    
    # Сохраняем
    save_platform_settings(db, category_id, platform_type, angles=current_angles)
    
    # Обновляем интерфейс
    show_angle_selector(call, platform_type, category_id, bot_id)


def handle_angles_all(call, platform_type, category_id, bot_id):
    """Выбрать все ракурсы"""
    all_angles = list(ANGLE_PRESETS.keys())
    save_platform_settings(db, category_id, platform_type, angles=all_angles)
    show_angle_selector(call, platform_type, category_id, bot_id)


def handle_angles_clear(call, platform_type, category_id, bot_id):
    """Очистить выбор ракурсов"""
    save_platform_settings(db, category_id, platform_type, angles=[])
    show_angle_selector(call, platform_type, category_id, bot_id)


def register_angle_handlers(bot_instance):
    """Регистрация обработчиков для выбора ракурсов"""
    
    @bot_instance.callback_query_handler(func=lambda call: call.data.startswith('next_angle_'))
    def handle_next_angle(call):
        parts = call.data.split('_')
        platform_type = parts[2]
        category_id = int(parts[3])
        bot_id = int(parts[4])
        show_angle_selector(call, platform_type, category_id, bot_id)
    
    @bot_instance.callback_query_handler(func=lambda call: call.data.startswith('toggle_angle_'))
    def handle_toggle(call):
        parts = call.data.split('_')
        # toggle_angle_pinterest_123_456_close_up
        # Собираем angle_code из всех частей после bot_id
        platform_type = parts[2]
        category_id = int(parts[3])
        bot_id = int(parts[4])
        angle_code = "_".join(parts[5:])  # Собираем всё что после bot_id
        handle_toggle_angle(call, platform_type, category_id, bot_id, angle_code)
    
    @bot_instance.callback_query_handler(func=lambda call: call.data.startswith('angles_all_'))
    def handle_all(call):
        parts = call.data.split('_')
        platform_type = parts[2]
        category_id = int(parts[3])
        bot_id = int(parts[4])
        handle_angles_all(call, platform_type, category_id, bot_id)
    
    @bot_instance.callback_query_handler(func=lambda call: call.data.startswith('angles_clear_'))
    def handle_clear(call):
        parts = call.data.split('_')
        platform_type = parts[2]
        category_id = int(parts[3])
        bot_id = int(parts[4])
        handle_angles_clear(call, platform_type, category_id, bot_id)
    
    print("  ├─ angle_selector.py загружен")


print("✅ platform_settings/angle_selector.py загружен")
