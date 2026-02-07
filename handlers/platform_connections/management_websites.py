# -*- coding: utf-8 -*-
"""
Управление websites - просмотр, редактирование, удаление
"""
from telebot import types
from loader import bot, db
from utils import escape_html
import json

@bot.callback_query_handler(func=lambda call: call.data == "manage_websites")
def manage_websites(call):
    """Список сайтов для управления"""
    user_id = call.from_user.id
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    text = (
        "🌐 <b>МОИ САЙТЫ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for idx, site in enumerate(websites):
        url = site.get('url', 'Unknown')
        username = site.get('username', 'Unknown')
        status = site.get('status', 'active')
        
        status_emoji = "✅" if status == 'active' else "⚠️"
        
        text += (
            f"{idx + 1}. {status_emoji} <code>{escape_html(url)}</code>\n"
            f"   Логин: {escape_html(username)}\n\n"
        )
        
        markup.add(
            types.InlineKeyboardButton(
                f"{idx + 1}. {url[:30]}...",
                callback_data=f"edit_website_{idx}"
            )
        )
    
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data="manage_platforms")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_website_") or call.data.startswith("view_website_"))
def edit_website(call):
    """Редактирование сайта"""
    user_id = call.from_user.id
    idx = int(call.data.split("_")[-1])
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    site = websites[idx]
    
    text = (
        "🌐 <b>УПРАВЛЕНИЕ САЙТОМ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"URL: <code>{escape_html(site.get('url', ''))}</code>\n"
        f"Логин: <code>{escape_html(site.get('username', ''))}</code>\n"
        f"Статус: {'✅ Активен' if site.get('status') == 'active' else '⚠️ Неактивен'}\n\n"
        "Выберите действие:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🔄 Тест подключения", callback_data=f"test_website_{idx}"),
        types.InlineKeyboardButton("📂 Рубрики WordPress", callback_data=f"wp_categories_{idx}"),
        types.InlineKeyboardButton("🏷 Метки WordPress", callback_data=f"wp_tags_{idx}"),
        types.InlineKeyboardButton("🔗 Внутренние ссылки", callback_data=f"internal_links_{idx}"),
        types.InlineKeyboardButton("🌐 Внешние ссылки", callback_data=f"external_links_{idx}"),
        types.InlineKeyboardButton("🔍 SEO настройки", callback_data=f"wp_seo_settings_{idx}"),
        types.InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_website_{idx}"),
        types.InlineKeyboardButton("🔙 К списку", callback_data="manage_websites")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_website_"))
def delete_website(call):
    """Удаление сайта"""
    user_id = call.from_user.id
    idx = int(call.data.split("_")[-1])
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    # Удаляем сайт
    deleted_site = websites.pop(idx)
    connections['websites'] = websites
    
    # Обновляем БД
    db.cursor.execute("""
        UPDATE users 
        SET platform_connections = %s::jsonb
        WHERE id = %s
    """, (json.dumps(connections), user_id))
    db.conn.commit()
    
    bot.answer_callback_query(call.id, f"✅ Сайт {deleted_site.get('url')} удален")
    
    # Возвращаемся к списку
    fake_call = type('obj', (object,), {
        'data': 'manage_websites',
        'from_user': call.from_user,
        'message': call.message,
        'id': call.id
    })()
    
    manage_websites(fake_call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("test_website_"))
def test_website(call):
    """Тест подключения к сайту"""
    user_id = call.from_user.id
    idx = int(call.data.split("_")[-1])
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    site = websites[idx]
    
    bot.answer_callback_query(call.id, "🔄 Проверяю подключение...")
    
    # Простой тест (в будущем - реальная проверка API)
    import requests
    
    try:
        url = site.get('url')
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            result = "✅ Сайт доступен"
        else:
            result = f"⚠️ Статус {response.status_code}"
    except Exception as e:
        result = f"❌ Ошибка: {str(e)[:100]}"
    
    bot.answer_callback_query(call.id, result, show_alert=True)


