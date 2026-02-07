"""
Подменю настроек изображений для платформ
"""
from telebot import types
from loader import bot, db
from utils import escape_html

# Безопасное логирование
try:
    from debug_logger import debug
except Exception:
    class SimpleDebug:
        def header(self, *args): pass
        def info(self, *args): pass
        def success(self, *args): pass
        def warning(self, *args): pass
        def error(self, *args): pass
        def debug(self, *args): pass
        def dict_dump(self, *args, **kwargs): pass
        def footer(self): pass
    debug = SimpleDebug()


@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_images_menu_"))
def handle_platform_images_menu(call):
    """Подменю настроек изображений"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    platform_id = "_".join(parts[6:])
    
    user_id = call.from_user.id
    
    # Получаем данные
    category = db.get_category(category_id)
    bot_data = db.get_bot(bot_id)
    
    if not category or not bot_data or bot_data['user_id'] != user_id:
        bot.answer_callback_query(call.id, "❌ Ошибка доступа")
        return
    
    category_name = category.get('name', 'Без названия')
    
    # Определяем название платформы
    platform_names = {
        'pinterest': 'Pinterest',
        'telegram': 'Telegram',
        'vk': 'ВКонтакте',
        'website': 'Website'
    }
    platform_name = platform_names.get(platform_type.lower(), platform_type.upper())
    
    # Получаем настройки
    from handlers.platform_settings.utils import get_platform_settings
    from handlers.platform_settings.constants import (
        IMAGE_STYLES, CAMERA_PRESETS, ANGLE_PRESETS, 
        QUALITY_PRESETS, TONE_PRESETS
    )
    
    settings = get_platform_settings(category, platform_type)
    
    # Формируем текст с настройками (показываем только включенные)
    settings_lines = []
    
    # Функция для удаления эмодзи из начала строки
    def remove_emoji(text):
        """Убирает эмодзи и пробел из начала строки"""
        if not text:
            return text
        # Убираем первый символ (эмодзи) и пробел если есть
        parts = text.split(' ', 1)
        if len(parts) > 1:
            return parts[1]
        return text
    
    # Форматы
    formats = settings.get('formats', [])
    if formats:
        settings_lines.append(f"📐 Формат превью: {', '.join(formats)}")
    
    # Стиль
    styles = settings.get('styles', [])
    if styles:
        styles_names = [remove_emoji(IMAGE_STYLES.get(s, {}).get('name', s)) for s in styles]
        settings_lines.append(f"🎨 Стиль: {', '.join(styles_names)}")
    
    # Текст на фото (показываем только если > 0)
    text_percent = settings.get('text_percent', '0')
    if text_percent and str(text_percent) != '0':
        settings_lines.append(f"📝 Текст на фото: {text_percent}%")
    
    # Коллаж (показываем только если > 0)
    collage_percent = settings.get('collage_percent', '0')
    if collage_percent and str(collage_percent) != '0':
        settings_lines.append(f"🖼 Коллаж: {collage_percent}%")
    
    # Камера
    cameras = settings.get('cameras', [])
    if cameras:
        cameras_names = [remove_emoji(CAMERA_PRESETS.get(c, {}).get('name', c)) for c in cameras]
        settings_lines.append(f"📷 Камера: {', '.join(cameras_names)}")
    
    # Ракурс
    angles = settings.get('angles', [])
    if angles:
        angles_names = [remove_emoji(ANGLE_PRESETS.get(a, {}).get('name', a)) for a in angles]
        settings_lines.append(f"📐 Ракурс: {', '.join(angles_names)}")
    
    # Качество
    quality = settings.get('quality', [])
    if quality:
        quality_names = [remove_emoji(QUALITY_PRESETS.get(q, {}).get('name', q)) for q in quality]
        settings_lines.append(f"💎 Качество: {', '.join(quality_names)}")
    
    # Тональность
    tones = settings.get('tones', [])
    if tones:
        tones_names = [remove_emoji(TONE_PRESETS.get(t, {}).get('name', t)) for t in tones]
        settings_lines.append(f"🌈 Тональность: {', '.join(tones_names)}")
    
    text = (
        f"🖼 <b>НАСТРОЙКИ ИЗОБРАЖЕНИЙ</b>\n"
        f"📱 Платформа: {platform_name}\n"
        f"📂 Категория: {category_name}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    if settings_lines:
        text += "<b>Текущие настройки:</b>\n" + "\n".join(settings_lines) + "\n\n"
    
    text += "Настройте параметры изображений для генерации:"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Для Website показываем "Формат превью" и "Форматы статьи"
    if platform_type.lower() == 'website':
        markup.row(
            types.InlineKeyboardButton(
                "📐 Формат превью",
                callback_data=f"ws_preview_format_{category_id}_{bot_id}"
            ),
            types.InlineKeyboardButton(
                "📸 Форматы статьи",
                callback_data=f"ws_article_images_format_{category_id}_{bot_id}"
            )
        )
    
    # Стиль и Количество (Количество только для website)
    if platform_type.lower() == 'website':
        markup.row(
            types.InlineKeyboardButton(
                "🎨 Стиль",
                callback_data=f"next_style_{platform_type}_{category_id}_{bot_id}"
            ),
            types.InlineKeyboardButton(
                "🔢 Количество",
                callback_data=f"platform_images_count_{category_id}_{bot_id}_{platform_type}_{platform_id}"
            )
        )
    else:
        # Для TG, Pinterest и VK - формат и стиль
        markup.row(
            types.InlineKeyboardButton(
                "📐 Формат",
                callback_data=f"platform_format_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            ),
            types.InlineKeyboardButton(
                "🎨 Стиль",
                callback_data=f"next_style_{platform_type}_{category_id}_{bot_id}"
            )
        )
    
    # Текст на фото и Коллаж
    markup.row(
        types.InlineKeyboardButton(
            "📝 Текст на фото",
            callback_data=f"next_text_percent_{platform_type}_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            "🖼 Коллаж фото",
            callback_data=f"next_collage_percent_{platform_type}_{category_id}_{bot_id}"
        )
    )
    
    # Камера и Ракурс
    markup.row(
        types.InlineKeyboardButton(
            "📷 Камера",
            callback_data=f"next_camera_{platform_type}_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            "📐 Ракурс",
            callback_data=f"next_angle_{platform_type}_{category_id}_{bot_id}"
        )
    )
    
    # Качество и Тональность
    markup.row(
        types.InlineKeyboardButton(
            "💎 Качество",
            callback_data=f"next_quality_{platform_type}_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            "🌈 Тональность",
            callback_data=f"next_tone_{platform_type}_{category_id}_{bot_id}"
        )
    )
    
    # Назад к платформе
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_menu_{category_id}_{bot_id}_{platform_type}_{platform_id}"
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
        bot.send_message(
            call.message.chat.id,
            text,
            reply_markup=markup,
            parse_mode='HTML'
        )
    
    bot.answer_callback_query(call.id)


# ═══════════════════════════════════════════════════════════════
# ПОДМЕНЮ: НАСТРОЙКИ ТЕКСТА
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_text_menu_"))
def handle_platform_text_menu(call):
    """Подменю настроек текста"""
    parts = call.data.split("_")
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    platform_id = "_".join(parts[6:])
    
    user_id = call.from_user.id
    
    # Получаем данные
    category = db.get_category(category_id)
    bot_data = db.get_bot(bot_id)
    
    if not category or not bot_data or bot_data['user_id'] != user_id:
        bot.answer_callback_query(call.id, "❌ Ошибка доступа")
        return
    
    # ═══════════════════════════════════════════════════════════════
    # ДЛЯ VK - СРАЗУ ОТКРЫВАЕМ ВЫБОР СТИЛЯ ТЕКСТА
    # ═══════════════════════════════════════════════════════════════
    if platform_type.lower() == 'vk':
        # Перенаправляем на выбор стиля текста
        call.data = f"platform_style_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        from handlers.text_style_settings import handle_text_style_main
        handle_text_style_main(call)
        return
    
    category_name = category.get('name', 'Без названия')
    
    # Определяем название платформы
    platform_names = {
        'pinterest': 'Pinterest',
        'telegram': 'Telegram',
        'vk': 'ВКонтакте',
        'website': 'Website'
    }
    platform_name = platform_names.get(platform_type.lower(), platform_type.upper())
    
    # Получаем текущие настройки
    import json
    
    # Стили текста
    settings = category.get('settings', {})
    if isinstance(settings, str):
        settings = json.loads(settings)
    
    selected_styles = settings.get(f'{platform_type}_text_styles', ['conversational'])
    if not isinstance(selected_styles, list):
        selected_styles = [selected_styles]
    
    from handlers.text_style_settings import TEXT_STYLES
    if selected_styles:
        styles_names = [TEXT_STYLES.get(s, {}).get('name', s) for s in selected_styles]
        styles_text = ', '.join(styles_names)
    else:
        styles_text = 'Не выбрано'
    
    # Количество слов (только для website)
    words_text = ''
    html_style_text = ''
    
    if platform_type == 'website':
        from handlers.website.article_generation import article_params_storage
        key = f"{user_id}_{category_id}"
        if key in article_params_storage:
            words = article_params_storage[key].get('words', 1500)
            tokens = (words // 100) * 10
            words_text = f"📊 Количество слов: {words} ({tokens} токенов)\n"
        
        # HTML стиль (только для website)
        from handlers.platform_settings.utils import get_platform_settings
        platform_settings = get_platform_settings(category, platform_type)
        html_style = platform_settings.get('html_style', 'news')
        
        html_styles_dict = {
            'news': '📰 Новостной',
            'blog': '📝 Блоговый',
            'magazine': '📖 Журнальный',
            'corporate': '💼 Корпоративный',
            'minimal': '✨ Минималистичный',
            'creative': '🎨 Креативный',
            'academic': '📚 Академический',
            'ecommerce': '🛍 Интернет-магазин',
            'landing': '🎯 Лендинг',
            'portfolio': '🖼 Портфолио'
        }
        html_style_name = html_styles_dict.get(html_style, html_style)
        html_style_text = f"📄 HTML стиль: {html_style_name}\n"
    
    text = (
        f"✍️ <b>НАСТРОЙКИ ТЕКСТА</b>\n"
        f"📱 Платформа: {platform_name}\n"
        f"📂 Категория: {category_name}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Текущие настройки:</b>\n"
        f"📝 Стили текста: {styles_text}\n"
        f"{words_text}"
        f"{html_style_text}\n"
        "Выберите параметр для настройки:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    # Стиль текста
    markup.add(
        types.InlineKeyboardButton(
            "📝 Стиль текста",
            callback_data=f"platform_style_{platform_type}_{category_id}_{bot_id}"
        )
    )
    
    # Количество слов (только для website)
    if platform_type == 'website':
        markup.add(
            types.InlineKeyboardButton(
                "📊 Количество слов",
                callback_data=f"platform_words_count_{category_id}_{bot_id}_{platform_type}_{platform_id}"
            )
        )
    
    # HTML стиль (только для website)
    if platform_type == 'website':
        markup.add(
            types.InlineKeyboardButton(
                "📄 HTML стиль",
                callback_data=f"platform_html_style_{category_id}_{bot_id}_{platform_type}_{platform_id}"
            )
        )
    
    # Назад к платформе
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_menu_{category_id}_{bot_id}_{platform_type}_{platform_id}"
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
        bot.send_message(
            call.message.chat.id,
            text,
            reply_markup=markup,
            parse_mode='HTML'
        )
    
    bot.answer_callback_query(call.id)


# ═══════════════════════════════════════════════════════════════
# ОБРАБОТЧИКИ ДЛЯ НОВЫХ КНОПОК ПОДМЕНЮ ИЗОБРАЖЕНИЯ
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_images_count_"))
def handle_platform_images_count(call):
    """Заглушка: Количество изображений"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_type = parts[5]
    platform_id = "_".join(parts[6:])
    
    bot.answer_callback_query(call.id, "⚙️ В разработке", show_alert=True)



