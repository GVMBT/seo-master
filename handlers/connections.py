"""
Модуль подключения CMS и социальных сетей
"""
from telebot import types
from loader import bot
from database.database import db
from utils import escape_html, safe_answer_callback
import json


# Состояния подключения
connection_state = {}


@bot.callback_query_handler(func=lambda call: call.data.startswith("web_connect_cms:"))
def handle_connect_cms(call):
    """Начало подключения WordPress"""
    bot_id = int(call.data.split(":")[1])
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    # Проверяем доступ
    bot_data = db.get_bot(bot_id)
    if not bot_data or bot_data['user_id'] != user_id:
        safe_answer_callback(bot, call.id, "❌ Ошибка доступа")
        return
    
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except Exception:
        pass
    
    text = (
        "🔌 <b>ПОДКЛЮЧЕНИЕ WORDPRESS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Для подключения к вашему сайту на WordPress нужны:\n\n"
        "1️⃣ <b>Логин администратора</b>\n"
        "2️⃣ <b>Пароль приложения</b> (не основной пароль!)\n\n"
        "📖 <b>Как создать пароль приложения:</b>\n"
        "• Войдите в WordPress админку\n"
        "• Перейдите в Пользователи → Профиль\n"
        "• Найдите раздел \"Пароли приложений\"\n"
        "• Создайте новый пароль приложения\n"
        "• Скопируйте его (он больше не покажется)\n\n"
        "⚠️ <b>Пароль будет удален сразу после проверки!</b>\n\n"
        "👇 Готовы начать?"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✅ Начать подключение", callback_data=f"start_wp_connect_{bot_id}"),
        types.InlineKeyboardButton("❌ Отмена", callback_data=f"open_bot_{bot_id}")
    )
    
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')
    safe_answer_callback(bot, call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("start_wp_connect_"))
