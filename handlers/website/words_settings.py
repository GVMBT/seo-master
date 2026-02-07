# -*- coding: utf-8 -*-
"""
Обработчик настройки объёма статьи для Website
"""
from telebot import types
from loader import bot, db
from utils import escape_html


@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_words_"))
def handle_platform_words(call):
    """Настройка объёма статьи (количества слов)"""
    parts = call.data.split("_")
    platform_type = parts[2]
    category_id = int(parts[3])
    bot_id = int(parts[4])
    
    user_id = call.from_user.id
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена", show_alert=True)
        return
    
    category_name = category.get('name', '')
    
    # Получаем platform_id из категории
    platforms = category.get('platforms', [])
    platform_id = None
    for p in platforms:
        if p.get('type', '').lower() == platform_type.lower():
            platform_id = p.get('id', '')
            break
    
    if not platform_id:
        platform_id = 'main'  # Fallback
    
    # Получаем текущие параметры из website_article_settings
    from handlers.website.article_generation import article_params_storage
    
    key = f"{user_id}_{category_id}"
    if key not in article_params_storage:
        article_params_storage[key] = {
            'words': 1500,
            'images': 3,
            'style': 'professional',
            'format': 'structured'
        }
    
    current_words = article_params_storage[key].get('words', 1500)
    
    # Расчет токенов: каждые 100 слов = 10 токенов
    tokens = (current_words // 100) * 10
    
    text = (
        f"📝 <b>ОБЪЁМ СТАТЬИ</b>\n"
        f"📂 Категория: {escape_html(category_name)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Текущий: <b>{current_words} слов</b>\n\n"
        f"💡 <i>Рекомендуется 1500-2500 слов для SEO</i>\n"
        f"💰 <i>Стоимость: каждые 100 слов = 10 токенов ({tokens} токенов)</i>"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=3)
    
    word_options = [800, 1000, 1200, 1500, 2000, 2500, 3000, 4000, 5000]
    
    buttons = []
    for words in word_options:
        check = " ✅" if words == current_words else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{words}{check}",
                callback_data=f"set_words_{category_id}_{bot_id}_{words}"
            )
        )
    
    # Добавляем кнопки по 3 в ряд
    for i in range(0, len(buttons), 3):
        row = buttons[i:i+3]
        markup.row(*row)
    
    markup.row(
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
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_words_"))
def handle_set_words(call):
    """Установка объёма статьи"""
    parts = call.data.split("_")
    category_id = int(parts[2])
    bot_id = int(parts[3])
    words = int(parts[4])
    
    user_id = call.from_user.id
    
    # КРИТИЧНО: Загружаем текущие настройки из БД!
    from handlers.website.article_generation import article_params_storage, get_image_settings
    
    key = f"{user_id}_{category_id}"
    
    # Загружаем существующие настройки (если есть)
    current_settings = get_image_settings(user_id, category_id)
    
    # Обновляем только words, остальное берём из текущих настроек
    current_settings['words'] = words
    article_params_storage[key] = current_settings
    
    print(f"\n📝 ИЗМЕНЕНИЕ КОЛИЧЕСТВА СЛОВ:")
    print(f"   user_id: {user_id}")
    print(f"   category_id: {category_id}")
    print(f"   words: {words}")
    print(f"   images (текущие): {current_settings.get('images', 3)}")
    print(f"   article_params_storage[{key}]: {article_params_storage[key]}")
    
    # КРИТИЧНО: Сохраняем в БД!
    from handlers.website.article_generation import save_image_settings
    print(f"   Вызываю save_image_settings...")
    save_image_settings(user_id, category_id, article_params_storage[key])
    print(f"   ✅ save_image_settings выполнен")
    
    # Расчет токенов
    tokens = (words // 100) * 10
    
    bot.answer_callback_query(call.id, f"✅ {words} слов ({tokens} токенов)")
    
    # Обновляем то же меню
    call.data = f"platform_words_website_{category_id}_{bot_id}"
    handle_platform_words(call)


print("✅ handlers/website_words_settings.py загружен")
