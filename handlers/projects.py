"""
Обработчик меню проектов (ботов) - расширенная версия
"""
import logging
from telebot import types
from loader import bot
from database.database import db
from utils import escape_html, safe_answer_callback
from datetime import datetime

logger = logging.getLogger(__name__)


def show_projects_menu(message):
    """Показать меню проектов с расширенной информацией"""
    user_id = message.from_user.id
    
    # DEBUG
    logger.debug(f"DEBUG show_projects_menu:")
    print(f"   user_id = {user_id}")
    print(f"   message.from_user = {message.from_user}")
    
    # Получаем список ботов пользователя
    bots = db.get_user_bots(user_id)
    
    # DEBUG
    print(f"   bots = {bots}")
    print(f"   len(bots) = {len(bots) if bots else 0}")
    
    if not bots:
        # Если ботов нет - предлагаем создать первого
        text = (
            "📁 <b>МОИ ПРОЕКТЫ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "У вас пока нет ни одного проекта.\n\n"
            "🚀 <b>Создайте своего первого бота!</b>\n\n"
            "После создания вы сможете:\n"
            "✅ Настроить категории товаров/услуг\n"
            "✅ Генерировать ключевые фразы с AI\n"
            "✅ Создавать описания с помощью Claude\n"
            "✅ Генерировать изображения с Nano Banana Pro\n"
            "✅ Загружать медиа-контент\n"
            "✅ Подключать площадки для автопостинга\n"
            "✅ Управлять ценами и отзывами\n\n"
            "👇 Нажмите кнопку ниже, чтобы начать:"
        )
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("➕ Создать первый проект", callback_data="create_bot")
        )
        
    else:
        # Показываем список ботов с расширенной статистикой
        text = (
            f"📁 <b>МОИ ПРОЕКТЫ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"📊 Всего проектов: <b>{len(bots)}</b>\n\n"
        )
        
        # Считаем общую статистику
        total_categories = 0
        total_keywords = 0
        total_media = 0
        
        for bot_item in bots:
            bot_id = bot_item['id']
            categories = db.get_bot_categories(bot_id)
            
            if categories:
                total_categories += len(categories)
                
                for cat in categories:
                    # Подсчитываем ключевые фразы
                    keywords = cat.get('keywords', [])
                    if isinstance(keywords, list):
                        total_keywords += len(keywords)
                    
                    # Подсчитываем медиа
                    media = cat.get('media', [])
                    if isinstance(media, list):
                        total_media += len(media)
        
        text += (
            f"📂 Категорий: <b>{total_categories}</b>\n"
            f"🔑 Ключевых фраз: <b>{total_keywords}</b>\n"
            f"📷 Медиа файлов: <b>{total_media}</b>\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "Выберите проект для работы:\n\n"
        )
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        # Добавляем кнопки для каждого бота
        for idx, bot_item in enumerate(bots[:15], 1):  # Показываем до 15
            bot_id = bot_item['id']
            bot_name = bot_item['name']
            
            # Получаем количество категорий
            categories = db.get_bot_categories(bot_id)
            cat_count = len(categories) if categories else 0
            
            # Формируем текст кнопки с номером
            btn_text = f"{idx}. {bot_name}"
            if cat_count > 0:
                btn_text += f" • {cat_count} кат."
            
            markup.add(
                types.InlineKeyboardButton(btn_text, callback_data=f"open_bot_{bot_id}")
            )
        
        # Кнопка быстрого доступа к публикациям
        markup.add(
            types.InlineKeyboardButton("🚀 Быстрый доступ к публикациям", callback_data="quick_publish_menu")
        )
        
        # Дополнительные кнопки
        markup.row(
            types.InlineKeyboardButton("➕ Создать", callback_data="create_bot"),
            types.InlineKeyboardButton("📊 Статистика", callback_data="projects_stats")
        )
        
        # Если ботов больше 15 - показываем кнопку "Показать все"
        if len(bots) > 15:
            markup.add(
                types.InlineKeyboardButton(f"📋 Показать все ({len(bots)})", callback_data="show_all_projects")
            )
    
    # Отправляем сообщение
    try:
        bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    except Exception as e:
        print(f"Ошибка отправки меню проектов: {e}")


