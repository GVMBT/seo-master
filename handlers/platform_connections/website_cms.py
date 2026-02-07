"""
Подключение Website - работа с CMS (WordPress, Tilda и т.д.)
"""
from telebot import types
from loader import bot, db
from utils import escape_html
from .utils import check_global_platform_uniqueness, user_adding_platform
from cms_platforms import get_cms_info, get_cms_instruction
import json


@bot.callback_query_handler(func=lambda call: call.data.startswith("add_cms_"))
def add_cms_start(call):
    """Показать инструкцию для выбранной CMS"""
    cms_id = call.data.replace("add_cms_", "")
    cms_info = get_cms_info(cms_id)
    
    if not cms_info:
        bot.answer_callback_query(call.id, "❌ CMS не найдена")
        return
    
    instruction = get_cms_instruction(cms_id)
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✅ Продолжить подключение", callback_data=f"cms_connect_{cms_id}"),
        types.InlineKeyboardButton("🔙 Назад к выбору", callback_data="add_platform_menu")
    )
    
    try:
        bot.edit_message_text(
            instruction,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    except Exception:
        bot.send_message(
            call.message.chat.id, 
            instruction, 
            reply_markup=markup, 
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("cms_connect_"))
def cms_connect_start(call):
    """Начать процесс подключения CMS"""
    cms_id = call.data.replace("cms_connect_", "")
    user_id = call.from_user.id
    cms_info = get_cms_info(cms_id)
    
    if not cms_info:
        bot.answer_callback_query(call.id, "❌ CMS не найдена")
        return
    
    # Сохраняем в временное хранилище
    user_adding_platform[user_id] = {
        'type': 'cms',
        'cms_id': cms_id,
        'cms_name': cms_info['name'],
        'step': 1,
        'data': {}
    }
    
    # Определяем первое поле для ввода
    required_fields = cms_info['requires']
    field_names = {
        'url': 'URL сайта',
        'shop_url': 'URL магазина',
        'portal_url': 'URL портала',
        'site_url': 'URL сайта',
        'site_id': 'Site ID',
        'username': 'Имя пользователя',
        'app_password': 'Пароль приложения',
        'api_token': 'API токен',
        'api_key': 'API ключ',
        'api_secret': 'API секрет',
        'access_token': 'Access Token',
        'client_id': 'Client ID',
        'client_secret': 'Client Secret',
        'webhook_url': 'Webhook URL',
        'public_key': 'Public Key',
        'secret_key': 'Secret Key'
    }
    
    first_field = required_fields[0]
    field_name = field_names.get(first_field, first_field)
    
    text = (
        f"{cms_info['emoji']} <b>ПОДКЛЮЧЕНИЕ {cms_info['name'].upper()}</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"<b>Шаг 1 из {len(required_fields)}</b>\n\n"
        f"Введите <b>{field_name}</b>:\n\n"
    )
    
    # Добавляем подсказки для конкретных полей
    if first_field == 'url':
        text += "💡 <i>Формат: https://ваш-сайт.ru</i>\n"
    elif first_field == 'shop_url':
        text += "💡 <i>Формат: ваш-магазин.myshopify.com</i>\n"
    elif first_field == 'site_id':
        text += "💡 <i>Найдите в URL редактора</i>\n"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("❌ Отмена", callback_data="add_platform_menu")
    )
    
    bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    # Регистрируем обработчик следующего сообщения
    bot.register_next_step_handler_by_chat_id(
        call.message.chat.id,
        process_cms_field,
        user_id,
        cms_id,
        first_field,
        0  # индекс текущего поля
    )
    
    bot.answer_callback_query(call.id)


