# -*- coding: utf-8 -*-
"""
Расширенные настройки изображений для Website
Включает: стиль, количество, текст на фото, коллаж, камера, ракурс, качество, тональность
"""
from telebot import types
from loader import bot, db

# Хранилище для параметров (общее с article_generation)
from handlers.website.article_generation import article_params_storage

# Константы
IMAGE_STYLES = {
    'photorealistic': '📸 Фотореалистичный',
    'anime': '🎌 Аниме',
    'oil_painting': '🎨 Масляная живопись',
    'watercolor': '🖌 Акварель',
    'cartoon': '🎭 Мультяшный',
    'sketch': '✏️ Набросок',
    '3d_render': '🎬 3D рендер',
    'pixel_art': '🕹 Пиксель-арт',
    'minimalism': '⚪️ Минимализм',
    'cyberpunk': '🌃 Киберпанк'
}

CAMERAS = {
    'canon_eos_r5': '📷 Canon EOS R5',
    'nikon_z9': '📸 Nikon Z9',
    'sony_a7r_iv': '📹 Sony A7R IV',
    'fujifilm_xt4': '🎥 Fujifilm X-T4',
    'leica_q2': '🎞 Leica Q2',
    'hasselblad_x1d': '🎬 Hasselblad X1D',
    'phase_one_xf': '🖼 Phase One XF',
    'pentax_645z': '📽 Pentax 645Z',
    'gopro_hero': '🏄 GoPro Hero',
    'dji_mavic': '🚁 DJI Mavic'
}

ANGLES = {
    'eye_level': '👁 На уровне глаз',
    'birds_eye': '🦅 Вид сверху',
    'low_angle': '⬇️ Снизу вверх',
    'high_angle': '⬆️ Сверху вниз',
    'dutch_angle': '🔄 Голландский угол',
    'over_shoulder': '👤 Через плечо',
    'close_up': '🔍 Крупный план',
    'wide_shot': '🌅 Широкий план',
    'macro': '🔬 Макро',
    'aerial': '🚁 Аэросъемка'
}

QUALITY_LEVELS = {
    'ultra_hd': '💎 Ultra HD',
    '8k': '🎬 8K',
    '4k': '📺 4K',
    'full_hd': '💻 Full HD',
    'hd': '📱 HD',
    'professional': '⭐️ Профессионал',
    'studio': '🎥 Студийное',
    'raw': '📸 RAW',
    'hdr': '🌈 HDR',
    'cinematic': '🎞 Кинематограф'
}

TONES = {
    'warm': '🔥 Теплая',
    'cool': '❄️ Холодная',
    'neutral': '⚪️ Нейтральная',
    'vibrant': '🌈 Яркая',
    'pastel': '🎨 Пастель',
    'monochrome': '⚫️ Монохром',
    'sepia': '📜 Сепия',
    'vintage': '📻 Винтаж',
    'neon': '💡 Неон',
    'natural': '🌿 Натуральная'
}


def get_user_advanced_params(user_id, category_id):
    """Получить расширенные параметры пользователя из БД"""
    from handlers.website.article_generation import get_image_settings
    settings = get_image_settings(user_id, category_id)
    
    # Если в настройках нет расширенных параметров, создаем их
    if 'advanced' not in settings:
        settings['advanced'] = {
            'styles': [],
            'images_count': 3,
            'text_on_image': 0,
            'collage_mode': 0,
            'cameras': [],
            'angles': [],
            'quality': [],
            'tones': []
        }
    
    return settings['advanced']


def save_user_advanced_params(user_id, category_id, adv_params):
    """Сохранить расширенные параметры в БД"""
    from handlers.website.article_generation import get_image_settings, save_image_settings
    settings = get_image_settings(user_id, category_id)
    settings['advanced'] = adv_params
    save_image_settings(user_id, category_id, settings)


# ============================================================
# СТИЛЬ ИЗОБРАЖЕНИЯ
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_adv_style_"))
def handle_style_menu(call):
    """Меню выбора стиля изображений"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    user_id = call.from_user.id
    
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
    
    # Добавляем кнопки по 2 в ряд
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_toggle_style_"))
def handle_toggle_style(call):
    """Toggle стиля"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    style_id = "_".join(parts[5:])
    user_id = call.from_user.id
    
    params = get_user_advanced_params(user_id, category_id)
    current_styles = params.get('styles', [])
    
    if style_id in current_styles:
        current_styles.remove(style_id)
    else:
        current_styles.append(style_id)
    
    params['styles'] = current_styles
    save_user_advanced_params(user_id, category_id, params)
    
    bot.answer_callback_query(call.id, f"✅ {IMAGE_STYLES[style_id]}")
    call.data = f"ws_adv_style_{category_id}_{bot_id}"
    handle_style_menu(call)


