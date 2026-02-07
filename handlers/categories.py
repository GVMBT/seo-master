"""
Обработчик работы с категориями
"""
from telebot import types
from loader import bot
from database.database import db
from utils import escape_html, safe_answer_callback


# Состояния создания категории
category_creation_state = {}


@bot.callback_query_handler(func=lambda call: call.data.startswith("create_category_"))
def handle_create_category(call):
    """Начало создания категории"""
    bot_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    # Проверяем что бот существует и принадлежит пользователю
    bot_data = db.get_bot(bot_id)
    if not bot_data or bot_data['user_id'] != user_id:
        safe_answer_callback(bot, call.id, "❌ Ошибка доступа")
        return
    
    # Удаляем предыдущее сообщение
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    # Отправляем запрос названия категории
    text = (
        "➕ <b>СОЗДАНИЕ КАТЕГОРИИ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Категория помогает структурировать товары или услуги.\n\n"
        "📝 <b>Введите название категории:</b>\n\n"
        "<i>Например: \"Женская одежда\", \"Ремонт квартир\", \"Консультации\"</i>"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data=f"open_bot_{bot_id}"))
    
    msg = bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    # ВАЖНО: Очищаем состояние keywords если оно есть
    from handlers.keywords import keywords_state
    if user_id in keywords_state:
        del keywords_state[user_id]
        print(f"🧹 Очищено состояние keywords для {user_id}")
    
    # Сохраняем состояние создания категории
    category_creation_state[user_id] = {
        'bot_id': bot_id,
        'step': 'waiting_name',
        'last_message_id': msg.message_id
    }
    
    safe_answer_callback(bot, call.id)


@bot.message_handler(func=lambda message: message.from_user.id in category_creation_state
                     and category_creation_state[message.from_user.id].get('step') == 'waiting_name')
def handle_category_name(message):
    """Обработка ввода названия категории"""
    user_id = message.from_user.id
    category_name = message.text.strip()
    
    state = category_creation_state.get(user_id)
    if not state:
        return
    
    bot_id = state['bot_id']
    
    # Валидация названия
    # Убрали ограничение на максимальную длину
    # if len(category_name) > 100:
    #     bot.reply_to(message, "❌ Название слишком длинное. Максимум 100 символов.")
    #     return
    
    if len(category_name) < 2:
        bot.reply_to(message, "❌ Название слишком короткое. Минимум 2 символа.")
        return
    
    # Создаем категорию в БД
    category_id = db.create_category(bot_id, category_name)
    
    if not category_id:
        bot.reply_to(message, "❌ Ошибка создания категории. Попробуйте позже.")
        del category_creation_state[user_id]
        return
    
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
    
    # Очищаем состояние
    del category_creation_state[user_id]
    
    # Показываем сообщение об успехе
    text = (
        "✅ <b>КАТЕГОРИЯ СОЗДАНА!</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📂 <b>Название:</b> {escape_html(category_name)}\n\n"
        "Теперь вы можете настроить категорию:\n\n"
        "🔑 <b>Ключевые фразы</b> - подбор для SEO\n"
        "📝 <b>Описание</b> - генерация с помощью AI\n"
        "💰 <b>Цены</b> - загрузка прайс-листа\n"
        "⭐️ <b>Отзывы</b> - управление отзывами\n\n"
        "👇 Выберите действие:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🔑 Ключевые фразы", callback_data=f"category_keywords_{category_id}"),
        types.InlineKeyboardButton("📝 Описание", callback_data=f"category_description_{category_id}"),
        types.InlineKeyboardButton("💰 Цены", callback_data=f"category_prices_{category_id}"),
        types.InlineKeyboardButton("⭐️ Отзывы", callback_data=f"category_reviews_{category_id}"),
        types.InlineKeyboardButton("🔙 К боту", callback_data=f"open_bot_{bot_id}")
    )
    
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')


