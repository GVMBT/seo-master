"""
Pinterest Settings - Настройки Pinterest (ссылка и доски)
"""
from telebot import types
from loader import bot, db
from utils import escape_html, safe_answer_callback
import json


# Хранилище состояний для ввода ссылки
pinterest_link_state = {}


# ═══════════════════════════════════════════════════════════════
# ССЫЛКА НА САЙТ
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith('pinterest_link_') 
                            and not call.data.startswith('pinterest_link_edit_')
                            and not call.data.startswith('pinterest_link_delete_'))
def handle_pinterest_link(call):
    """Настройка ссылки на сайт для Pinterest"""
    try:
        print(f"🔍 handle_pinterest_link вызван с callback_data: {call.data}")
        parts = call.data.split('_')
        print(f"🔍 parts после split: {parts}")
        # pinterest_link_123_456_789
        # parts[0]='pinterest', parts[1]='link', parts[2]=123, parts[3]=456, parts[4]=789
        category_id = int(parts[2])
        bot_id = int(parts[3])
        platform_id = parts[4]
        print(f"✅ Распарсено: category_id={category_id}, bot_id={bot_id}, platform_id={platform_id}")
        
        user_id = call.from_user.id
        
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
            return
        
        category_name = category.get('name', 'Без названия')
        
        # Получаем текущую ссылку
        settings = category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        current_link = settings.get('pinterest_link', '')
        
        # Текст
        if current_link:
            link_text = f"<code>{escape_html(current_link)}</code>"
        else:
            link_text = "Не указана"
        
        text = (
            f"🔗 <b>ССЫЛКА НА САЙТ</b>\n"
            f"📂 Категория: {escape_html(category_name)}\n"
            "━━━━━━━━━━━━━━\n\n"
            f"<b>Текущая ссылка:</b>\n{link_text}\n\n"
            "Эта ссылка будет добавлена ко всем пинам.\n"
            "Пользователи смогут перейти на ваш сайт.\n\n"
            "💡 <b>Выберите действие:</b>"
        )
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        markup.add(
            types.InlineKeyboardButton(
                "✏️ Изменить ссылку",
                callback_data=f"pinterest_link_edit_{category_id}_{bot_id}_{platform_id}"
            )
        )
        
        if current_link:
            markup.add(
                types.InlineKeyboardButton(
                    "❌ Удалить ссылку",
                    callback_data=f"pinterest_link_delete_{category_id}_{bot_id}_{platform_id}"
                )
            )
        
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"platform_menu_{category_id}_{bot_id}_pinterest_{platform_id}"
            )
        )
        
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='HTML'
        )
        
        safe_answer_callback(bot, call.id)
        
    except Exception as e:
        print(f"❌ Ошибка в handle_pinterest_link: {e}")
        safe_answer_callback(bot, call.id, "❌ Ошибка", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith('pinterest_link_edit_'))
def handle_pinterest_link_edit(call):
    """Начало редактирования ссылки"""
    try:
        parts = call.data.split('_')
        category_id = int(parts[3])
        bot_id = int(parts[4])
        platform_id = parts[5]
        
        user_id = call.from_user.id
        
        # Сохраняем состояние
        pinterest_link_state[user_id] = {
            'category_id': category_id,
            'bot_id': bot_id,
            'platform_id': platform_id,
            'message_id': call.message.message_id
        }
        
        text = (
            "🔗 <b>ВВОД ССЫЛКИ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Введите ссылку на ваш сайт.\n\n"
            "<b>Примеры:</b>\n"
            "• <code>https://example.com</code>\n"
            "• <code>https://mysite.ru/products</code>\n"
            "• <code>https://shop.com</code>\n\n"
            "💡 Ссылка должна начинаться с <code>http://</code> или <code>https://</code>"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "❌ Отмена",
                callback_data=f"pinterest_link_{category_id}_{bot_id}_{platform_id}"
            )
        )
        
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='HTML'
        )
        
        bot.register_next_step_handler(call.message, process_pinterest_link, user_id)
        
        safe_answer_callback(bot, call.id)
        
    except Exception as e:
        print(f"❌ Ошибка в handle_pinterest_link_edit: {e}")
        safe_answer_callback(bot, call.id, "❌ Ошибка", show_alert=True)


