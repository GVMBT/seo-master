"""
Настройки пользователя - уведомления, API ключи, поддержка
"""
from telebot import types
from loader import bot
from database.database import db
from config import ADMIN_ID
from utils import escape_html, safe_answer_callback


@bot.message_handler(func=lambda message: message.text == "⚙️ Настройки")
def show_settings(message):
    """Показать меню настроек"""
    user_id = message.from_user.id
    
    text = (
        "⚙️ <b>НАСТРОЙКИ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Выберите раздел:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🔔 Уведомления", callback_data="settings_notifications"),
        types.InlineKeyboardButton("🔗 Мои подключения", callback_data="settings_api_keys"),
        types.InlineKeyboardButton("💬 Техподдержка", callback_data="settings_support"),
        types.InlineKeyboardButton("ℹ️ О боте", callback_data="settings_about")
    )
    
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')


@bot.callback_query_handler(func=lambda call: call.data == "settings_notifications")
def handle_notifications_settings(call):
    """Настройки уведомлений"""
    user_id = call.from_user.id
    
    # Получаем текущие настройки
    user = db.get_user(user_id)
    settings = user.get('notification_settings', {})
    
    if isinstance(settings, str):
        import json
        settings = json.loads(settings)
    
    # Настройки по умолчанию
    task_notifications = settings.get('task_notifications', True)
    balance_notifications = settings.get('balance_notifications', True)
    news_notifications = settings.get('news_notifications', True)
    
    text = (
        "🔔 <b>УВЕДОМЛЕНИЯ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Выберите типы уведомлений:\n\n"
        f"{'✅' if task_notifications else '❌'} Уведомления о завершении задач\n"
        f"{'✅' if balance_notifications else '❌'} Уведомления об окончании токенов\n"
        f"{'✅' if news_notifications else '❌'} Новости и обновления\n"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton(
            f"{'✅' if task_notifications else '❌'} Задачи",
            callback_data="notif_toggle_task"
        ),
        types.InlineKeyboardButton(
            f"{'✅' if balance_notifications else '❌'} Баланс",
            callback_data="notif_toggle_balance"
        )
    )
    markup.row(
        types.InlineKeyboardButton(
            f"{'✅' if news_notifications else '❌'} Новости",
            callback_data="notif_toggle_news"
        )
    )
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_settings"))
    
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
    
    safe_answer_callback(bot, call.id)


@bot.callback_query_handler(func=lambda call: call.data == "settings_support")
def handle_support(call):
    """Техподдержка"""
    text = (
        "💬 <b>ТЕХПОДДЕРЖКА</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "📧 <b>Способы связи:</b>\n\n"
        f"👤 Администратор: <code>{ADMIN_ID}</code>\n"
        "📱 Telegram: @support_bot (в разработке)\n"
        "📧 Email: support@example.com\n\n"
        "⏰ <b>Время работы:</b> 24/7\n"
        "⚡ <b>Средний ответ:</b> 1-2 часа\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "📋 <b>Частые вопросы:</b>\n\n"
        "• Как пополнить токены?\n"
        "  → 💎 Тарифы → Пополнить баланс\n\n"
        "• Как подключить WordPress?\n"
        "  → Откройте бота → Подключить WordPress\n\n"
        "• Как создать категорию?\n"
        "  → Откройте бота → Создать категорию\n\n"
        "💡 Полная документация: /help"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📚 Документация", url="https://docs.example.com"),
        types.InlineKeyboardButton("💬 Написать в поддержку", callback_data="contact_support"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_settings")
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
    
    safe_answer_callback(bot, call.id)


@bot.callback_query_handler(func=lambda call: call.data == "contact_support")
def handle_contact_support(call):
    """Написать в поддержку (заглушка)"""
    text = (
        "💬 <b>ОБРАЩЕНИЕ В ПОДДЕРЖКУ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "<i>Раздел в разработке</i>\n\n"
        f"Пока что напишите напрямую:\n"
        f"👤 @{ADMIN_ID}"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="settings_support"))
    
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='HTML'
        )
    except Exception:
        pass
    
    safe_answer_callback(bot, call.id)


@bot.callback_query_handler(func=lambda call: call.data == "settings_about")
def handle_about(call):
    """О боте"""
    text = (
        "ℹ️ <b>О БОТЕ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "🤖 <b>AI Bot Creator v1.0</b>\n\n"
        "Умный помощник для создания и управления ботами с AI.\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "<b>✨ ВОЗМОЖНОСТИ:</b>\n"
        "• Создание персональных ботов\n"
        "• Настройка категорий товаров/услуг\n"
        "• AI-подбор ключевых фраз\n"
        "• Подключение WordPress\n"
        "• Технический аудит сайтов\n"
        "• Генерация контента\n\n"
        "<b>🛠 ТЕХНОЛОГИИ:</b>\n"
        "• Python + PostgreSQL\n"
        "• Claude AI (Anthropic)\n"
        "• Telegram Bot API\n\n"
        "<b>📊 СТАТИСТИКА:</b>\n"
        "• Пользователей: 1,000+\n"
        "• Ботов создано: 5,000+\n"
        "• Категорий: 15,000+\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "© 2026 AI Bot Creator\n"
        "Версия: 1.0.0\n"
        "Дата обновления: 24.01.2026"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🌐 Сайт", url="https://example.com"),
        types.InlineKeyboardButton("📱 Канал", url="https://t.me/botcreator")
    )
    markup.add(
        types.InlineKeyboardButton("⭐ Оценить", url="https://t.me/botfather"),
        types.InlineKeyboardButton("📤 Поделиться", callback_data="share_bot")
    )
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_settings")
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
    
    safe_answer_callback(bot, call.id)


