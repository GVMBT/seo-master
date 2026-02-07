"""
Универсальный планировщик для всех платформ
Поддерживает: Telegram, Pinterest, VK, Website
"""
from telebot import types
from loader import bot, db
from utils import escape_html, safe_answer_callback
import json

print("✅ handlers/platform_scheduler.py загружен")


# ═══════════════════════════════════════════════════════════════
# КОНСТАНТЫ
# ═══════════════════════════════════════════════════════════════

# Временное хранилище состояния настройки
scheduler_states = {}


# ═══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════

def _init_scheduler_state(user_id, category_id, bot_id, platform_type, platform_id, frequency, posts_per_day):
    """Инициализация состояния планировщика"""
    scheduler_states[user_id] = {
        'category_id': category_id,
        'bot_id': bot_id,
        'platform_type': platform_type,
        'platform_id': platform_id,
        'frequency': frequency,
        'posts_per_day': posts_per_day
    }


def _get_platform_scheduler(category_id, platform_type, platform_id):
    """Получить настройки планировщика для платформы"""
    category = db.get_category(category_id)
    if not category:
        return None
    
    schedulers = category.get('platform_schedulers', {})
    key = f"{platform_type}_{platform_id}"
    return schedulers.get(key, {})


def _save_platform_scheduler(category_id, platform_type, platform_id, schedule_data):
    """Сохранить настройки планировщика"""
    category = db.get_category(category_id)
    if not category:
        return False
    
    schedulers = category.get('platform_schedulers', {})
    key = f"{platform_type}_{platform_id}"
    schedulers[key] = schedule_data
    
    db.update_category(category_id, platform_schedulers=schedulers)
    return True