@bot.callback_query_handler(func=lambda call: call.data.startswith("manage_categories_"))
def handle_manage_categories(call):
    """Управление категориями"""
    bot_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    # Проверяем доступ
    bot_data = db.get_bot(bot_id)
    if not bot_data or bot_data['user_id'] != user_id:
        safe_answer_callback(bot, call.id, "❌ Ошибка доступа")
        return
    
    # Получаем категории
    categories = db.get_bot_categories(bot_id)
    
    if not categories:
        safe_answer_callback(bot, call.id, "❌ Категорий нет")
        return
    
    bot_name = bot_data['name']
    
    text = (
        f"📂 <b>КАТЕГОРИИ БОТА</b>\n"
        f"🤖 {escape_html(bot_name)}\n"
        "━━━━━━━━━━━━━━\n\n"
        f"Всего категорий: {len(categories)}\n\n"
        "Выберите категорию для управления:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    # Добавляем кнопки для каждой категории
    for category in categories:
        # Безопасное получение данных
        if not isinstance(category, dict):
            category = dict(category)
        
        category_id = category.get('id')
        category_name = category.get('name', 'Без названия')
        
        if not category_id:
            continue
        
        btn_text = f"📂 {category_name}"
        markup.add(
            types.InlineKeyboardButton(btn_text, callback_data=f"open_category_{category_id}")
        )
    
    # Кнопка добавления новой категории
    markup.add(
        types.InlineKeyboardButton("➕ Добавить категорию", callback_data=f"create_category_{bot_id}"),
        types.InlineKeyboardButton("🔙 К боту", callback_data=f"open_bot_{bot_id}")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("open_category_"))
def handle_open_category(call):
    """Открытие карточки категории"""
    category_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        safe_answer_callback(bot, call.id, "❌ Категория не найдена")
        return
    
    bot_id = category['bot_id']
    
    # Проверяем доступ через бота
    bot_data = db.get_bot(bot_id)
    if not bot_data or bot_data['user_id'] != user_id:
        safe_answer_callback(bot, call.id, "❌ Ошибка доступа")
        return
    
    category_name = category.get('name', 'Без названия')
    description = category.get('description', '')
    
    # Проверяем наличие данных
    has_keywords = bool(category.get('keywords'))
    
    # Проверка медиа: должны быть реальные файлы, не только служебные поля
    media = category.get('media')
    has_media = False
    if media:
        if isinstance(media, list):
            # Если массив - проверяем что не пустой
            has_media = len(media) > 0
        elif isinstance(media, dict):
            # Если словарь - проверяем есть ли 'items' с файлами
            items = media.get('items', [])
            has_media = len(items) > 0
    
    has_description = bool(description)
    has_prices = bool(category.get('prices'))
    has_reviews = bool(category.get('reviews'))
    
    # СУММАРНАЯ ИНФОРМАЦИЯ О ПЛАНИРОВЩИКАХ
    from handlers.global_scheduler import get_platform_scheduler
    
    total_schedulers = 0
    total_posts_per_week = 0
    total_tokens_per_week = 0
    total_tokens_per_month = 0
    active_platforms = []
    
    # Получаем подключения бота
    bot_connections = bot_data.get('connected_platforms', {})
    if isinstance(bot_connections, str):
        try:
            import json
            bot_connections = json.loads(bot_connections)
        except Exception:
            bot_connections = {}
    
    # Проверяем все платформы
    for platform_type in ['pinterest', 'telegram', 'vk', 'website']:
        platform_list = []
        
        # Проверяем новую структуру (без 's')
        if platform_type in bot_connections:
            temp_list = bot_connections[platform_type]
            if isinstance(temp_list, list):
                platform_list = temp_list
            elif temp_list:
                platform_list = [temp_list]
        
        # Проверяем старую структуру (с 's' в конце)
        old_key = platform_type + 's'
        if old_key in bot_connections:
            temp_list = bot_connections[old_key]
            if isinstance(temp_list, list):
                platform_list.extend(temp_list)
            elif temp_list:
                platform_list.append(temp_list)
        
        for platform_id in platform_list:
            # Извлекаем ID если это словарь
            if isinstance(platform_id, dict):
                platform_id = platform_id.get('id', platform_id)
            
            schedule = get_platform_scheduler(category_id, platform_type, platform_id)
            
            if schedule.get('enabled', False):
                total_schedulers += 1
                days = schedule.get('days', [])
                posts_per_day = schedule.get('posts_per_day', 1) or 1
                
                # Считаем посты в неделю: дни × посты в день
                posts_week = len(days) * posts_per_day if days else 0
                
                total_posts_per_week += posts_week
                
                # Эмодзи платформ
                platform_emoji = {
                    'pinterest': '📌',
                    'telegram': '✈️',
                    'vk': '🔵',
                    'website': '🌐'
                }.get(platform_type, '📱')
                
                active_platforms.append(f"{platform_emoji} {posts_week}/нед")
    
    total_tokens_per_week = total_posts_per_week * 40
    total_tokens_per_month = total_tokens_per_week * 4
    
    text = (
        f"📂 <b>КАТЕГОРИЯ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"<b>Название:</b> {escape_html(category_name)}\n\n"
    )
    
    # Добавляем информацию о планировщиках если есть активные
    if total_schedulers > 0:
        platforms_text = ", ".join(active_platforms)
        text += (
            "📅 <b>АВТОПОСТИНГ:</b> 🟢 Активен\n"
            f"   • Платформ: {total_schedulers}\n"
            f"   • {platforms_text}\n"
            f"   • Всего постов/неделю: {total_posts_per_week}\n\n"
            "💰 <b>ЗАТРАТЫ НА ПУБЛИКАЦИИ:</b>\n"
            f"   • Неделя: {total_tokens_per_week} токенов\n"
            f"   • Месяц: {total_tokens_per_month} токенов\n\n"
        )
    
    text += (
        "<b>📊 ЗАПОЛНЕНИЕ:</b>\n"
        f"{'✅' if has_keywords else '❌'} Ключевые фразы\n"
        f"{'✅' if has_description else '❌'} Описание\n"
        f"{'✅' if has_prices else '❌'} Цены\n"
        f"{'✅' if has_reviews else '❌'} Отзывы\n\n"
        "👇 Выберите раздел для работы:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            f"🔑 Ключевые фразы {'✅' if has_keywords else ''}",
            callback_data=f"category_keywords_{category_id}"
        ),
        types.InlineKeyboardButton(
            f"📝 Описание {'✅' if has_description else ''}",
            callback_data=f"category_description_{category_id}"
        ),
        types.InlineKeyboardButton(
            f"💰 Цены {'✅' if has_prices else ''}",
            callback_data=f"category_prices_{category_id}"
        ),
        types.InlineKeyboardButton(
            f"⭐️ Отзывы {'✅' if has_reviews else ''}",
            callback_data=f"category_reviews_{category_id}"
        )
    )
    
    # ДОБАВЛЯЕМ КНОПКИ ПОДКЛЮЧЕНИЯ ПЛОЩАДОК
    # Получаем все верифицированные площадки пользователя
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {}) if user else {}
    
    # Получаем подключения бота (какие площадки привязаны к этому боту)
    bot_connections = bot_data.get('connected_platforms', {})
    if isinstance(bot_connections, str):
        try:
            bot_connections = json.loads(bot_connections)
        except Exception:
            bot_connections = {}
    
    # Показываем ТОЛЬКО верифицированные площадки с кнопками подключения/отключения
    verified_sites = [s for s in connections.get('websites', []) if s.get('status') == 'active']
    
    for site in verified_sites:
        url = site.get('url', '')
        cms = site.get('cms', 'Website')
        site_id = site.get('url', '')  # Используем URL как ID
        
        # Проверяем подключена ли эта площадка к боту
        is_connected = site_id in bot_connections.get('websites', [])
        
        # Иконка статуса
        icon = "🟢" if is_connected else "❌"
        button_text = f"{icon} {cms}: {url[:25]}..."
        
        markup.add(
            types.InlineKeyboardButton(
                button_text,
                callback_data=f"platform_menu_{category_id}_{bot_id}_website_{site_id}"
            )
        )
    
    # Кнопки для соцсетей (если есть верифицированные)
    verified_pinterest = [p for p in connections.get('pinterests', []) if p.get('status') == 'active']
    for pinterest in verified_pinterest:
        board = pinterest.get('board', 'Pinterest')
        pinterest_id = pinterest.get('board', '')
        is_connected = pinterest_id in bot_connections.get('pinterests', [])
        icon = "🟢" if is_connected else "❌"
        
        markup.add(
            types.InlineKeyboardButton(
                f"{icon} Pinterest: {board}",
                callback_data=f"platform_menu_{category_id}_{bot_id}_pinterest_{pinterest_id}"
            )
        )
    
    verified_telegram = [t for t in connections.get('telegrams', []) if t.get('status') == 'active']
    for telegram in verified_telegram:
        channel = telegram.get('channel', 'Telegram')
        telegram_id = telegram.get('channel', '')
        is_connected = telegram_id in bot_connections.get('telegrams', [])
        icon = "🟢" if is_connected else "❌"
        
        markup.add(
            types.InlineKeyboardButton(
                f"{icon} Telegram: @{channel}",
                callback_data=f"platform_menu_{category_id}_{bot_id}_telegram_{telegram_id}"
            )
        )
    
    # VK подключения
    verified_vk = [v for v in connections.get('vks', []) if v.get('status') == 'active']
    for vk in verified_vk:
        group_name = vk.get('group_name', 'ВКонтакте')
        vk_type = vk.get('type', 'user')
        
        # Определяем ID в зависимости от типа
        if vk_type == 'group':
            vk_id = str(vk.get('group_id', ''))  # Для группы
            icon_prefix = "📝"  # Иконка группы
        else:
            vk_id = str(vk.get('user_id', ''))   # Для личной страницы
            icon_prefix = "👤"  # Иконка личной страницы
        
        # Проверка подключения (новая структура: [{'id': 'user_id или group_id'}])
        vk_list = bot_connections.get('vk', [])
        is_connected = False
        for item in vk_list:
            if isinstance(item, dict) and str(item.get('id')) == vk_id:
                is_connected = True
                break
            elif isinstance(item, str) and str(item) == vk_id:
                is_connected = True
                break
        
        status_icon = "🟢" if is_connected else "❌"
        
        markup.add(
            types.InlineKeyboardButton(
                f"{status_icon} {icon_prefix} {group_name}",
                callback_data=f"platform_menu_{category_id}_{bot_id}_vk_{vk_id}"
            )
        )
    
    # Настройки и навигация
    markup.add(
        types.InlineKeyboardButton("⚙️ Настройки категории", callback_data=f"category_settings_{category_id}"),
        types.InlineKeyboardButton("🔙 К списку категорий", callback_data=f"manage_categories_{bot_id}")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("category_settings_"))