@bot.callback_query_handler(func=lambda call: call.data == "share_bot")
def handle_share_bot(call):
    """Поделиться ботом"""
    from config import BOT_USERNAME
    
    # Пытаемся получить реальное имя бота
    try:
        bot_info = bot.get_me()
        bot_username = bot_info.username
    except Exception:
        bot_username = BOT_USERNAME
    
    share_text = (
        "🤖 Попробуй AI Bot Creator!\n\n"
        "Создавай умных ботов с AI за минуты:\n"
        "✅ Подбор ключевых фраз\n"
        "✅ Генерация контента\n"
        "✅ Анализ сайтов\n\n"
        f"👉 t.me/{bot_username}"
    )
    
    bot.answer_callback_query(
        call.id,
        "Отправьте это сообщение друзьям!",
        show_alert=False
    )
    
    # Отправляем сообщение для копирования
    bot.send_message(
        call.message.chat.id,
        f"<code>{escape_html(share_text)}</code>\n\n<i>Скопируйте и отправьте друзьям!</i>",
        parse_mode='HTML'
    )


@bot.callback_query_handler(func=lambda call: call.data == "back_to_settings")
def back_to_settings(call):
    """Возврат в меню настроек"""
    text = (
        "⚙️ <b>НАСТРОЙКИ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Выберите раздел:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🔔 Уведомления", callback_data="settings_notifications"),
        types.InlineKeyboardButton("🔗 Мои подключения", callback_data="settings_api_keys"),
        types.InlineKeyboardButton("💬 Техподдержка", callback_data="settings_support"),
        types.InlineKeyboardButton("ℹ️ О боте", callback_data="settings_about")
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
    
    safe_answer_callback(bot, call.id)


@bot.message_handler(commands=['help'])
def show_help(message):
    """Показать помощь"""
    text = (
        "📚 <b>ПОМОЩЬ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "<b>🚀 БЫСТРЫЙ СТАРТ:</b>\n\n"
        "1️⃣ Создайте бота:\n"
        "   📁 Проекты → ➕ Создать бота\n\n"
        "2️⃣ Добавьте категорию:\n"
        "   Откройте бота → ➕ Создать категорию\n\n"
        "3️⃣ Подберите ключевые фразы:\n"
        "   Категория → 🔑 Ключевые фразы\n\n"
        "4️⃣ Подключите WordPress:\n"
        "   Бот → 🔌 Подключить WordPress\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "<b>📋 ОСНОВНЫЕ КОМАНДЫ:</b>\n\n"
        "/start - Главное меню\n"
        "/help - Эта справка\n"
        "/actions - Стоимость операций\n\n"
        "<b>📱 РАЗДЕЛЫ:</b>\n\n"
        "📁 Проекты - Управление ботами\n"
        "👤 Профиль - Баланс и статистика\n"
        "💎 Тарифы - Пакеты токенов\n"
        "⚙️ Настройки - Настройки и поддержка\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "💡 Больше информации:\n"
        "⚙️ Настройки → 💬 Техподдержка"
    )
    
    bot.send_message(message.chat.id, text, parse_mode='HTML')


print("✅ handlers/settings.py загружен")


# Обработчики переключения уведомлений
@bot.callback_query_handler(func=lambda call: call.data.startswith("notif_toggle_"))
def handle_notification_toggle(call):
    """Переключение настроек уведомлений"""
    user_id = call.from_user.id
    notification_type = call.data.replace("notif_toggle_", "")
    
    # Получаем текущие настройки
    user = db.get_user(user_id)
    settings = user.get('notification_settings', {})
    
    if isinstance(settings, str):
        import json
        settings = json.loads(settings)
    
    # Переключаем настройку
    setting_map = {
        'task': 'task_notifications',
        'balance': 'balance_notifications',
        'news': 'news_notifications'
    }
    
    setting_key = setting_map.get(notification_type)
    if setting_key:
        current = settings.get(setting_key, True)
        settings[setting_key] = not current
        
        # Сохраняем
        db.update_user(user_id, notification_settings=json.dumps(settings))
        
        # Обновляем меню
        handle_notifications_settings(call)
    
    bot.answer_callback_query(call.id)