# ═══════════════════════════════════════════════════════════════
# ШАГ 1: ВЫБОР ЧАСТОТЫ (1-7 ДНЕЙ В НЕДЕЛЮ)
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("old_scheduler_setup_"))
def handle_scheduler_setup(call):
    """Начало настройки планировщика - выбор частоты"""
    parts = call.data.split("_")
    
    platform_type = parts[2]
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = "_".join(parts[5:])
    
    category = db.get_category(category_id)
    if not category:
        safe_answer_callback(bot, call.id, "❌ Категория не найдена")
        return
    
    category_name = category.get('name', 'Без названия')
    
    # Получаем текущие настройки планировщика
    schedule = _get_platform_scheduler(category_id, platform_type, platform_id)
    is_enabled = schedule.get('enabled', False)
    
    if is_enabled:
        freq = schedule.get('frequency', 1)
        ppd = schedule.get('posts_per_day', 1)
        status = f"🟢 Активен: {freq}x/нед"
        if ppd > 1:
            status += f", {ppd} пост/день"
        text = (
            f"📅 <b>ПЛАНИРОВЩИК ПУБЛИКАЦИЙ</b>\n"
            f"📂 Категория: {escape_html(category_name)}\n"
            f"📱 Платформа: {platform_type.upper()}\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"📊 Статус: {status}\n\n"
            f"<b>Сколько постов в неделю?</b>"
        )
    else:
        text = (
            f"📅 <b>ПЛАНИРОВЩИК ПУБЛИКАЦИЙ</b>\n"
            f"📂 Категория: {escape_html(category_name)}\n"
            f"📱 Платформа: {platform_type.upper()}\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"<b>Сколько постов в неделю?</b>"
        )
    
    markup = types.InlineKeyboardMarkup(row_width=7)
    
    # Кнопки 1-7
    buttons = []
    for i in range(1, 8):
        buttons.append(types.InlineKeyboardButton(
            str(i),
            callback_data=f"sched_freq_{platform_type}_{category_id}_{bot_id}_{platform_id}_{i}"
        ))
    markup.add(*buttons)
    
    # Кнопка отключения если активен
    if is_enabled:
        markup.add(types.InlineKeyboardButton(
            "🔴 Отключить планировщик",
            callback_data=f"sched_disable_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        ))
    
    markup.add(types.InlineKeyboardButton(
        "🔙 К планировщику",
        callback_data=f"platform_scheduler_{platform_type}_{category_id}_{bot_id}_{platform_id}"
    ))
    
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
    
    safe_answer_callback(bot, call.id)


# ═══════════════════════════════════════════════════════════════
# ШАГ 2: ВЫБОР ПОСТОВ В ДЕНЬ (ЕСЛИ ВЫБРАНО 7 ДНЕЙ)
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("sched_freq_"))
def handle_schedule_frequency(call):
    """Обработка выбора частоты"""
    parts = call.data.split("_")
    
    platform_type = parts[2]
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = parts[5] if len(parts) == 7 else "_".join(parts[5:-1])
    frequency = int(parts[-1])
    
    user_id = call.from_user.id
    
    # Если выбрано 7 - спрашиваем количество постов в день
    if frequency == 7:
        text = (
            f"📅 <b>ПЛАНИРОВЩИК ПУБЛИКАЦИЙ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"✅ Выбрано: <b>Каждый день (7x/нед)</b>\n\n"
            f"<b>Сколько постов в день?</b>"
        )
        
        markup = types.InlineKeyboardMarkup(row_width=5)
        buttons = []
        for i in range(1, 6):
            buttons.append(types.InlineKeyboardButton(
                str(i),
                callback_data=f"sched_ppd_{platform_type}_{category_id}_{bot_id}_{platform_id}_{i}"
            ))
        markup.add(*buttons)
        markup.add(types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"scheduler_setup_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        ))
        
        try:
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup,
                parse_mode='HTML'
            )
        except Exception as e:
            bot.send_message(
                call.message.chat.id,
                text,
                reply_markup=markup,
                parse_mode='HTML'
            )
    else:
        # НЕ сохраняем сразу - переходим к выбору досок/топиков
        user_id = call.from_user.id
        _init_scheduler_state(user_id, category_id, bot_id, platform_type, platform_id, frequency, 1)
        
        # Переходим к выбору досок/топиков (если нужно)
        _show_boards_topics_selection(
            call.message.chat.id,
            call.message.message_id,
            user_id,
            category_id,
            bot_id,
            platform_type,
            platform_id,
            frequency,
            1
        )
    
    safe_answer_callback(bot, call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("sched_ppd_"))
def handle_schedule_posts_per_day(call):
    """Обработка выбора постов в день"""
    parts = call.data.split("_")
    
    platform_type = parts[2]
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = parts[5] if len(parts) == 7 else "_".join(parts[5:-1])
    posts_per_day = int(parts[-1])
    
    user_id = call.from_user.id
    _init_scheduler_state(user_id, category_id, bot_id, platform_type, platform_id, 7, posts_per_day)
    
    # Переходим к выбору досок/топиков (если нужно)
    _show_boards_topics_selection(
        call.message.chat.id,
        call.message.message_id,
        user_id,
        category_id,
        bot_id,
        platform_type,
        platform_id,
        7,  # Каждый день
        posts_per_day
    )
    
    safe_answer_callback(bot, call.id)


# ═══════════════════════════════════════════════════════════════
# ШАГ 3: ВЫБОР ДОСОК (PINTEREST) ИЛИ ТОПИКОВ (TELEGRAM)
# ═══════════════════════════════════════════════════════════════

def _show_boards_topics_selection(chat_id, message_id, user_id, category_id, bot_id, platform_type, platform_id, frequency, posts_per_day):
    """Показать выбор досок для Pinterest или топиков для Telegram"""
    
    # Для Pinterest - выбор досок
    if platform_type == 'pinterest':
        _show_pinterest_boards_selection(chat_id, message_id, user_id, category_id, bot_id, platform_id, frequency, posts_per_day)
    
    # Для Telegram - выбор топиков
    elif platform_type == 'telegram':
        _show_telegram_topics_selection(chat_id, message_id, user_id, category_id, bot_id, platform_id, frequency, posts_per_day)
    
    # Для остальных платформ - сразу сохраняем
    else:
        _save_and_activate_scheduler(chat_id, message_id, category_id, bot_id, platform_type, platform_id, frequency, posts_per_day)


def _show_pinterest_boards_selection(chat_id, message_id, user_id, category_id, bot_id, platform_id, frequency, posts_per_day, platform_type='pinterest'):
    """Выбор досок Pinterest"""
    
    print(f"\n{'~'*60}")
    print(f"📋 _show_pinterest_boards_selection ВЫЗВАНА")
    print(f"   category_id: {category_id}")
    print(f"   bot_id: {bot_id}")
    print(f"   platform_id: {platform_id}")
    print(f"   frequency: {frequency}")
    print(f"   posts_per_day: {posts_per_day}")
    print(f"{'~'*60}\n")
    
    # Получаем доски через Pinterest API
    user_data = db.get_user(user_id)
    connections = user_data.get('platform_connections', {}) if user_data else {}
    pinterests = connections.get('pinterests', [])
    
    # Загружаем доски через API
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
    
    print(f"   📊 Найдено досок через API: {len(all_boards)}")
    
    # Читаем выбранные доски из настроек категории
    import json
    settings = category.get('settings', {})
    if isinstance(settings, str):
        settings = json.loads(settings)
    selected_boards = settings.get('pinterest_selected_boards', [])
    
    print(f"📊 ОТЛАДКА выбора досок:")
    print(f"   category_id: {category_id}")
    print(f"   settings keys: {list(settings.keys())}")
    print(f"   pinterest_selected_boards: {selected_boards}")
    
    # Если досок нет - показываем это и предлагаем обновить
    if not all_boards or len(all_boards) == 0:
        text = (
            f"📅 <b>ПЛАНИРОВЩИК ПУБЛИКАЦИЙ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"<b>Шаг 3:</b> Выбор досок (опционально)\n\n"
            f"⚠️ <b>Доски не загружены</b>\n"
            f"<i>Посты будут публиковаться на все доски.\n\n"
            f"Чтобы выбрать конкретные доски - убедитесь, что аккаунт Pinterest подключён правильно.</i>"
        )
    else:
        # Показываем список досок с возможностью выбора
        if selected_boards:
            selected_text = f"✅ Выбрано: <b>{len(selected_boards)}</b> доск(и)"
        else:
            selected_text = "📭 <i>Публикация на все доски</i>"
        
        text = (
            f"📅 <b>ПЛАНИРОВЩИК ПУБЛИКАЦИЙ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"<b>Шаг 3:</b> Выбор досок (опционально)\n\n"
            f"{selected_text}\n\n"
            f"💡 <b>Выберите доски для публикации:</b>"
        )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    # Кнопки досок (если есть)
    if all_boards and len(all_boards) > 0:
        for board in all_boards[:20]:  # Максимум 20 досок
            board_name = board.get('name', 'Без названия')
            board_id = board.get('id', '')
            
            if not board_id:
                continue
            
            is_selected = board_id in selected_boards
            btn_text = f"✅ {board_name}" if is_selected else f"☐ {board_name}"
            
            markup.add(types.InlineKeyboardButton(
                btn_text,
                callback_data=f"sched_board_toggle_{category_id}_{bot_id}_{platform_id}_{board_id}"
            ))
    
    # Кнопки навигации
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"scheduler_setup_pinterest_{category_id}_{bot_id}_{platform_id}"
        ),
        types.InlineKeyboardButton(
            "✅ Продолжить без выбора" if (not all_boards or len(all_boards) == 0) else "✅ Готово",
            callback_data=f"sched_boards_done_pinterest_{category_id}_{bot_id}_{platform_id}_{frequency}_{posts_per_day}"
        )
    )
    
    print(f"   🔘 Создана кнопка 'Готово' с callback_data:")
    print(f"      sched_boards_done_pinterest_{category_id}_{bot_id}_{platform_id}_{frequency}_{posts_per_day}")
    
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')


