# -*- coding: utf-8 -*-
"""
Универсальные расширенные настройки изображений для Pinterest, Telegram, VK
Включает: стиль, текст на фото, коллаж, камера, ракурс, качество, тональность
(БЕЗ форматов и количества)
"""
from telebot import types
from loader import bot, db


# ═══════════════════════════════════════════════════════════════
# КОНСТАНТЫ (те же что и для Website)
# ═══════════════════════════════════════════════════════════════

IMAGE_STYLES_RU = [
    ('photorealistic', '📸 Фотореализм'),
    ('anime', '🌸 Anime'),
    ('oil_painting', '🎨 Картина маслом'),
    ('watercolor', '🖼 Акварель'),
    ('cartoon', '🎬 Cartoon'),
    ('sketch', '✏️ Карандашный набросок'),
    ('3d_render', '🎭 3D рендер'),
    ('pixel_art', '🎪 Pixel Art'),
    ('minimalism', '⚪ Минимализм'),
    ('cyberpunk', '🤖 Киберпанк')
]

CAMERAS = [
    ('canon_eos_r5', '📷 Canon EOS R5'),
    ('nikon_z9', '📷 Nikon Z9'),
    ('sony_a7r_iv', '📷 Sony A7R IV'),
    ('fujifilm_xt4', '📷 Fujifilm X-T4'),
    ('leica_q2', '📷 Leica Q2'),
    ('hasselblad_x1d', '📷 Hasselblad X1D'),
    ('phase_one_xf', '📷 Phase One XF'),
    ('pentax_645z', '📷 Pentax 645Z'),
    ('gopro_hero', '📷 GoPro Hero'),
    ('dji_mavic', '🚁 DJI Mavic')
]

ANGLES = [
    ('eye_level', '👁 На уровне глаз'),
    ('birds_eye', '🦅 С высоты птичьего полета'),
    ('low_angle', '⬆️ Снизу вверх'),
    ('high_angle', '⬇️ Сверху вниз'),
    ('dutch_angle', '🔄 Голландский угол'),
    ('over_shoulder', '👤 Через плечо'),
    ('close_up', '🔍 Крупный план'),
    ('wide_shot', '🌐 Широкий план'),
    ('macro', '🔬 Макро'),
    ('aerial', '🚁 Аэросъемка')
]

QUALITY_LEVELS = [
    ('ultra_hd', '💎 Ultra HD'),
    ('8k', '🎬 8K'),
    ('4k', '📺 4K'),
    ('full_hd', '🖥 Full HD'),
    ('hd', '📱 HD'),
    ('professional', '⭐ Professional'),
    ('studio', '🎥 Studio Quality'),
    ('raw', '📸 RAW'),
    ('hdr', '🌟 HDR'),
    ('cinematic', '🎞 Cinematic')
]

TONES = [
    ('warm', '🔥 Теплые тона'),
    ('cool', '❄️ Холодные тона'),
    ('neutral', '⚪ Нейтральные'),
    ('vibrant', '🌈 Яркие'),
    ('pastel', '🎨 Пастельные'),
    ('monochrome', '⚫ Монохром'),
    ('sepia', '🟫 Сепия'),
    ('vintage', '📜 Винтаж'),
    ('neon', '💡 Неон'),
    ('natural', '🌿 Естественные')
]

PLATFORM_NAMES = {
    'pinterest': 'Pinterest',
    'telegram': 'Telegram',
    'vk': 'VK',
}


# ═══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════

def get_settings_key(user_id, category_id, platform_type):
    """Получить ключ для хранения настроек"""
    return f"adv_{platform_type}_{user_id}_{category_id}"


def get_settings(user_id, category_id, platform_type):
    """Получить настройки или создать дефолтные"""
    # Используем единое хранилище
    try:
        from handlers.website.article_generation import article_params_storage
    except Exception:
        article_params_storage = {}
    
    key = get_settings_key(user_id, category_id, platform_type)
    
    if key not in article_params_storage:
        article_params_storage[key] = {
            'styles': [],
            'text_on_image': 0,
            'collage_mode': 0,
            'cameras': [],
            'angles': [],
            'quality': [],
            'tones': []
        }
    
    return article_params_storage[key]


def save_settings(user_id, category_id, platform_type, **kwargs):
    """Сохранить настройки"""
    try:
        from handlers.website.article_generation import article_params_storage
    except Exception:
        article_params_storage = {}
    
    key = get_settings_key(user_id, category_id, platform_type)
    
    if key not in article_params_storage:
        article_params_storage[key] = {}
    
    article_params_storage[key].update(kwargs)


