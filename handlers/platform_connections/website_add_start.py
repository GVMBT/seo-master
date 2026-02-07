"""
Подключение Website - начало процесса
"""
from telebot import types
from loader import bot, db
from utils import escape_html
from .utils import check_global_platform_uniqueness, user_adding_platform
import json


@bot.callback_query_handler(func=lambda call: call.data == "add_platform_website")
def add_platform_website_start(call):
    """Начало подключения сайта - перенаправляем на WordPress"""
    # Перенаправляем на новый обработчик WordPress
    call.data = "add_cms_wordpress"
    add_cms_start(call)
    
    text = (
        "🌐 <b>ПОДКЛЮЧЕНИЕ САЙТА</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "<b>Шаг 1 из 3:</b> URL сайта\n\n"
        "Отправьте адрес вашего WordPress сайта.\n\n"
        "<b>Пример:</b> <code>https://mysite.com</code>\n\n"
        "<i>💡 Убедитесь что у вас WordPress сайт с установленным плагином REST API</i>"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("❌ Отмена", callback_data="add_platform_menu")
    )
    
    # Устанавливаем режим ожидания
    user_adding_platform[user_id] = {
        'type': 'website',
        'step': 'url',
        'data': {}
    }
    
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
    
    bot.answer_callback_query(call.id, "📝 Ожидаю URL сайта...")


# Обработчик ввода данных для подключения
@bot.message_handler(func=lambda message: message.from_user.id in user_adding_platform)
def handle_platform_input(message):
    """Обработка ввода данных подключения"""
    user_id = message.from_user.id
    
    if user_id not in user_adding_platform:
        return
    
    platform_data = user_adding_platform[user_id]
    platform_type = platform_data['type']
    step = platform_data['step']
    
    # ============ САЙТ ============
    if platform_type == 'website':
        if step == 'url':
            # Сохраняем URL
            url = message.text.strip()
            
            # Валидация URL
            if not url.startswith('http'):
                url = 'https://' + url
            
            platform_data['data']['url'] = url
            platform_data['step'] = 'username'
            
            text = (
                "🌐 <b>ПОДКЛЮЧЕНИЕ САЙТА</b>\n"
                "━━━━━━━━━━━━━━\n\n"
                f"✅ URL: <code>{escape_html(url)}</code>\n\n"
                "<b>Шаг 2 из 3:</b> Логин администратора\n\n"
                "Отправьте логин пользователя WordPress с правами администратора.\n\n"
                "<b>Пример:</b> <code>admin</code>"
            )
            
            bot.send_message(message.chat.id, text, parse_mode='HTML')
            
        elif step == 'username':
            # Сохраняем username
            username = message.text.strip()
            platform_data['data']['username'] = username
            platform_data['step'] = 'password'
            
            text = (
                "🌐 <b>ПОДКЛЮЧЕНИЕ САЙТА</b>\n"
                "━━━━━━━━━━━━━━\n\n"
                f"✅ URL: <code>{escape_html(platform_data['data']['url'])}</code>\n"
                f"✅ Логин: <code>{escape_html(username)}</code>\n\n"
                "<b>Шаг 3 из 3:</b> Пароль приложения\n\n"
                "📝 <b>Как получить пароль приложения:</b>\n\n"
                "1. Войдите в WordPress админ-панель\n"
                "2. Пользователи → Ваш профиль\n"
                "3. Прокрутите вниз до \"Пароли приложений\"\n"
                "4. Создайте новый пароль приложения\n"
                "5. Отправьте его сюда\n\n"
                "⚠️ <b>Пароль будет автоматически удален после сохранения!</b>"
            )
            
            bot.send_message(message.chat.id, text, parse_mode='HTML')
            
        elif step == 'password':
            # Сохраняем пароль и завершаем
            password = message.text.strip()
            
            # Удаляем сообщение с паролем
            try:
                bot.delete_message(message.chat.id, message.message_id)
            except Exception:
                pass
            
            # ========== ПРОВЕРКА УНИКАЛЬНОСТИ ==========
            url = platform_data['data']['url']
            uniqueness = check_global_platform_uniqueness('website', url)
            if not uniqueness['is_unique']:
                # Платформа уже подключена
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
                
                del user_adding_platform[user_id]
                bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')
                return
            # ==========================================
            
            # Сохраняем подключение
            user = db.get_user(user_id)
            connections = user.get('platform_connections', {})
            
            if not isinstance(connections, dict):
                connections = {}
            
            if 'websites' not in connections:
                connections['websites'] = []
            
            # Добавляем новый сайт
            connections['websites'].append({
                'url': platform_data['data']['url'],
                'username': platform_data['data']['username'],
                'password': password,  # В реальности нужно шифровать!
                'added_at': 'NOW()',
                'status': 'active'
            })
            
            # Обновляем в БД
            db.cursor.execute("""
                UPDATE users 
                SET platform_connections = %s::jsonb
                WHERE id = %s
            """, (json.dumps(connections), user_id))
            db.conn.commit()
            
            # Убираем из ожидания
            del user_adding_platform[user_id]
            
            text = (
                "✅ <b>САЙТ ПОДКЛЮЧЕН!</b>\n"
                "━━━━━━━━━━━━━━\n\n"
                f"🌐 URL: <code>{escape_html(platform_data['data']['url'])}</code>\n"
                f"👤 Логин: <code>{escape_html(platform_data['data']['username'])}</code>\n"
                f"🔒 Пароль: сохранен\n\n"
                "Теперь вы можете публиковать контент на этот сайт напрямую из бота!"
            )
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("🔌 Мои подключения", callback_data="settings_api_keys"),
                types.InlineKeyboardButton("➕ Добавить ещё", callback_data="add_platform_menu")
            )
            
            bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    
    # ============================================================================
    # VK ОБРАБОТКА УДАЛЕНА
    # ============================================================================
    # Весь VK OAuth теперь в handlers/vk_integration/
    # ============================================================================


print("✅ handlers/platform_connections/website_add_start.py загружен")
