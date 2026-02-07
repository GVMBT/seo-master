"""
Настройки качества и тональности изображений
"""
from telebot import types
from loader import bot, db

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


@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_quality_"))
def handle_platform_quality(call):
    """Настройка качества"""
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
    
    # Получаем текущие настройки
    from handlers.platform_settings.utils import get_platform_settings
    settings = get_platform_settings(category, platform_type)
    current_quality = settings.get('quality', 'none')
    
    quality_options = {
        'standard': '📱 Standard',
        'hd': '📺 HD (720p)',
        'full_hd': '🖥️ Full HD (1080p)',
        '2k': '🎬 2K (1440p)',
        '4k': '⭐ 4K (2160p)',
        '8k': '💎 8K (4320p)',
        'ultra_hd': '🔥 Ultra HD',
        'none': '❌ Не указано'
    }
    
    current_name = quality_options.get(current_quality, 'Не указано')
    
    text = (
        f"⭐ <b>КАЧЕСТВО ИЗОБРАЖЕНИЙ</b>\n"
        f"📂 {category.get('name', 'Без названия')}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Текущее: <b>{current_name}</b>\n\n"
        "Выберите качество:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    buttons = []
    for quality_code, quality_name in quality_options.items():
        if quality_code == 'none':
            continue
        check = " ✅" if quality_code == current_quality else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{quality_name}{check}",
                callback_data=f"set_quality_{category_id}_{bot_id}_{platform_type}_{quality_code}_{platform_id}"
            )
        )
    
    # Добавляем по 2 кнопки в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])
    
    # Кнопка "Не указано"
    markup.row(
        types.InlineKeyboardButton(
            f"❌ Не указано{' ✅' if current_quality == 'none' else ''}",
            callback_data=f"set_quality_{category_id}_{bot_id}_{platform_type}_none_{platform_id}"
        )
    )
    
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_quality_"))
def handle_set_quality(call):
    """Установка качества"""
    parts = call.data.split("_")
    category_id = int(parts[2])
    bot_id = int(parts[3])
    platform_type = parts[4]
    quality_code = parts[5]
    platform_id = "_".join(parts[6:])
    
    user_id = call.from_user.id
    category = db.get_category(category_id)
    
    if not category:
        bot.answer_callback_query(call.id, "❌ Ошибка")
        return
    
    # Сохраняем настройку
    from handlers.platform_settings.utils import get_platform_settings, save_platform_settings
    settings = get_platform_settings(category, platform_type)
    settings['quality'] = quality_code
    save_platform_settings(category, platform_type, settings)
    
    quality_names = {
        'standard': 'Standard',
        'hd': 'HD',
        'full_hd': 'Full HD',
        '2k': '2K',
        '4k': '4K',
        '8k': '8K',
        'ultra_hd': 'Ultra HD',
        'none': 'Не указано'
    }
    
    bot.answer_callback_query(call.id, f"✅ {quality_names.get(quality_code, 'OK')}")
    
    # Возвращаемся в меню качества
    call.data = f"platform_quality_{category_id}_{bot_id}_{platform_type}_{platform_id}"
    handle_platform_quality(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_tone_"))
def handle_platform_tone(call):
    """Настройка тональности"""
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
    
    # Получаем текущие настройки (список тональностей)
    from handlers.platform_settings.utils import get_platform_settings
    settings = get_platform_settings(category, platform_type)
    current_tones = settings.get('tones', [])
    # Поддержка старого формата
    if isinstance(current_tones, str):
        current_tones = [current_tones] if current_tones != 'none' else []
    
    tone_options = {
        'bright': '☀️ Яркая',
        'dark': '🌙 Темная',
        'warm': '🔥 Теплая',
        'cool': '❄️ Холодная',
        'vintage': '📼 Винтаж',
        'cinematic': '🎬 Кинематограф',
        'vibrant': '🌈 Насыщенная',
        'pastel': '🎨 Пастельная',
        'monochrome': '⚫ Монохром',
        'natural': '🌿 Естественная'
    }
    
    tones_text = ", ".join([tone_options.get(t, t) for t in current_tones]) if current_tones else "❌ Не указано"
    
    text = (
        f"🎭 <b>ТОНАЛЬНОСТЬ ИЗОБРАЖЕНИЙ</b>\n"
        f"📂 {category.get('name', 'Без названия')}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Текущая: <b>{tones_text}</b>\n\n"
        "Выберите цветовую тональность:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    buttons = []
    for tone_code, tone_name in tone_options.items():
        check = " ✅" if tone_code in current_tones else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{tone_name}{check}",
                callback_data=f"set_tone_{category_id}_{bot_id}_{platform_type}_{tone_code}_{platform_id}"
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_tone_"))
def handle_set_tone(call):
    """Установка тональности (toggle)"""
    parts = call.data.split("_")
    category_id = int(parts[2])
    bot_id = int(parts[3])
    platform_type = parts[4]
    tone_code = parts[5]
    platform_id = "_".join(parts[6:])
    
    user_id = call.from_user.id
    category = db.get_category(category_id)
    
    if not category:
        bot.answer_callback_query(call.id, "❌ Ошибка")
        return
    
    # Получаем/инициализируем тональности
    from handlers.platform_settings.utils import get_platform_settings, save_platform_settings
    settings = get_platform_settings(category, platform_type)
    current_tones = settings.get('tones', [])
    # Поддержка старого формата
    if isinstance(current_tones, str):
        current_tones = [current_tones] if current_tones != 'none' else []
    
    # Toggle
    if tone_code in current_tones:
        current_tones.remove(tone_code)
        action = "убрана"
    else:
        current_tones.append(tone_code)
        action = "добавлена"
    
    # Сохраняем
    settings['tones'] = current_tones
    save_platform_settings(category, platform_type, settings)
    
    tone_names = {
        'bright': 'Яркая',
        'dark': 'Темная',
        'warm': 'Теплая',
        'cool': 'Холодная',
        'vintage': 'Винтаж',
        'cinematic': 'Кинематограф',
        'vibrant': 'Насыщенная',
        'pastel': 'Пастельная',
        'monochrome': 'Монохром',
        'natural': 'Естественная'
    }
    
    bot.answer_callback_query(call.id, f"✅ {tone_names.get(tone_code, tone_code)} {action}")
    
    # Возвращаемся в меню тональности
    call.data = f"platform_tone_{category_id}_{bot_id}_{platform_type}_{platform_id}"
    handle_platform_tone(call)


# ═══════════════════════════════════════════════════════════════
# ОБРАБОТЧИК: КОЛИЧЕСТВО СЛОВ
# ═══════════════════════════════════════════════════════════════


print("✅ platform_category/quality_tone.py загружен")