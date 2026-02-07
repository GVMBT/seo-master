"""
Подменю настроек текста для платформ
Количество слов и HTML стиль
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_words_count_"))
def handle_platform_words_count(call):
    """Настройка количества слов в статье"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_type = parts[5]
    platform_id = "_".join(parts[6:])
    
    user_id = call.from_user.id
    category = db.get_category(category_id)
    bot_data = db.get_bot(bot_id)
    
    if not category or not bot_data or bot_data['user_id'] != user_id:
        bot.answer_callback_query(call.id, "❌ Ошибка доступа")
        return
    
    # Получаем текущее значение
    from handlers.website.article_generation import article_params_storage
    key = f"{user_id}_{category_id}"
    current_words = article_params_storage.get(key, {}).get('words', 1500)
    
    # Расчет токенов: каждые 100 слов = 10 токенов
    tokens = (current_words // 100) * 10
    
    text = (
        f"📊 <b>КОЛИЧЕСТВО СЛОВ В СТАТЬЕ</b>\n"
        f"📂 {category.get('name', 'Без названия')}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Текущее: <b>{current_words} слов</b>\n\n"
        f"💡 <i>Рекомендуется 1500-2500 слов для SEO</i>\n"
        f"💰 <i>Стоимость: каждые 100 слов = 10 токенов ({tokens} токенов)</i>\n\n"
        "Выберите количество слов:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=3)
    
    words_options = [500, 1000, 1500, 2000, 2500, 3000]
    buttons = []
    
    for words in words_options:
        check = " ✅" if words == current_words else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{words}{check}",
                callback_data=f"set_words_count_{category_id}_{bot_id}_{platform_type}_{words}_{platform_id}"
            )
        )
    
    for i in range(0, len(buttons), 3):
        markup.row(*buttons[i:i+3])
    
    markup.row(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_text_menu_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        )
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_words_count_"))
def handle_set_words_count(call):
    """Установка количества слов"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_type = parts[5]
    words = int(parts[6])
    platform_id = "_".join(parts[7:])
    
    user_id = call.from_user.id
    
    # Сохраняем количество слов
    from handlers.website.article_generation import article_params_storage
    
    key = f"{user_id}_{category_id}"
    if key not in article_params_storage:
        article_params_storage[key] = {
            'words': 1500,
            'images': 3,
            'style': 'professional',
            'format': 'structured',
            'preview_format': '16:9',
            'article_images_format': '16:9'
        }
    
    article_params_storage[key]['words'] = words
    
    # Расчет токенов
    tokens = (words // 100) * 10
    
    bot.answer_callback_query(call.id, f"✅ {words} слов ({tokens} токенов)")
    
    # Возвращаемся в меню количества слов
    call.data = f"platform_words_count_{category_id}_{bot_id}_{platform_type}_{platform_id}"
    handle_platform_words_count(call)


# ═══════════════════════════════════════════════════════════════
# ОБРАБОТЧИК: HTML СТИЛЬ
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_html_style_"))
def handle_platform_html_style(call):
    """Настройка HTML стиля для статей"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_type = parts[5]
    platform_id = "_".join(parts[6:])
    
    user_id = call.from_user.id
    category = db.get_category(category_id)
    bot_data = db.get_bot(bot_id)
    
    if not category or not bot_data or bot_data['user_id'] != user_id:
        bot.answer_callback_query(call.id, "❌ Ошибка доступа")
        return
    
    # Получаем текущие настройки
    from handlers.platform_settings.utils import get_platform_settings
    settings = get_platform_settings(category, platform_type)
    current_html_style = settings.get('html_style', 'news')
    
    html_style_options = {
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
    
    current_name = html_style_options.get(current_html_style, 'Новостной')
    
    text = (
        f"📄 <b>HTML СТИЛЬ СТАТЕЙ</b>\n"
        f"📂 {category.get('name', 'Без названия')}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Текущий: <b>{current_name}</b>\n\n"
        "Выберите HTML стиль оформления:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    buttons = []
    for style_code, style_name in html_style_options.items():
        check = " ✅" if style_code == current_html_style else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{style_name}{check}",
                callback_data=f"set_html_style_{category_id}_{bot_id}_{platform_type}_{style_code}_{platform_id}"
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
            callback_data=f"platform_text_menu_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        )
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"⚠️ Не удалось отредактировать сообщение HTML стиля: {e}")
        bot.answer_callback_query(call.id, "✅ Настройки обновлены")


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_html_style_"))
def handle_set_html_style(call):
    """Установка HTML стиля"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_type = parts[5]
    style_code = parts[6]
    platform_id = "_".join(parts[7:])
    
    user_id = call.from_user.id
    category = db.get_category(category_id)
    
    if not category:
        bot.answer_callback_query(call.id, "❌ Ошибка")
        return
    
    # Сохраняем настройку - передаем ТОЛЬКО html_style
    from handlers.platform_settings.utils import save_platform_settings_simple
    result = save_platform_settings_simple(category, platform_type, {'html_style': style_code})
    
    if not result:
        bot.answer_callback_query(call.id, "❌ Ошибка сохранения", show_alert=True)
        return
    
    style_names = {
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
    
    bot.answer_callback_query(call.id, f"✅ {style_names.get(style_code, 'OK')}")
    
    # ВАЖНО: Получаем свежие данные категории из БД после сохранения
    from loader import db as db_loader
    from handlers.platform_settings.utils import get_platform_settings
    category = db_loader.get_category(category_id)
    
    # Обновляем меню HTML стиля
    user_id = call.from_user.id
    bot_data = db_loader.get_bot(bot_id)
    
    if not category or not bot_data or bot_data['user_id'] != user_id:
        return
    
    # Получаем обновленные настройки
    updated_settings = get_platform_settings(category, platform_type)
    current_html_style = updated_settings.get('html_style', 'news')
    
    html_style_options = {
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
    
    current_name = html_style_options.get(current_html_style, 'Новостной')
    
    text = (
        f"📄 <b>HTML СТИЛЬ СТАТЕЙ</b>\n"
        f"📂 {category.get('name', 'Без названия')}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Текущий: <b>{current_name}</b>\n\n"
        "Выберите HTML стиль оформления:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    buttons = []
    for style_code_iter, style_name in html_style_options.items():
        check = " ✅" if style_code_iter == current_html_style else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{style_name}{check}",
                callback_data=f"set_html_style_{category_id}_{bot_id}_{platform_type}_{style_code_iter}_{platform_id}"
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
            callback_data=f"platform_text_menu_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        )
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception as e:
        error_msg = str(e)
        if "message is not modified" in error_msg:
            # Сообщение уже актуальное, это нормально
            pass
        else:
            print(f"⚠️ Ошибка редактирования: {e}")


# Обработчик для кнопки "К платформе" из website модуля

print("✅ platform_category/text_menu.py загружен")