# Управление соцсетями (VK, Pinterest, Telegram)
@bot.callback_query_handler(func=lambda call: call.data in ["manage_vks", "manage_pinterests", "manage_telegrams"])
def manage_social_platforms(call):
    """Перенаправление на общий обработчик управления соцсетями"""
    # Эта функция теперь в management_social.py
    from .management_social import manage_social_platforms as handler
    handler(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("wp_categories_"))
def handle_wp_categories(call):
    """Настройка рубрик WordPress"""
    idx = int(call.data.split("_")[2])
    user_id = call.from_user.id
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    site = websites[idx]
    current_categories = site.get('wp_categories', '')
    
    text = (
        "📂 <b>РУБРИКИ WORDPRESS</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"URL: <code>{site.get('url', '')}</code>\n\n"
        f"<b>Текущие рубрики:</b>\n"
        f"<code>{escape_html(current_categories) if current_categories else 'Не указаны (будет использоваться название категории)'}</code>\n\n"
        "📝 <b>Как настроить:</b>\n"
        "1. Введите названия рубрик через запятую\n"
        "2. Например: <code>Новости, Статьи, Обзоры</code>\n"
        "3. Рубрики будут автоматически созданы на сайте при публикации\n\n"
        "💡 Если не указать - будет использоваться название категории бота"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✏️ Изменить рубрики", callback_data=f"edit_wp_categories_{idx}"),
        types.InlineKeyboardButton("🗑 Очистить", callback_data=f"clear_wp_categories_{idx}"),
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"view_website_{idx}")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_wp_categories_"))
def edit_wp_categories_prompt(call):
    """Запрос на ввод рубрик"""
    idx = int(call.data.split("_")[3])
    user_id = call.from_user.id
    
    # Сохраняем idx в состояние для последующего обработчика
    from handlers.state_manager import set_user_state
    set_user_state(user_id, 'waiting_wp_categories', {'idx': idx, 'message_id': call.message.message_id})
    
    text = (
        "📂 <b>ВВЕДИТЕ РУБРИКИ</b>\n\n"
        "Отправьте названия рубрик через запятую.\n\n"
        "Например:\n"
        "<code>Новости, Статьи, Обзоры, Советы</code>\n\n"
        "Отправьте /cancel для отмены"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data=f"wp_categories_{idx}"))
    
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("clear_wp_categories_"))
def clear_wp_categories(call):
    """Очистка рубрик"""
    idx = int(call.data.split("_")[3])
    user_id = call.from_user.id
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    # Очищаем рубрики
    websites[idx]['wp_categories'] = ''
    
    # Сохраняем
    if not isinstance(connections, dict):
        connections = {}
    connections['websites'] = websites
    
    db.update_user(user_id, {'platform_connections': connections})
    
    bot.answer_callback_query(call.id, "✅ Рубрики очищены")
    
    # Возвращаемся к просмотру
    call.data = f"wp_categories_{idx}"
    handle_wp_categories(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("wp_tags_"))
def handle_wp_tags(call):
    """Настройка меток WordPress"""
    idx = int(call.data.split("_")[2])
    user_id = call.from_user.id
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    site = websites[idx]
    current_tags = site.get('wp_tags', '')
    
    text = (
        "🏷 <b>МЕТКИ WORDPRESS</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"URL: <code>{site.get('url', '')}</code>\n\n"
        f"<b>Текущие метки:</b>\n"
        f"<code>{escape_html(current_tags) if current_tags else 'Не указаны (будут использоваться ключевые слова категории)'}</code>\n\n"
        "📝 <b>Как настроить:</b>\n"
        "1. Введите метки через запятую\n"
        "2. Например: <code>дизайн, интерьер, ремонт, стиль</code>\n"
        "3. Метки будут автоматически созданы на сайте при публикации\n\n"
        "💡 Если не указать - будут использоваться ключевые слова из категории бота"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✏️ Изменить метки", callback_data=f"edit_wp_tags_{idx}"),
        types.InlineKeyboardButton("🗑 Очистить", callback_data=f"clear_wp_tags_{idx}"),
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"view_website_{idx}")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_wp_tags_"))
def edit_wp_tags_prompt(call):
    """Запрос на ввод меток"""
    idx = int(call.data.split("_")[3])
    user_id = call.from_user.id
    
    # Сохраняем idx в состояние
    from handlers.state_manager import set_user_state
    set_user_state(user_id, 'waiting_wp_tags', {'idx': idx, 'message_id': call.message.message_id})
    
    text = (
        "🏷 <b>ВВЕДИТЕ МЕТКИ</b>\n\n"
        "Отправьте метки через запятую.\n\n"
        "Например:\n"
        "<code>дизайн, интерьер, ремонт, стиль, декор</code>\n\n"
        "Отправьте /cancel для отмены"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data=f"wp_tags_{idx}"))
    
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("clear_wp_tags_"))
def clear_wp_tags(call):
    """Очистка меток"""
    idx = int(call.data.split("_")[3])
    user_id = call.from_user.id
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    # Очищаем метки
    websites[idx]['wp_tags'] = ''
    
    # Сохраняем
    if not isinstance(connections, dict):
        connections = {}
    connections['websites'] = websites
    
    db.update_user(user_id, {'platform_connections': connections})
    
    bot.answer_callback_query(call.id, "✅ Метки очищены")
    
    # Возвращаемся к просмотру
    call.data = f"wp_tags_{idx}"
    handle_wp_tags(call)