def handle_category_settings(call):
    """Настройки категории"""
    category_id = int(call.data.split("_")[-1])
    
    category = db.get_category(category_id)
    if not category:
        safe_answer_callback(bot, call.id, "❌ Категория не найдена")
        return
    
    category_name = category.get('name', 'Без названия')
    bot_id = category['bot_id']
    
    text = (
        f"⚙️ <b>НАСТРОЙКИ КАТЕГОРИИ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📂 <b>Название:</b> {escape_html(category_name)}\n\n"
        "Что вы хотите сделать?"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✏️ Переименовать", callback_data=f"rename_category_{category_id}"),
        types.InlineKeyboardButton("🗑 Удалить категорию", callback_data=f"delete_category_{category_id}"),
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"open_category_{category_id}")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_category_"))
def handle_delete_category_confirm(call):
    """Подтверждение удаления категории"""
    category_id = int(call.data.split("_")[-1])
    
    category = db.get_category(category_id)
    if not category:
        safe_answer_callback(bot, call.id, "❌ Категория не найдена")
        return
    
    category_name = category.get('name', 'Без названия')
    
    text = (
        f"⚠️ <b>УДАЛЕНИЕ КАТЕГОРИИ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"Вы действительно хотите удалить категорию <b>{escape_html(category_name)}</b>?\n\n"
        "🗑 Будут удалены:\n"
        "• Все ключевые фразы\n"
        "• Все медиа\n"
        "• Описание\n"
        "• Цены\n"
        "• Отзывы\n\n"
        "<b>Это действие нельзя отменить!</b>"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_category_{category_id}"),
        types.InlineKeyboardButton("❌ Отмена", callback_data=f"open_category_{category_id}")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_delete_category_"))
def handle_delete_category_execute(call):
    """Выполнение удаления категории"""
    category_id = int(call.data.split("_")[-1])
    
    category = db.get_category(category_id)
    if not category:
        safe_answer_callback(bot, call.id, "❌ Категория не найдена")
        return
    
    bot_id = category['bot_id']
    
    # Удаляем категорию
    if db.delete_category(category_id):
        text = (
            "✅ <b>КАТЕГОРИЯ УДАЛЕНА</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Категория и все связанные данные успешно удалены."
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("📂 К списку категорий", callback_data=f"manage_categories_{bot_id}"),
            types.InlineKeyboardButton("🤖 К боту", callback_data=f"open_bot_{bot_id}")
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
        
        safe_answer_callback(bot, call.id, "✅ Удалено")
    else:
        safe_answer_callback(bot, call.id, "❌ Ошибка удаления", show_alert=True)


print("✅ handlers/categories.py загружен")
