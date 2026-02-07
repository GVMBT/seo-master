# -*- coding: utf-8 -*-
"""
Обработчики расширенных настроек изображений для Website
next_style_, next_text_percent_, next_collage_percent_, next_camera_, next_angle_, next_quality_, next_tone_
"""
from telebot import types
from loader import bot, db
from handlers.website.image_advanced_settings import (
    get_user_advanced_params, save_user_advanced_params,
    IMAGE_STYLES, CAMERAS, ANGLES, QUALITY_LEVELS, TONES
)


# ============================================================
# СТИЛЬ ИЗОБРАЖЕНИЯ
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("next_style_website_"))
def handle_next_style(call):
    """Меню выбора стиля изображений"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    user_id = call.from_user.id
    
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    params = get_user_advanced_params(user_id, category_id)
    current_styles = params.get('styles', [])
    
    text = (
        f"🎨 <b>СТИЛЬ ИЗОБРАЖЕНИЯ</b>\n\n"
        f"Выбрано: {len(current_styles)}\n"
        f"Выберите стили (можно несколько):"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for style_id, style_name in IMAGE_STYLES.items():
        is_selected = style_id in current_styles
        checkmark = " ✅" if is_selected else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{style_name}{checkmark}",
                callback_data=f"ws_toggle_style_{category_id}_{bot_id}_{style_id}"
            )
        )
    
    # По 2 в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])
    
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"platform_format_website_{category_id}_{bot_id}")
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


# ============================================================
# ТЕКСТ НА ФОТО
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("next_text_percent_website_"))
def handle_next_text_percent(call):
    """Меню настройки текста на фото"""
    parts = call.data.split("_")
    category_id = int(parts[4])
    bot_id = int(parts[5])
    user_id = call.from_user.id
    
    params = get_user_advanced_params(user_id, category_id)
    current_text = params.get('text_on_image', 0)
    
    text = (
        f"📝 <b>ТЕКСТ НА ФОТО</b>\n\n"
        f"Текущее: {current_text}%\n"
        f"Выберите процент покрытия:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=5)
    percentages = [0, 25, 50, 75, 100]
    buttons = []
    for perc in percentages:
        checkmark = " ✅" if perc == current_text else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{perc}%{checkmark}",
                callback_data=f"ws_set_text_{category_id}_{bot_id}_{perc}"
            )
        )
    
    markup.row(*buttons)
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"platform_format_website_{category_id}_{bot_id}")
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


# ============================================================
# КОЛЛАЖ ФОТО
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("next_collage_percent_website_"))
def handle_next_collage_percent(call):
    """Меню настройки коллажа фото"""
    parts = call.data.split("_")
    category_id = int(parts[4])
    bot_id = int(parts[5])
    user_id = call.from_user.id
    
    params = get_user_advanced_params(user_id, category_id)
    current_collage = params.get('collage_mode', 0)
    
    text = (
        f"🖼 <b>КОЛЛАЖ ФОТО</b>\n\n"
        f"Текущее: {current_collage}%\n"
        f"Выберите вероятность коллажа:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=5)
    percentages = [0, 25, 50, 75, 100]
    buttons = []
    for perc in percentages:
        checkmark = " ✅" if perc == current_collage else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{perc}%{checkmark}",
                callback_data=f"ws_set_collage_{category_id}_{bot_id}_{perc}"
            )
        )
    
    markup.row(*buttons)
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"platform_format_website_{category_id}_{bot_id}")
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_set_collage_"))
def handle_set_collage(call):
    """Установка коллажа"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    perc = int(parts[5])
    user_id = call.from_user.id
    
    params = get_user_advanced_params(user_id, category_id)
    params['collage_mode'] = perc
    save_user_advanced_params(user_id, category_id, params)
    
    bot.answer_callback_query(call.id, f"✅ Установлено: {perc}%")
    call.data = f"next_collage_percent_website_{category_id}_{bot_id}"
    handle_next_collage_percent(call)


# ============================================================
# КАМЕРА
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("next_camera_website_"))
def handle_next_camera(call):
    """Меню выбора камеры"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    user_id = call.from_user.id
    
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    params = get_user_advanced_params(user_id, category_id)
    current_cameras = params.get('cameras', [])
    
    text = (
        f"📷 <b>КАМЕРА</b>\n\n"
        f"Выбрано: {len(current_cameras)}\n"
        f"Выберите камеры (можно несколько):"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for camera_id, camera_name in CAMERAS.items():
        is_selected = camera_id in current_cameras
        checkmark = " ✅" if is_selected else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{camera_name}{checkmark}",
                callback_data=f"ws_toggle_camera_{category_id}_{bot_id}_{camera_id}"
            )
        )
    
    # По 2 в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])
    
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"platform_format_website_{category_id}_{bot_id}")
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_toggle_camera_"))
def handle_toggle_camera(call):
    """Toggle камеры"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    camera_id = "_".join(parts[5:])
    user_id = call.from_user.id
    
    params = get_user_advanced_params(user_id, category_id)
    current_cameras = params.get('cameras', [])
    
    if camera_id in current_cameras:
        current_cameras.remove(camera_id)
    else:
        current_cameras.append(camera_id)
    
    params['cameras'] = current_cameras
    save_user_advanced_params(user_id, category_id, params)
    
    bot.answer_callback_query(call.id, f"✅ {CAMERAS[camera_id]}")
    call.data = f"next_camera_website_{category_id}_{bot_id}"
    handle_next_camera(call)


