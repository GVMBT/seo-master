# -*- coding: utf-8 -*-
"""
Подключение VK через токены (два способа)
"""
from telebot import types
from loader import bot, db
import json


@bot.callback_query_handler(func=lambda call: call.data == 'add_platform_vk')
def handle_vk_connection_choice(call):
    """
    Подключение VK через универсальный токен
    """
    user_id = call.from_user.id
    
    bot.answer_callback_query(call.id)
    
    # Красивая инструкция с vkhost.github.io
    message_text = (
        "🔵 <b>Подключение ВКонтакте</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "Получите <b>универсальный токен</b> который работает для:\n"
        "✅ Вашей личной страницы\n"
        "✅ Всех ваших групп и сообществ\n"
        "✅ Публикации с фото и текстом\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "<b>📋 Пошаговая инструкция:</b>\n\n"
        
        "<b>1️⃣ Откройте генератор токенов</b>\n"
        "Перейдите по ссылке:\n"
        "🔗 <a href='https://vkhost.github.io'>vkhost.github.io</a>\n\n"
        
        "<b>2️⃣ Выберите приложение</b>\n"
        "Нажмите на кнопку <b>VK Admin</b>\n"
        "(первая кнопка в верхнем ряду)\n\n"
        
        "<b>3️⃣ Войдите в VK</b>\n"
        "Авторизуйтесь в своём аккаунте\n\n"
        
        "<b>4️⃣ Скопируйте токен из URL</b>\n"
        "⚠️ <b>ВАЖНО!</b> После авторизации вас перенаправит на страницу.\n"
        "В адресной строке браузера появится длинная ссылка:\n\n"
        
        "<code>https://oauth.vk.com/blank.html#access_token=vk1.a.XXXX...&expires_in...</code>\n\n"
        
        "Вам нужно скопировать <b>только токен</b> - всё между:\n"
        "• Началом: <code>access_token=</code>\n"
        "• Концом: <code>&expires_in</code>\n\n"
        
        "Токен начинается с <code>vk1.a.</code> и дальше много букв/цифр\n\n"
        
        "<b>5️⃣ Отправьте боту</b>\n"
        "Просто вставьте токен следующим сообщением\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "💡 <b>Важно знать:</b>\n"
        "• Один токен работает для всех групп\n"
        "• Можно подключить всё сразу или по одному\n"
        "• Токен бессрочный (не истекает)\n"
        "• Полностью безопасно через официальный OAuth\n\n"
        
        "🔒 <i>Токен хранится в зашифрованном виде</i>"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            "❌ Отмена",
            callback_data="back_to_add_platform"
        )
    )
    
    # Устанавливаем флаг ожидания токена (всегда как personal)
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    if isinstance(connections, str):
        connections = json.loads(connections)
    
    connections['_vk_awaiting_token'] = {
        'type': 'personal',  # Всегда личный токен
        'timestamp': str(call.message.date)
    }
    
    db.cursor.execute("""
        UPDATE users
        SET platform_connections = %s::jsonb
        WHERE id = %s
    """, (json.dumps(connections), user_id))
    db.conn.commit()
    
    bot.edit_message_text(
        message_text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=markup,
        disable_web_page_preview=True  # Отключаем превью ссылки
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('vk_method_group_'))
def handle_vk_group_token_instruction(call):
    """
    Инструкция для токена сообщества
    """
    user_id = call.from_user.id
    
    bot.answer_callback_query(call.id)
    
    message_text = (
        "📝 <b>Подключение через токен сообщества</b>\n\n"
        "<b>Шаг 1:</b> Зайдите в настройки вашей группы VK:\n"
        "Управление → <b>Дополнительно</b> → Работа с API\n\n"
        "<b>Шаг 2:</b> Создайте ключ доступа:\n"
        "• Нажмите <b>Создать ключ</b>\n"
        "• <b>ОБЯЗАТЕЛЬНО</b> поставьте галочки:\n"
        "  ✅ Разрешить приложению доступ к управлению сообществом\n"
        "  ✅ Разрешить приложению доступ к <b>фотографиям</b> сообщества\n"
        "  ✅ Разрешить приложению доступ к <b>стене</b> сообщества\n\n"
        "⚠️ <b>БЕЗ ЭТИХ ГАЛОЧЕК ПУБЛИКАЦИЯ НЕ БУДЕТ РАБОТАТЬ!</b>\n\n"
        "⚠️ <b>Если не подключена двухфакторная аутентификация:</b>\n"
        "1. Перейдите в VK ID → «Безопасность и вход»\n"
        "2. Способы входа → Двухфакторная аутентификация → Вкл.\n"
        "3. Подключите телефон\n"
        "4. Вернитесь в группу и создайте ключ\n"
        "5. Подтвердите действие через СМС\n\n"
        "<b>Шаг 3:</b> Скопируйте появившийся токен\n"
        "(начинается с <code>vk1.a.</code>)\n\n"
        "<b>Шаг 4:</b> Отправьте токен боту\n"
        "Просто вставьте и отправьте следующим сообщением\n\n"
        "⚠️ <b>Важно:</b> Токен действует только для ОДНОЙ группы!"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "◀️ Назад к выбору способа",
            callback_data="add_platform_vk"
        )
    )
    
    bot.edit_message_text(
        message_text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=markup
    )
    
    # Устанавливаем состояние ожидания токена
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    if isinstance(connections, str):
        connections = json.loads(connections)
    
    connections['_vk_awaiting_token'] = {
        'type': 'group',
        'message_id': call.message.message_id
    }
    
    db.cursor.execute("""
        UPDATE users
        SET platform_connections = %s::jsonb
        WHERE id = %s
    """, (json.dumps(connections), user_id))
    db.conn.commit()
    
    # Отправляем сообщение с кнопкой Отмена
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "❌ Отмена",
        callback_data="vk_cancel_token_input"
    ))
    
    bot.send_message(
        user_id,
        "💬 Теперь отправьте токен группы VK\n\n"
        "Или нажмите Отмена чтобы выйти:",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('vk_method_personal_'))
