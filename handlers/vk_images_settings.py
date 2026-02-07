# -*- coding: utf-8 -*-
"""
Настройки изображений для платформы VK
"""
from telebot import types
from loader import bot, db


@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_format_vk_"))
def handle_vk_images_menu(call):
    """Меню настроек изображений для VK"""
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
    
    params = get_platform_settings(category, 'vk')
    
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
        angles_names = [remove_emoji(ANGLE_PRESETS.get(a, {}).get('name', a)) for c in angles]
        settings_lines.append(f"📐 Ракурс: {', '.join(angles_names)}")
    
    # Тональность
    tones = params.get('tones', [])
    if tones:
        tones_names = [remove_emoji(TONE_PRESETS.get(t, {}).get('name', t)) for t in tones]
        settings_lines.append(f"🎭 Тональность: {', '.join(tones_names)}")
    
    # Качество
    quality = params.get('quality', '')
    if quality:
        quality_name = remove_emoji(QUALITY_PRESETS.get(quality, {}).get('name', quality))
        settings_lines.append(f"⭐ Качество: {quality_name}")
    
    # Заголовок
    text = (
        f"🎨 <b>НАСТРОЙКИ ИЗОБРАЖЕНИЙ</b>\n"
        f"🔵 Платформа: ВКонтакте\n"
        f"📂 Категория: {category_name}\n"
        "━━━━━━━━━━━━━━━━━\n\n"
    )
    
    # Текущие настройки
    if settings_lines:
        text += "<b>📊 Текущие настройки:</b>\n"
        for line in settings_lines:
            text += f"• {line}\n"
        text += "\n"
    else:
        text += "<i>⚙️ Настройки не выбраны (используются значения по умолчанию)</i>\n\n"
    
    # Кнопки меню
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Форматы
    markup.add(
        types.InlineKeyboardButton(
            f"📐 Форматы ({len(formats)})",
            callback_data=f"format_select_vk_{category_id}_{bot_id}"
        )
    )
    
    # Стили
    markup.add(
        types.InlineKeyboardButton(
            f"🎨 Стили ({len(styles)})",
            callback_data=f"style_select_vk_{category_id}_{bot_id}"
        )
    )
    
    # Текст и Коллаж в одной строке
    markup.row(
        types.InlineKeyboardButton(
            f"📝 Текст ({text_percent}%)",
            callback_data=f"text_select_vk_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            f"🖼 Коллаж ({collage_percent}%)",
            callback_data=f"collage_select_vk_{category_id}_{bot_id}"
        )
    )
    
    # Тональность и Камера
    markup.row(
        types.InlineKeyboardButton(
            f"🎭 Тональность ({len(tones)})",
            callback_data=f"tone_select_vk_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            f"📷 Камера ({len(cameras)})",
            callback_data=f"camera_select_vk_{category_id}_{bot_id}"
        )
    )
    
    # Ракурс и Качество
    markup.row(
        types.InlineKeyboardButton(
            f"📐 Ракурс ({len(angles)})",
            callback_data=f"angle_select_vk_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            f"⭐ Качество",
            callback_data=f"quality_select_vk_{category_id}_{bot_id}"
        )
    )
    
    # Кнопка "Назад"
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_images_menu_vk_{category_id}_{bot_id}_{platform_id}"
        )
    )
    
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='HTML'
    )
    bot.answer_callback_query(call.id)


# ═══════════════════════════════════════════════════════════════
# ОБРАБОТЧИКИ КНОПОК НАСТРОЕК VK
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("format_select_vk_"))
def handle_vk_format_select(call):
    """Переход к выбору форматов для VK"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    
    from handlers.platform_settings.format_selector import show_format_selector
    show_format_selector(call, 'vk', category_id, bot_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("style_select_vk_"))
def handle_vk_style_select(call):
    """Переход к выбору стилей для VK"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    
    from handlers.platform_settings.style_selector import show_style_selector
    show_style_selector(call, 'vk', category_id, bot_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("text_select_vk_"))
def handle_vk_text_select(call):
    """Переход к выбору процента текста для VK"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    
    from handlers.platform_settings.text_collage_selector import show_text_selector
    show_text_selector(call, 'vk', category_id, bot_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("collage_select_vk_"))
def handle_vk_collage_select(call):
    """Переход к выбору процента коллажа для VK"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    
    from handlers.platform_settings.text_collage_selector import show_collage_selector
    show_collage_selector(call, 'vk', category_id, bot_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("tone_select_vk_"))
def handle_vk_tone_select(call):
    """Переход к выбору тональности для VK"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    
    from handlers.platform_settings.tone_camera_selector import show_tone_selector
    show_tone_selector(call, 'vk', category_id, bot_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("camera_select_vk_"))
def handle_vk_camera_select(call):
    """Переход к выбору камеры для VK"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    
    from handlers.platform_settings.tone_camera_selector import show_camera_selector
    show_camera_selector(call, 'vk', category_id, bot_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("angle_select_vk_"))
def handle_vk_angle_select(call):
    """Переход к выбору ракурса для VK"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    
    from handlers.platform_settings.angle_selector import show_angle_selector
    show_angle_selector(call, 'vk', category_id, bot_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("quality_select_vk_"))
def handle_vk_quality_select(call):
    """Переход к выбору качества для VK"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    
    from handlers.platform_settings.quality_selector import show_quality_selector
    show_quality_selector(call, 'vk', category_id, bot_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("back_to_vk_"))
def handle_back_to_vk(call):
    """Возврат в меню настроек изображений VK"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    
    # Получаем platform_id (первый активный VK)
    user_id = call.from_user.id
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    vks = connections.get('vks', []) if isinstance(connections, dict) else []
    
    platform_id = 'main'  # По умолчанию
    for idx, vk in enumerate(vks):
        if isinstance(vk, dict) and vk.get('status') == 'active':
            platform_id = str(idx)
            break
    
    # Редирект на меню настроек изображений VK
    call.data = f"platform_images_menu_vk_{category_id}_{bot_id}_{platform_id}"
    from handlers.platform_category.images_menu import handle_platform_images_menu
    handle_platform_images_menu(call)


print("✅ handlers/vk_images_settings.py загружен")