def process_pinterest_link(message, user_id):
    """Обработка введённой ссылки"""
    try:
        if user_id not in pinterest_link_state:
            bot.send_message(message.chat.id, "❌ Сессия истекла")
            return
        
        state = pinterest_link_state[user_id]
        category_id = state['category_id']
        bot_id = state['bot_id']
        platform_id = state['platform_id']
        
        # Проверяем отмену
        if message.text.startswith('/') or message.text == "❌ Отмена":
            del pinterest_link_state[user_id]
            bot.send_message(message.chat.id, "❌ Отменено")
            return
        
        link = message.text.strip()
        
        # Валидация ссылки
        if not link.startswith('http://') and not link.startswith('https://'):
            bot.send_message(
                message.chat.id,
                "❌ Неверный формат ссылки!\n\n"
                "Ссылка должна начинаться с <code>http://</code> или <code>https://</code>\n\n"
                "Попробуйте ещё раз:",
                parse_mode='HTML'
            )
            bot.register_next_step_handler(message, process_pinterest_link, user_id)
            return
        
        # Сохраняем ссылку
        category = db.get_category(category_id)
        if not category:
            del pinterest_link_state[user_id]
            bot.send_message(message.chat.id, "❌ Категория не найдена")
            return
        
        settings = category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        settings['pinterest_link'] = link
        
        # Обновляем в БД
        db.cursor.execute("""
            UPDATE categories
            SET settings = %s::jsonb
            WHERE id = %s
        """, (json.dumps(settings), category_id))
        db.conn.commit()
        
        # Очищаем состояние
        del pinterest_link_state[user_id]
        
        # Показываем результат
        text = (
            "✅ <b>ССЫЛКА СОХРАНЕНА!</b>\n\n"
            f"Ссылка: <code>{escape_html(link)}</code>\n\n"
            "Теперь все пины будут содержать эту ссылку."
        )
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.row(
            types.InlineKeyboardButton(
                "🏠 Настройки ссылки",
                callback_data=f"pinterest_link_{category_id}_{bot_id}_{platform_id}"
            ),
            types.InlineKeyboardButton(
                "🔙 К Pinterest",
                callback_data=f"open_platform_pinterest_{category_id}_{bot_id}_{platform_id}"
            )
        )
        
        bot.send_message(
            message.chat.id,
            text,
            reply_markup=markup,
            parse_mode='HTML'
        )
        
    except Exception as e:
        print(f"❌ Ошибка в process_pinterest_link: {e}")
        if user_id in pinterest_link_state:
            del pinterest_link_state[user_id]
        bot.send_message(message.chat.id, f"❌ Ошибка сохранения: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith('pinterest_link_delete_'))
def handle_pinterest_link_delete(call):
    """Удаление ссылки"""
    try:
        parts = call.data.split('_')
        category_id = int(parts[3])
        bot_id = int(parts[4])
        platform_id = parts[5]
        
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
            return
        
        # Удаляем ссылку
        settings = category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        if 'pinterest_link' in settings:
            del settings['pinterest_link']
        
        # Обновляем в БД
        db.cursor.execute("""
            UPDATE categories
            SET settings = %s::jsonb
            WHERE id = %s
        """, (json.dumps(settings), category_id))
        db.conn.commit()
        
        safe_answer_callback(bot, call.id, "✅ Ссылка удалена")
        
        # Возвращаемся к настройкам
        handle_pinterest_link(call)
        
    except Exception as e:
        print(f"❌ Ошибка в handle_pinterest_link_delete: {e}")
        safe_answer_callback(bot, call.id, "❌ Ошибка", show_alert=True)


# ═══════════════════════════════════════════════════════════════
# ВЫБОР ДОСОК
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith('pinterest_boards_')
                            and not call.data.startswith('pinterest_boards_all_')
                            and not call.data.startswith('pinterest_boards_clear_'))