@bot.callback_query_handler(func=lambda call: call.data.startswith("wp_seo_settings_"))
def handle_wp_seo_settings(call):
    """Меню SEO настроек"""
    idx = int(call.data.split("_")[3])
    user_id = call.from_user.id
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    site = websites[idx]
    
    # Получаем текущие настройки
    canonical_url = site.get('seo_canonical', '')
    robots_meta = site.get('seo_robots', 'index, follow')
    schema_type = site.get('seo_schema_type', 'Article')
    
    text = (
        "🔍 <b>SEO НАСТРОЙКИ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"URL: <code>{site.get('url', '')}</code>\n\n"
        "<b>Текущие настройки:</b>\n\n"
        f"🔗 <b>Canonical URL:</b>\n"
        f"<code>{escape_html(canonical_url) if canonical_url else 'Авто (URL статьи)'}</code>\n\n"
        f"🤖 <b>Robots Meta:</b>\n"
        f"<code>{robots_meta}</code>\n\n"
        f"📊 <b>Schema.org тип:</b>\n"
        f"<code>{schema_type}</code>\n\n"
        "Настройте SEO параметры для всех статей:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🔗 Canonical URL", callback_data=f"seo_canonical_{idx}"),
        types.InlineKeyboardButton("🤖 Robots Meta", callback_data=f"seo_robots_{idx}"),
        types.InlineKeyboardButton("📊 Schema.org тип", callback_data=f"seo_schema_{idx}"),
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"view_website_{idx}")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("seo_canonical_"))
def handle_seo_canonical(call):
    """Настройка Canonical URL"""
    idx = int(call.data.split("_")[2])
    user_id = call.from_user.id
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    site = websites[idx]
    current_canonical = site.get('seo_canonical', '')
    
    text = (
        "🔗 <b>CANONICAL URL</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"<b>Текущее значение:</b>\n"
        f"<code>{escape_html(current_canonical) if current_canonical else 'Авто (URL статьи)'}</code>\n\n"
        "📝 <b>Что это:</b>\n"
        "Canonical URL указывает поисковикам на основную версию страницы. "
        "Используется для борьбы с дублями контента.\n\n"
        "💡 <b>Рекомендация:</b>\n"
        "• Оставьте пустым для автоматического URL\n"
        "• Или укажите свой домен для всех статей\n"
        "• Например: <code>https://ecosteni.ru</code>\n\n"
        "Выберите действие:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✏️ Изменить", callback_data=f"edit_seo_canonical_{idx}"),
        types.InlineKeyboardButton("🗑 Очистить (авто)", callback_data=f"clear_seo_canonical_{idx}"),
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"wp_seo_settings_{idx}")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_seo_canonical_"))
def edit_seo_canonical_prompt(call):
    """Запрос на ввод Canonical URL"""
    idx = int(call.data.split("_")[3])
    user_id = call.from_user.id
    
    from handlers.state_manager import set_user_state
    set_user_state(user_id, 'waiting_seo_canonical', {'idx': idx})
    
    text = (
        "🔗 <b>ВВЕДИТЕ CANONICAL URL</b>\n\n"
        "Отправьте базовый URL вашего сайта.\n\n"
        "Например:\n"
        "<code>https://ecosteni.ru</code>\n\n"
        "Или отправьте /cancel для отмены"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data=f"seo_canonical_{idx}"))
    
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("clear_seo_canonical_"))
def clear_seo_canonical(call):
    """Очистка Canonical URL"""
    idx = int(call.data.split("_")[3])
    user_id = call.from_user.id
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    websites[idx]['seo_canonical'] = ''
    connections['websites'] = websites
    db.update_user(user_id, {'platform_connections': connections})
    
    bot.answer_callback_query(call.id, "✅ Canonical URL очищен (будет автоматически)")
    
    call.data = f"seo_canonical_{idx}"
    handle_seo_canonical(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("seo_robots_"))