def _show_telegram_topics_selection(chat_id, message_id, user_id, category_id, bot_id, platform_id, frequency, posts_per_day):
    """Выбор топиков Telegram"""
    
    # Получаем список топиков из категории (НЕ из settings!)
    category = db.get_category(category_id)
    telegram_topics = category.get('telegram_topics', [])
    
    # КРИТИЧЕСКАЯ ПРОВЕРКА: если telegram_topics не список - сбрасываем!
    if not isinstance(telegram_topics, list):
        print(f"⚠️ WARNING: telegram_topics не список! Тип: {type(telegram_topics)}")
        telegram_topics = []
    
    state = scheduler_states.get(user_id, {})
    selected_topics = state.get('selected_topics', [])
    
    # Если топиков нет - показываем это и предлагаем добавить
    if not telegram_topics or len(telegram_topics) == 0:
        text = (
            f"📅 <b>ПЛАНИРОВЩИК ПУБЛИКАЦИЙ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"<b>Шаг 3:</b> Выбор топиков (опционально)\n\n"
            f"⚠️ <b>Топики не настроены</b>\n"
            f"<i>Посты будут публиковаться в общий чат.\n\n"
            f"Если хотите публиковать в топики - сначала настройте их в разделе \"Настройка топиков\"</i>"
        )
    else:
        # Показываем список топиков с возможностью выбора
        if selected_topics:
            selected_text = f"✅ Выбрано: <b>{len(selected_topics)}</b> топик(ов)"
        else:
            selected_text = "📭 <i>Публикация в основной чат (без топиков)</i>"
        
        text = (
            f"📅 <b>ПЛАНИРОВЩИК ПУБЛИКАЦИЙ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"<b>Шаг 3:</b> Выбор топиков (опционально)\n\n"
            f"{selected_text}\n\n"
            f"💡 <b>Выберите топики для публикации:</b>"
        )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    # Кнопки топиков (если есть)
    if telegram_topics and len(telegram_topics) > 0:
        for topic in telegram_topics:
            # Новый формат: {'topic_id': 123, 'topic_name': 'Name'}
            if isinstance(topic, dict):
                topic_id = topic.get('topic_id')
                topic_name = topic.get('topic_name', 'Без названия')
            else:
                # Старый формат (на всякий случай)
                print(f"⚠️ Топик в старом формате: {topic}")
                continue
            
            if not topic_id:
                continue
            
            is_selected = topic_id in selected_topics
            btn_text = f"✅ {topic_name}" if is_selected else f"☐ {topic_name}"
            
            markup.add(types.InlineKeyboardButton(
                btn_text,
                callback_data=f"sched_topic_toggle_{category_id}_{bot_id}_{platform_id}_{topic_id}"
            ))
    
    # Кнопки навигации
    nav_buttons = []
    nav_buttons.append(types.InlineKeyboardButton(
        "🔙 Назад",
        callback_data=f"scheduler_setup_telegram_{category_id}_{bot_id}_{platform_id}"
    ))
    
    # Если топиков нет - кнопка "Настроить топики"
    if not telegram_topics or len(telegram_topics) == 0:
        nav_buttons.append(types.InlineKeyboardButton(
            "⚙️ Настроить топики",
            callback_data=f"telegram_topics_{category_id}_{bot_id}_{platform_id}"
        ))
    
    nav_buttons.append(types.InlineKeyboardButton(
        "✅ Продолжить без топиков" if (not telegram_topics or len(telegram_topics) == 0) else "✅ Готово",
        callback_data=f"sched_topics_done_telegram_{category_id}_{bot_id}_{platform_id}_{frequency}_{posts_per_day}"
    ))
    
    for btn in nav_buttons:
        markup.add(btn)
    
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')


