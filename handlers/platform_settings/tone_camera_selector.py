"""
Tone & Camera Selector - Выбор тональности и камеры
Опциональные настройки для детальной настройки изображений
"""
import logging

logger = logging.getLogger(__name__)

from telebot import types

from loader import bot

from database.database import db

from .constants import TONE_PRESETS, CAMERA_PRESETS, PLATFORM_NAMES

from .utils import get_platform_settings, save_platform_settings



# ═══════════════════════════════════════════════════════════════
# ТОНАЛЬНОСТЬ
# ═══════════════════════════════════════════════════════════════

def show_tone_selector(call, platform_type, category_id, bot_id, platform_id='main'):
    """
    Показать интерфейс выбора тональности
    """
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    category_name = category.get('name', 'Без названия')
    settings = get_platform_settings(category, platform_type)
    current_tones = settings['tones']
    platform_name = PLATFORM_NAMES.get(platform_type, platform_type.upper())
    
    # Фильтруем только валидные тональности (которые есть в TONE_PRESETS)
    valid_tones = [tone for tone in current_tones if tone in TONE_PRESETS]
    
    # Если после фильтрации список изменился - сохраняем
    if len(valid_tones) != len(current_tones):
        print(f"⚠️  Найдены невалидные тональности! Было: {current_tones}, стало: {valid_tones}")
        current_tones = valid_tones
        save_platform_settings(db, category_id, platform_type, tones=current_tones)
    else:
        current_tones = valid_tones
    
    # Текст
    if len(current_tones) == 0:
        selected_text = "Выберите тональности (можно несколько):"
    else:
        selected_text = f"Выбрано: {len(current_tones)}"
    
    text = (
        f"🌈 <b>ТОНАЛЬНОСТЬ</b>\n\n"
        f"{selected_text}"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Кнопки тональностей по 2 в ряд
    buttons = []
    for tone_code, tone_data in TONE_PRESETS.items():
        is_selected = tone_code in current_tones
        # Название уже содержит эмодзи
        button_text = tone_data['name']
        if is_selected:
            button_text += " ✅"
        
        buttons.append(
            types.InlineKeyboardButton(
                button_text,
                callback_data=f"toggle_tone_{platform_type}_{category_id}_{bot_id}_{tone_code}"
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


def handle_toggle_tone(call, platform_type, category_id, bot_id, tone_code):
    """Переключить тональность"""
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    settings = get_platform_settings(category, platform_type)
    current_tones = settings['tones'].copy()
    
    if tone_code in current_tones:
        current_tones.remove(tone_code)
    else:
        current_tones.append(tone_code)
    
    save_platform_settings(db, category_id, platform_type, tones=current_tones)
    bot.answer_callback_query(call.id)
    show_tone_selector(call, platform_type, category_id, bot_id)


# ═══════════════════════════════════════════════════════════════
# КАМЕРА
# ═══════════════════════════════════════════════════════════════

def show_camera_selector(call, platform_type, category_id, bot_id, platform_id='main'):
    """
    Показать интерфейс выбора камеры
    """
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    category_name = category.get('name', 'Без названия')
    settings = get_platform_settings(category, platform_type)
    current_cameras = settings['cameras']
    platform_name = PLATFORM_NAMES.get(platform_type, platform_type.upper())
    
    # Фильтруем только валидные камеры (которые есть в CAMERA_PRESETS)
    valid_cameras = [cam for cam in current_cameras if cam in CAMERA_PRESETS]
    
    # Если после фильтрации список изменился - сохраняем
    if len(valid_cameras) != len(current_cameras):
        print(f"⚠️  Найдены невалидные камеры! Было: {current_cameras}, стало: {valid_cameras}")
        current_cameras = valid_cameras
        save_platform_settings(db, category_id, platform_type, cameras=current_cameras)
    else:
        current_cameras = valid_cameras
    
    # DEBUG: Выводим что в current_cameras
    logger.debug("DEBUG Camera Selector:")
    print(f"   current_cameras = {current_cameras}")
    print(f"   len = {len(current_cameras)}")
    
    # Текст
    if len(current_cameras) == 0:
        selected_text = "Выберите камеры (можно несколько):"
    else:
        selected_text = f"Выбрано: {len(current_cameras)}"
    
    text = (
        f"📷 <b>КАМЕРА</b>\n\n"
        f"{selected_text}"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Кнопки камер по 2 в ряд
    buttons = []
    for camera_code, camera_data in CAMERA_PRESETS.items():
        is_selected = camera_code in current_cameras
        # Убираем эмодзи из названия для кнопки
        camera_name = camera_data['name'].replace('📷 ', '').replace('⚡ ', '')
        # Добавляем галочку если выбрано
        button_text = f"{camera_data['name'].split()[0]} {camera_name}"
        if is_selected:
            button_text += " ✅"
        
        buttons.append(
            types.InlineKeyboardButton(
                button_text,
                callback_data=f"toggle_camera_{platform_type}_{category_id}_{bot_id}_{camera_code}"
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


def handle_toggle_camera(call, platform_type, category_id, bot_id, camera_code):
    """Переключить камеру"""
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    settings = get_platform_settings(category, platform_type)
    current_cameras = settings['cameras'].copy()
    
    if camera_code in current_cameras:
        current_cameras.remove(camera_code)
    else:
        current_cameras.append(camera_code)
    
    save_platform_settings(db, category_id, platform_type, cameras=current_cameras)
    bot.answer_callback_query(call.id)
    show_camera_selector(call, platform_type, category_id, bot_id)


def handle_save_settings(call, platform_type, category_id, bot_id):
    """Сохранение завершено - возврат к платформе"""
    text = (
        "✅ <b>НАСТРОЙКИ СОХРАНЕНЫ!</b>\n\n"
        "Все параметры генерации изображений\n"
        "успешно сохранены и будут использоваться\n"
        "при публикации контента."
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "🔙 К категории",
            callback_data=f"open_category_{category_id}"
        )
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                            reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id, "✅ Настройки сохранены!")


# ═══════════════════════════════════════════════════════════════
# РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ
# ═══════════════════════════════════════════════════════════════

# Тональность
@bot.callback_query_handler(func=lambda call: call.data.startswith("next_tone_"))
def callback_next_tone(call):
    parts = call.data.split("_")
    show_tone_selector(call, parts[2], int(parts[3]), int(parts[4]))

@bot.callback_query_handler(func=lambda call: call.data.startswith("toggle_tone_"))
def callback_toggle_tone(call):
    parts = call.data.split("_")
    # toggle_tone_pinterest_123_456_light_airy
    # parts[0] = toggle, parts[1] = tone, parts[2] = pinterest, parts[3] = 123, parts[4] = 456
    # parts[5:] = light_airy (может содержать underscore)
    platform_type = parts[2]
    category_id = int(parts[3])
    bot_id = int(parts[4])
    tone_code = "_".join(parts[5:])  # Собираем всё что после bot_id
    
    handle_toggle_tone(call, platform_type, category_id, bot_id, tone_code)

@bot.callback_query_handler(func=lambda call: call.data.startswith("tones_all_"))
def callback_tones_all(call):
    parts = call.data.split("_")
    save_platform_settings(db, int(parts[3]), parts[2], tones=list(TONE_PRESETS.keys()))
    bot.answer_callback_query(call.id, "✅ Все тональности")
    show_tone_selector(call, parts[2], int(parts[3]), int(parts[4]))

@bot.callback_query_handler(func=lambda call: call.data.startswith("tones_clear_"))
def callback_tones_clear(call):
    parts = call.data.split("_")
    save_platform_settings(db, int(parts[3]), parts[2], tones=[])
    bot.answer_callback_query(call.id, "✅ Тональность случайная")
    show_tone_selector(call, parts[2], int(parts[3]), int(parts[4]))

# Камера
@bot.callback_query_handler(func=lambda call: call.data.startswith("next_camera_"))
def callback_next_camera(call):
    parts = call.data.split("_")
    show_camera_selector(call, parts[2], int(parts[3]), int(parts[4]))

@bot.callback_query_handler(func=lambda call: call.data.startswith("toggle_camera_"))
def callback_toggle_camera(call):
    parts = call.data.split("_")
    # toggle_camera_pinterest_123_456_canon_r5
    # Собираем camera_code из всех частей после bot_id
    platform_type = parts[2]
    category_id = int(parts[3])
    bot_id = int(parts[4])
    camera_code = "_".join(parts[5:])
    
    handle_toggle_camera(call, platform_type, category_id, bot_id, camera_code)

@bot.callback_query_handler(func=lambda call: call.data.startswith("cameras_all_"))
def callback_cameras_all(call):
    parts = call.data.split("_")
    save_platform_settings(db, int(parts[3]), parts[2], cameras=list(CAMERA_PRESETS.keys()))
    bot.answer_callback_query(call.id, "✅ Все камеры")
    show_camera_selector(call, parts[2], int(parts[3]), int(parts[4]))

@bot.callback_query_handler(func=lambda call: call.data.startswith("cameras_clear_"))
def callback_cameras_clear(call):
    parts = call.data.split("_")
    save_platform_settings(db, int(parts[3]), parts[2], cameras=[])
    bot.answer_callback_query(call.id, "✅ Камера случайная")
    show_camera_selector(call, parts[2], int(parts[3]), int(parts[4]))

# Сохранение
@bot.callback_query_handler(func=lambda call: call.data.startswith("save_settings_"))
def callback_save_settings(call):
    parts = call.data.split("_")
    handle_save_settings(call, parts[2], int(parts[3]), int(parts[4]))

print("✅ platform_settings/tone_camera_selector.py загружен")