# УДАЛЕНО: Заглушки больше не нужны, функции работают через основные обработчики
# platform_text_percent, platform_collage_percent и т.д.



# ═══════════════════════════════════════════════════════════════
# КАМЕРА (МНОЖЕСТВЕННЫЙ ВЫБОР)
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_camera_"))
def handle_platform_camera(call):
    """Настройка камеры (множественный выбор)"""
    parts = call.data.split("_")
    category_id = int(parts[2])
    bot_id = int(parts[3])
    platform_type = parts[4]
    platform_id = "_".join(parts[5:])
    
    user_id = call.from_user.id
    category = db.get_category(category_id)
    
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    # Получаем текущие настройки (список камер)
    from handlers.platform_settings.utils import get_platform_settings
    settings = get_platform_settings(category, platform_type)
    current_cameras = settings.get('cameras', [])
    # Поддержка старого формата (строка)
    if isinstance(current_cameras, str):
        current_cameras = [current_cameras] if current_cameras != 'none' else []
    
    camera_options = {
        'smartphone': '📱 Смартфон',
        'dslr': '📷 Зеркалка',
        'mirrorless': '🎥 Беззеркалка',
        'drone': '🚁 Дрон',
        'action': '📹 Экшн-камера',
        'cinema': '🎬 Кино-камера',
        'instant': '📸 Моментальная',
        'professional': '🔭 Профессиональная'
    }
    
    cameras_text = ", ".join([camera_options.get(c, c) for c in current_cameras]) if current_cameras else "❌ Не указано"
    
    text = (
        f"📷 <b>ТИП КАМЕРЫ</b>\n"
        f"📂 {category.get('name', 'Без названия')}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Текущая: <b>{cameras_text}</b>\n\n"
        "Выберите тип камеры:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    buttons = []
    for camera_code, camera_name in camera_options.items():
        check = " ✅" if camera_code in current_cameras else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{camera_name}{check}",
                callback_data=f"set_camera_{category_id}_{bot_id}_{platform_type}_{camera_code}_{platform_id}"
            )
        )
    
    # Добавляем по 2 кнопки в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])
    
    markup.row(
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_camera_"))
def handle_set_camera(call):
    """Установка типа камеры (toggle)"""
    parts = call.data.split("_")
    category_id = int(parts[2])
    bot_id = int(parts[3])
    platform_type = parts[4]
    camera_code = parts[5]
    platform_id = "_".join(parts[6:])
    
    user_id = call.from_user.id
    category = db.get_category(category_id)
    
    if not category:
        bot.answer_callback_query(call.id, "❌ Ошибка")
        return
    
    # Получаем/инициализируем камеры
    from handlers.platform_settings.utils import get_platform_settings, save_platform_settings_simple
    settings = get_platform_settings(category, platform_type)
    current_cameras = settings.get('cameras', [])
    # Поддержка старого формата
    if isinstance(current_cameras, str):
        current_cameras = [current_cameras] if current_cameras != 'none' else []
    
    # Toggle
    if camera_code in current_cameras:
        current_cameras.remove(camera_code)
        action = "убрана"
    else:
        current_cameras.append(camera_code)
        action = "добавлена"
    
    # Сохраняем
    settings['cameras'] = current_cameras
    save_platform_settings_simple(category, platform_type, settings)
    
    camera_names = {
        'smartphone': 'Смартфон',
        'dslr': 'Зеркалка',
        'mirrorless': 'Беззеркалка',
        'drone': 'Дрон',
        'action': 'Экшн-камера',
        'cinema': 'Кино-камера',
        'instant': 'Моментальная',
        'professional': 'Профессиональная'
    }
    
    bot.answer_callback_query(call.id, f"✅ {camera_names.get(camera_code, camera_code)} {action}")
    
    # Возвращаемся в меню камеры
    call.data = f"platform_camera_{category_id}_{bot_id}_{platform_type}_{platform_id}"
    handle_platform_camera(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_angle_"))
def handle_platform_angle(call):
    """Настройка ракурса"""
    parts = call.data.split("_")
    category_id = int(parts[2])
    bot_id = int(parts[3])
    platform_type = parts[4]
    platform_id = "_".join(parts[5:])
    
    user_id = call.from_user.id
    category = db.get_category(category_id)
    
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    # Получаем текущие настройки (список ракурсов)
    from handlers.platform_settings.utils import get_platform_settings
    settings = get_platform_settings(category, platform_type)
    current_angles = settings.get('angles', [])
    # Поддержка старого формата
    if isinstance(current_angles, str):
        current_angles = [current_angles] if current_angles != 'none' else []
    
    angle_options = {
        'eye_level': '👁️ На уровне глаз',
        'high_angle': '⬆️ Сверху',
        'low_angle': '⬇️ Снизу',
        'birds_eye': '🦅 С высоты',
        'worms_eye': '🐛 От земли',
        'dutch_angle': '📐 Наклон',
        'closeup': '🎯 Крупный план',
        'wide_shot': '📺 Общий план'
    }
    
    angles_text = ", ".join([angle_options.get(a, a) for a in current_angles]) if current_angles else "❌ Не указано"
    
    text = (
        f"🎯 <b>РАКУРС СЪЕМКИ</b>\n"
        f"📂 {category.get('name', 'Без названия')}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Текущий: <b>{angles_text}</b>\n\n"
        "Выберите ракурс:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    buttons = []
    for angle_code, angle_name in angle_options.items():
        check = " ✅" if angle_code in current_angles else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{angle_name}{check}",
                callback_data=f"set_angle_{category_id}_{bot_id}_{platform_type}_{angle_code}_{platform_id}"
            )
        )
    
    # Добавляем по 2 кнопки в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])
    
    markup.row(
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_angle_"))
def handle_set_angle(call):
    """Установка ракурса (toggle)"""
    parts = call.data.split("_")
    category_id = int(parts[2])
    bot_id = int(parts[3])
    platform_type = parts[4]
    angle_code = parts[5]
    platform_id = "_".join(parts[6:])
    
    user_id = call.from_user.id
    category = db.get_category(category_id)
    
    if not category:
        bot.answer_callback_query(call.id, "❌ Ошибка")
        return
    
    # Получаем/инициализируем ракурсы
    from handlers.platform_settings.utils import get_platform_settings, save_platform_settings_simple
    settings = get_platform_settings(category, platform_type)
    current_angles = settings.get('angles', [])
    # Поддержка старого формата
    if isinstance(current_angles, str):
        current_angles = [current_angles] if current_angles != 'none' else []
    
    # Toggle
    if angle_code in current_angles:
        current_angles.remove(angle_code)
        action = "убран"
    else:
        current_angles.append(angle_code)
        action = "добавлен"
    
    # Сохраняем
    settings['angles'] = current_angles
    save_platform_settings_simple(category, platform_type, settings)
    
    angle_names = {
        'eye_level': 'На уровне глаз',
        'high_angle': 'Сверху',
        'low_angle': 'Снизу',
        'birds_eye': 'С высоты',
        'worms_eye': 'От земли',
        'dutch_angle': 'Наклон',
        'closeup': 'Крупный план',
        'wide_shot': 'Общий план'
    }
    
    bot.answer_callback_query(call.id, f"✅ {angle_names.get(angle_code, angle_code)} {action}")
    
    # Возвращаемся в меню ракурса
    call.data = f"platform_angle_{category_id}_{bot_id}_{platform_type}_{platform_id}"
    handle_platform_angle(call)



print("✅ platform_category/images_menu.py загружен")