def handle_pinterest_boards(call):
    """Выбор досок Pinterest для публикации"""
    try:
        parts = call.data.split('_')
        # pinterest_boards_123_456_789
        # parts[0]='pinterest', parts[1]='boards', parts[2]=123, parts[3]=456, parts[4]=789
        category_id = int(parts[2])
        bot_id = int(parts[3])
        platform_id = parts[4]
        
        user_id = call.from_user.id
        
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
            return
        
        category_name = category.get('name', 'Без названия')
        
        # Получаем пользователя для доступа к platform_connections
        user_data = db.get_user(user_id)
        if not user_data:
            safe_answer_callback(bot, call.id, "❌ Данные не найдены", show_alert=True)
            return
        
        # Получаем список досок Pinterest через API
        connections = user_data.get('platform_connections', {})
        pinterests = connections.get('pinterests', [])
        
        if not pinterests:
            bot.answer_callback_query(
                call.id,
                "❌ Нет подключённых аккаунтов Pinterest",
                show_alert=True
            )
            return
        
        # Получаем доски через API
        from platforms.pinterest.client import PinterestClient
        
        all_boards = []
        for pinterest in pinterests:
            access_token = pinterest.get('access_token')
            if not access_token:
                continue
            
            try:
                client = PinterestClient(access_token)
                boards = client.get_boards()
                
                for board in boards:
                    all_boards.append({
                        'name': board.get('name', 'Без названия'),
                        'id': board.get('id', ''),
                        'username': pinterest.get('username', 'Unknown')
                    })
            except Exception as e:
                print(f"❌ Ошибка получения досок: {e}")
                continue
        
        if not all_boards:
            bot.answer_callback_query(
                call.id,
                "❌ Не удалось загрузить доски. Проверьте подключение Pinterest.",
                show_alert=True
            )
            return
        
        # Получаем выбранные доски
        settings = category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        selected_boards = settings.get('pinterest_boards', [])
        
        # Если ничего не выбрано - по умолчанию все
        if not selected_boards:
            selected_text = "Все доски (по умолчанию)"
        else:
            selected_text = f"{len(selected_boards)} досок"
        
        # Текст
        text = (
            f"📋 <b>ВЫБОР ДОСОК PINTEREST</b>\n"
            f"📂 Категория: {escape_html(category_name)}\n"
            "━━━━━━━━━━━━━━\n\n"
            f"<b>Выбрано:</b> {selected_text}\n\n"
            "Выберите доски для публикации пинов.\n"
            "Если ничего не выбрано - постинг на все доски.\n\n"
            "💡 <b>Доступные доски:</b>"
        )
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        # Кнопки досок
        for idx, board in enumerate(all_boards):
            board_id = board['id']
            board_name = board['name']
            
            # Проверяем выбрана ли доска (по имени, а не по ID)
            is_selected = board_name in selected_boards
            button_text = f"✅ {board_name}" if is_selected else f"☐ {board_name}"
            
            markup.add(
                types.InlineKeyboardButton(
                    button_text,
                    # Используем индекс вместо имени (экономим место в callback_data)
                    callback_data=f"pinterest_board_toggle_{category_id}_{bot_id}_{platform_id}_{idx}"
                )
            )
        
        # Кнопки управления
        markup.row(
            types.InlineKeyboardButton(
                "☑️ Все доски",
                callback_data=f"pinterest_boards_all_{category_id}_{bot_id}_{platform_id}"
            ),
            types.InlineKeyboardButton(
                "❌ Сбросить",
                callback_data=f"pinterest_boards_clear_{category_id}_{bot_id}_{platform_id}"
            )
        )
        
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"platform_menu_{category_id}_{bot_id}_pinterest_{platform_id}"
            )
        )
        
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='HTML'
        )
        
        safe_answer_callback(bot, call.id)
        
    except Exception as e:
        print(f"❌ Ошибка в handle_pinterest_boards: {e}")
        import traceback
        traceback.print_exc()
        safe_answer_callback(bot, call.id, "❌ Ошибка", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith('pinterest_board_toggle_'))
