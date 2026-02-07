# -*- coding: utf-8 -*-
"""
Настройки изображений для платформы Pinterest
"""
from telebot import types
from loader import bot, db


@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_format_pinterest_"))
def handle_pinterest_images_menu(call):
    """Меню настроек изображений для Pinterest"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = "_".join(parts[5:]) if len(parts) > 5 else "main"
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    # Конвертируем в dict если нужно
    if not isinstance(category, dict):
        category = dict(category)
    
    category_name = category.get('name', 'Без названия')
    
    # Получаем настройки
    from handlers.platform_settings.utils import get_platform_settings
    from handlers.platform_settings.constants import IMAGE_STYLES, CAMERA_PRESETS, ANGLE_PRESETS, QUALITY_PRESETS, TONE_PRESETS
    
    user_id = call.from_user.id
    
    params = get_platform_settings(category, 'pinterest')
    
    # Получаем форматы
    formats = params.get('formats', [])
    if isinstance(formats, str):
        formats = [formats]
    
    # Формируем текст с настройками (показываем только включенные)
    settings_lines = []
    
    # Функция для удаления эмодзи из начала строки
    def remove_emoji(text):
        if not text:
            return text
        parts = text.split(' ', 1)
        if len(parts) > 1:
            return parts[1]
        return text
    
    # Формат
    if formats:
        settings_lines.append(f"📐 Формат: {', '.join(formats)}")
    
    # Стиль
    styles = params.get('styles', [])
    if styles:
        styles_names = [remove_emoji(IMAGE_STYLES.get(s, {}).get('name', s)) for s in styles]
        settings_lines.append(f"🎨 Стиль: {', '.join(styles_names)}")
    
    # Текст на фото (показываем только если > 0)
    text_percent = params.get('text_percent', '0')
    if text_percent and str(text_percent) != '0':
        settings_lines.append(f"📝 Текст на фото: {text_percent}%")
    
    # Коллаж (показываем только если > 0)
    collage_percent = params.get('collage_percent', '0')
    if collage_percent and str(collage_percent) != '0':
        settings_lines.append(f"🖼 Коллаж: {collage_percent}%")
    
    # Камера
    cameras = params.get('cameras', [])
    if cameras:
        cameras_names = [remove_emoji(CAMERA_PRESETS.get(c, {}).get('name', c)) for c in cameras]
        settings_lines.append(f"📷 Камера: {', '.join(cameras_names)}")
    
    # Ракурс
    angles = params.get('angles', [])
    if angles:
        angles_names = [remove_emoji(ANGLE_PRESETS.get(a, {}).get('name', a)) for a in angles]
        settings_lines.append(f"📐 Ракурс: {', '.join(angles_names)}")
    
    # Качество
    quality = params.get('quality', [])
    if quality:
        quality_names = [remove_emoji(QUALITY_PRESETS.get(q, {}).get('name', q)) for q in quality]
        settings_lines.append(f"💎 Качество: {', '.join(quality_names)}")
    
    # Тональность
    tones = params.get('tones', [])
    if tones:
        tones_names = [remove_emoji(TONE_PRESETS.get(t, {}).get('name', t)) for t in tones]
        settings_lines.append(f"🌈 Тональность: {', '.join(tones_names)}")
    
    text = (
        f"🖼 <b>НАСТРОЙКИ ИЗОБРАЖЕНИЙ</b>\n"
        f"📂 Категория: {category_name}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    if settings_lines:
        text += "<b>Текущие настройки:</b>\n" + "\n".join(settings_lines) + "\n\n"
    
    text += "Настройте параметры изображений для генерации."
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton(
            "📐 Формат",
            callback_data=f"pin_preview_format_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            "🎨 Стиль",
            callback_data=f"next_style_pinterest_{category_id}_{bot_id}"
        )
    )
    markup.row(
        types.InlineKeyboardButton(
            "📝 Текст на фото",
            callback_data=f"next_text_percent_pinterest_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            "🖼 Коллаж фото",
            callback_data=f"next_collage_percent_pinterest_{category_id}_{bot_id}"
        )
    )
    markup.row(
        types.InlineKeyboardButton(
            "📷 Камера",
            callback_data=f"next_camera_pinterest_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            "📐 Ракурс",
            callback_data=f"next_angle_pinterest_{category_id}_{bot_id}"
        )
    )
    markup.row(
        types.InlineKeyboardButton(
            "💎 Качество",
            callback_data=f"next_quality_pinterest_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            "🌈 Тональность",
            callback_data=f"next_tone_pinterest_{category_id}_{bot_id}"
        )
    )
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_images_menu_pinterest_{category_id}_{bot_id}_{platform_id}"
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("pin_preview_format_"))
def handle_pinterest_preview_format_select(call):
    """Выбор формата превью (множественный выбор)"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = "_".join(parts[5:]) if len(parts) > 5 else "main"
    
    user_id = call.from_user.id
    category = db.get_category(category_id)
    
    from handlers.platform_settings.utils import get_platform_settings
    from handlers.platform_settings.constants import PLATFORM_FORMATS
    
    settings = get_platform_settings(category, 'pinterest')
    current_formats = settings.get('formats', [])
    if isinstance(current_formats, str):
        current_formats = [current_formats]
    
    # Форматы для Pinterest из констант
    formats = PLATFORM_FORMATS.get('pinterest', [
        ('2:3', '📱 2:3 (портрет)'),
        ('1:1', '⬜ 1:1 (квадрат)'),
        ('4:5', '📱 4:5 (портрет)'),
        ('9:16', '📱 9:16 (сторис)'),
        ('3:4', '📱 3:4 (портрет)'),
        ('16:9', '📺 16:9 (широкий)'),
        ('21:9', '📺 21:9 (ультра-широкий)'),
        ('24:9', '📺 24:9 (панорама)')
    ])
    
    text = (
        f"📐 <b>ФОРМАТ ПРЕВЬЮ</b>\n"
        f"Текущий: {', '.join(current_formats) if current_formats else 'Не выбран'}\n\n"
        f"Выберите формат (можно несколько):"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    
    for format_code, format_name in formats:
        is_selected = format_code in current_formats
        checkmark = " ✅" if is_selected else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{format_code} {checkmark}",
                callback_data=f"pin_set_format_{category_id}_{bot_id}_{format_code}"
            )
        )
    
    # Добавляем кнопки по 2 в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])
    
    markup.row(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_images_menu_pinterest_{category_id}_{bot_id}_{platform_id}"
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("pin_set_format_"))
def handle_pinterest_set_format(call):
    """Установка формата превью (toggle)"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    format_code = parts[5]
    
    user_id = call.from_user.id
    category = db.get_category(category_id)
    
    from handlers.platform_settings.utils import get_platform_settings, save_platform_settings
    settings = get_platform_settings(category, 'pinterest')
    current_formats = settings.get('formats', [])
    if isinstance(current_formats, str):
        current_formats = [current_formats]
    
    # Toggle
    if format_code in current_formats:
        current_formats.remove(format_code)
        action = "убран"
    else:
        current_formats.append(format_code)
        action = "добавлен"
    
    # Сохраняем
    save_platform_settings(db, category_id, 'pinterest', formats=current_formats)
    
    bot.answer_callback_query(call.id, f"✅ {format_code} {action}")
    
    # Обновляем меню
    call.data = f"pin_preview_format_{category_id}_{bot_id}"
    handle_pinterest_preview_format_select(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("pin_images_count_"))
def handle_pinterest_images_count_menu(call):
    """Меню выбора количества изображений"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = "_".join(parts[5:]) if len(parts) > 5 else "main"
    
    user_id = call.from_user.id
    category = db.get_category(category_id)
    
    from handlers.platform_settings.utils import get_platform_settings
    settings = get_platform_settings(category, 'pinterest')
    
    current_count = settings.get('images_count', 3)
    
    text = (
        f"🔢 <b>КОЛИЧЕСТВО ИЗОБРАЖЕНИЙ</b>\n"
        f"Текущее: {current_count}\n\n"
        f"Выберите количество изображений для статьи:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=5)
    
    # Кнопки 1-10
    buttons = []
    for i in range(1, 11):
        checkmark = " ✅" if i == current_count else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{i}{checkmark}",
                callback_data=f"pin_set_img_count_{i}_{category_id}_{bot_id}"
            )
        )
    
    # По 5 кнопок в ряд
    markup.row(*buttons[:5])
    markup.row(*buttons[5:])
    
    markup.row(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_images_menu_pinterest_{category_id}_{bot_id}_{platform_id}"
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("pin_set_img_count_"))
def handle_pinterest_set_img_count(call):
    """Установка количества изображений"""
    parts = call.data.split("_")
    count = int(parts[4])
    category_id = int(parts[5])
    bot_id = int(parts[6])
    
    user_id = call.from_user.id
    category = db.get_category(category_id)
    
    from handlers.platform_settings.utils import save_platform_settings
    save_platform_settings(db, category_id, 'pinterest', images_count=count)
    
    bot.answer_callback_query(call.id, f"✅ Установлено: {count} изображений")
    
    # Возвращаемся в меню количества
    call.data = f"pin_images_count_{category_id}_{bot_id}"
    handle_pinterest_images_count_menu(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("back_to_pinterest_"))
def handle_back_to_pinterest(call):
    """Возврат в меню настроек изображений Pinterest"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    
    # Получаем platform_id (первый активный pinterest)
    user_id = call.from_user.id
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    pinterests = connections.get('pinterests', []) if isinstance(connections, dict) else []
    
    platform_id = 'main'  # По умолчанию
    for idx, pinterest in enumerate(pinterests):
        if isinstance(pinterest, dict) and pinterest.get('status') == 'active':
            platform_id = str(idx)
            break
    
    # Редирект на меню настроек изображений Pinterest
    call.data = f"platform_images_menu_pinterest_{category_id}_{bot_id}_{platform_id}"
    from handlers.platform_category.images_menu import handle_platform_images_menu
    handle_platform_images_menu(call)


print("✅ handlers/pinterest_images_settings.py загружен")
