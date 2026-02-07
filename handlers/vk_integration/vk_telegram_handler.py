# -*- coding: utf-8 -*-
"""
Telegram обработчик для VK авторизации (OAuth через ngrok)
"""
from telebot import types
from loader import bot, db
from .vk_config import get_vk_auth_url


@bot.callback_query_handler(func=lambda call: call.data == "add_platform_vk")
def handle_connect_vk(call):
    """
    Обработчик кнопки "Подключить VK" 
    Отправляет пользователю ссылку для авторизации через OAuth
    """
    user_id = call.from_user.id

    # Генерируем URL для авторизации
    auth_url = get_vk_auth_url(user_id)

    text = (
        "🔑 <b>ПОДКЛЮЧЕНИЕ ВКОНТАКТЕ</b>\n\n"
        "Для подключения VK аккаунта нажмите кнопку ниже.\n\n"
        "✅ <b>Что это даст:</b>\n"
        "• Автоматическая публикация постов в VK\n"
        "• Управление сообществом\n"
        "• Получение статистики\n\n"
        "🔒 Ваши данные в безопасности."
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "🔑 Войти через VK",
            url=auth_url
        )
    )
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data="add_platform_menu"
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


@bot.callback_query_handler(func=lambda call: call.data == "check_vk_connection")
def handle_check_vk_connection(call):
    """
    Проверяет статус подключения VK
    """
    user_id = call.from_user.id

    # Получаем пользователя
    user = db.get_user(user_id)
    if not user:
        bot.answer_callback_query(call.id, "❌ Пользователь не найден")
        return

    # Проверяем подключение VK
    platform_connections = user.get('platform_connections', {})
    if isinstance(platform_connections, str):
        import json
        platform_connections = json.loads(platform_connections)

    vk_connection = platform_connections.get('vk')

    if vk_connection and vk_connection.get('status') == 'active':
        text = (
            "✅ <b>VK ПОДКЛЮЧЕН</b>\n\n"
            f"👤 Имя: {vk_connection.get('first_name', '')} {vk_connection.get('last_name', '')}\n"
            f"🆔 VK ID: {vk_connection.get('user_id')}\n"
            f"📧 Email: {vk_connection.get('email', 'Не указан')}\n\n"
            "Вы можете публиковать посты в VK!"
        )

        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "🔌 Отключить VK",
                callback_data="disconnect_vk"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data="platforms"
            )
        )
    else:
        text = (
            "❌ <b>VK НЕ ПОДКЛЮЧЕН</b>\n\n"
            "Для публикации в VK необходимо\n"
            "подключить ваш аккаунт."
        )

        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "🔑 Подключить VK",
                callback_data="add_platform_vk"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data="platforms"
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


@bot.callback_query_handler(func=lambda call: call.data == "disconnect_vk")
def handle_disconnect_vk(call):
    """
    Отключает VK от аккаунта
    """
    user_id = call.from_user.id

    try:
        # Получаем пользователя
        user = db.get_user(user_id)
        if not user:
            bot.answer_callback_query(call.id, "❌ Пользователь не найден")
            return

        # Удаляем VK подключение
        import json
        platform_connections = user.get('platform_connections', {})
        if isinstance(platform_connections, str):
            platform_connections = json.loads(platform_connections)

        if 'vk' in platform_connections:
            del platform_connections['vk']

        db.cursor.execute("""
            UPDATE users
            SET platform_connections = %s::jsonb
            WHERE id = %s
        """, (json.dumps(platform_connections), user_id))

        db.conn.commit()

        bot.answer_callback_query(call.id, "✅ VK отключен", show_alert=True)

        # Возвращаемся в меню проверки
        call.data = "check_vk_connection"
        handle_check_vk_connection(call)

    except Exception as e:
        print(f"❌ Ошибка отключения VK: {e}")
        bot.answer_callback_query(call.id, "❌ Ошибка отключения")


print("✅ VK Telegram Handler загружен")