def process_cms_field(message, user_id, cms_id, field_name, field_index):
    """Обработка ввода поля CMS"""
    value = message.text.strip()
    
    if not user_adding_platform.get(user_id):
        bot.send_message(message.chat.id, "❌ Сессия истекла. Начните заново.")
        return
    
    cms_info = get_cms_info(cms_id)
    required_fields = cms_info['requires']
    
    # Сохраняем значение
    user_adding_platform[user_id]['data'][field_name] = value
    
    # Проверяем есть ли еще поля
    next_index = field_index + 1
    
    if next_index < len(required_fields):
        # Есть еще поля - запрашиваем следующее
        next_field = required_fields[next_index]
        
        field_names = {
            'url': 'URL сайта',
            'shop_url': 'URL магазина',
            'portal_url': 'URL портала',
            'site_url': 'URL сайта',
            'site_id': 'Site ID',
            'username': 'Имя пользователя',
            'app_password': 'Пароль приложения',
            'api_token': 'API токен',
            'api_key': 'API ключ',
            'api_secret': 'API секрет',
            'access_token': 'Access Token',
            'client_id': 'Client ID',
            'client_secret': 'Client Secret',
            'webhook_url': 'Webhook URL',
            'public_key': 'Public Key',
            'secret_key': 'Secret Key'
        }
        
        field_display_name = field_names.get(next_field, next_field)
        
        text = (
            f"{cms_info['emoji']} <b>ПОДКЛЮЧЕНИЕ {cms_info['name'].upper()}</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"<b>Шаг {next_index + 1} из {len(required_fields)}</b>\n\n"
            f"Введите <b>{field_display_name}</b>:"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("❌ Отмена", callback_data="add_platform_menu")
        )
        
        bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')
        
        # Регистрируем обработчик следующего поля
        bot.register_next_step_handler_by_chat_id(
            message.chat.id,
            process_cms_field,
            user_id,
            cms_id,
            next_field,
            next_index
        )
    else:
        # Все поля заполнены - сохраняем подключение
        save_cms_connection(message.chat.id, user_id, cms_id)


def save_cms_connection(chat_id, user_id, cms_id):
    """Сохранить подключение CMS в БД"""
    if user_id not in user_adding_platform:
        bot.send_message(chat_id, "❌ Ошибка: данные не найдены")
        return
    
    cms_info = get_cms_info(cms_id)
    data = user_adding_platform[user_id]['data']
    
    # Получаем URL сайта (может быть в разных полях)
    url = data.get('url') or data.get('shop_url') or data.get('portal_url') or data.get('site_url', '')
    
    # ========== ПРОВЕРКА УНИКАЛЬНОСТИ ==========
    uniqueness = check_global_platform_uniqueness('website', url)
    if not uniqueness['is_unique']:
        # Платформа уже подключена у другого пользователя
        owner_display = f"@{uniqueness['owner_username']}" if uniqueness['owner_username'] else f"ID: {uniqueness['owner_id']}"
        
        text = (
            "❌ <b>ПЛАТФОРМА УЖЕ ПОДКЛЮЧЕНА</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"🌐 <b>Сайт:</b> {escape_html(url)}\n\n"
            "⚠️ Этот сайт уже подключен к другому аккаунту.\n\n"
            "Каждая платформа может быть подключена только к одному аккаунту в системе.\n\n"
            "<i>💡 Если это ваш сайт, отключите его от другого аккаунта или обратитесь в поддержку.</i>"
        )
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🔙 Вернуться к подключениям", callback_data="settings_api_keys")
        )
        
        # Очищаем временное хранилище
        del user_adding_platform[user_id]
        
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')
        return
    # ==========================================
    
    # Формируем объект подключения
    connection = {
        'url': url,
        'cms': cms_info['name'],
        'cms_id': cms_id,
        'status': 'active',  # В реальности нужна проверка подключения
        'api_data': data,
        'added_at': None  # БД добавит timestamp
    }
    
    # Получаем текущие подключения
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    if not isinstance(connections, dict):
        connections = {}
    
    websites = connections.get('websites', [])
    websites.append(connection)
    connections['websites'] = websites
    
    # Сохраняем в БД
    db.update_user(user_id, platform_connections=connections)
    
    # Очищаем временное хранилище
    del user_adding_platform[user_id]
    
    # Отправляем подтверждение
    text = (
        f"✅ <b>{cms_info['name']} ПОДКЛЮЧЕН!</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"🌐 <b>Сайт:</b> {escape_html(url)}\n"
        f"🟢 <b>Статус:</b> Активен\n\n"
        f"Теперь вы можете использовать этот сайт для публикации контента!"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🔌 Мои подключения", callback_data="settings_api_keys"),
        types.InlineKeyboardButton("➕ Добавить еще", callback_data="add_platform_menu")
    )
    
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')


# ═══════════════════════════════════════════════════════════════
# ПОДКЛЮЧЕНИЕ САЙТА (WordPress) - СТАРЫЙ КОД ДЛЯ СОВМЕСТИМОСТИ
# ═══════════════════════════════════════════════════════════════


print("✅ handlers/platform_connections/website_cms.py загружен")