# Обработчики переключения досок/топиков
@bot.callback_query_handler(func=lambda call: call.data.startswith("sched_board_toggle_"))
def handle_board_toggle(call):
    """Переключение выбора доски"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = parts[5]
    board_id = parts[6]
    
    user_id = call.from_user.id
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    # Получаем настройки
    import json
    settings = category.get('settings', {})
    if isinstance(settings, str):
        settings = json.loads(settings)
    
    # Получаем текущие выбранные доски для Pinterest
    selected_boards = settings.get('pinterest_selected_boards', [])
    
    # Переключаем выбор
    if board_id in selected_boards:
        selected_boards.remove(board_id)
    else:
        selected_boards.append(board_id)
    
    # Сохраняем в настройки категории
    settings['pinterest_selected_boards'] = selected_boards
    
    db.cursor.execute("""
        UPDATE categories
        SET settings = %s::jsonb
        WHERE id = %s
    """, (json.dumps(settings), category_id))
    db.conn.commit()
    
    print(f"💾 Сохранены выбранные доски для категории {category_id}: {selected_boards}")
    
    # Обновляем сообщение
    _show_pinterest_boards_selection(call.message.chat.id, call.message.message_id, user_id, category_id, bot_id, platform_id, 1, 1)
    
    safe_answer_callback(bot, call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("sched_topic_toggle_"))
def handle_topic_toggle(call):
    """Переключение выбора топика"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = parts[5]
    topic_id = int(parts[6])  # ВАЖНО: преобразуем в int!
    
    user_id = call.from_user.id
    state = scheduler_states.get(user_id, {})
    selected_topics = state.get('selected_topics', [])
    
    # Переключаем выбор
    if topic_id in selected_topics:
        selected_topics.remove(topic_id)
    else:
        selected_topics.append(topic_id)
    
    state['selected_topics'] = selected_topics
    scheduler_states[user_id] = state
    
    # Обновляем сообщение
    frequency = state.get('frequency', 1)
    posts_per_day = state.get('posts_per_day', 1)
    _show_telegram_topics_selection(call.message.chat.id, call.message.message_id, user_id, category_id, bot_id, platform_id, frequency, posts_per_day)
    
    safe_answer_callback(bot, call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("sched_boards_done_") or call.data.startswith("sched_topics_done_"))