# ============================================================
# РАКУРС
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("next_angle_website_"))
def handle_next_angle(call):
    """Меню выбора ракурса"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    user_id = call.from_user.id
    
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    params = get_user_advanced_params(user_id, category_id)
    current_angles = params.get('angles', [])
    
    text = (
        f"📐 <b>РАКУРС</b>\n\n"
        f"Выбрано: {len(current_angles)}\n"
        f"Выберите ракурсы (можно несколько):"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for angle_id, angle_name in ANGLES.items():
        is_selected = angle_id in current_angles
        checkmark = " ✅" if is_selected else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{angle_name}{checkmark}",
                callback_data=f"ws_toggle_angle_{category_id}_{bot_id}_{angle_id}"
            )
        )
    
    # По 2 в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])
    
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"platform_format_website_{category_id}_{bot_id}")
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_toggle_angle_"))
def handle_toggle_angle(call):
    """Toggle ракурса"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    angle_id = "_".join(parts[5:])
    user_id = call.from_user.id
    
    params = get_user_advanced_params(user_id, category_id)
    current_angles = params.get('angles', [])
    
    if angle_id in current_angles:
        current_angles.remove(angle_id)
    else:
        current_angles.append(angle_id)
    
    params['angles'] = current_angles
    save_user_advanced_params(user_id, category_id, params)
    
    bot.answer_callback_query(call.id, f"✅ {ANGLES[angle_id]}")
    call.data = f"next_angle_website_{category_id}_{bot_id}"
    handle_next_angle(call)


# ============================================================
# КАЧЕСТВО
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("next_quality_website_"))
def handle_next_quality(call):
    """Меню выбора качества"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    user_id = call.from_user.id
    
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    params = get_user_advanced_params(user_id, category_id)
    current_quality = params.get('quality', [])
    
    text = (
        f"💎 <b>КАЧЕСТВО</b>\n\n"
        f"Выбрано: {len(current_quality)}\n"
        f"Выберите уровни качества (можно несколько):"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for quality_id, quality_name in QUALITY_LEVELS.items():
        is_selected = quality_id in current_quality
        checkmark = " ✅" if is_selected else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{quality_name}{checkmark}",
                callback_data=f"ws_toggle_quality_{category_id}_{bot_id}_{quality_id}"
            )
        )
    
    # По 2 в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])
    
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"platform_format_website_{category_id}_{bot_id}")
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_toggle_quality_"))
def handle_toggle_quality(call):
    """Toggle качества"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    quality_id = "_".join(parts[5:])
    user_id = call.from_user.id
    
    params = get_user_advanced_params(user_id, category_id)
    current_quality = params.get('quality', [])
    
    if quality_id in current_quality:
        current_quality.remove(quality_id)
    else:
        current_quality.append(quality_id)
    
    params['quality'] = current_quality
    save_user_advanced_params(user_id, category_id, params)
    
    bot.answer_callback_query(call.id, f"✅ {QUALITY_LEVELS[quality_id]}")
    call.data = f"next_quality_website_{category_id}_{bot_id}"
    handle_next_quality(call)


# ============================================================
# ТОНАЛЬНОСТЬ
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("next_tone_website_"))
def handle_next_tone(call):
    """Меню выбора тональности"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    user_id = call.from_user.id
    
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    params = get_user_advanced_params(user_id, category_id)
    current_tones = params.get('tones', [])
    
    text = (
        f"🌈 <b>ТОНАЛЬНОСТЬ</b>\n\n"
        f"Выбрано: {len(current_tones)}\n"
        f"Выберите тональности (можно несколько):"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for tone_id, tone_name in TONES.items():
        is_selected = tone_id in current_tones
        checkmark = " ✅" if is_selected else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{tone_name}{checkmark}",
                callback_data=f"ws_toggle_tone_{category_id}_{bot_id}_{tone_id}"
            )
        )
    
    # По 2 в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])
    
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"platform_format_website_{category_id}_{bot_id}")
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_toggle_tone_"))
def handle_toggle_tone(call):
    """Toggle тональности"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    tone_id = parts[5]
    user_id = call.from_user.id
    
    params = get_user_advanced_params(user_id, category_id)
    current_tones = params.get('tones', [])
    
    if tone_id in current_tones:
        current_tones.remove(tone_id)
    else:
        current_tones.append(tone_id)
    
    params['tones'] = current_tones
    save_user_advanced_params(user_id, category_id, params)
    
    bot.answer_callback_query(call.id, f"✅ {TONES[tone_id]}")
    call.data = f"next_tone_website_{category_id}_{bot_id}"
    handle_next_tone(call)


print("✅ handlers/website/image_settings_handlers.py загружен")