def handle_vk_personal_token_instruction(call):
    """
    Инструкция для личного токена
    """
    user_id = call.from_user.id
    
    bot.answer_callback_query(call.id)
    
    # Генерируем OAuth ссылку
    oauth_url = (
        f"https://oauth.vk.com/authorize"
        f"?client_id=5354809"
        f"&scope=wall,photos,groups,offline"
        f"&redirect_uri=https://oauth.vk.com/blank.html"
        f"&display=page"
        f"&response_type=token"
        f"&v=5.131"
    )
    
    message_text = (
        "👤 <b>Подключение через личный токен</b>\n\n"
        "⚠️ <b>ВАЖНО:</b> VK ограничивает публикации на личные страницы.\n"
        "Рекомендуем использовать <b>токен группы</b> вместо личного.\n\n"
        "<b>Шаг 1:</b> Нажмите на кнопку ниже ⬇️\n\n"
        "<b>Шаг 2:</b> Разрешите доступ к:\n"
        "• Фотографиям\n"
        "• Стене\n"
        "• Группам\n"
        "• Оффлайн доступу\n\n"
        "<b>Шаг 3:</b> После разрешения вы увидите адресную строку:\n"
        "<code>https://oauth.vk.com/blank.html#access_token=vk1.a....</code>\n\n"
        "<b>Шаг 4:</b> Скопируйте весь токен после <code>access_token=</code> и до <code>&expires_in</code>\n\n"
        "<b>Шаг 5:</b> Отправьте токен боту следующим сообщением\n\n"
        "💡 <b>Токен начинается с:</b> <code>vk1.a.</code>"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "🔵 Получить токен VK",
            url=oauth_url
        ),
        types.InlineKeyboardButton(
            "◀️ Назад к выбору способа",
            callback_data="add_platform_vk"
        )
    )
    
    bot.edit_message_text(
        message_text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=markup
    )
    
    # Устанавливаем состояние ожидания токена
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    if isinstance(connections, str):
        connections = json.loads(connections)
    
    connections['_vk_awaiting_token'] = {
        'type': 'personal',
        'message_id': call.message.message_id
    }
    
    db.cursor.execute("""
        UPDATE users
        SET platform_connections = %s::jsonb
        WHERE id = %s
    """, (json.dumps(connections), user_id))
    db.conn.commit()
    
    # Отправляем сообщение с кнопкой Отмена
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "❌ Отмена",
        callback_data="vk_cancel_token_input"
    ))
    
    bot.send_message(
        user_id,
        "💬 Теперь отправьте личный токен VK\n\n"
        "Или нажмите Отмена чтобы выйти:",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data == 'vk_cancel_token_input')
def handle_vk_cancel_token(call):
    """
    Отмена ввода VK токена
    """
    user_id = call.from_user.id
    
    bot.answer_callback_query(call.id, "❌ Ввод токена отменён")
    
    # Удаляем флаг ожидания
    try:
        user = db.get_user(user_id)
        connections = user.get('platform_connections', {})
        if isinstance(connections, str):
            connections = json.loads(connections)
        
        if '_vk_awaiting_token' in connections:
            del connections['_vk_awaiting_token']
            
            db.cursor.execute("""
                UPDATE users
                SET platform_connections = %s::jsonb
                WHERE id = %s
            """, (json.dumps(connections), user_id))
            db.conn.commit()
    except Exception as e:
        print(f"Ошибка при отмене VK токена: {e}")
    
    # Удаляем сообщение
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    # Возвращаемся в главное меню
    bot.send_message(
        user_id,
        "✅ Ввод токена отменён.\n\n"
        "Используйте /start чтобы вернуться в меню."
    )


print("✅ handlers/platform_connections/vk_direct.py загружен")