def handle_boards_topics_done(call):
    """Завершение выбора досок/топиков"""
    parts = call.data.split("_")
    
    if call.data.startswith("sched_boards_done_"):
        platform_type = parts[3]
        category_id = int(parts[4])
        bot_id = int(parts[5])
        platform_id = parts[6]
        frequency = int(parts[7])
        posts_per_day = int(parts[8])
    else:  # topics_done
        platform_type = parts[3]
        category_id = int(parts[4])
        bot_id = int(parts[5])
        platform_id = parts[6]
        frequency = int(parts[7])
        posts_per_day = int(parts[8])
    
    user_id = call.from_user.id
    state = scheduler_states.get(user_id, {})
    selected_boards = state.get('selected_boards', [])
    selected_topics = state.get('selected_topics', [])
    
    # Сохраняем с выбранными досками/топиками
    _save_and_activate_scheduler(
        call.message.chat.id,
        call.message.message_id,
        category_id,
        bot_id,
        platform_type,
        platform_id,
        frequency,
        posts_per_day,
        selected_boards if platform_type == 'pinterest' else [],
        selected_topics if platform_type == 'telegram' else []
    )
    
    # Очищаем state
    if user_id in scheduler_states:
        del scheduler_states[user_id]
    
    safe_answer_callback(bot, call.id)


# ═══════════════════════════════════════════════════════════════
# СОХРАНЕНИЕ И АКТИВАЦИЯ
# ═══════════════════════════════════════════════════════════════

