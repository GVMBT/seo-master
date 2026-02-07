"""
Обработка выбора VK профиля или группы после OAuth
"""
from telebot import types
from loader import bot, db
import json
import time


@bot.callback_query_handler(func=lambda call: call.data.startswith('vk_select_') or call.data.startswith('vk_toggle_'))
def handle_vk_selection(call):
    """
    Обработчик выбора VK профиля или группы
    
    Callback data:
    - vk_toggle_user - переключить выбор личной страницы
    - vk_toggle_group_{group_index} - переключить выбор группы
    - vk_select_confirm - подтвердить выбранное
    - vk_select_cancel_{user_id} - отмена
    
    Старые callback (для совместимости):
    - vk_select_user_{user_id} - выбор только личной страницы
    - vk_select_group_{user_id}_{group_index} - выбор только группы
    """
    user_id = call.from_user.id
    
    try:
        # Получаем пользователя и временные данные
        user = db.get_user(user_id)
        
        if not user:
            bot.answer_callback_query(call.id, "❌ Пользователь не найден")
            return
        
        connections = user.get('platform_connections', {})
        if isinstance(connections, str):
            connections = json.loads(connections)
        
        # Проверяем наличие временных данных выбора
        pending_data = connections.get('_vk_selection_pending')
        
        if not pending_data:
            bot.answer_callback_query(call.id, "❌ Данные выбора не найдены. Попробуйте подключить VK заново.")
            bot.delete_message(call.message.chat.id, call.message.message_id)
            return
        
        # ============================================
        # ОБРАБОТКА ОТМЕНЫ
        # ============================================
        
        if call.data.startswith('vk_select_cancel_'):
            # Удаляем временные данные
            del connections['_vk_selection_pending']
            
            db.cursor.execute("""
                UPDATE users
                SET platform_connections = %s::jsonb
                WHERE id = %s
            """, (json.dumps(connections), user_id))
            db.conn.commit()
            
            bot.answer_callback_query(call.id, "❌ Подключение отменено")
            
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton(
                    "🏠 Вернуться в меню",
                    callback_data="back_to_settings"
                )
            )
            
            bot.edit_message_text(
                "❌ Подключение VK отменено.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
            return
        
        # ============================================
        # НОВАЯ ЛОГИКА: МНОЖЕСТВЕННЫЙ ВЫБОР
        # ============================================
        
        # Получаем или создаём список выбранных
        if '_vk_selected' not in pending_data:
            pending_data['_vk_selected'] = []
        
        selected = pending_data['_vk_selected']
        
        # Обработка переключения выбора
        if call.data.startswith('vk_toggle_'):
            if call.data == 'vk_toggle_user':
                # Переключаем личную страницу
                if 'user' in selected:
                    selected.remove('user')
                else:
                    selected.append('user')
            elif call.data.startswith('vk_toggle_group_'):
                # Переключаем группу
                group_idx = int(call.data.split('_')[-1])
                group_key = f'group_{group_idx}'
                
                if group_key in selected:
                    selected.remove(group_key)
                else:
                    selected.append(group_key)
            
            # Сохраняем выбор
            pending_data['_vk_selected'] = selected
            connections['_vk_selection_pending'] = pending_data
            
            db.cursor.execute("""
                UPDATE users
                SET platform_connections = %s::jsonb
                WHERE id = %s
            """, (json.dumps(connections), user_id))
            db.conn.commit()
            
            # Обновляем сообщение с новыми чекбоксами
            _update_selection_message(call, pending_data, selected)
            bot.answer_callback_query(call.id)
            return
        
        # Обработка подтверждения выбора
        if call.data == 'vk_select_confirm':
            if len(selected) == 0:
                bot.answer_callback_query(call.id, "⚠️ Выберите хотя бы одно подключение", show_alert=True)
                return
            
            # Сохраняем выбранные подключения
            _save_selected_connections(call, user_id, pending_data, selected)
            return
        
        # ============================================
        # СТАРАЯ ЛОГИКА: Одиночный выбор (для совместимости)
        # ============================================
        
        # Парсим callback data
        parts = call.data.split('_')
        selection_type = parts[2]  # 'user' или 'group'
        
        # Получаем данные для сохранения
        access_token = pending_data['access_token']
        refresh_token = pending_data.get('refresh_token')
        device_id = pending_data.get('device_id')
        expires_in = pending_data.get('expires_in', 86400)
        vk_user_id = pending_data['user_id']
        email = pending_data.get('email')
        available_groups = pending_data.get('available_groups', [])
        
        # Импортируем VKOAuth для получения информации
        from handlers.vk_integration.vk_oauth import VKOAuth
        
        # Получаем информацию о пользователе VK
        vk_user_info = VKOAuth.get_user_info(access_token, vk_user_id)
        
        if not vk_user_info:
            bot.answer_callback_query(call.id, "❌ Не удалось получить информацию VK")
            return
        
        # Вычисляем время истечения токена
        # Если expires_in = 0 (бессрочный) → ставим expires_at = 0
        if expires_in == 0:
            expires_at = 0  # Бессрочный токен
            print(f"ℹ️ Бессрочный токен (expires_in=0), устанавливаем expires_at=0")
        else:
            expires_at = int(time.time()) + expires_in
            print(f"ℹ️ Токен с ограниченным сроком: expires_at={expires_at}")
        
        # Инициализируем массив VK подключений
        if 'vks' not in connections:
            connections['vks'] = []
        
        vks = connections['vks']
        if not isinstance(vks, list):
            vks = []
        
        # ============================================
        # ВЫБОР ЛИЧНОЙ СТРАНИЦЫ
        # ============================================
        
        if selection_type == 'user':
            # Проверка глобальной уникальности
            db.cursor.execute("""
                SELECT u.id, u.username
                FROM users u
                WHERE u.platform_connections::text LIKE %s
            """, (f'%"user_id": "{vk_user_id}"%',))
            
            existing_users = db.cursor.fetchall()
            
            if existing_users:
                for existing_user in existing_users:
                    existing_user_id = existing_user.get('id') if isinstance(existing_user, dict) else existing_user[0]
                    
                    if existing_user_id != user_id:
                        bot.answer_callback_query(call.id, "❌ Эта страница уже подключена у другого пользователя")
                        return
            
            # Проверка у текущего пользователя
            for existing_vk in vks:
                if existing_vk.get('user_id') == vk_user_id and existing_vk.get('type') == 'user':
                    bot.answer_callback_query(call.id, "❌ Эта страница уже подключена")
                    return
            
            # Создаём подключение личной страницы
            vk_connection = {
                'type': 'user',
                'id': vk_user_id,  # ID для поиска
                'user_id': vk_user_id,  # Дублируем для совместимости
                'access_token': access_token,
                'refresh_token': refresh_token,
                'device_id': device_id,
                'expires_at': expires_at,
                'email': email,
                'first_name': vk_user_info.get('first_name'),
                'last_name': vk_user_info.get('last_name'),
                'photo': vk_user_info.get('photo_200'),
                'status': 'active',
                'connected_at': 'now()',
                'group_name': f"{vk_user_info.get('first_name', '')} {vk_user_info.get('last_name', '')}".strip()
            }
            
            vks.append(vk_connection)
            
            bot.answer_callback_query(call.id, "✅ Личная страница подключена!")
            success_text = f"✅ Подключена личная страница VK:\n👤 {vk_connection['group_name']}"
        
        # ============================================
        # ВЫБОР ГРУППЫ
        # ============================================
        
        elif selection_type == 'group':
            # Получаем индекс группы
            group_index = int(parts[4])
            
            if group_index >= len(available_groups):
                bot.answer_callback_query(call.id, "❌ Группа не найдена")
                return
            
            selected_group = available_groups[group_index]
            group_id = selected_group['id']
            
            # Проверка глобальной уникальности
            db.cursor.execute("""
                SELECT u.id, u.username
                FROM users u
                WHERE u.platform_connections::text LIKE %s
            """, (f'%"group_id": {group_id}%',))
            
            existing_users = db.cursor.fetchall()
            
            if existing_users:
                for existing_user in existing_users:
                    existing_user_id = existing_user.get('id') if isinstance(existing_user, dict) else existing_user[0]
                    
                    if existing_user_id != user_id:
                        bot.answer_callback_query(call.id, "❌ Эта группа уже подключена у другого пользователя")
                        return
            
            # Проверка у текущего пользователя
            for existing_vk in vks:
                if existing_vk.get('group_id') == group_id:
                    bot.answer_callback_query(call.id, "❌ Эта группа уже подключена")
                    return
            
            # Создаём подключение группы
            # ВАЖНО: Определяем тип токена из pending_data
            token_type = pending_data.get('token_type', 'personal')
            
            # Если токен личный (user/personal), оставляем type='user'
            # Если токен группы (group), используем type='group'
            if token_type == 'group':
                connection_type = 'group'
            else:
                connection_type = 'user'  # Личный токен, но публикация в группу
            
            vk_connection = {
                'type': connection_type,  # 'user' для личного токена, 'group' для токена группы
                'id': str(-group_id),  # ID для поиска (отрицательный как строка)
                'user_id': vk_user_id,  # ID владельца токена
                'group_id': -group_id,  # ОТРИЦАТЕЛЬНЫЙ для VK API!
                'access_token': access_token,
                'refresh_token': refresh_token,
                'device_id': device_id,
                'expires_at': expires_at,
                'email': email,
                'first_name': vk_user_info.get('first_name'),
                'last_name': vk_user_info.get('last_name'),
                'photo': selected_group.get('photo_200'),
                'status': 'active',
                'connected_at': 'now()',
                'group_name': selected_group['name'],
                'screen_name': selected_group.get('screen_name', ''),
                'members_count': selected_group.get('members_count', 0)
            }
            
            vks.append(vk_connection)
            
            members_text = f" ({vk_connection['members_count']:,} подписчиков)" if vk_connection['members_count'] > 0 else ""
            bot.answer_callback_query(call.id, "✅ Группа подключена!")
            success_text = f"✅ Подключена группа VK:\n📝 {vk_connection['group_name']}{members_text}"
        
        else:
            bot.answer_callback_query(call.id, "❌ Неизвестный тип выбора")
            return
        
        # ============================================
        # СОХРАНЕНИЕ В БД
        # ============================================
        
        connections['vks'] = vks
        
        # Удаляем временные данные
        if '_vk_selection_pending' in connections:
            del connections['_vk_selection_pending']
        
        db.cursor.execute("""
            UPDATE users
            SET platform_connections = %s::jsonb
            WHERE id = %s
        """, (json.dumps(connections), user_id))
        db.conn.commit()
        
        print(f"✅ VK подключение сохранено для пользователя {user_id}")
        print(f"   Тип: {vk_connection['type']}")
        print(f"   Название: {vk_connection['group_name']}")
        
        # Обновляем сообщение с кнопкой возврата
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "🏠 Вернуться в меню",
                callback_data="back_to_settings"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "➕ Добавить еще площадку",
                callback_data="add_platform"
            )
        )
        
        bot.edit_message_text(
            success_text + "\n\n💡 Можете подключить еще группы через 'Добавить площадку'",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        
    except Exception as e:
        print(f"❌ Ошибка обработки выбора VK: {e}")
        import traceback
        traceback.print_exc()
        bot.answer_callback_query(call.id, f"❌ Ошибка: {str(e)}")


# ═══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ МНОЖЕСТВЕННОГО ВЫБОРА
# ═══════════════════════════════════════════════════════════════

def _update_selection_message(call, pending_data, selected):
    """Обновляет сообщение с чекбоксами"""
    vk_user_id = pending_data['user_id']
    available_groups = pending_data.get('available_groups', [])
    
    # Импортируем для получения имени
    from handlers.vk_integration.vk_oauth import VKOAuth
    vk_user_info = VKOAuth.get_user_info(pending_data['access_token'], vk_user_id)
    vk_name = f"{vk_user_info.get('first_name', '')} {vk_user_info.get('last_name', '')}".strip()
    
    # Формируем красивый текст
    selected_count = len(selected)
    groups_word = "группу" if len(available_groups) == 1 else "группы" if len(available_groups) < 5 else "групп"
    
    # Статус выбора
    if selected_count == 0:
        status_emoji = "⚠️"
        status_text = "Ничего не выбрано"
    elif selected_count == 1:
        status_emoji = "✅"
        status_text = "Выбрано 1 подключение"
    else:
        status_emoji = "✅"
        status_text = f"Выбрано {selected_count} подключения"
    
    text = (
        "✅ <b>Токен успешно проверен!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        f"👤 <b>Ваш аккаунт:</b> {vk_name}\n"
        f"📝 <b>Доступно {groups_word}:</b> {len(available_groups)}\n\n"
        
        f"{status_emoji} <b>Статус:</b> {status_text}\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "<b>Выберите что подключить:</b>\n"
        "<i>Нажимайте на кнопки чтобы выбрать/отменить</i>"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    # Кнопка личной страницы с чекбоксом
    user_checked = 'user' in selected
    user_icon = "✅" if user_checked else "☐"
    markup.add(
        types.InlineKeyboardButton(
            f"{user_icon} Личная страница ({vk_name})",
            callback_data="vk_toggle_user"
        )
    )
    
    # Кнопки групп с чекбоксами
    for idx, group in enumerate(available_groups[:10]):
        group_key = f'group_{idx}'
        group_checked = group_key in selected
        group_icon = "✅" if group_checked else "☐"
        
        group_name = group['name']
        members = group.get('members_count', 0)
        members_text = f" ({members:,})" if members > 0 else ""
        
        markup.add(
            types.InlineKeyboardButton(
                f"{group_icon} {group_name}{members_text}",
                callback_data=f"vk_toggle_group_{idx}"
            )
        )
    
    # Кнопки действий
    if selected_count > 0:
        confirm_text = f"✅ Подключить выбранное ({selected_count})"
    else:
        confirm_text = "⚠️ Выберите хотя бы одно"
    
    markup.row(
        types.InlineKeyboardButton(
            confirm_text,
            callback_data="vk_select_confirm"
        )
    )
    markup.add(
        types.InlineKeyboardButton(
            "❌ Отмена",
            callback_data=f"vk_select_cancel_{call.from_user.id}"
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
        pass  # Сообщение не изменилось


def _save_selected_connections(call, user_id, pending_data, selected):
    """Сохраняет выбранные подключения"""
    from handlers.vk_integration.vk_oauth import VKOAuth
    
    access_token = pending_data['access_token']
    refresh_token = pending_data.get('refresh_token')
    device_id = pending_data.get('device_id')
    expires_in = pending_data.get('expires_in', 0)
    vk_user_id = pending_data['user_id']
    email = pending_data.get('email')
    available_groups = pending_data.get('available_groups', [])
    
    # Получаем информацию о пользователе
    vk_user_info = VKOAuth.get_user_info(access_token, vk_user_id)
    
    if not vk_user_info:
        bot.answer_callback_query(call.id, "❌ Не удалось получить информацию VK")
        return
    
    # Вычисляем expires_at
    if expires_in == 0:
        expires_at = 0
    else:
        expires_at = int(time.time()) + expires_in
    
    # Получаем текущие подключения
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {})
    if isinstance(connections, str):
        connections = json.loads(connections)
    
    if 'vks' not in connections:
        connections['vks'] = []
    
    vks = connections['vks']
    if not isinstance(vks, list):
        vks = []
    
    connected_names = []
    
    # Сохраняем личную страницу если выбрана
    if 'user' in selected:
        # Проверяем что не подключена
        user_exists = any(
            str(vk.get('user_id')) == str(vk_user_id) and not vk.get('group_id')
            for vk in vks
        )
        
        if not user_exists:
            vk_connection = {
                'type': 'user',
                'id': str(vk_user_id),
                'user_id': vk_user_id,
                'access_token': access_token,
                'refresh_token': refresh_token,
                'device_id': device_id,
                'expires_at': expires_at,
                'email': email,
                'first_name': vk_user_info.get('first_name'),
                'last_name': vk_user_info.get('last_name'),
                'photo': vk_user_info.get('photo_200'),
                'status': 'active',
                'connected_at': 'now()',
                'group_name': f"{vk_user_info.get('first_name', '')} {vk_user_info.get('last_name', '')}".strip()
            }
            vks.append(vk_connection)
            connected_names.append(f"👤 {vk_connection['group_name']}")
    
    # Сохраняем выбранные группы
    for item in selected:
        if item.startswith('group_'):
            group_idx = int(item.split('_')[1])
            
            if group_idx >= len(available_groups):
                continue
            
            selected_group = available_groups[group_idx]
            group_id = selected_group['id']
            
            # Проверяем что не подключена
            group_exists = any(
                vk.get('group_id') == -group_id
                for vk in vks
            )
            
            if not group_exists:
                token_type = pending_data.get('token_type', 'personal')
                connection_type = 'user' if token_type != 'group' else 'group'
                
                vk_connection = {
                    'type': connection_type,
                    'id': str(-group_id),
                    'user_id': vk_user_id,
                    'group_id': -group_id,
                    'access_token': access_token,
                    'refresh_token': refresh_token,
                    'device_id': device_id,
                    'expires_at': expires_at,
                    'email': email,
                    'first_name': vk_user_info.get('first_name'),
                    'last_name': vk_user_info.get('last_name'),
                    'photo': selected_group.get('photo_200'),
                    'status': 'active',
                    'connected_at': 'now()',
                    'group_name': selected_group['name'],
                    'screen_name': selected_group.get('screen_name', ''),
                    'members_count': selected_group.get('members_count', 0)
                }
                vks.append(vk_connection)
                
                members_text = f" ({vk_connection['members_count']:,})" if vk_connection['members_count'] > 0 else ""
                connected_names.append(f"📝 {vk_connection['group_name']}{members_text}")
    
    # Сохраняем в БД
    connections['vks'] = vks
    
    if '_vk_selection_pending' in connections:
        del connections['_vk_selection_pending']
    
    db.cursor.execute("""
        UPDATE users
        SET platform_connections = %s::jsonb
        WHERE id = %s
    """, (json.dumps(connections), user_id))
    db.conn.commit()
    
    print(f"✅ VK подключение сохранено для пользователя {user_id}")
    print(f"   Подключено: {len(connected_names)} шт.")
    
    # Формируем сообщение
    success_text = (
        f"✅ <b>Подключено VK ({len(connected_names)}):</b>\n\n" +
        "\n".join(connected_names)
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "🏠 В главное меню",
            callback_data="back_to_settings"
        )
    )
    
    bot.answer_callback_query(call.id, "✅ Подключено!")
    
    bot.edit_message_text(
        success_text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='HTML'
    )


print("✅ handlers/platform_connections/vk_selection.py загружен")
