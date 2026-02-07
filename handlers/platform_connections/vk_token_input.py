# -*- coding: utf-8 -*-
"""
Обработка VK токенов от пользователей
"""
from telebot import types
from loader import bot, db
import requests
import json
import re


@bot.message_handler(func=lambda message: check_vk_token_awaiting(message))
def handle_vk_token_input(message):
    """
    Обработка токена от пользователя
    """
    user_id = message.from_user.id
    token = message.text.strip()
    
    # Удаляем сообщение с токеном для безопасности
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass
    
    # Проверяем формат токена
    if not token.startswith('vk1.'):
        # КРИТИЧНО: Добавляем кнопку Отмена
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "❌ Отмена ввода токена",
            callback_data="vk_cancel_token_input"
        ))
        
        bot.send_message(
            user_id,
            "❌ Неверный формат токена!\n\n"
            "Токен должен начинаться с <code>vk1.a.</code> или <code>vk1.g.</code>\n\n"
            "Попробуйте ещё раз.",
            parse_mode='HTML',
            reply_markup=markup
        )
        return
    
    # Получаем тип токена из состояния (всегда personal теперь)
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    if isinstance(connections, str):
        connections = json.loads(connections)
    
    token_type = connections.get('_vk_awaiting_token', {}).get('type', 'personal')
    
    print(f"🔍 Проверка VK токена, тип: {token_type}")
    
    # Проверяем валидность токена
    # ВСЕГДА проверяем как личный токен (универсальный)
    try:
        # Проверяем токен через users.get
        response = requests.get(
            "https://api.vk.com/method/users.get",
            params={
                "access_token": token,
                "v": "5.131",
                "fields": "photo_200"
            },
            timeout=10
        )
        
        result = response.json()
        
        if 'error' in result:
            error_msg = result['error'].get('error_msg', 'Unknown error')
            
            # КРИТИЧНО: Добавляем кнопку Отмена
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(
                "❌ Отмена ввода токена",
                callback_data="vk_cancel_token_input"
            ))
            
            bot.send_message(
                user_id,
                f"❌ Ошибка проверки токена:\n\n"
                f"<code>{error_msg}</code>\n\n"
                f"Убедитесь что вы получили токен через vkhost.github.io → VK Admin\n\n"
                f"Токен должен начинаться с <code>vk1.a.</code>",
                parse_mode='HTML',
                reply_markup=markup
            )
            return
        
        if not result.get('response') or len(result['response']) == 0:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(
                "❌ Отмена ввода токена",
                callback_data="vk_cancel_token_input"
            ))
            
            bot.send_message(
                user_id,
                "❌ Не удалось получить информацию о пользователе.\n\n"
                "Проверьте правильность токена и попробуйте снова.",
                reply_markup=markup
            )
            return
        
        vk_user = result['response'][0]
        vk_id = str(vk_user['id'])
        vk_name = f"{vk_user.get('first_name', '')} {vk_user.get('last_name', '')}".strip()
        screen_name = f"id{vk_id}"
        
        print(f"✅ VK личный токен валиден: {vk_name} (ID: {vk_id})")
        
        # Получаем список групп где пользователь администратор
        user_groups = []
        
        groups_response = requests.get(
            "https://api.vk.com/method/groups.get",
            params={
                "access_token": token,
                "v": "5.131",
                "filter": "admin,editor",  # Только где админ/редактор
                "extended": 1,
                "fields": "members_count,photo_200"
            },
            timeout=10
        )
        
        groups_result = groups_response.json()
        
        if 'response' in groups_result and 'items' in groups_result['response']:
            for group in groups_result['response']['items']:
                user_groups.append({
                    'id': group['id'],
                    'name': group['name'],
                    'screen_name': group.get('screen_name', ''),
                    'photo_200': group.get('photo_200', ''),
                    'members_count': group.get('members_count', 0)
                })
        
        print(f"📝 Найдено групп: {len(user_groups)}")
        
        # Сохраняем временные данные для выбора
        user = db.get_user(user_id)
        connections = user.get('platform_connections', {})
        if isinstance(connections, str):
            connections = json.loads(connections)
        
        connections['_vk_selection_pending'] = {
            'access_token': token,
            'refresh_token': None,
            'device_id': None,
            'expires_in': 0,  # Бессрочный
            'user_id': vk_id,
            'email': None,
            'available_groups': user_groups,
            'token_type': 'personal'  # Всегда personal
        }
        
        # Удаляем флаг ожидания
        if '_vk_awaiting_token' in connections:
            del connections['_vk_awaiting_token']
        
        db.cursor.execute("""
            UPDATE users
            SET platform_connections = %s::jsonb
            WHERE id = %s
        """, (json.dumps(connections), user_id))
        db.conn.commit()
        
        # Отправляем меню выбора с красивым оформлением
        groups_word = "группу" if len(user_groups) == 1 else "группы" if len(user_groups) < 5 else "групп"
        
        message_text = (
            "✅ <b>Токен успешно проверен!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            f"👤 <b>Ваш аккаунт:</b> {vk_name}\n"
            f"📝 <b>Доступно {groups_word}:</b> {len(user_groups)}\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            "<b>Выберите что хотите подключить:</b>\n"
            "<i>💡 Можно выбрать несколько нажимая на кнопки</i>"
        )
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        # Всегда показываем личную страницу с чекбоксом
        markup.add(
            types.InlineKeyboardButton(
                f"☐ Личная страница ({vk_name})",
                callback_data="vk_toggle_user"
            )
        )
        
        # Показываем все группы с чекбоксами
        for idx, group in enumerate(user_groups[:10]):
            group_name = group['name']
            members = group.get('members_count', 0)
            members_text = f" ({members:,})" if members > 0 else ""
            
            markup.add(
                types.InlineKeyboardButton(
                    f"☐ {group_name}{members_text}",
                    callback_data=f"vk_toggle_group_{idx}"
                )
            )
        
        # Кнопки действий
        markup.row(
            types.InlineKeyboardButton(
                "⚠️ Выберите хотя бы одно",
                callback_data="vk_select_confirm"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "❌ Отмена",
                callback_data=f"vk_select_cancel_{user_id}"
            )
        )
        
        bot.send_message(
            user_id,
            message_text,
            parse_mode='HTML',
            reply_markup=markup
        )
        
    except Exception as e:
        print(f"❌ Ошибка обработки токена: {e}")
        import traceback
        traceback.print_exc()
        
        bot.send_message(
            user_id,
            f"❌ Ошибка при проверке токена:\n\n"
            f"<code>{str(e)}</code>\n\n"
            f"Попробуйте получить токен заново.",
            parse_mode='HTML'
        )


