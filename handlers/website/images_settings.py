# -*- coding: utf-8 -*-
"""
Настройки изображений для платформы Website
"""
import logging

logger = logging.getLogger(__name__)

from telebot import types

from loader import bot, db



@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_format_website_"))
def handle_website_images_menu(call):
    """Меню настроек изображений для Website"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    platform_id = "_".join(parts[5:]) if len(parts) > 5 else "main"
    bot_id = int(parts[4])
    
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
    from handlers.website.article_generation import get_image_settings
    user_id = call.from_user.id
    
    params = get_image_settings(user_id, category_id)
    
    # Получаем форматы (поддержка старого формата)
    preview_formats = params.get('preview_formats', ['16:9'])
    if isinstance(preview_formats, str):
        preview_formats = [preview_formats]
    
    article_formats = params.get('article_images_formats', [])
    if isinstance(article_formats, str):
        article_formats = [article_formats]
    
    images_count = params.get('images_count', 3)
    
    # Получаем расширенные параметры
    from handlers.website.image_advanced_settings import get_user_advanced_params, IMAGE_STYLES, CAMERAS, ANGLES, QUALITY_LEVELS, TONES
    adv_params = get_user_advanced_params(user_id, category_id)
    
    # Формируем текст с расширенными настройками
    settings_lines = [
        f"📐 Формат превью: {', '.join(preview_formats)}",
        f"📸 Форматы для статьи: {', '.join(article_formats) if article_formats else 'Не выбраны'}"
    ]
    
    # Стиль
    if adv_params.get('styles'):
        styles_names = [IMAGE_STYLES.get(s, s) for s in adv_params['styles']]
        settings_lines.append(f"🎨 Стиль: {', '.join(styles_names)}")
    
    # Количество
    if adv_params.get('images_count'):
        settings_lines.append(f"🔢 Количество: {adv_params['images_count']}")
    
    # Текст на фото
    if adv_params.get('text_on_image', 0) > 0:
        settings_lines.append(f"📝 Текст на фото: {adv_params['text_on_image']}%")
    
    # Коллаж
    if adv_params.get('collage_mode', 0) > 0:
        settings_lines.append(f"🖼 Коллаж: {adv_params['collage_mode']}%")
    
    # Камера
    if adv_params.get('cameras'):
        cameras_names = [CAMERAS.get(c, c).split(' ', 1)[1] for c in adv_params['cameras']]  # Убираем эмодзи
        settings_lines.append(f"📷 Камера: {', '.join(cameras_names)}")
    
    # Ракурс
    if adv_params.get('angles'):
        angles_names = [ANGLES.get(a, a).split(' ', 1)[1] for a in adv_params['angles']]  # Убираем эмодзи
        settings_lines.append(f"📐 Ракурс: {', '.join(angles_names)}")
    
    # Качество
    if adv_params.get('quality'):
        quality_names = [QUALITY_LEVELS.get(q, q).split(' ', 1)[1] for q in adv_params['quality']]
        settings_lines.append(f"💎 Качество: {', '.join(quality_names)}")
    
    # Тональность
    if adv_params.get('tones'):
        tones_names = [TONES.get(t, t).split(' ', 1)[1] for t in adv_params['tones']]
        settings_lines.append(f"🌈 Тональность: {', '.join(tones_names)}")
    
    text = (
        f"🖼 <b>НАСТРОЙКИ ИЗОБРАЖЕНИЙ</b>\n"
        f"📂 Категория: {category_name}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Текущие настройки:</b>\n"
        + "\n".join(settings_lines) + "\n\n"
        f"Настройте параметры изображений для генерации."
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
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
    markup.row(
        types.InlineKeyboardButton(
            "🎨 Стиль",
            callback_data=f"next_style_website_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            "🔢 Количество",
            callback_data=f"ws_adv_count_{category_id}_{bot_id}"  # Пока оставим старый
        )
    )
    markup.row(
        types.InlineKeyboardButton(
            "📝 Текст на фото",
            callback_data=f"next_text_percent_website_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            "🖼 Коллаж фото",
            callback_data=f"next_collage_percent_website_{category_id}_{bot_id}"
        )
    )
    markup.row(
        types.InlineKeyboardButton(
            "📷 Камера",
            callback_data=f"next_camera_website_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            "📐 Ракурс",
            callback_data=f"next_angle_website_{category_id}_{bot_id}"
        )
    )
    markup.row(
        types.InlineKeyboardButton(
            "💎 Качество",
            callback_data=f"next_quality_website_{category_id}_{bot_id}"
        ),
        types.InlineKeyboardButton(
            "🌈 Тональность",
            callback_data=f"next_tone_website_{category_id}_{bot_id}"
        )
    )
    
    # Получаем platform_id для кнопки "Назад"
    bot_data = db.get_bot(bot_id)
    platform_id = "main"  # дефолтное значение
    
    if bot_data:
        connections = bot_data.get('connected_platforms', {})
        if isinstance(connections, dict):
            websites = connections.get('websites', [])
            if websites and len(websites) > 0:
                platform_id = websites[0] if isinstance(websites[0], str) else websites[0].get('url', 'main')
    
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_menu_{category_id}_{bot_id}_website_{platform_id}"
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_preview_format_"))
def handle_preview_format_select(call):
    """Выбор формата превью (множественный выбор)"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = "_".join(parts[5:]) if len(parts) > 5 else "main"
    
    user_id = call.from_user.id
    
    from handlers.website.article_generation import get_image_settings, save_image_settings
    settings = get_image_settings(user_id, category_id)
    current_formats = settings.get('preview_formats', ['16:9'])
    if isinstance(current_formats, str):
        current_formats = [current_formats]
    
    formats = [
        ('32:9', '🖥️', 'Ультраширокий'),
        ('24:9', '🎬', 'Киноформат'),
        ('21:9', '📺', 'Широкий'),
        ('16:9', '📺', 'Стандарт'),
        ('16:10', '💻', 'Компьютер'),
        ('3:2', '📷', 'Фото'),
        ('4:3', '📺', 'Классика'),
        ('5:4', '🖼', 'Портрет')
    ]
    
    text = (
        f"📐 <b>ФОРМАТ ПРЕВЬЮ</b>\n"
        f"Текущий: {', '.join(current_formats)}\n\n"
        f"Выберите формат:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    
    for format_code, emoji, name in formats:
        is_selected = format_code in current_formats
        checkmark = " ✅" if is_selected else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{format_code} {emoji}{checkmark}",
                callback_data=f"ws_set_format_{category_id}_{bot_id}_{format_code}"
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
            callback_data=f"platform_format_website_{category_id}_{bot_id}"
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_set_format_"))
def handle_set_preview_format(call):
    """Установка формата превью (single choice - один выбор)"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    format_code = parts[5]
    
    user_id = call.from_user.id
    
    # Получаем настройки
    from handlers.website.article_generation import get_image_settings, save_image_settings
    settings = get_image_settings(user_id, category_id)
    
    # Single choice: заменяем все форматы на выбранный
    settings['preview_formats'] = [format_code]
    save_image_settings(user_id, category_id, settings)
    
    bot.answer_callback_query(call.id, f"✅ Выбран формат {format_code}")
    
    # Обновляем меню формата превью (остаемся на том же экране)
    call.data = f"ws_preview_format_{category_id}_{bot_id}"
    handle_preview_format_select(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_article_images_format_"))
def handle_article_images_format_select(call):
    """Выбор формата изображений в статье (множественный выбор)"""
    try:
        logger.debug(f" ws_article_images_format_ вызван с callback_data={call.data}")
        
        parts = call.data.split("_")
        logger.debug(f" parts={parts}")
        
        category_id = int(parts[4])
        bot_id = int(parts[5])
        
        logger.debug(f" category_id={category_id}, bot_id={bot_id}")
    except Exception as e:
        print(f"❌ ОШИБКА парсинга callback_data в ws_article_images_format: {e}")
        print(f"   callback_data: {call.data}")
        bot.answer_callback_query(call.id, "❌ Ошибка парсинга данных", show_alert=True)
        return
    
    user_id = call.from_user.id
    
    from handlers.website.article_generation import article_params_storage
    key = f"{user_id}_{category_id}"
    
    if key not in article_params_storage:
        article_params_storage[key] = {
            'words': 1500,
            'images': 3,
            'style': 'professional',
            'format': 'structured',
            'article_images_formats': []
        }
    
    # Получаем текущие форматы
    current_formats = article_params_storage[key].get('article_images_formats', [])
    if isinstance(current_formats, str):
        current_formats = [current_formats]
    
    # 16 форматов для статьи
    formats = [
        ('32:9', '🖥️'), ('24:9', '🎬'), ('21:9', '📺'), ('16:9', '📺'),
        ('16:10', '💻'), ('3:2', '📷'), ('4:3', '📺'), ('5:4', '🖼'),
        ('1:1', '⬛'), ('4:5', '📱'), ('9:16', '📱'), ('2:3', '🖼'),
        ('3:4', '📱'), ('5:7', '📄'), ('A4', '📄'), ('letter', '📄')
    ]
    
    text = (
        f"📸 <b>ФОРМАТЫ В СТАТЬЕ</b>\n"
        f"Текущий: {', '.join(current_formats) if current_formats else 'Не выбрано'}\n\n"
        f"Выберите форматы (можно несколько):"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    
    for format_code, emoji in formats:
        is_selected = format_code in current_formats
        checkmark = " ✅" if is_selected else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{format_code} {emoji}{checkmark}",
                callback_data=f"ws_set_article_format_{category_id}_{bot_id}_{format_code}"
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
            callback_data=f"platform_format_website_{category_id}_{bot_id}"
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
        print(f"✅ Сообщение успешно обновлено")
    except Exception as e:
        print(f"❌ ОШИБКА edit_message в формате статьи: {e}")
        try:
            bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
            print(f"✅ Отправлено новое сообщение")
        except Exception as e2:
            print(f"❌ ОШИБКА send_message в формате статьи: {e2}")
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_set_article_format_"))
def handle_set_article_format(call):
    """Установка формата изображений в статье (toggle)"""
    parts = call.data.split("_")
    category_id = int(parts[4])
    bot_id = int(parts[5])
    format_code = parts[6]
    
    user_id = call.from_user.id
    
    from handlers.website.article_generation import article_params_storage
    
    key = f"{user_id}_{category_id}"
    if key not in article_params_storage:
        article_params_storage[key] = {
            'words': 1500,
            'images': 3,
            'style': 'professional',
            'format': 'structured',
            'article_images_formats': []
        }
    
    current_formats = article_params_storage[key].get('article_images_formats', [])
    if isinstance(current_formats, str):
        current_formats = [current_formats]
    
    # Toggle
    if format_code in current_formats:
        current_formats.remove(format_code)
        action = "убран"
    else:
        current_formats.append(format_code)
        action = "добавлен"
    
    article_params_storage[key]['article_images_formats'] = current_formats
    
    bot.answer_callback_query(call.id, f"✅ {format_code} {action}")
    
    # Обновляем меню
    call.data = f"ws_article_images_format_{category_id}_{bot_id}"
    handle_article_images_format_select(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("ws_images_count_"))
def handle_images_count_menu(call):
    """Меню выбора количества изображений"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = "_".join(parts[5:]) if len(parts) > 5 else "main"
    
    user_id = call.from_user.id
    
    from handlers.website.article_generation import get_image_settings, save_image_settings
    key = f"{user_id}_{category_id}"
    
    # Получаем настройки из БД
    settings = get_image_settings(user_id, category_id)
    
    # Читаем количество изображений (проверяем оба места)
    current_count = settings.get('images', 3)
    if 'advanced' in settings and settings['advanced'].get('images_count'):
        current_count = settings['advanced']['images_count']
    
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
                callback_data=f"set_img_count_{i}_{category_id}_{bot_id}"
            )
        )
    
    # По 5 кнопок в ряд
    markup.row(*buttons[:5])
    markup.row(*buttons[5:])
    
    markup.row(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_format_website_{category_id}_{bot_id}"
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_img_count_"))
def handle_set_img_count(call):
    """Установка количества изображений"""
    parts = call.data.split("_")
    count = int(parts[3])
    category_id = int(parts[4])
    bot_id = int(parts[5])
    
    user_id = call.from_user.id
    
    from handlers.website.article_generation import get_image_settings, save_image_settings
    
    print(f"\n🖼️ ИЗМЕНЕНИЕ КОЛИЧЕСТВА ИЗОБРАЖЕНИЙ:")
    print(f"   user_id: {user_id}")
    print(f"   category_id: {category_id}")
    print(f"   count: {count}")
    
    # Получаем текущие настройки
    settings = get_image_settings(user_id, category_id)
    print(f"   Текущие settings до изменения: {settings}")
    
    # Обновляем количество изображений
    settings['images'] = count  # Основное поле
    settings['images_count'] = count  # Дублируем на верхний уровень
    if 'advanced' not in settings:
        settings['advanced'] = {}
    settings['advanced']['images_count'] = count  # Дублируем в advanced
    
    print(f"   Обновленные settings: images={settings['images']}, images_count={settings.get('images_count')}, advanced.images_count={settings['advanced']['images_count']}")
    
    # Сохраняем в БД
    print(f"   Вызываю save_image_settings...")
    save_image_settings(user_id, category_id, settings)
    print(f"   ✅ save_image_settings выполнен")
    
    bot.answer_callback_query(call.id, f"✅ Установлено: {count} изображений")
    
    # Возвращаемся в меню количества
    call.data = f"ws_images_count_{category_id}_{bot_id}"
    handle_images_count_menu(call)




@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_images_menu_website_"))
def handle_platform_images_menu_website(call):
    """Редирект для Website: platform_images_menu → platform_format_website"""
    parts = call.data.split("_")
    # platform_format_website_{category_id}_{bot_id}
    # parts: [platform, images, menu, website, category_id, bot_id, platform_id...]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    
    # Редирект на правильный обработчик для Website
    call.data = f"platform_format_website_{category_id}_{bot_id}"
    handle_website_images_menu(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("back_to_wpc_"))
def handle_back_to_wpc(call):
    """Возврат в меню WPC категории"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    
    # Получаем platform_id (первый активный website)
    user_id = call.from_user.id
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', []) if isinstance(connections, dict) else []
    
    platform_id = '1'  # По умолчанию
    for website in websites:
        if isinstance(website, dict) and website.get('status') == 'active':
            platform_id = website.get('url', '1')
            break
    
    # Редирект на меню настроек изображений Website
    call.data = f"platform_format_website_{category_id}_{bot_id}"
    from handlers.platform_category.images_menu import handle_platform_images_menu
    handle_platform_images_menu(call)


print("✅ handlers/website/images_settings.py загружен")