def _save_and_activate_scheduler(chat_id, message_id, category_id, bot_id, platform_type, platform_id, frequency, posts_per_day, boards=None, topics=None):
    """Сохранить настройки и активировать планировщик"""
    
    schedule_data = {
        'enabled': True,
        'frequency': frequency,
        'posts_per_day': posts_per_day,
        'auto_generate': True
    }
    
    # Добавляем доски для Pinterest
    if boards:
        schedule_data['boards'] = boards
    
    # Добавляем топики для Telegram
    if topics:
        schedule_data['topics'] = topics
    
    success = _save_platform_scheduler(category_id, platform_type, platform_id, schedule_data)
    
    if success:
        category = db.get_category(category_id)
        category_name = category.get('name', 'Без названия')
        
        # Форматируем текст о частоте
        if frequency == 7:
            freq_text = f"Каждый день, {posts_per_day} {'пост' if posts_per_day == 1 else 'поста' if posts_per_day < 5 else 'постов'}/день"
        else:
            freq_text = f"{frequency}x в неделю"
        
        text = (
            f"✅ <b>ПЛАНИРОВЩИК АКТИВИРОВАН!</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"📂 Категория: {escape_html(category_name)}\n"
            f"📱 Платформа: {platform_type.upper()}\n\n"
            f"📅 Частота: <b>{freq_text}</b>\n"
            f"🤖 Автогенерация: Включена\n"
        )
        
        # Добавляем информацию о досках Pinterest
        if platform_type == 'pinterest':
            if boards and len(boards) > 0:
                text += f"📌 Доски: <b>{len(boards)}</b> выбрано\n"
            else:
                text += f"📌 Доски: <i>Не выбрано</i> (будет дефолтная доска)\n"
        
        # Добавляем информацию о топиках Telegram
        if platform_type == 'telegram':
            if topics and len(topics) > 0:
                text += f"💬 Топики: <b>{len(topics)}</b> выбрано\n"
            else:
                text += f"💬 Топики: <i>Не выбрано</i> (будет общий чат)\n"
        
        text += f"\nБот будет автоматически публиковать посты по расписанию!"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "⚙️ Изменить настройки",
                callback_data=f"scheduler_setup_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "🔙 К платформе",
                callback_data=f"platform_menu_{category_id}_{bot_id}_{platform_type}_{platform_id}"
            )
        )
    else:
        text = "❌ Ошибка сохранения настроек"
        markup = None
    
    try:
        bot.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=markup,
            parse_mode='HTML'
        )
    except Exception:
        bot.send_message(
            chat_id,
            text,
            reply_markup=markup,
            parse_mode='HTML'
        )


# ═══════════════════════════════════════════════════════════════
# ОТКЛЮЧЕНИЕ ПЛАНИРОВЩИКА
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("sched_disable_"))
def handle_schedule_disable(call):
    """Отключение планировщика"""
    parts = call.data.split("_")
    
    platform_type = parts[2]
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = "_".join(parts[5:])
    
    # Отключаем планировщик
    schedule_data = {
        'enabled': False
    }
    
    success = _save_platform_scheduler(category_id, platform_type, platform_id, schedule_data)
    
    if success:
        category = db.get_category(category_id)
        category_name = category.get('name', 'Без названия')
        
        text = (
            f"🔴 <b>ПЛАНИРОВЩИК ОТКЛЮЧЕН</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"📂 Категория: {escape_html(category_name)}\n"
            f"📱 Платформа: {platform_type.upper()}\n\n"
            f"Автоматическая публикация остановлена"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "🟢 Включить снова",
                callback_data=f"scheduler_setup_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "🔙 К платформе",
                callback_data=f"platform_menu_{category_id}_{bot_id}_{platform_type}_{platform_id}"
            )
        )
    else:
        text = "❌ Ошибка отключения"
        markup = None
    
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
    
    safe_answer_callback(bot, call.id, "✅ Планировщик отключен")