def start_wp_connection(call):
    """Запуск процесса подключения WordPress"""
    bot_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except Exception:
        pass
    
    # Инициализируем состояние
    connection_state[user_id] = {
        'bot_id': bot_id,
        'type': 'wordpress',
        'step': 'url'
    }
    
    text = (
        "🔌 <b>ШАГ 1: URL САЙТА</b>\n\n"
        "Введите адрес вашего WordPress сайта:\n\n"
        "<i>Например: https://mysite.com</i>"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_connection_{bot_id}"))
    
    msg = bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')
    connection_state[user_id]['last_message_id'] = msg.message_id
    
    safe_answer_callback(bot, call.id)


@bot.message_handler(func=lambda m: m.from_user.id in connection_state 
                     and connection_state[m.from_user.id]['step'] == 'url')
def handle_wp_url(message):
    """Обработка URL WordPress"""
    user_id = message.from_user.id
    state = connection_state.get(user_id)
    
    if not state:
        return
    
    url = message.text.strip()
    
    # Простая валидация URL
    if not url.startswith('http'):
        url = 'https://' + url
    
    # Сохраняем URL
    state['wp_url'] = url
    state['step'] = 'login'
    
    # Удаляем предыдущее сообщение
    try:
        bot.delete_message(message.chat.id, state['last_message_id'])
    except Exception:
        pass
    
    # Удаляем сообщение пользователя
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass
    
    text = (
        "🔌 <b>ШАГ 2: ЛОГИН</b>\n\n"
        f"✅ Сайт: <code>{escape_html(url)}</code>\n\n"
        "Введите логин администратора WordPress:"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_connection_{state['bot_id']}"))
    
    msg = bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    state['last_message_id'] = msg.message_id


@bot.message_handler(func=lambda m: m.from_user.id in connection_state 
                     and connection_state[m.from_user.id]['step'] == 'login')
def handle_wp_login(message):
    """Обработка логина WordPress"""
    user_id = message.from_user.id
    state = connection_state.get(user_id)
    
    if not state:
        return
    
    login = message.text.strip()
    
    # Сохраняем логин
    state['wp_login'] = login
    state['step'] = 'password'
    
    # Удаляем сообщения
    try:
        bot.delete_message(message.chat.id, state['last_message_id'])
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass
    
    text = (
        "🔌 <b>ШАГ 3: ПАРОЛЬ ПРИЛОЖЕНИЯ</b>\n\n"
        f"✅ Сайт: <code>{escape_html(state['wp_url'])}</code>\n"
        f"✅ Логин: <code>{escape_html(login)}</code>\n\n"
        "🔑 Введите пароль приложения WordPress:\n\n"
        "⚠️ <b>Это сообщение будет удалено сразу после проверки!</b>"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_connection_{state['bot_id']}"))
    
    msg = bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    state['last_message_id'] = msg.message_id


@bot.message_handler(func=lambda m: m.from_user.id in connection_state 
                     and connection_state[m.from_user.id]['step'] == 'password')
def handle_wp_password(message):
    """Обработка пароля WordPress и проверка подключения"""
    user_id = message.from_user.id
    state = connection_state.get(user_id)
    
    if not state:
        return
    
    password = message.text.strip()
    
    # ВАЖНО: Сразу удаляем сообщение с паролем!
    try:
        bot.delete_message(message.chat.id, message.message_id)
        bot.delete_message(message.chat.id, state['last_message_id'])
    except Exception:
        pass
    
    # Показываем процесс проверки
    checking_msg = bot.send_message(
        message.chat.id,
        "⏳ Проверяю подключение к WordPress...",
        parse_mode='HTML'
    )
    
    # Реальная проверка подключения к WordPress
    import requests
    import time
    
    is_connected = False
    error_message = None
    
    try:
        # Проверяем доступность API WordPress
        api_url = f"{site_url.rstrip('/')}/wp-json/wp/v2"
        
        # Timeout 5 секунд
        response = requests.get(api_url, timeout=5)
        
        if response.status_code == 200:
            # API доступен, проверяем авторизацию
            auth_url = f"{api_url}/users/me"
            auth_response = requests.get(
                auth_url,
                auth=(username, app_password),
                timeout=5
            )
            
            if auth_response.status_code == 200:
                is_connected = True
            else:
                error_message = f"Ошибка авторизации: {auth_response.status_code}"
        else:
            error_message = f"WordPress API недоступен: {response.status_code}"
            
    except requests.exceptions.Timeout:
        error_message = "Таймаут подключения (сайт не отвечает)"
    except requests.exceptions.ConnectionError:
        error_message = "Ошибка подключения (проверьте URL)"
    except Exception as e:
        error_message = f"Ошибка: {str(e)[:100]}"
    
    # Если проверка не прошла - показываем ошибку
    if not is_connected:
        bot.edit_message_text(
            f"❌ Не удалось подключиться к WordPress\n\n"
            f"Причина: {error_message}\n\n"
            f"Проверьте:\n"
            f"• URL сайта корректен\n"
            f"• WordPress API включен\n"
            f"• Логин и пароль правильные",
            message.chat.id,
            checking_msg.message_id,
            parse_mode='HTML'
        )
        
        # Возвращаем в начало
        show_connections_menu(message)
        return
    
    # Сохраняем данные подключения
    bot_id = state['bot_id']
    bot_data = db.get_bot(bot_id)
    
    if bot_data:
        company_data = bot_data.get('company_data', {})
        if isinstance(company_data, str):
            company_data = json.loads(company_data)
        
        company_data['wp_credentials'] = {
            'url': state['wp_url'],
            'login': state['wp_login'],
            'password': password,  # В продакшене шифровать!
            'status': 'connected',
            'connected_at': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        db.update_bot_company_data(bot_id, company_data)
    
    # Удаляем состояние
    del connection_state[user_id]
    
    # Показываем успех
    try:
        bot.delete_message(message.chat.id, checking_msg.message_id)
    except Exception:
        pass
    
    text = (
        "✅ <b>WORDPRESS ПОДКЛЮЧЕН!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🌐 Сайт: <code>{escape_html(state['wp_url'])}</code>\n"
        f"👤 Логин: <code>{escape_html(state['wp_login'])}</code>\n"
        f"🔐 Пароль: <code>{'*' * 16}</code>\n\n"
        "Теперь вы можете:\n"
        "• Публиковать статьи автоматически\n"
        "• Управлять постами из бота\n"
        "• Получать статистику\n"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🤖 К боту", callback_data=f"open_bot_{bot_id}"))
    
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')


@bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_connection_"))
def cancel_connection(call):
    """Отмена подключения"""
    bot_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    # Очищаем состояние
    if user_id in connection_state:
        del connection_state[user_id]
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    text = "❌ Подключение отменено"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🤖 К боту", callback_data=f"open_bot_{bot_id}"))
    
    bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    safe_answer_callback(bot, call.id)


# ═══════════════════════════════════════════════════════════════
# ПОДКЛЮЧЕНИЕ PINTEREST
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("pinterest_auth_"))
def handle_pinterest_auth(call):
    """Авторизация Pinterest (заглушка)"""
    bot_id = int(call.data.split("_")[-1])
    
    text = (
        "📌 <b>ПОДКЛЮЧЕНИЕ PINTEREST</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<i>Раздел в разработке</i>\n\n"
        "Будет доступно:\n"
        "• OAuth авторизация\n"
        "• Выбор доски\n"
        "• Автопостинг пинов\n"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"open_bot_{bot_id}"))
    
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


# ═══════════════════════════════════════════════════════════════
# ПОДКЛЮЧЕНИЕ TELEGRAM
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("reconnect_telegram_"))
def handle_telegram_reconnect(call):
    """Подключение Telegram бота (заглушка)"""
    bot_id = int(call.data.split("_")[-1])
    
    text = (
        "✈️ <b>ПОДКЛЮЧЕНИЕ TELEGRAM</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<i>Раздел в разработке</i>\n\n"
        "Будет доступно:\n"
        "• Ввод токена бота\n"
        "• Привязка канала\n"
        "• Автопостинг\n"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"open_bot_{bot_id}"))
    
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


print("✅ handlers/connections.py загружен")