def check_vk_token_awaiting(message):
    """
    Проверяет ожидает ли бот VK токен от пользователя
    """
    if not message.text:
        return False
    
    user_id = message.from_user.id
    
    try:
        user = db.get_user(user_id)
        connections = user.get('platform_connections', {})
        if isinstance(connections, str):
            connections = json.loads(connections)
        
        return '_vk_awaiting_token' in connections
    except Exception:
        return False


@bot.callback_query_handler(func=lambda call: call.data == 'vk_cancel_token_input')
def handle_vk_cancel_token_input(call):
    """
    Отмена ввода VK токена
    """
    user_id = call.from_user.id
    
    bot.answer_callback_query(call.id, "✅ Ввод токена отменён")
    
    # Удаляем флаг ожидания
    try:
        user = db.get_user(user_id)
        connections = user.get('platform_connections', {})
        if isinstance(connections, str):
            import json
            connections = json.loads(connections)
        
        if '_vk_awaiting_token' in connections:
            del connections['_vk_awaiting_token']
            
            import json
            db.cursor.execute("""
                UPDATE users
                SET platform_connections = %s::jsonb
                WHERE id = %s
            """, (json.dumps(connections), user_id))
            db.conn.commit()
            
            print(f"✅ Флаг _vk_awaiting_token удалён для user {user_id}")
    except Exception as e:
        print(f"❌ Ошибка при отмене VK токена: {e}")
    
    # Удаляем сообщение с ошибкой
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    # Отправляем подтверждение
    bot.send_message(
        user_id,
        "✅ Ввод VK токена отменён.\n\n"
        "Используйте /start чтобы вернуться в меню."
    )


print("✅ handlers/platform_connections/vk_token_input.py загружен")