# ============================================================
# КОЛИЧЕСТВО ИЗОБРАЖЕНИЙ
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_adv_count_"))
def handle_count_menu(call):
    """Меню выбора количества изображений"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    user_id = call.from_user.id
    
    params = get_user_advanced_params(user_id, category_id)
    current_count = params.get('images_count', 3)
    
    text = (
        f"🔢 <b>КОЛИЧЕСТВО ИЗОБРАЖЕНИЙ</b>\n\n"
        f"Текущее: {current_count}\n"
        f"Выберите количество:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=5)
    buttons = []
    for i in range(1, 11):
        checkmark = " ✅" if i == current_count else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{i}{checkmark}",
                callback_data=f"ws_set_count_{category_id}_{bot_id}_{i}"
            )
        )
    
    # По 5 кнопок в ряд
    for i in range(0, len(buttons), 5):
        markup.row(*buttons[i:i+5])
    
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"platform_format_website_{category_id}_{bot_id}")
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_set_count_"))
def handle_set_count(call):
    """Установка количества"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    count = int(parts[5])
    user_id = call.from_user.id
    
    params = get_user_advanced_params(user_id, category_id)
    params['images_count'] = count
    save_user_advanced_params(user_id, category_id, params)
    
    bot.answer_callback_query(call.id, f"✅ Установлено: {count}")
    call.data = f"ws_adv_count_{category_id}_{bot_id}"
    handle_count_menu(call)


# ============================================================
# ТЕКСТ НА ФОТО
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_adv_text_"))
def handle_text_menu(call):
    """Меню настройки текста на фото"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_set_text_"))
def handle_set_text(call):
    """Установка текста"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    perc = int(parts[5])
    user_id = call.from_user.id
    
    params = get_user_advanced_params(user_id, category_id)
    params['text_on_image'] = perc
    save_user_advanced_params(user_id, category_id, params)
    
    bot.answer_callback_query(call.id, f"✅ Установлено: {perc}%")
    call.data = f"ws_adv_text_{category_id}_{bot_id}"
    handle_text_menu(call)


# ============================================================
# КОЛЛАЖ ФОТО
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_adv_collage_"))
def handle_collage_menu(call):
    """Меню настройки коллажа"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
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
    call.data = f"ws_adv_collage_{category_id}_{bot_id}"
    handle_collage_menu(call)


# ============================================================
# КАМЕРА
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_adv_camera_"))
def handle_camera_menu(call):
    """Меню выбора камеры"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    user_id = call.from_user.id
    
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
    
    # Добавляем кнопки по 2 в ряд
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
    camera_id = "_".join(parts[5:])  # Соединяем все части начиная с [5]
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
    call.data = f"ws_adv_camera_{category_id}_{bot_id}"
    handle_camera_menu(call)


# ============================================================
# РАКУРС
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_adv_angle_"))
def handle_angle_menu(call):
    """Меню выбора ракурса"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    user_id = call.from_user.id
    
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
    
    # Добавляем кнопки по 2 в ряд
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
    call.data = f"ws_adv_angle_{category_id}_{bot_id}"
    handle_angle_menu(call)


# ============================================================
# КАЧЕСТВО
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_adv_quality_"))
def handle_quality_menu(call):
    """Меню выбора качества"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    user_id = call.from_user.id
    
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
    
    # Добавляем кнопки по 2 в ряд
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
    call.data = f"ws_adv_quality_{category_id}_{bot_id}"
    handle_quality_menu(call)


# ============================================================
# ТОНАЛЬНОСТЬ
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_adv_tone_"))
def handle_tone_menu(call):
    """Меню выбора тональности"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    user_id = call.from_user.id
    
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
    
    # Добавляем кнопки по 2 в ряд
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
    tone_id = "_".join(parts[5:])
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
    call.data = f"ws_adv_tone_{category_id}_{bot_id}"
    handle_tone_menu(call)


print("✅ handlers/website/image_advanced_settings.py загружен")