@bot.message_handler(func=lambda message: message.text == "📁 Проекты")
def handle_projects_button(message):
    """Обработчик кнопки 'Проекты'"""
    show_projects_menu(message)


@bot.callback_query_handler(func=lambda call: call.data == "show_projects")
def handle_show_projects_callback(call):
    """Обработчик callback для показа списка проектов"""
    # Создаем fake message
    fake_msg = type('obj', (object,), {
        'from_user': call.from_user,
        'chat': type('obj', (object,), {'id': call.message.chat.id})()
    })()
    
    # Удаляем предыдущее сообщение
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    show_projects_menu(fake_msg)
    safe_answer_callback(bot, call.id)


# ═══════════════════════════════════════════════════════════════
# ДЕТАЛЬНАЯ СТАТИСТИКА ПРОЕКТОВ
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data == "projects_stats")
def show_projects_statistics(call):
    """Показать детальную статистику всех проектов"""
    user_id = call.from_user.id
    
    bots = db.get_user_bots(user_id)
    
    if not bots:
        safe_answer_callback(bot, call.id, "❌ Нет проектов")
        return
    
    text = (
        "📊 <b>СТАТИСТИКА ПРОЕКТОВ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
    )
    
    # Собираем детальную статистику
    total_categories = 0
    total_keywords = 0
    total_media = 0
    total_descriptions = 0
    total_prices = 0
    total_reviews = 0
    
    most_active_bot = None
    max_categories = 0
    
    for bot_item in bots:
        bot_id = bot_item['id']
        bot_name = bot_item['name']
        categories = db.get_bot_categories(bot_id)
        
        if not categories:
            continue
        
        cat_count = len(categories)
        total_categories += cat_count
        
        # Обновляем самый активный бот
        if cat_count > max_categories:
            max_categories = cat_count
            most_active_bot = bot_name
        
        for cat in categories:
            # Ключевые фразы
            keywords = cat.get('keywords', [])
            if isinstance(keywords, list):
                total_keywords += len(keywords)
            
            # Медиа
            media = cat.get('media', [])
            if isinstance(media, list):
                total_media += len(media)
            
            # Описания
            if cat.get('description'):
                total_descriptions += 1
            
            # Цены
            prices = cat.get('prices', {})
            if isinstance(prices, dict) and prices:
                total_prices += len(prices)
            
            # Отзывы
            reviews = cat.get('reviews', [])
            if isinstance(reviews, list):
                total_reviews += len(reviews)
    
    # Средние показатели
    avg_categories = total_categories / len(bots) if bots else 0
    avg_keywords = total_keywords / total_categories if total_categories else 0
    
    text += (
        f"<b>📁 ПРОЕКТЫ:</b>\n"
        f"• Всего: <code>{len(bots)}</code>\n"
        f"• Самый активный: <b>{most_active_bot or 'N/A'}</b> ({max_categories} кат.)\n\n"
        
        f"<b>📂 КАТЕГОРИИ:</b>\n"
        f"• Всего: <code>{total_categories}</code>\n"
        f"• В среднем: <code>{avg_categories:.1f}</code> на проект\n\n"
        
        f"<b>🔑 КОНТЕНТ:</b>\n"
        f"• Ключевых фраз: <code>{total_keywords}</code>\n"
        f"• В среднем: <code>{avg_keywords:.1f}</code> на категорию\n"
        f"• Описаний: <code>{total_descriptions}</code>\n\n"
        
        f"<b>📷 МЕДИА:</b>\n"
        f"• Файлов: <code>{total_media}</code>\n\n"
        
        f"<b>💰 ДОПОЛНИТЕЛЬНО:</b>\n"
        f"• Прайс-листов: <code>{total_prices}</code>\n"
        f"• Отзывов: <code>{total_reviews}</code>\n\n"
        
        "━━━━━━━━━━━━━━\n\n"
        "<i>💡 Продолжайте развивать ваши проекты!</i>"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("📈 Топ проектов", callback_data="top_projects"),
        types.InlineKeyboardButton("🔙 К проектам", callback_data="show_projects")
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


@bot.callback_query_handler(func=lambda call: call.data == "top_projects")
def show_top_projects(call):
    """Показать топ проектов по активности"""
    user_id = call.from_user.id
    
    bots = db.get_user_bots(user_id)
    
    if not bots:
        safe_answer_callback(bot, call.id, "❌ Нет проектов")
        return
    
    # Собираем статистику для каждого бота
    bot_stats = []
    
    for bot_item in bots:
        bot_id = bot_item['id']
        bot_name = bot_item['name']
        categories = db.get_bot_categories(bot_id)
        
        cat_count = len(categories) if categories else 0
        keywords_count = 0
        media_count = 0
        
        if categories:
            for cat in categories:
                keywords = cat.get('keywords', [])
                if isinstance(keywords, list):
                    keywords_count += len(keywords)
                
                media = cat.get('media', [])
                if isinstance(media, list):
                    media_count += len(media)
        
        # Считаем общий балл активности
        activity_score = cat_count * 10 + keywords_count + media_count * 2
        
        bot_stats.append({
            'id': bot_id,
            'name': bot_name,
            'categories': cat_count,
            'keywords': keywords_count,
            'media': media_count,
            'score': activity_score
        })
    
    # Сортируем по активности
    bot_stats.sort(key=lambda x: x['score'], reverse=True)
    
    text = (
        "📈 <b>ТОП ПРОЕКТОВ ПО АКТИВНОСТИ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
    )
    
    medals = ["🥇", "🥈", "🥉"]
    
    for idx, stat in enumerate(bot_stats[:10], 1):
        medal = medals[idx-1] if idx <= 3 else f"{idx}."
        
        text += (
            f"{medal} <b>{stat['name']}</b>\n"
            f"   📂 {stat['categories']} кат. | "
            f"🔑 {stat['keywords']} фраз | "
            f"📷 {stat['media']} медиа\n"
            f"   💯 Активность: <code>{stat['score']}</code>\n\n"
        )
    
    text += "━━━━━━━━━━━━━━\n"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("📊 Общая статистика", callback_data="projects_stats"),
        types.InlineKeyboardButton("🔙 К проектам", callback_data="show_projects")
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


# ═══════════════════════════════════════════════════════════════
# ПОКАЗ ВСЕХ ПРОЕКТОВ (ПОСТРАНИЧНО)
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("show_all_projects"))
def show_all_projects(call):
    """Показать все проекты постранично"""
    user_id = call.from_user.id
    
    # Получаем страницу из callback (по умолчанию 0)
    parts = call.data.split("_")
    page = int(parts[-1]) if len(parts) > 3 and parts[-1].isdigit() else 0
    
    bots = db.get_user_bots(user_id)
    
    if not bots:
        safe_answer_callback(bot, call.id, "❌ Нет проектов")
        return
    
    # Пагинация
    per_page = 10
    total_pages = (len(bots) + per_page - 1) // per_page
    start_idx = page * per_page
    end_idx = start_idx + per_page
    
    current_bots = bots[start_idx:end_idx]
    
    text = (
        f"📁 <b>ВСЕ ПРОЕКТЫ</b>\n"
        f"Страница {page + 1} из {total_pages}\n"
        "━━━━━━━━━━━━━━\n\n"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for idx, bot_item in enumerate(current_bots, start_idx + 1):
        bot_id = bot_item['id']
        bot_name = bot_item['name']
        
        categories = db.get_bot_categories(bot_id)
        cat_count = len(categories) if categories else 0
        
        btn_text = f"{idx}. {bot_name}"
        if cat_count > 0:
            btn_text += f" • {cat_count} кат."
        
        markup.add(
            types.InlineKeyboardButton(btn_text, callback_data=f"open_bot_{bot_id}")
        )
    
    # Кнопки навигации
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(
            types.InlineKeyboardButton("◀️ Назад", callback_data=f"show_all_projects_{page-1}")
        )
    
    if page < total_pages - 1:
        nav_buttons.append(
            types.InlineKeyboardButton("Вперед ▶️", callback_data=f"show_all_projects_{page+1}")
        )
    
    if nav_buttons:
        markup.row(*nav_buttons)
    
    markup.add(
        types.InlineKeyboardButton("🔙 К главному меню", callback_data="show_projects")
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


# ═══════════════════════════════════════════════════════════════
# БЫСТРЫЕ ДЕЙСТВИЯ С ПРОЕКТАМИ
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data == "quick_actions_projects")
def show_quick_actions(call):
    """Быстрые действия с проектами"""
    text = (
        "⚡ <b>БЫСТРЫЕ ДЕЙСТВИЯ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Выберите действие:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("➕ Создать новый проект", callback_data="create_bot"),
        types.InlineKeyboardButton("📊 Статистика проектов", callback_data="projects_stats"),
        types.InlineKeyboardButton("📈 Топ по активности", callback_data="top_projects"),
        types.InlineKeyboardButton("🔍 Поиск проекта", callback_data="search_project"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="show_projects")
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


# Заглушка для поиска
@bot.callback_query_handler(func=lambda call: call.data == "search_project")
def search_project(call):
    """Поиск проекта (заглушка)"""
    text = (
        "🔍 <b>ПОИСК ПРОЕКТА</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Функция поиска будет доступна в ближайшее время!\n\n"
        "Вы сможете искать проекты по:\n"
        "• Названию\n"
        "• Категориям\n"
        "• Ключевым словам\n\n"
        "<i>Следите за обновлениями</i>"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data="show_projects")
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


@bot.callback_query_handler(func=lambda call: call.data == "quick_publish_menu")
def show_quick_publish_menu(call):
    """Меню быстрого доступа к публикациям"""
    user_id = call.from_user.id
    
    # Получаем все проекты пользователя
    bots = db.get_user_bots(user_id)
    
    if not bots:
        safe_answer_callback(bot, call.id, "❌ У вас нет проектов", show_alert=True)
        return
    
    # DEBUG: Выводим информацию о проектах
    logger.debug(f"DEBUG: Проекты пользователя {user_id}")
    print(f"📊 Всего проектов: {len(bots)}")
    for bot_item in bots:
        print(f"  📁 Проект: {bot_item.get('name')} (ID: {bot_item.get('id')})")
        
        # Проверяем оба возможных места хранения подключений
        connections1 = bot_item.get('connected_platforms', {})
        connections2 = bot_item.get('platform_connections', {})
        
        print(f"    connected_platforms: {type(connections1)} - {list(connections1.keys()) if isinstance(connections1, dict) else 'не словарь'}")
        print(f"    platform_connections: {type(connections2)} - {list(connections2.keys()) if isinstance(connections2, dict) else 'не словарь'}")
    
    text = """
🚀 <b>БЫСТРЫЙ ДОСТУП К ПУБЛИКАЦИЯМ</b>

Выберите платформу для мгновенной публикации:
• Публикация из случайной категории
• Без подтверждений и вопросов
• Моментальная отправка

<i>Показаны только подключенные платформы</i>
"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    platforms_found = False
    platform_names = {
        'website': ('🌐 WordPress', 'website'),
        'pinterest': ('📌 Pinterest', 'pinterest'),
        'telegram': ('✈️ Telegram', 'telegram'),
        'vk': ('🔵 VK', 'vk')
    }
    
    # Собираем ВСЕ конкретные подключения из всех проектов
    all_connections = []
    
    for bot_item in bots:
        # Проверяем ОБА возможных поля
        bot_connections = bot_item.get('connected_platforms', {})
        
        # Если пусто - пробуем platform_connections
        if not bot_connections or not isinstance(bot_connections, dict):
            bot_connections = bot_item.get('platform_connections', {})
        
        print(f"\n🔍 Проект '{bot_item.get('name')}' - подключения:")
        print(f"   Тип: {type(bot_connections)}")
        if isinstance(bot_connections, dict):
            print(f"   Ключи: {list(bot_connections.keys())}")
        
        # WordPress сайты
        if 'website' in bot_connections or 'websites' in bot_connections:
            # Сначала пробуем множественное число (старый формат)
            websites = bot_connections.get('websites') or bot_connections.get('website', [])
            
            print(f"   🔍 WordPress RAW type: {type(websites)}")
            print(f"   🔍 WordPress RAW value: {repr(websites)[:200]}")
            
            # Если это строка JSON - парсим
            if isinstance(websites, str):
                try:
                    import json
                    websites = json.loads(websites)
                    print(f"   ✅ JSON parsed, new type: {type(websites)}")
                except Exception as e:
                    print(f"   ❌ JSON parse failed: {e}")
                    websites = []
            
            if not isinstance(websites, list):
                websites = [websites] if websites else []
            
            print(f"   📦 WordPress: найдено {len(websites)} подключений")
            
            for ws in websites:
                # Старый формат: просто URL строка
                if isinstance(ws, str):
                    print(f"      🔄 WordPress: преобразуем строку '{ws}' в объект")
                    # Создаём объект из URL
                    ws = {
                        'domain': ws.replace('https://', '').replace('http://', '').split('/')[0],
                        'url': ws,
                        'status': 'active',  # Считаем активным
                        'id': ws  # ID = URL
                    }
                
                # Проверяем что ws - это словарь
                if not isinstance(ws, dict):
                    print(f"      ⚠️ WordPress подключение НЕ словарь: {type(ws)}")
                    continue
                
                print(f"      🔍 WordPress: status={ws.get('status')}, domain={ws.get('domain', ws.get('url'))}")
                
                if ws.get('status') == 'active':
                    domain = ws.get('domain', ws.get('url', 'Сайт'))
                    # Убираем http(s):// для краткости
                    domain = domain.replace('https://', '').replace('http://', '').split('/')[0]
                    
                    # Добавляем префикс "Сайт:"
                    display_name = f"Сайт: {domain}"
                    
                    all_connections.append({
                        'icon': '🌐',
                        'name': display_name,
                        'platform': 'website',
                        'connection_id': ws.get('id'),
                        'bot_id': bot_item['id']
                    })
        
        # Pinterest доски
        if 'pinterest' in bot_connections or 'pinterests' in bot_connections:
            pinterests = bot_connections.get('pinterests') or bot_connections.get('pinterest', [])
            
            # Если это строка JSON - парсим
            if isinstance(pinterests, str):
                try:
                    import json
                    pinterests = json.loads(pinterests)
                except Exception:
                    pinterests = []
            
            if not isinstance(pinterests, list):
                pinterests = [pinterests] if pinterests else []
            
            print(f"   📦 Pinterest: найдено {len(pinterests)} подключений")
            
            for pin in pinterests:
                # Старый формат: board_id строка
                if isinstance(pin, str):
                    print(f"      🔄 Pinterest: преобразуем строку '{pin}' в объект")
                    pin = {
                        'board_id': pin,
                        'board_name': f'Доска {pin[:20]}',
                        'status': 'active',
                        'id': pin
                    }
                
                if not isinstance(pin, dict):
                    print(f"      ⚠️ Pinterest подключение НЕ словарь: {type(pin)}")
                    continue
                
                print(f"      🔍 Pinterest: status={pin.get('status')}, board={pin.get('board_name')}")
                
                if pin.get('status') == 'active':
                    board_name = pin.get('board_name', pin.get('username', 'Pinterest'))
                    # Убираем слово "Доска" если оно есть
                    board_name = board_name.replace('Доска ', '').strip()
                    display_name = f"Pinterest: {board_name}"
                    
                    all_connections.append({
                        'icon': '📌',
                        'name': display_name,
                        'platform': 'pinterest',
                        'connection_id': pin.get('board_id'),
                        'bot_id': bot_item['id']
                    })
        
        # Telegram каналы
        if 'telegram' in bot_connections or 'telegrams' in bot_connections:
            telegrams = bot_connections.get('telegrams') or bot_connections.get('telegram', [])
            
            # Если это строка JSON - парсим
            if isinstance(telegrams, str):
                try:
                    import json
                    telegrams = json.loads(telegrams)
                except Exception:
                    telegrams = []
            
            if not isinstance(telegrams, list):
                telegrams = [telegrams] if telegrams else []
            
            print(f"   📦 Telegram: найдено {len(telegrams)} подключений")
            
            for tg in telegrams:
                # Старый формат: channel_id или @username строка
                if isinstance(tg, str):
                    print(f"      🔄 Telegram: преобразуем строку '{tg}' в объект")
                    tg = {
                        'channel_id': tg,
                        'channel_name': tg.replace('@', ''),
                        'status': 'active',
                        'id': tg
                    }
                
                if not isinstance(tg, dict):
                    print(f"      ⚠️ Telegram подключение НЕ словарь: {type(tg)}")
                    continue
                
                print(f"      🔍 Telegram: status={tg.get('status')}, channel={tg.get('channel_name')}")
                
                if tg.get('status') == 'active':
                    channel_name = tg.get('channel_name', tg.get('title', 'Канал'))
                    display_name = f"Telegram: {channel_name}"
                    
                    all_connections.append({
                        'icon': '✈️',
                        'name': display_name,
                        'platform': 'telegram',
                        'connection_id': tg.get('channel_id'),
                        'bot_id': bot_item['id']
                    })
        
        # VK страницы и группы
        if 'vk' in bot_connections or 'vks' in bot_connections:
            # КРИТИЧНО: СНАЧАЛА читаем из user.platform_connections (там полные данные)
            user = db.get_user(user_id)
            user_platform_conns = user.get('platform_connections', {})
            if isinstance(user_platform_conns, str):
                try:
                    import json
                    user_platform_conns = json.loads(user_platform_conns)
                except Exception:
                    user_platform_conns = {}
            
            vks = user_platform_conns.get('vks', [])
            
            if vks and len(vks) > 0:
                print(f"   ✅ VK: читаем из user.platform_connections: {len(vks)}")
                # DEBUG
                for idx, vk_debug in enumerate(vks, 1):
                    print(f"   🔍 VK объект #{idx}:")
                    if isinstance(vk_debug, dict):
                        print(f"      id: {vk_debug.get('id')}, group_name: {vk_debug.get('group_name')}, type: {vk_debug.get('type')}")
            
            # Fallback на bot.connected_platforms (только ID, без имён)
            if not vks or vks == []:
                vks = bot_connections.get('vks') or bot_connections.get('vk', [])
                print(f"   ⚠️ VK: fallback на bot (только ID): {len(vks) if isinstance(vks, list) else 0}")
            
            print(f"   🔍 VK RAW type: {type(vks)}")
            print(f"   🔍 VK RAW value: {repr(vks)[:200]}")
            
            # Если это строка JSON - парсим
            if isinstance(vks, str):
                try:
                    import json
                    vks = json.loads(vks)
                except Exception:
                    vks = []
            
            if not isinstance(vks, list):
                vks = [vks] if vks else []
            
            print(f"   📦 VK: найдено {len(vks)} подключений")
            
            for vk in vks:
                # Старый формат: может быть строка или объект без полей
                if isinstance(vk, str):
                    print(f"      🔄 VK: преобразуем строку '{vk}' в объект")
                    vk = {
                        'id': vk,
                        'user_id': vk,
                        'type': 'user',
                        'group_name': f'VK {vk}',
                        'status': 'active'
                    }
                
                if not isinstance(vk, dict):
                    print(f"      ⚠️ VK подключение НЕ словарь: {type(vk)}")
                    continue
                
                # Валидация: проверяем что это реальное VK подключение
                vk_id = vk.get('id') or vk.get('user_id') or vk.get('group_id')
                
                # Пропускаем невалидные ID
                if not vk_id or vk_id in ['main', 'default', 'null', 'undefined']:
                    print(f"      ❌ VK невалидный ID: {vk_id} - пропускаем")
                    continue
                
                # Пропускаем если ID не число (для user) и не выглядит как group_id
                if isinstance(vk_id, str):
                    # Убираем минус для проверки
                    check_id = vk_id.lstrip('-')
                    if not check_id.isdigit():
                        print(f"      ❌ VK ID не число: {vk_id} - пропускаем")
                        continue
                
                # Если объект пустой или без status - добавляем status
                if not vk.get('status'):
                    print(f"      🔄 VK: добавляем status=active к объекту")
                    vk['status'] = 'active'
                
                # Если нет group_name - используем дефолтное значение
                if not vk.get('group_name'):
                    vk['group_name'] = 'VK Страница'
                
                # Если нет type - определяем по ID
                if not vk.get('type'):
                    vk['type'] = 'group' if str(vk_id).startswith('-') else 'user'
                
                print(f"      🔍 VK: status={vk.get('status')}, type={vk.get('type')}, name={vk.get('group_name')}, id={vk_id}")
                
                if vk.get('status') == 'active':
                    group_name = vk.get('group_name', 'Страница')
                    vk_type = vk.get('type', 'user')
                    
                    # Создаём уникальный ключ
                    unique_key = f"vk_{vk_type}_{vk_id}"
                    
                    print(f"      🔍 VK unique_key: {unique_key}")
                    
                    # ТОЧНО КАК В main_menu.py - определяем иконку по типу
                    if vk_type == 'group':
                        icon = '📝'  # Группа
                        members = vk.get('members_count', 0)
                        members_text = f" ({members:,})" if members > 0 else ""
                        display_name = f"VK ({group_name}){members_text}"
                    else:
                        icon = '👤'  # Личная страница
                        display_name = f"VK ({group_name})"
                    
                    # Проверка на дубль - используем unique_key
                    is_duplicate = any(
                        conn.get('unique_key') == unique_key
                        for conn in all_connections
                    )
                    
                    if is_duplicate:
                        print(f"      ⚠️ VK дубль пропущен: {unique_key}")
                        continue
                    
                    print(f"      🔍 ДОБАВЛЯЕМ VK:")
                    print(f"         vk_id = {vk_id} (type: {type(vk_id)})")
                    print(f"         icon = {icon}")
                    print(f"         display_name = {display_name}")
                    
                    all_connections.append({
                        'icon': icon,
                        'name': display_name,
                        'platform': 'vk',
                        'connection_id': vk_id,
                        'unique_key': unique_key,  # Для проверки дублей
                        'bot_id': bot_item['id']
                    })
                    print(f"      ✅ Добавлен VK: connection_id={vk_id}")
        
    # Добавляем кнопки для каждого подключения
    print(f"\n✅ ИТОГО найдено подключений: {len(all_connections)}")
    for conn in all_connections:
        print(f"   {conn['icon']} {conn['name']} ({conn['platform']})")
    
    for conn in all_connections:
        platforms_found = True
        # Ограничиваем длину названия (учитываем префикс)
        full_display = f"{conn['icon']} {conn['name']}"
        display_name = full_display[:45] + '...' if len(full_display) > 45 else full_display
        
        # КРИТИЧНО: Добавляем connection_id чтобы различать подключения
        callback_data = f"quick_publish_{conn['platform']}_{conn['bot_id']}_{conn['connection_id']}"
        print(f"   🔘 Кнопка: {display_name} → callback={callback_data}")
        
        markup.add(
            types.InlineKeyboardButton(
                display_name,
                callback_data=callback_data
            )
        )
    
    if not platforms_found:
        text += "\n\n⚠️ <b>Нет подключенных платформ</b>\n"
        text += "Подключите площадки в настройках проектов"
    
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_projects")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("quick_publish_"))
def handle_quick_publish(call):
    """Быстрая публикация на платформу"""
    logger.debug(f" Получен callback_data = {call.data}")
    
    # Парсим: quick_publish_PLATFORM_BOT_ID_CONNECTION_ID
    parts = call.data.replace("quick_publish_", "").split('_')
    
    logger.debug(f" parts после split = {parts}")
    
    platform_type = None
    target_bot_id = None
    connection_id = None
    
    if len(parts) >= 3:
        # Новый формат с connection_id
        platform_type = parts[0]  # vk, website, telegram, etc
        target_bot_id = int(parts[1])  # ID проекта
        connection_id = '_'.join(parts[2:])  # ID подключения (может содержать _)
    elif len(parts) >= 2:
        # Средний формат без connection_id
        platform_type = parts[0]
        target_bot_id = int(parts[1])
    else:
        # Старый формат
        platform_type = parts[0]
    
    user_id = call.from_user.id
    
    print(f"🚀 Quick publish: platform={platform_type}, bot_id={target_bot_id}, connection_id={connection_id}")
    
    safe_answer_callback(bot, call.id, f"🔄 Публикую на {platform_type.upper()}...")
    
    try:
        # Если указан конкретный bot_id - используем его
        if target_bot_id:
            bot_data = db.get_bot(target_bot_id)
            if not bot_data or bot_data.get('user_id') != user_id:
                bot.send_message(call.message.chat.id, "❌ Проект не найден")
                return
            
            # Берём категории из этого проекта
            categories = db.get_bot_categories(target_bot_id)
            if not categories:
                bot.send_message(call.message.chat.id, f"❌ Нет категорий в проекте {bot_data.get('name')}")
                return
            
            # Выбираем случайную категорию
            import random
            category = random.choice(categories)
            bot_id = target_bot_id
            category_id = category['id']
        else:
            # Старая логика - из всех проектов
            # Получаем все проекты пользователя
            bots = db.get_user_bots(user_id)
            
            # Собираем все категории из всех проектов
            all_categories = []
            for bot_item in bots:
                bot_id_item = bot_item['id']
                categories = db.get_bot_categories(bot_id_item)
                if categories:
                    for cat in categories:
                        all_categories.append({
                            'category': cat,
                            'bot_id': bot_id_item,
                            'bot_name': bot_item['name']
                        })
            
            if not all_categories:
                bot.send_message(call.message.chat.id, "❌ Нет категорий для публикации")
                return
            
            # Выбираем случайную категорию
            import random
            selected = random.choice(all_categories)
            category = selected['category']
            bot_id = selected['bot_id']
            category_id = category['id']
        
        # Получаем platform_id из подключений
        bot_data = db.get_bot(bot_id)
        bot_connections = bot_data.get('connected_platforms', {})
        
        # Ищем platform_id (может быть в старом или новом формате)
        platform_key_old = f"{platform_type}s"  # websites, telegrams
        platform_key_new = platform_type  # website, telegram
        
        platforms_list = bot_connections.get(platform_key_new) or bot_connections.get(platform_key_old) or []
        
        if not platforms_list:
            bot.send_message(call.message.chat.id, f"❌ Платформа {platform_type.upper()} не подключена")
            return
        
        # КРИТИЧНО: Ищем нужную платформу по connection_id
        platform_obj = None
        
        if connection_id:
            # Ищем по connection_id
            for plat in platforms_list:
                if isinstance(plat, dict):
                    plat_id = str(plat.get('id') or plat.get('user_id') or plat.get('group_id') or plat.get('board_id') or plat.get('channel_id') or '')
                else:
                    plat_id = str(plat)
                
                if plat_id == str(connection_id):
                    platform_obj = plat
                    print(f"✅ Найдена платформа по connection_id={connection_id}")
                    break
        
        # Fallback: берём первую
        if not platform_obj and isinstance(platforms_list, list) and len(platforms_list) > 0:
            platform_obj = platforms_list[0]
            print(f"⚠️ Используем первую платформу (fallback)")
        
        if not platform_obj:
            bot.send_message(call.message.chat.id, f"❌ Платформа не найдена")
            return
        
        # Извлекаем ID из объекта
        if isinstance(platform_obj, dict):
            platform_id = platform_obj.get('id') or platform_obj.get('user_id') or platform_obj.get('group_id') or platform_obj.get('board_id') or platform_obj.get('channel_id')
            print(f"📝 Извлекли platform_id из объекта: {platform_id}")
        else:
            platform_id = platform_obj
        
        # Перенаправляем на обработчик публикации
        from handlers.platform_category.main_menu import handle_platform_ai_post
        
        # Создаём фейковый callback для публикации
        class FakeCall:
            def __init__(self, data, message, from_user, call_id):
                self.data = data
                self.message = message
                self.from_user = from_user
                self.id = call_id  # Используем реальный ID
        
        fake_call = FakeCall(
            data=f"platform_ai_post_{platform_type}_{category_id}_{bot_id}_{platform_id}",
            message=call.message,
            from_user=call.from_user,
            call_id=call.id  # Передаём реальный ID оригинального callback
        )
        
        # Вызываем обработчик публикации
        handle_platform_ai_post(fake_call)
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"❌ ОШИБКА В QUICK_PUBLISH:")
        print(error_details)
        bot.send_message(call.message.chat.id, f"❌ Ошибка публикации: {e}\n\nДетали в логах.")



@bot.callback_query_handler(func=lambda call: call.data == "back_to_projects")
def back_to_projects(call):
    """Возврат к меню проектов"""
    # ВАЖНО: Создаем фейковый message объект с правильным user_id
    # Потому что call.message.from_user.id = ID бота, а не пользователя!
    fake_message = type('obj', (object,), {
        'from_user': call.from_user,  # Берем from_user из call, а не из message!
        'chat': call.message.chat
    })()
    
    show_projects_menu(fake_message)
    safe_answer_callback(bot, call.id)


print("✅ handlers/projects.py (расширенный) загружен")