# ═══════════════════════════════════════════════════════════════
# ГЛАВНОЕ МЕНЮ
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_adv_settings_"))
def handle_advanced_menu(call):
    """Главное меню расширенных настроек"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    
    user_id = call.from_user.id
    settings = get_settings(user_id, category_id, platform_type)
    
    category = db.get_category(category_id)
    category_name = category.get('name', 'Без названия') if category else 'Без названия'
    platform_name = PLATFORM_NAMES.get(platform_type, platform_type.upper())
    
    text = (
        f"🎨 <b>СТИЛЬ ИЗОБРАЖЕНИЯ</b>\n"
        f"📱 Платформа: {platform_name}\n\n"
        f"Настройте дополнительные параметры генерации изображений."
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            "🎨 Стиль (10 шт)",
            callback_data=f"plat_adv_style_{platform_type}_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            f"📝 Текст на фото: {settings['text_on_image']}%",
            callback_data=f"plat_adv_text_{platform_type}_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            f"🖼 Коллаж фото: {settings['collage_mode']}%",
            callback_data=f"plat_adv_collage_{platform_type}_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            "📷 Камера (10 шт)",
            callback_data=f"plat_adv_camera_{platform_type}_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            "📐 Ракурс (10 шт)",
            callback_data=f"plat_adv_angle_{platform_type}_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            "💎 Качество (10 шт)",
            callback_data=f"plat_adv_quality_{platform_type}_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            "🌈 Тональность (10 шт)",
            callback_data=f"plat_adv_tone_{platform_type}_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_images_menu_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        )
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


# ═══════════════════════════════════════════════════════════════
# СТИЛЬ
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("plat_adv_style_"))
def handle_style_menu(call):
    """Меню выбора стилей"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    
    user_id = call.from_user.id
    settings = get_settings(user_id, category_id, platform_type)
    current_styles = settings.get('styles', [])
    
    # ✅ УНИФИЦИРОВАНО С WEBSITE: добавлен счётчик
    text = (
        f"🎨 <b>СТИЛЬ ИЗОБРАЖЕНИЯ</b>\n\n"
        f"Выбрано: {len(current_styles)}\n"
        f"Выберите стили (можно несколько):"
    )
    
    # ✅ УНИФИЦИРОВАНО С WEBSITE: кнопки по 2 в ряд
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    
    for style_code, style_name in IMAGE_STYLES_RU:
        is_selected = style_code in current_styles
        checkmark = " ✅" if is_selected else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{style_name}{checkmark}",
                callback_data=f"plat_toggle_style_{platform_type}_{category_id}_{bot_id}_{style_code}"
            )
        )
    
    # По 2 в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])
    
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_adv_settings_{platform_type}_{category_id}_{bot_id}"
        )
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("plat_toggle_style_"))
def handle_toggle_style(call):
    """Переключение стиля"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    style_code = "_".join(parts[6:])
    
    user_id = call.from_user.id
    settings = get_settings(user_id, category_id, platform_type)
    current_styles = settings.get('styles', [])
    
    if style_code in current_styles:
        current_styles.remove(style_code)
    else:
        current_styles.append(style_code)
    
    save_settings(user_id, category_id, platform_type, styles=current_styles)
    bot.answer_callback_query(call.id)
    
    call.data = f"plat_adv_style_{platform_type}_{category_id}_{bot_id}"
    handle_style_menu(call)


# ═══════════════════════════════════════════════════════════════
# ТЕКСТ НА ФОТО
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("plat_adv_text_"))
def handle_text_menu(call):
    """Меню настройки текста на фото"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    
    user_id = call.from_user.id
    settings = get_settings(user_id, category_id, platform_type)
    current_value = settings.get('text_on_image', 0)
    
    text = f"📝 <b>ТЕКСТ НА ФОТО</b>\n\nТекущее значение: {current_value}%\n\nВыберите интенсивность:"
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for value in [0, 25, 50, 75, 100]:
        checkmark = " ✅" if value == current_value else ""
        markup.add(
            types.InlineKeyboardButton(
                f"{value}%{checkmark}",
                callback_data=f"plat_set_text_{platform_type}_{category_id}_{bot_id}_{value}"
            )
        )
    
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_adv_settings_{platform_type}_{category_id}_{bot_id}"
        )
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("plat_set_text_"))
def handle_set_text(call):
    """Установка текста на фото"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    value = int(parts[6])
    
    user_id = call.from_user.id
    save_settings(user_id, category_id, platform_type, text_on_image=value)
    
    bot.answer_callback_query(call.id, f"✅ Установлено: {value}%")
    
    call.data = f"platform_adv_settings_{platform_type}_{category_id}_{bot_id}"
    handle_advanced_menu(call)


# ═══════════════════════════════════════════════════════════════
# КОЛЛАЖ ФОТО
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("plat_adv_collage_"))
def handle_collage_menu(call):
    """Меню настройки коллажа"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    
    user_id = call.from_user.id
    settings = get_settings(user_id, category_id, platform_type)
    current_value = settings.get('collage_mode', 0)
    
    text = f"🖼 <b>КОЛЛАЖ ФОТО</b>\n\nТекущее значение: {current_value}%\n\nВыберите режим коллажа:"
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for value in [0, 25, 50, 75, 100]:
        checkmark = " ✅" if value == current_value else ""
        markup.add(
            types.InlineKeyboardButton(
                f"{value}%{checkmark}",
                callback_data=f"plat_set_collage_{platform_type}_{category_id}_{bot_id}_{value}"
            )
        )
    
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_adv_settings_{platform_type}_{category_id}_{bot_id}"
        )
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("plat_set_collage_"))
def handle_set_collage(call):
    """Установка режима коллажа"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    value = int(parts[6])
    
    user_id = call.from_user.id
    save_settings(user_id, category_id, platform_type, collage_mode=value)
    
    bot.answer_callback_query(call.id, f"✅ Установлено: {value}%")
    
    call.data = f"platform_adv_settings_{platform_type}_{category_id}_{bot_id}"
    handle_advanced_menu(call)


# ═══════════════════════════════════════════════════════════════
# КАМЕРА
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("plat_adv_camera_"))
def handle_camera_menu(call):
    """Меню выбора камеры"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    
    user_id = call.from_user.id
    settings = get_settings(user_id, category_id, platform_type)
    current_cameras = settings.get('cameras', [])
    
    # ✅ УНИФИЦИРОВАНО С WEBSITE: добавлен счётчик
    text = (
        f"📷 <b>КАМЕРА</b>\n\n"
        f"Выбрано: {len(current_cameras)}\n"
        f"Выберите камеры (можно несколько):"
    )
    
    # ✅ УНИФИЦИРОВАНО С WEBSITE: кнопки по 2 в ряд
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    
    for camera_code, camera_name in CAMERAS:
        is_selected = camera_code in current_cameras
        checkmark = " ✅" if is_selected else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{camera_name}{checkmark}",
                callback_data=f"plat_toggle_camera_{platform_type}_{category_id}_{bot_id}_{camera_code}"
            )
        )
    
    # По 2 в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])
    
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_adv_settings_{platform_type}_{category_id}_{bot_id}"
        )
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("plat_toggle_camera_"))
def handle_toggle_camera(call):
    """Переключение камеры"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    camera_code = "_".join(parts[6:])
    
    user_id = call.from_user.id
    settings = get_settings(user_id, category_id, platform_type)
    current_cameras = settings.get('cameras', [])
    
    if camera_code in current_cameras:
        current_cameras.remove(camera_code)
    else:
        current_cameras.append(camera_code)
    
    save_settings(user_id, category_id, platform_type, cameras=current_cameras)
    bot.answer_callback_query(call.id)
    
    call.data = f"plat_adv_camera_{platform_type}_{category_id}_{bot_id}"
    handle_camera_menu(call)


# ═══════════════════════════════════════════════════════════════
# РАКУРС
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("plat_adv_angle_"))
def handle_angle_menu(call):
    """Меню выбора ракурса"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    
    user_id = call.from_user.id
    settings = get_settings(user_id, category_id, platform_type)
    current_angles = settings.get('angles', [])
    
    # ✅ УНИФИЦИРОВАНО С WEBSITE: добавлен счётчик
    text = (
        f"📐 <b>РАКУРС</b>\n\n"
        f"Выбрано: {len(current_angles)}\n"
        f"Выберите ракурсы (можно несколько):"
    )
    
    # ✅ УНИФИЦИРОВАНО С WEBSITE: кнопки по 2 в ряд
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    
    for angle_code, angle_name in ANGLES:
        is_selected = angle_code in current_angles
        checkmark = " ✅" if is_selected else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{angle_name}{checkmark}",
                callback_data=f"plat_toggle_angle_{platform_type}_{category_id}_{bot_id}_{angle_code}"
            )
        )
    
    # По 2 в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])
    
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_adv_settings_{platform_type}_{category_id}_{bot_id}"
        )
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("plat_toggle_angle_"))
def handle_toggle_angle(call):
    """Переключение ракурса"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    angle_code = "_".join(parts[6:])
    
    user_id = call.from_user.id
    settings = get_settings(user_id, category_id, platform_type)
    current_angles = settings.get('angles', [])
    
    if angle_code in current_angles:
        current_angles.remove(angle_code)
    else:
        current_angles.append(angle_code)
    
    save_settings(user_id, category_id, platform_type, angles=current_angles)
    bot.answer_callback_query(call.id)
    
    call.data = f"plat_adv_angle_{platform_type}_{category_id}_{bot_id}"
    handle_angle_menu(call)


# ═══════════════════════════════════════════════════════════════
# КАЧЕСТВО
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("plat_adv_quality_"))
def handle_quality_menu(call):
    """Меню выбора качества"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    
    user_id = call.from_user.id
    settings = get_settings(user_id, category_id, platform_type)
    current_quality = settings.get('quality', [])
    
    # ✅ УНИФИЦИРОВАНО С WEBSITE: добавлен счётчик
    text = (
        f"💎 <b>КАЧЕСТВО</b>\n\n"
        f"Выбрано: {len(current_quality)}\n"
        f"Выберите уровни качества (можно несколько):"
    )
    
    # ✅ УНИФИЦИРОВАНО С WEBSITE: кнопки по 2 в ряд
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    
    for quality_code, quality_name in QUALITY_LEVELS:
        is_selected = quality_code in current_quality
        checkmark = " ✅" if is_selected else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{quality_name}{checkmark}",
                callback_data=f"plat_toggle_quality_{platform_type}_{category_id}_{bot_id}_{quality_code}"
            )
        )
    
    # По 2 в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])
    
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_adv_settings_{platform_type}_{category_id}_{bot_id}"
        )
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("plat_toggle_quality_"))
def handle_toggle_quality(call):
    """Переключение качества"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    quality_code = "_".join(parts[6:])
    
    user_id = call.from_user.id
    settings = get_settings(user_id, category_id, platform_type)
    current_quality = settings.get('quality', [])
    
    if quality_code in current_quality:
        current_quality.remove(quality_code)
    else:
        current_quality.append(quality_code)
    
    save_settings(user_id, category_id, platform_type, quality=current_quality)
    bot.answer_callback_query(call.id)
    
    call.data = f"plat_adv_quality_{platform_type}_{category_id}_{bot_id}"
    handle_quality_menu(call)


# ═══════════════════════════════════════════════════════════════
# ТОНАЛЬНОСТЬ
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("plat_adv_tone_"))
def handle_tone_menu(call):
    """Меню выбора тональности"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    
    user_id = call.from_user.id
    settings = get_settings(user_id, category_id, platform_type)
    current_tones = settings.get('tones', [])
    
    # ✅ УНИФИЦИРОВАНО С WEBSITE: добавлен счётчик
    text = (
        f"🌈 <b>ТОНАЛЬНОСТЬ</b>\n\n"
        f"Выбрано: {len(current_tones)}\n"
        f"Выберите тональности (можно несколько):"
    )
    
    # ✅ УНИФИЦИРОВАНО С WEBSITE: кнопки по 2 в ряд
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    
    for tone_code, tone_name in TONES:
        is_selected = tone_code in current_tones
        checkmark = " ✅" if is_selected else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{tone_name}{checkmark}",
                callback_data=f"plat_toggle_tone_{platform_type}_{category_id}_{bot_id}_{tone_code}"
            )
        )
    
    # По 2 в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])
    
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_adv_settings_{platform_type}_{category_id}_{bot_id}"
        )
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("plat_toggle_tone_"))
def handle_toggle_tone(call):
    """Переключение тональности"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    tone_code = "_".join(parts[6:])
    
    user_id = call.from_user.id
    settings = get_settings(user_id, category_id, platform_type)
    current_tones = settings.get('tones', [])
    
    if tone_code in current_tones:
        current_tones.remove(tone_code)
    else:
        current_tones.append(tone_code)
    
    save_settings(user_id, category_id, platform_type, tones=current_tones)
    bot.answer_callback_query(call.id)
    
    call.data = f"plat_adv_tone_{platform_type}_{category_id}_{bot_id}"
    handle_tone_menu(call)


print("✅ handlers/platform_category/image_advanced_settings.py загружен")