def handle_seo_robots(call):
    """Настройка Robots Meta"""
    idx = int(call.data.split("_")[2])
    user_id = call.from_user.id
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    site = websites[idx]
    current_robots = site.get('seo_robots', 'index, follow')
    
    text = (
        "🤖 <b>ROBOTS META</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"<b>Текущее значение:</b>\n"
        f"<code>{current_robots}</code>\n\n"
        "📝 <b>Что это:</b>\n"
        "Указание для поисковых роботов:\n"
        "• <b>index</b> - индексировать страницу\n"
        "• <b>noindex</b> - не индексировать\n"
        "• <b>follow</b> - переходить по ссылкам\n"
        "• <b>nofollow</b> - не переходить\n\n"
        "Выберите вариант:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            "✅ index, follow" + (" ✓" if current_robots == "index, follow" else ""),
            callback_data=f"set_robots_{idx}_index_follow"
        ),
        types.InlineKeyboardButton(
            "❌ noindex, follow" + (" ✓" if current_robots == "noindex, follow" else ""),
            callback_data=f"set_robots_{idx}_noindex_follow"
        ),
        types.InlineKeyboardButton(
            "❌ noindex, nofollow" + (" ✓" if current_robots == "noindex, nofollow" else ""),
            callback_data=f"set_robots_{idx}_noindex_nofollow"
        ),
        types.InlineKeyboardButton(
            "⚠️ index, nofollow" + (" ✓" if current_robots == "index, nofollow" else ""),
            callback_data=f"set_robots_{idx}_index_nofollow"
        ),
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"wp_seo_settings_{idx}")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_robots_"))
def set_robots_meta(call):
    """Установка Robots Meta"""
    parts = call.data.split("_")
    idx = int(parts[2])
    robots_value = f"{parts[3]}, {parts[4]}"
    user_id = call.from_user.id
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    websites[idx]['seo_robots'] = robots_value
    connections['websites'] = websites
    db.update_user(user_id, {'platform_connections': connections})
    
    bot.answer_callback_query(call.id, f"✅ Установлено: {robots_value}")
    
    call.data = f"seo_robots_{idx}"
    handle_seo_robots(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("seo_schema_"))