def handle_pinterest_board_toggle(call):
    """Переключение выбора доски"""
    try:
        parts = call.data.split('_')
        category_id = int(parts[3])
        bot_id = int(parts[4])
        platform_id = parts[5]
        board_index = int(parts[6])  # Индекс доски в списке
        
        user_id = call.from_user.id
        
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
            return
        
        # Получаем список досок заново чтобы найти имя по индексу
        user_data = db.get_user(user_id)
        if not user_data:
            safe_answer_callback(bot, call.id, "❌ Данные не найдены", show_alert=True)
            return
        
        connections = user_data.get('platform_connections', {})
        pinterests = connections.get('pinterests', [])
        
        if not pinterests:
            safe_answer_callback(bot, call.id, "❌ Нет подключённых аккаунтов Pinterest", show_alert=True)
            return
        
        # Получаем доски через API
        from platforms.pinterest.client import PinterestClient
        
        all_boards = []
        for pinterest in pinterests:
            access_token = pinterest.get('access_token')
            if not access_token:
                continue
            
            try:
                client = PinterestClient(access_token)
                boards = client.get_boards()
                
                for board in boards:
                    all_boards.append({
                        'name': board.get('name', 'Без названия'),
                        'id': board.get('id', ''),
                        'username': pinterest.get('username', 'Unknown')
                    })
            except Exception as e:
                print(f"❌ Ошибка получения досок: {e}")
                continue
        
        if board_index >= len(all_boards):
            safe_answer_callback(bot, call.id, "❌ Доска не найдена", show_alert=True)
            return
        
        # Получаем имя доски по индексу
        board_name = all_boards[board_index]['name']
        
        # Получаем выбранные доски (теперь это имена, а не ID)
        settings = category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        selected_boards = settings.get('pinterest_boards', [])
        
        # Переключаем (по имени)
        if board_name in selected_boards:
            selected_boards.remove(board_name)
        else:
            selected_boards.append(board_name)
        
        # Сохраняем
        settings['pinterest_boards'] = selected_boards
        
        db.cursor.execute("""
            UPDATE categories
            SET settings = %s::jsonb
            WHERE id = %s
        """, (json.dumps(settings), category_id))
        db.conn.commit()
        
        safe_answer_callback(bot, call.id)
        
        # Обновляем интерфейс
        call.data = f"pinterest_boards_{category_id}_{bot_id}_{platform_id}"
        handle_pinterest_boards(call)
        
    except Exception as e:
        print(f"❌ Ошибка в handle_pinterest_board_toggle: {e}")
        import traceback
        traceback.print_exc()
        safe_answer_callback(bot, call.id, "❌ Ошибка", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith('pinterest_boards_all_'))
def handle_pinterest_boards_all(call):
    """Выбрать все доски"""
    try:
        parts = call.data.split('_')
        category_id = int(parts[3])
        bot_id = int(parts[4])
        platform_id = parts[5]
        
        user_id = call.from_user.id
        
        # Получаем пользователя
        user_data = db.get_user(user_id)
        if not user_data:
            safe_answer_callback(bot, call.id, "❌ Данные не найдены", show_alert=True)
            return
        
        # Получаем все доски через API
        connections = user_data.get('platform_connections', {})
        pinterests = connections.get('pinterests', [])
        
        all_board_ids = []
        from platforms.pinterest.client import PinterestClient
        
        for pinterest in pinterests:
            access_token = pinterest.get('access_token')
            if not access_token:
                continue
            
            try:
                client = PinterestClient(access_token)
                boards = client.get_boards()
                all_board_ids.extend([board.get('id', '') for board in boards if board.get('id')])
            except Exception as e:
                print(f"❌ Ошибка получения досок: {e}")
                continue
        
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
            return
        
        # Сохраняем все доски
        settings = category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        settings['pinterest_boards'] = all_board_ids
        
        db.cursor.execute("""
            UPDATE categories
            SET settings = %s::jsonb
            WHERE id = %s
        """, (json.dumps(settings), category_id))
        db.conn.commit()
        
        safe_answer_callback(bot, call.id, "✅ Выбраны все доски")
        
        # Обновляем интерфейс
        call.data = f"pinterest_boards_{category_id}_{bot_id}_{platform_id}"
        handle_pinterest_boards(call)
        
    except Exception as e:
        print(f"❌ Ошибка в handle_pinterest_boards_all: {e}")
        safe_answer_callback(bot, call.id, "❌ Ошибка", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith('pinterest_boards_clear_'))
def handle_pinterest_boards_clear(call):
    """Сбросить выбор досок (постинг на все)"""
    try:
        parts = call.data.split('_')
        category_id = int(parts[3])
        bot_id = int(parts[4])
        platform_id = parts[5]
        
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
            return
        
        # Очищаем выбор
        settings = category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        settings['pinterest_boards'] = []
        
        db.cursor.execute("""
            UPDATE categories
            SET settings = %s::jsonb
            WHERE id = %s
        """, (json.dumps(settings), category_id))
        db.conn.commit()
        
        safe_answer_callback(bot, call.id, "✅ Постинг на все доски")
        
        # Обновляем интерфейс
        call.data = f"pinterest_boards_{category_id}_{bot_id}_{platform_id}"
        handle_pinterest_boards(call)
        
    except Exception as e:
        print(f"❌ Ошибка в handle_pinterest_boards_clear: {e}")
        safe_answer_callback(bot, call.id, "❌ Ошибка", show_alert=True)


print("✅ handlers/pinterest_settings.py загружен")