def handle_seo_schema(call):
    """Настройка Schema.org типа"""
    idx = int(call.data.split("_")[2])
    user_id = call.from_user.id
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    site = websites[idx]
    current_schema = site.get('seo_schema_type', 'Article')
    
    text = (
        "📊 <b>SCHEMA.ORG ТИП</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"<b>Текущий тип:</b> <code>{current_schema}</code>\n\n"
        "📝 <b>Что это:</b>\n"
        "Тип контента для поисковиков и соцсетей:\n"
        "• <b>Article</b> - обычная статья (по умолчанию)\n"
        "• <b>Product</b> - товар с ценой\n"
        "• <b>Recipe</b> - рецепт\n"
        "• <b>Review</b> - обзор/отзыв\n"
        "• <b>HowTo</b> - инструкция\n"
        "• <b>FAQPage</b> - вопросы-ответы\n\n"
        "Выберите тип контента:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    schema_types = [
        ("📰 Article", "Article"),
        ("🛍 Product", "Product"),
        ("🍳 Recipe", "Recipe"),
        ("⭐ Review", "Review"),
        ("📋 HowTo", "HowTo"),
        ("❓ FAQPage", "FAQPage"),
        ("📺 VideoObject", "VideoObject"),
        ("🎵 MusicRecording", "MusicRecording")
    ]
    
    buttons = []
    for label, value in schema_types:
        check = " ✓" if current_schema == value else ""
        buttons.append(
            types.InlineKeyboardButton(
                f"{label}{check}",
                callback_data=f"set_schema_{idx}_{value}"
            )
        )
    
    # Добавляем кнопки по 2 в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i+1])
        else:
            markup.row(buttons[i])
    
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"wp_seo_settings_{idx}"))
    
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_schema_"))
def set_schema_type(call):
    """Установка Schema.org типа"""
    parts = call.data.split("_")
    idx = int(parts[2])
    schema_type = parts[3]
    user_id = call.from_user.id
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    websites[idx]['seo_schema_type'] = schema_type
    connections['websites'] = websites
    db.update_user(user_id, {'platform_connections': connections})
    
    bot.answer_callback_query(call.id, f"✅ Установлено: {schema_type}")
    
    call.data = f"seo_schema_{idx}"
    handle_seo_schema(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("internal_links_"))
def handle_internal_links(call):
    """Управление внутренними ссылками"""
    idx = int(call.data.split("_")[2])
    user_id = call.from_user.id
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    site = websites[idx]
    internal_links = site.get('internal_links', [])
    
    text = (
        "🔗 <b>ВНУТРЕННИЕ ССЫЛКИ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"URL: <code>{site.get('url', '')}</code>\n\n"
    )
    
    if internal_links:
        text += f"<b>Собрано ссылок:</b> {len(internal_links)}\n\n"
        text += (
            "<b>Приоритет:</b>\n"
            "🔴 Высокий | 🟡 Средний | ⚪ Низкий\n\n"
        )
        # Показываем топ-5
        for i, link in enumerate(internal_links[:5], 1):
            priority_emoji = "🔴" if link.get('priority', 1) == 3 else "🟡" if link.get('priority', 1) == 2 else "⚪"
            text += f"{priority_emoji} <a href=\"{link['url']}\">{link['title'][:40]}...</a>\n"
        
        if len(internal_links) > 5:
            text += f"\n...и ещё {len(internal_links) - 5} ссылок\n"
    else:
        text += "📭 <b>Ссылки не собраны</b>\n\n"
        text += "Нажмите 'Автосбор ссылок' чтобы краулер прошёлся по сайту и нашёл важные страницы.\n"
    
    text += (
        "\n💡 <b>Как работает:</b>\n"
        "• Краулер обходит до 50 страниц\n"
        "• Находит важные разделы (услуги, товары, контакты)\n"
        "• Избегает 404 и служебных страниц\n"
        "• Ссылки с высоким приоритетом добавляются чаще\n"
        "• Ссылки добавляются в статьи по правилам SEO"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🤖 Автосбор ссылок", callback_data=f"crawl_site_{idx}"),
        types.InlineKeyboardButton("🗑 Очистить", callback_data=f"clear_internal_links_{idx}"),
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"view_website_{idx}")
    )
    
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    except Exception:
        bot.send_message(
            call.message.chat.id, 
            text, 
            reply_markup=markup, 
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("crawl_site_"))
def start_crawling(call):
    """Запуск краулера"""
    idx = int(call.data.split("_")[2])
    user_id = call.from_user.id
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    site = websites[idx]
    site_url = site.get('url', '').rstrip('/')
    
    # НЕ вызываем answer_callback_query здесь - операция долгая и callback протухнет
    
    # Удаляем старое сообщение
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    # Отправляем GIF с прогресс-баром
    from utils.progress_bars import generate_gradient_progress_bar
    
    # Используем GIF с сайта
    gif_url = "https://ecosteni.ru/wp-content/uploads/2026/01/202601191550.gif"
    
    has_gif = False
    
    try:
        initial_text = (
            f"<b>АВТОСБОР ССЫЛОК</b> 0%\n"
            f"⚪⚪⚪⚪⚪⚪⚪⚪⚪⚪⚪⚪\n\n"
            f"🌐 Сайт: <code>{site_url}</code>\n\n"
            f"🕷 Запуск краулера..."
        )
        
        progress_msg = bot.send_animation(
            call.message.chat.id,
            gif_url,
            caption=initial_text,
            parse_mode='HTML'
        )
        has_gif = True
        print(f"✅ GIF отправлен с сайта: {gif_url}")
    except Exception as e:
        print(f"❌ Ошибка отправки GIF: {e}")
        progress_msg = bot.send_message(
            call.message.chat.id,
            f"<b>АВТОСБОР ССЫЛОК</b> 0%\n"
            f"⚪⚪⚪⚪⚪⚪⚪⚪⚪⚪⚪⚪\n\n"
            f"🌐 Сайт: <code>{site_url}</code>\n\n"
            f"🕷 Запуск краулера...",
            parse_mode='HTML'
        )
    
    # Функция обновления прогресса
    def update_progress(current, total, status_text):
        try:
            progress_bar = generate_gradient_progress_bar(
                int((current / total) * 100),
                total_blocks=12,
                title="АВТОСБОР ССЫЛОК"
            )
            
            text = (
                f"{progress_bar}\n\n"
                f"🌐 Сайт: <code>{site_url}</code>\n\n"
                f"{status_text}"
            )
            
            if has_gif:
                # Если GIF - редактируем caption
                bot.edit_message_caption(
                    text,
                    call.message.chat.id,
                    progress_msg.message_id,
                    parse_mode='HTML'
                )
            else:
                # Если обычное сообщение - редактируем text
                bot.edit_message_text(
                    text,
                    call.message.chat.id,
                    progress_msg.message_id,
                    parse_mode='HTML'
                )
        except Exception as e:
            print(f"⚠️ Ошибка обновления прогресса: {e}")
    
    # Запускаем краулер с прогресс-баром
    update_progress(1, 12, "🔍 Анализ главной страницы...")
    
    import time
    time.sleep(0.5)  # Дать время на отображение
    
    update_progress(2, 12, "🌐 Загрузка структуры сайта...")
    time.sleep(0.5)
    
    update_progress(3, 12, "🕷 Поиск внутренних ссылок...")
    time.sleep(0.5)
    
    from utils.site_crawler import crawl_website
    
    # ВАЖНО: crawl_website блокирует выполнение
    # Обновляем до и после
    update_progress(4, 12, "📡 Краулинг сайта (может занять до минуты)...")
    
    result = crawl_website(site_url, max_pages=50, timeout=60)
    
    update_progress(9, 12, "📊 Анализ приоритетов...")
    time.sleep(0.3)
    
    update_progress(11, 12, "✅ Сохранение данных...")
    time.sleep(0.3)
    
    # Удаляем GIF
    try:
        bot.delete_message(call.message.chat.id, progress_msg.message_id)
    except Exception:
        pass
    
    if result['success']:
        # Сохраняем ссылки
        websites[idx]['internal_links'] = result['links']
        connections['websites'] = websites
        db.update_user(user_id, {'platform_connections': connections})
        
        # Формируем отчет
        text = (
            f"✅ <b>АВТОСБОР ЗАВЕРШЕН</b>\n\n"
            f"📊 Посещено страниц: {result.get('total_visited', 0)}\n"
            f"🔗 Собрано ссылок: {len(result['links'])}\n\n"
            f"<b>Приоритет ссылок:</b>\n"
            f"🔴 Высокий — ключевые страницы (услуги, товары, контакты)\n"
            f"🟡 Средний — важные разделы (о компании, портфолио)\n"
            f"⚪ Низкий — дополнительные страницы (блог, новости)\n\n"
            f"<b>Топ-10 важных страниц:</b>\n\n"
        )
        
        for i, link in enumerate(result['links'][:10], 1):
            priority = link.get('priority', 1)
            priority_emoji = "🔴" if priority == 3 else "🟡" if priority == 2 else "⚪"
            text += f"{i}. {priority_emoji} <a href=\"{link['url']}\">{link['title'][:50]}...</a>\n"
        
        text += (
            "\n💡 <b>Как используются:</b>\n"
            "• Высокий приоритет — добавляются в 80% статей\n"
            "• Средний приоритет — добавляются в 50% статей\n"
            "• Низкий приоритет — добавляются в 20% статей"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 К настройкам", callback_data=f"internal_links_{idx}"))
        
        bot.send_message(
            call.message.chat.id,
            text,
            reply_markup=markup,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    else:
        bot.send_message(
            call.message.chat.id,
            f"❌ <b>ОШИБКА АВТОСБОРА</b>\n\n"
            f"Сайт: <code>{site_url}</code>\n\n"
            f"Причина: {result.get('error', 'Неизвестная ошибка')}\n\n"
            f"Попробуйте позже или проверьте доступность сайта.",
            parse_mode='HTML'
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("clear_internal_links_"))
def clear_internal_links(call):
    """Очистка внутренних ссылок"""
    idx = int(call.data.split("_")[3])
    user_id = call.from_user.id
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    websites[idx]['internal_links'] = []
    connections['websites'] = websites
    db.update_user(user_id, {'platform_connections': connections})
    
    bot.answer_callback_query(call.id, "✅ Внутренние ссылки очищены")
    
    call.data = f"internal_links_{idx}"
    handle_internal_links(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("external_links_"))
def handle_external_links(call):
    """Управление внешними ссылками (соцсети)"""
    idx = int(call.data.split("_")[2])
    user_id = call.from_user.id
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    site = websites[idx]
    external_links = site.get('external_links', '')
    
    text = (
        "🌐 <b>ВНЕШНИЕ ССЫЛКИ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"URL: <code>{site.get('url', '')}</code>\n\n"
    )
    
    if external_links:
        text += f"<b>Сохранённые ссылки:</b>\n<code>{escape_html(external_links)}</code>\n\n"
    else:
        text += "📭 <b>Ссылки не указаны</b>\n\n"
    
    text += (
        "💡 <b>Как добавить:</b>\n"
        "Укажите ссылки на ваши соцсети через запятую.\n\n"
        "<b>Примеры:</b>\n"
        "• https://t.me/yourcompany\n"
        "• https://vk.com/yourcompany\n"
        ""
        "Эти ссылки будут добавлены в статьи по правилам SEO."
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✏️ Изменить ссылки", callback_data=f"edit_external_links_{idx}"),
        types.InlineKeyboardButton("🗑 Очистить", callback_data=f"clear_external_links_{idx}"),
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"view_website_{idx}")
    )
    
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    except Exception:
        bot.send_message(
            call.message.chat.id, 
            text, 
            reply_markup=markup, 
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_external_links_"))
def edit_external_links_prompt(call):
    """Запрос на ввод внешних ссылок"""
    idx = int(call.data.split("_")[3])
    user_id = call.from_user.id
    
    from handlers.state_manager import set_user_state
    set_user_state(user_id, 'waiting_external_links', {'idx': idx})
    
    text = (
        "🌐 <b>ВВЕДИТЕ ВНЕШНИЕ ССЫЛКИ</b>\n\n"
        "Отправьте ссылки на ваши соцсети через запятую или с новой строки.\n\n"
        "<b>Пример:</b>\n"
        "<code>https://t.me/dizainservis, https://vk.com/dizainservis</code>\n\n"
        "Или отправьте /cancel для отмены"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data=f"external_links_{idx}"))
    
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("clear_external_links_"))
def clear_external_links(call):
    """Очистка внешних ссылок"""
    idx = int(call.data.split("_")[3])
    user_id = call.from_user.id
    
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    websites = connections.get('websites', [])
    
    if idx >= len(websites):
        bot.answer_callback_query(call.id, "❌ Сайт не найден")
        return
    
    websites[idx]['external_links'] = ''
    connections['websites'] = websites
    db.update_user(user_id, {'platform_connections': connections})
    
    bot.answer_callback_query(call.id, "✅ Внешние ссылки очищены")
    
    call.data = f"external_links_{idx}"
    handle_external_links(call)


print("✅ handlers/platform_connections/management_websites.py загружен")
