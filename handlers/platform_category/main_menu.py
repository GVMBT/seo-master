"""
Меню управления платформой в контексте категории
Позволяет подключать/отключать платформу, делать посты, настраивать планировщик
"""
import os
import logging
from telebot import types
from loader import bot, db
from utils import escape_html
import json
from datetime import datetime

logger = logging.getLogger(__name__)

# Безопасное логирование
try:
    from debug_logger import debug
except Exception:
    # Fallback - простой print
    class SimpleDebug:
        def header(self, *args): pass
        def info(self, *args): pass
        def success(self, *args): pass
        def warning(self, *args): pass
        def error(self, *args): pass
        def debug(self, *args): pass
        def dict_dump(self, *args, **kwargs): pass
        def footer(self): pass
    debug = SimpleDebug()


@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_menu_"))
def handle_platform_menu(call):
    """
    Открытие меню управления платформой для категории
    
    Формат: platform_menu_{category_id}_{bot_id}_{platform_type}_{platform_id}
    Или: platform_menu_manage_{category_id}_{bot_id}_{platform_type}_{platform_id}
    """
    debug.header("HANDLE_PLATFORM_MENU")
    debug.info("callback_data", call.data)
    
    # Убираем _manage если есть
    callback_data = call.data.replace("platform_menu_manage_", "platform_menu_")
    
    parts = callback_data.split("_")
    
    # Парсим параметры
    category_id = int(parts[2])
    bot_id = int(parts[3])
    platform_type = parts[4]  # website, pinterest, telegram
    platform_id = "_".join(parts[5:])  # ID платформы (может содержать _)
    
    debug.info("category_id", category_id)
    debug.info("bot_id", bot_id)
    debug.info("platform_type", platform_type)
    debug.info("platform_id", platform_id)
    
    user_id = call.from_user.id
    
    # Получаем данные
    category = db.get_category(category_id)
    bot_data = db.get_bot(bot_id)
    
    if not category or not bot_data or bot_data['user_id'] != user_id:
        bot.answer_callback_query(call.id, "❌ Ошибка доступа")
        return
    
    category_name = category.get('name', 'Без названия')
    
    # Получаем информацию о платформе
    user = db.get_user(user_id)
    connections = user.get('platform_connections', {}) if user else {}
    
    # Получаем подключения бота
    bot_connections = bot_data.get('connected_platforms', {})
    if isinstance(bot_connections, str):
        try:
            bot_connections = json.loads(bot_connections)
        except Exception:
            bot_connections = {}
    
    debug.dict_dump("bot_connections", bot_connections)
    
    # Определяем активность подключения
    # Новая структура: {pinterest: [{id: "username"}], telegram: [{id: "channel"}]}
    # Старая структура: {pinterests: ["username"], telegrams: ["channel"]}
    is_connected = False
    
    # 1. Проверяем новую структуру (без 's' в конце)
    if platform_type in bot_connections:
        platform_list = bot_connections[platform_type]
        debug.debug(f"Found '{platform_type}' in bot_connections (new structure)")
        debug.dict_dump(f"platform_list", platform_list)
        
        if isinstance(platform_list, list):
            # Проверяем список объектов
            for idx, item in enumerate(platform_list):
                debug.debug(f"Checking item [{idx}]: {item}")
                if isinstance(item, dict):
                    item_id = item.get('id')
                    debug.info(f"item_id", item_id)
                    debug.info(f"platform_id", platform_id)
                    debug.info(f"Match?", item_id == platform_id)
                    if item_id == platform_id:
                        is_connected = True
                        debug.success("✅ MATCH in new structure (dict)!")
                        break
                elif isinstance(item, str):
                    # Список строк (промежуточный формат)
                    debug.info(f"item (string)", item)
                    debug.info(f"platform_id", platform_id)
                    if item == platform_id:
                        is_connected = True
                        debug.success("✅ MATCH in new structure (string)!")
                        break
    else:
        debug.warning(f"'{platform_type}' NOT in bot_connections")
    
    # 2. Проверяем старую структуру (с 's' в конце)
    if not is_connected:
        old_key = platform_type + 's'
        platforms_list = bot_connections.get(old_key, [])
        debug.debug(f"Checking old structure '{old_key}'")
        debug.dict_dump(f"platforms_list (old)", platforms_list)
        
        if isinstance(platforms_list, list):
            # В старой структуре это список строк
            for item in platforms_list:
                debug.debug(f"Checking old item: {item}")
                if item == platform_id:
                    is_connected = True
                    debug.success("✅ MATCH in old structure!")
                    break
    
    debug.info("FINAL is_connected", is_connected)
    debug.footer()
    
    # Получаем название платформы
    platform_name = ""
    platform_emoji = ""
    
    if platform_type == "website":
        sites = connections.get('websites', [])
        for site in sites:
            if site.get('url', '') == platform_id:
                platform_name = site.get('cms', 'Website')
                platform_emoji = "🌐"
                break
    elif platform_type == "pinterest":
        pinterests = connections.get('pinterests', [])
        for pinterest in pinterests:
            if pinterest.get('board', '') == platform_id:
                platform_name = f"Pinterest: {pinterest.get('board', '')}"
                platform_emoji = "📌"
                break
    elif platform_type == "telegram":
        telegrams = connections.get('telegrams', [])
        for telegram in telegrams:
            if telegram.get('channel', '') == platform_id:
                platform_name = f"Telegram: @{telegram.get('channel', '')}"
                platform_emoji = "✈️"
                break
    elif platform_type == "vk":
        vks = connections.get('vks', [])
        for vk in vks:
            if str(vk.get('user_id', '')) == str(platform_id):
                platform_name = f"VK: {vk.get('group_name', 'ВКонтакте')}"
                platform_emoji = "💬"
                break
    
    # Формируем текст
    status_icon = "🟢" if is_connected else "❌"
    status_text = "ПОДКЛЮЧЕНА" if is_connected else "ОТКЛЮЧЕНА"
    
    text = (
        f"{platform_emoji} <b>{platform_name}</b>\n"
        f"📂 Категория: {escape_html(category_name)}\n"
        "━━━━━━━━━━━━━━\n\n"
        f"<b>Статус:</b> {status_icon} {status_text}\n\n"
    )
    
    if is_connected:
        # Получаем информацию о планировщике
        from handlers.global_scheduler import _get_platform_scheduler
        import datetime
        
        schedule = _get_platform_scheduler(category_id, platform_type, platform_id)
        is_scheduler_enabled = schedule.get('enabled', False)
        
        if is_scheduler_enabled:
            days = schedule.get('days', [])  # ['mon', 'tue', ...]
            posts_per_day = schedule.get('posts_per_day', 1) or 1
            
            # Названия дней
            days_names = {
                'mon': 'Пн', 'tue': 'Вт', 'wed': 'Ср',
                'thu': 'Чт', 'fri': 'Пт', 'sat': 'Сб', 'sun': 'Вс'
            }
            
            # Правильный порядок дней недели
            days_order = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
            
            # Сортируем дни по правильному порядку
            sorted_days = sorted(days, key=lambda d: days_order.index(d) if d in days_order else 999)
            
            days_text = ", ".join([days_names.get(d, d) for d in sorted_days]) if sorted_days else "Не выбраны"
            
            # Расчёт постов в неделю
            posts_per_week = len(days) * posts_per_day if days else 0
            
            # Форматируем расписание
            if len(days) == 7:
                schedule_text = f"Каждый день ({days_text}), {posts_per_day} {'пост' if posts_per_day == 1 else 'поста' if posts_per_day < 5 else 'постов'}/день"
            else:
                schedule_text = f"{days_text}, {posts_per_day} {'раз' if posts_per_day == 1 else 'раза' if posts_per_day < 5 else 'раз'}/день"
            
            # Расчёт затрат (40 токенов за пост)
            tokens_per_week = posts_per_week * 40
            tokens_per_month = tokens_per_week * 4
            
            # Следующая публикация (примерно)
            if len(days) == 7:
                # Каждый день - через ~24/posts_per_day часов
                hours_until_next = 24 / posts_per_day if posts_per_day > 0 else 24
                next_time = datetime.datetime.now() + datetime.timedelta(hours=hours_until_next)
            elif len(days) > 0:
                # Через ~7/количество_дней
                days_until_next = 7 / len(days)
                next_time = datetime.datetime.now() + datetime.timedelta(days=days_until_next)
            else:
                next_time = datetime.datetime.now()
            
            next_time_str = next_time.strftime("%d.%m в %H:%M")
            
            text += (
                "📅 <b>ПЛАНИРОВЩИК:</b> 🟢 Активен\n"
                f"   • Расписание: {schedule_text}\n"
                f"   • Постов в неделю: {posts_per_week}\n"
                f"   • Следующая публикация: ~{next_time_str}\n\n"
                "💰 <b>ЗАТРАТЫ НА ПУБЛИКАЦИИ:</b>\n"
                f"   • Неделя: {tokens_per_week} токенов\n"
                f"   • Месяц: {tokens_per_month} токенов\n\n"
            )
        else:
            text += (
                "📅 <b>ПЛАНИРОВЩИК:</b> ⚪ Не настроен\n\n"
            )
        
        text += (
            "✅ Платформа активна для этой категории\n\n"
            "<b>Доступные действия:</b>\n"
            "• Опубликовать пост вручную\n"
            "• Настроить автопостинг\n"
            "• Отключить платформу\n"
        )
    else:
        text += (
            "❌ Платформа не активна\n\n"
            "Подключите платформу, чтобы публиковать контент из этой категории.\n"
        )
    
    # Создаем клавиатуру
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    if is_connected:
        # Активная платформа - показываем функции
        # Меняем текст кнопки в зависимости от платформы
        if platform_type.lower() == 'pinterest':
            post_button_text = "📌 Опубликовать пин"
        elif platform_type.lower() == 'telegram':
            post_button_text = "📤 Опубликовать пост"
        else:
            post_button_text = "📤 Опубликовать"
        
        # Опубликовать - большая кнопка на всю ширину
        markup.add(
            types.InlineKeyboardButton(
                post_button_text,
                callback_data=f"platform_ai_post_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            )
        )
        
        # Кнопки настроек для всех платформ
        markup.row(
            types.InlineKeyboardButton(
                "🖼 Изображения",
                callback_data=f"platform_images_menu_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            ),
            types.InlineKeyboardButton(
                "✍️ Текст",
                callback_data=f"platform_text_menu_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            )
        )
        
        markup.add(
            types.InlineKeyboardButton(
                "📷 Мои медиа",
                callback_data=f"platform_media_{platform_type}_{category_id}_{bot_id}"
            )
        )
        
        # Кнопка "Ссылка на сайт" для всех платформ КРОМЕ website
        if platform_type.lower() != 'website':
            markup.add(
                types.InlineKeyboardButton(
                    "🔗 Ссылка на сайт",
                    callback_data=f"platform_link_{platform_type}_{category_id}_{bot_id}_{platform_id}"
                )
            )
        
        # Специальная кнопка "Выбор досок" только для Pinterest
        if platform_type.lower() == 'pinterest':
            markup.add(
                types.InlineKeyboardButton(
                    "📋 Выбор досок",
                    callback_data=f"pinterest_boards_{category_id}_{bot_id}_{platform_id}"
                )
            )
        
        # Специальная кнопка "Настройка топиков" только для Telegram
        if platform_type.lower() == 'telegram':
            markup.add(
                types.InlineKeyboardButton(
                    "📡 Настройка топиков",
                    callback_data=f"telegram_topics_{category_id}_{bot_id}_{platform_id}"
                )
            )
        
        markup.add(
            types.InlineKeyboardButton(
                "❌ Отключить платформу",
                callback_data=f"platform_toggle_{category_id}_{bot_id}_{platform_type}_{platform_id}"
            )
        )
    else:
        # Неактивная платформа - только подключение
        markup.add(
            types.InlineKeyboardButton(
                "✅ Подключить платформу",
                callback_data=f"platform_toggle_{category_id}_{bot_id}_{platform_type}_{platform_id}"
            )
        )
    
    # Кнопка назад
    markup.add(
        types.InlineKeyboardButton(
            "🔙 К категории",
            callback_data=f"open_category_{category_id}"
        )
    )
    
    # Отправляем сообщение
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_toggle_"))
def handle_platform_toggle(call):
    """
    Переключение подключения платформы (вкл/выкл)
    
    Формат: platform_toggle_{category_id}_{bot_id}_{platform_type}_{platform_id}
    """
    parts = call.data.split("_")
    
    category_id = int(parts[2])
    bot_id = int(parts[3])
    platform_type = parts[4]
    platform_id = "_".join(parts[5:])
    
    user_id = call.from_user.id
    
    # Получаем бота
    bot_data = db.get_bot(bot_id)
    
    if not bot_data or bot_data['user_id'] != user_id:
        bot.answer_callback_query(call.id, "❌ Нет доступа")
        return
    
    # Получаем текущие подключения
    bot_connections = bot_data.get('connected_platforms', {})
    if isinstance(bot_connections, str):
        try:
            bot_connections = json.loads(bot_connections)
        except Exception:
            bot_connections = {}
    
    if not isinstance(bot_connections, dict):
        bot_connections = {}
    
    # Работаем с новой структурой (без 's')
    # {pinterest: [{id: "username"}], telegram: [{id: "channel"}]}
    if platform_type not in bot_connections:
        bot_connections[platform_type] = []
    
    platform_list = bot_connections[platform_type]
    if not isinstance(platform_list, list):
        platform_list = []
    
    # Проверяем активность (ищем в списке объектов)
    is_active = False
    active_index = -1
    
    for i, item in enumerate(platform_list):
        if isinstance(item, dict) and item.get('id') == platform_id:
            is_active = True
            active_index = i
            break
        elif isinstance(item, str) and item == platform_id:
            is_active = True
            active_index = i
            break
    
    # Переключаем
    if is_active:
        # Отключаем
        platform_list.pop(active_index)
        action = "отключена"
        icon = "❌"
    else:
        # Подключаем - добавляем как объект с id
        platform_list.append({'id': platform_id})
        action = "подключена"
        icon = "✅"
    
    bot_connections[platform_type] = platform_list
    
    # Сохраняем в БД
    db.update_bot(bot_id, connected_platforms=bot_connections)
    
    # Возвращаемся в меню платформы
    call.data = f"platform_menu_{category_id}_{bot_id}_{platform_type}_{platform_id}"
    handle_platform_menu(call)
    
    bot.answer_callback_query(call.id, f"{icon} Платформа {action}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_post_"))
def handle_platform_post(call):
    """Ручная публикация поста на платформу"""
    parts = call.data.split("_")
    
    platform_type = parts[2]  # website, pinterest, telegram
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = "_".join(parts[5:])
    
    # Получаем данные категории
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    category_name = category.get('name', 'Без названия')
    description = category.get('description', '')
    
    text = (
        f"✍️ <b>ПУБЛИКАЦИЯ ПОСТА</b>\n"
        f"📂 Категория: {escape_html(category_name)}\n"
        f"📱 Платформа: {platform_type.upper()}\n"
        "━━━━━━━━━━━━━━\n\n"
        "Выберите способ создания поста:\n"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    # Если есть описание - можно использовать его
    if description:
        markup.add(
            types.InlineKeyboardButton(
                "📝 Использовать готовое описание",
                callback_data=f"post_use_desc_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            )
        )
    
    markup.add(
        types.InlineKeyboardButton(
            "✍️ Написать текст вручную",
            callback_data=f"post_manual_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        )
    )
    
    markup.add(
        types.InlineKeyboardButton(
            "🤖 Сгенерировать с AI",
            callback_data=f"platform_ai_post_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        )
    )
    
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_menu_{category_id}_{bot_id}_{platform_type}_{platform_id}"
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_ai_post_"))
def handle_platform_ai_post(call):
    """Генерация и публикация поста с помощью AI"""
    parts = call.data.split("_")
    
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    platform_id = "_".join(parts[6:])
    
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    category_name = category.get('name', 'Без названия')
    user_id = call.from_user.id
    
    # Словарь названий публикаций для разных платформ
    platform_names = {
        'pinterest': {
            'title': 'ПИНА',
            'noun': 'пин',
            'action': 'опубликует пин'
        },
        'telegram': {
            'title': 'ПОСТА',
            'noun': 'пост',
            'action': 'опубликует пост'
        },
        'vk': {
            'title': 'ПОСТА',
            'noun': 'пост',
            'action': 'опубликует пост'
        },
        'website': {
            'title': 'СТАТЬИ',
            'noun': 'статью',
            'action': 'создаст статью'
        }
    }
    
    # Получаем название для текущей платформы
    platform_info = platform_names.get(platform_type.lower(), {
        'title': 'КОНТЕНТА',
        'noun': 'контент',
        'action': 'создаст контент'
    })
    
    # Проверяем баланс
    tokens = db.get_user_tokens(user_id)
    
    # Для Pinterest: изображение (30) + текст (10) = 40 токенов
    if platform_type.lower() == 'pinterest':
        cost = 40
        cost_breakdown = (
            "💰 <b>Стоимость публикации:</b>\n"
            "• Генерация изображения: 30 токенов\n"
            "• Генерация текста: 10 токенов\n"
            "• <b>Итого: 40 токенов</b>\n\n"
        )
    elif platform_type.lower() == 'telegram':
        cost = 40
        cost_breakdown = (
            "💰 <b>Стоимость публикации:</b>\n"
            "• Генерация текста (до 100 слов): 10 токенов\n"
            "• Генерация изображения: 30 токенов\n"
            "• <b>Итого: 40 токенов</b>\n\n"
        )
    elif platform_type.lower() == 'website':
        # Для Website рассчитываем по настройкам из БД
        from handlers.website.article_generation import get_image_settings
        settings = get_image_settings(user_id, category_id)
        
        # Защита от отсутствия параметров
        if not settings or not isinstance(settings, dict):
            settings = {'words': 1500, 'images': 3}
        
        # Получаем количество слов и изображений из настроек
        words = settings.get('words', 1500)
        images = settings.get('images', 3)
        
        # Если images = 0, пробуем взять из advanced
        if not images:
            advanced = settings.get('advanced', {})
            images = advanced.get('images_count', 3)
        
        # Расчёт стоимости: текст (10 токенов за 100 слов) + изображения (30 токенов за штуку)
        text_cost = (words // 100) * 10
        if text_cost == 0:
            text_cost = 10
        image_cost = (images + 1) * 30  # +1 за обложку
        cost = text_cost + image_cost
        
        cost_breakdown = (
            f"💰 <b>Стоимость публикации:</b>\n"
            f"• Генерация изображения: {image_cost} токенов ({images} + обложка)\n"
            f"• Генерация текста: {text_cost} токенов (~{words} слов)\n"
            f"• <b>Итого: {cost} токенов</b>\n\n"
        )
    else:
        # Для VK, Pinterest, Telegram: текст (20) + изображение (30) = 50 токенов
        cost = 50
        cost_breakdown = (
            "💰 <b>Стоимость:</b> 50 токенов\n"
            "• Генерация текста: 20 токенов\n"
            "• Генерация изображения: 30 токенов\n\n"
        )
    
    # Проверяем GOD режим для отображения баланса
    from config import ADMIN_ID
    admin_id = int(ADMIN_ID) if ADMIN_ID else None
    is_god = (admin_id and user_id == admin_id)
    
    if is_god:
        balance_display = "∞ (безлимит)"
    else:
        balance_display = f"{tokens:,} токенов"
    
    text = (
        f"📌 <b>ПУБЛИКАЦИЯ {platform_info['title'].upper()}</b>\n"
        f"📂 Категория: {escape_html(category_name)}\n"
        "━━━━━━━━━━━━━━\n\n"
        f"{cost_breakdown}"
        f"💳 Ваш баланс: <b>{balance_display}</b>\n\n"
    )
    
    if tokens < cost and not is_god:
        # Проверяем GOD режим
        from config import ADMIN_ID
        admin_id = int(ADMIN_ID) if ADMIN_ID else None
        is_god = (admin_id and user_id == admin_id)
        
        if is_god:
            # Для GOD показываем что токенов достаточно (безлимит)
            text += (
                f"👑 <b>GOD режим:</b> Безлимитные токены\n\n"
                f"AI создаст и {platform_info['action']}:\n"
                "• Уникальное изображение\n"
                "• Описание с ключевыми словами\n"
                "• Автоматическая публикация\n\n"
                "Подтвердить публикацию?"
            )
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "✅ Да, опубликовать",
                    callback_data=f"ai_post_confirm_{platform_type}_{category_id}_{bot_id}_{platform_id}"
                )
            )
            markup.add(
                types.InlineKeyboardButton(
                    "🔙 Назад",
                    callback_data=f"platform_menu_{category_id}_{bot_id}_{platform_type}_{platform_id}"
                )
            )
        else:
            # Для обычных пользователей - недостаточно токенов
            text += (
                f"❌ <b>Недостаточно токенов!</b>\n\n"
                f"Нужно: <b>{cost}</b> токенов\n"
                f"У вас: <b>{tokens}</b> токенов\n"
                f"Не хватает: <b>{cost - tokens}</b> токенов\n\n"
                f"💡 Пополните баланс для публикации"
            )
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "💳 Пополнить баланс",
                    callback_data="tariffs"
                )
            )
            markup.add(
                types.InlineKeyboardButton(
                    "🔙 Назад",
                    callback_data=f"platform_menu_{category_id}_{bot_id}_{platform_type}_{platform_id}"
                )
            )
    else:
        if platform_type.lower() == 'telegram':
            text += (
                f"AI создаст и {platform_info['action']}:\n"
                "• Уникальное изображение\n"
                "• Текст до 100 слов (без хештегов)\n"
                "• Автоматическая публикация в канал\n\n"
                "❗️ Пост будет опубликован сразу\n"
                "Подтвердить публикацию?"
            )
        else:
            text += (
                f"AI создаст и {platform_info['action']}:\n"
                "• Уникальное изображение\n"
                "• Описание с ключевыми словами\n"
                "• Автоматическая публикация\n\n"
                "Подтвердить публикацию?"
            )
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(
                "✅ Да, опубликовать",
                callback_data=f"ai_post_confirm_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"platform_menu_{category_id}_{bot_id}_{platform_type}_{platform_id}"
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("ai_post_confirm_"))
def handle_ai_post_confirm(call):
    """Подтверждение генерации AI поста"""
    parts = call.data.split("_")
    
    platform_type = parts[3]
    category_id = int(parts[4])
    bot_id = int(parts[5])
    platform_id = "_".join(parts[6:])
    
    user_id = call.from_user.id
    
    # Словарь названий для разных платформ
    platform_names = {
        'pinterest': {
            'title': 'ПИНА',
            'noun_gen': 'пина',  # родительный падеж
            'platform_name': 'Pinterest'
        },
        'telegram': {
            'title': 'ПОСТА',
            'noun_gen': 'поста',
            'platform_name': 'Telegram'
        },
        'vk': {
            'title': 'ПОСТА',
            'noun_gen': 'поста',
            'platform_name': 'VK'
        },
        'website': {
            'title': 'СТАТЬИ',
            'noun_gen': 'статьи',
            'platform_name': 'сайт'
        }
    }
    
    # Получаем название для текущей платформы
    platform_info = platform_names.get(platform_type.lower(), {
        'title': 'КОНТЕНТА',
        'noun_gen': 'контента',
        'platform_name': 'платформу'
    })
    
    # Списываем токены сразу
    if platform_type.lower() == 'pinterest':
        cost = 40  # изображение 30 + текст 10
    elif platform_type.lower() == 'telegram':
        cost = 50  # текст 20 + изображение 30
    elif platform_type.lower() == 'vk':
        cost = 50  # текст 20 + изображение 30
    else:
        cost = 20
    
    # Проверяем и списываем токены
    from config import ADMIN_ID
    
    # Конвертируем ADMIN_ID в int (он загружается как строка из .env)
    admin_id = int(ADMIN_ID) if ADMIN_ID else None
    
    # Проверяем ADMIN_ID (GOD режим)
    is_god_mode = (admin_id and user_id == admin_id)
    
    if not is_god_mode:
        # Дополнительно проверяем роль в БД
        user = db.get_user(user_id)
        if user:
            if not isinstance(user, dict):
                user = dict(user)
            
            role = user.get('role', '')
            if role and 'GOD' in role.upper():
                is_god_mode = True
    
    if not is_god_mode:
        # Для обычных пользователей проверяем токены
        tokens = db.get_user_tokens(user_id)
        if tokens < cost:
            bot.answer_callback_query(call.id, f"❌ Недостаточно токенов! Нужно: {cost}", show_alert=True)
            return
        
        # Списываем токены
        if not db.update_tokens(user_id, -cost):
            bot.answer_callback_query(call.id, "❌ Ошибка списания токенов", show_alert=True)
            return
    else:
        # GOD режим - токены не списываем
        logger.info(f"👑 ADMIN/GOD режим: токены не списываются для user_id={user_id}")
    
    new_balance = db.get_user_tokens(user_id)
    
    # ═══════════════════════════════════════════════════════════════
    # WEBSITE - ПЕРЕНАПРАВЛЕНИЕ НА СПЕЦИАЛЬНЫЙ ОБРАБОТЧИК
    # ═══════════════════════════════════════════════════════════════
    if platform_type.lower() == 'website':
        # Возвращаем токены - они спишутся в обработчике website
        db.update_tokens(user_id, cost)
        
        # Перенаправляем на правильный обработчик
        call.data = f"platform_ai_post_website_{category_id}_{bot_id}_{platform_id}"
        
        # Импортируем и вызываем обработчик website
        from handlers.website.article_generation import handle_platform_ai_post_website
        handle_platform_ai_post_website(call)
        return
    
    # ═══════════════════════════════════════════════════════════════
    # TELEGRAM - СРАЗУ ГЕНЕРАЦИЯ И ПУБЛИКАЦИЯ С ИЗОБРАЖЕНИЕМ
    # ═══════════════════════════════════════════════════════════════
    if platform_type.lower() == 'telegram':
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            db.update_tokens(user_id, cost)
            bot.answer_callback_query(call.id, "❌ Категория не найдена")
            return
        
        category_name = category.get('name', 'Без названия')
        description = category.get('description', '')
        telegram_topics = category.get('telegram_topics', [])
        
        # КРИТИЧЕСКАЯ ПРОВЕРКА: если telegram_topics не список - сбрасываем!
        if not isinstance(telegram_topics, list):
            print(f"⚠️ WARNING в публикации: telegram_topics не список! Тип: {type(telegram_topics)}")
            print(f"⚠️ Значение: {telegram_topics}")
            telegram_topics = []
        
        # Если есть топики - спрашиваем куда публиковать
        if telegram_topics:
            # Отладка
            logger.debug(f" telegram_topics = {telegram_topics}")
            logger.debug(f" Количество топиков: {len(telegram_topics)}")
            
            text = (
                f"📡 <b>ВЫБОР ТОПИКА</b>\n"
                f"📂 Категория: {escape_html(category_name)}\n"
                "━━━━━━━━━━━━━━\n\n"
                "В какой топик опубликовать пост?\n\n"
            )
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            
            for i, topic in enumerate(telegram_topics):
                topic_id = topic.get('topic_id')
                topic_name = topic.get('topic_name', 'Без названия')
                
                logger.debug(f" Топик {i+1}: ID={topic_id}, Name={topic_name}")
                
                markup.add(
                    types.InlineKeyboardButton(
                        f"📌 {topic_name}",
                        callback_data=f"telegram_publish_topic_{category_id}_{bot_id}_{platform_id}_{topic_id}"
                    )
                )
            
            markup.add(
                types.InlineKeyboardButton(
                    "📤 В основной чат (без топика)",
                    callback_data=f"telegram_publish_topic_{category_id}_{bot_id}_{platform_id}_0"
                )
            )
            
            markup.add(
                types.InlineKeyboardButton(
                    "❌ Отмена (вернуть токены)",
                    callback_data=f"telegram_cancel_publish_{category_id}_{bot_id}_{platform_id}_{cost}"
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
            return
        
        # Если топиков нет - публикуем в основной чат
        else:
            bot.answer_callback_query(call.id, "🤖 Генерирую и публикую...")
            
            # ВАЖНО: Удаляем меню с кнопками
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass
            
            _telegram_publish_post(
                call, 
                category_id, 
                bot_id, 
                platform_id, 
                topic_id=0, 
                cost=cost, 
                new_balance=new_balance,
                platform_info=platform_info
            )
            return
    
    # ═══════════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════════
    # PINTEREST - МОДУЛЬНАЯ ПУБЛИКАЦИЯ
    # ═══════════════════════════════════════════════════════════════
    if platform_type.lower() == 'pinterest':
        bot.answer_callback_query(call.id, "🤖 Генерирую и публикую...")
        
        # Удаляем меню
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        
        # Прогресс-бар
        from utils.generation_progress import show_generation_progress
        progress = show_generation_progress(call.message.chat.id, "pinterest", total_steps=10)
        progress.start("🚀 Начинаем генерацию...")
        
        category = db.get_category(category_id)
        if not category:
            db.update_tokens(user_id, cost)
            bot.send_message(call.message.chat.id, "❌ Категория не найдена. Токены возвращены.")
            return
        
        category_name = category.get('name', 'Без названия')
        
        # PinterestPublisher делает ВСЁ сам (единая фраза, генерация, публикация)
        try:
            from handlers.auto_publish.platforms.pinterest import PinterestPublisher
            
            print(f"🔍 Создаём PinterestPublisher:")
            print(f"   category_id: {category_id} (type: {type(category_id)})")
            print(f"   platform_id: {platform_id} (type: {type(platform_id)})")
            print(f"   user_id: {user_id} (type: {type(user_id)})")
            
            publisher = PinterestPublisher(
                category_id=category_id, 
                platform_id=platform_id,
                user_id=user_id,
                progress_callback=lambda step, msg, detail: progress.update(step, msg, detail)
            )
            
            success, error, post_url = publisher.execute()
            
            if not success:
                raise Exception(error or 'Ошибка публикации')
            
            progress.finish()
            
            # Получаем доску Pinterest для platform_detail
            platform_detail = None
            try:
                from database.database import db as db_check
                user_check = db_check.get_user(user_id)
                connections = user_check.get('platform_connections', {})
                if isinstance(connections, str):
                    import json
                    connections = json.loads(connections)
                
                pinterests = connections.get('pinterests', [])
                for pin in pinterests:
                    if isinstance(pin, dict):
                        pin_board = pin.get('board') or pin.get('username')
                        if str(pin_board) == str(platform_id):
                            board_name = pin.get('board_name') or pin_board
                            platform_detail = f'Доска: {board_name}'
                            break
            except Exception:
                pass
            
            # Используем универсальное сообщение успеха
            from utils.success_message import send_unified_success_message
            
            send_unified_success_message(
                bot=bot,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                platform_type='pinterest',
                category_name=category_name,
                cost=cost,
                new_balance=new_balance,
                word_count=0,  # Pinterest не показывает слова
                post_url=post_url,
                platform_detail=platform_detail,
                category_id=category_id,
                bot_id=bot_id,
                platform_id=platform_id
            )
            
        except Exception as e:
            progress.finish()
            print(f"❌ Ошибка: {e}")
            import traceback
            traceback.print_exc()
            db.update_tokens(user_id, cost)
            bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}\n\nТокены возвращены.")
        
        return
    
    
    # VK - прямая публикация (как Pinterest)
    if platform_type.lower() == 'vk':
        bot.answer_callback_query(call.id, "🤖 Генерирую и публикую в VK...")
        
        # ВАЖНО: Удаляем меню с кнопками
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        
        # Вызываем функцию прямой публикации
        # КРИТИЧНО: Перезагружаем модуль чтобы применить изменения
        import importlib
        import handlers.platform_category.vk_direct_publish
        importlib.reload(handlers.platform_category.vk_direct_publish)
        
        from handlers.platform_category.vk_direct_publish import publish_vk_directly
        publish_vk_directly(call, user_id, bot_id, platform_id, category_id, cost)
        return
    
    # Для других платформ - старая логика с показом поста
    bot.answer_callback_query(call.id, "🤖 Генерирую пост...")
    
    try:
        bot.edit_message_text(
            f"🤖 <b>Генерация {platform_info['noun_gen']}...</b>\n\n"
            f"Claude AI создаёт уникальный {platform_info['noun_gen'].lower()} для вас.\n"
            "Это займёт несколько секунд ⏳",
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML'
        )
    except Exception:
        pass
    
    # Получаем данные категории
    category = db.get_category(category_id)
    if not category:
        db.update_tokens(user_id, cost)  # Возвращаем токены
        bot.send_message(call.message.chat.id, "❌ Ошибка: категория не найдена")
        return
    
    category_name = category.get('name', 'Без названия')
    description = category.get('description', '')
    keywords = category.get('keywords', [])
    
    # МИГРАЦИЯ: Генерируем через unified_generator
    from ai.unified_generator import generate_for_platform
    
    # Выбираем фразу из описания
    import random
    selected_phrase = ''
    if description:
        phrases = [s.strip() for s in description.split(',') if s.strip()]
        if phrases:
            selected_phrase = random.choice(phrases)
    
    # Определяем платформу
    platform_map = {
        'website': 'website',
        'pinterest': 'pinterest',
        'telegram': 'telegram',
        'vk': 'vk'
    }
    
    target_platform = platform_map.get(platform_type, 'telegram')
    
    result = generate_for_platform(
        platform=target_platform,
        category_name=category_name,
        selected_phrase=selected_phrase,
        style='conversational'
    )
    
    if result.get('success'):
        post_text = result['text']
        
        # Показываем результат
        text = (
            f"✅ <b>{platform_info['title'].upper()} СГЕНЕРИРОВАН{'А' if platform_info['title'] == 'СТАТЬИ' else ''}!</b>\n"
            f"📱 Платформа: {platform_info['platform_name']}\n"
            "━━━━━━━━━━━━━━\n\n"
            f"{post_text}\n\n"
            "━━━━━━━━━━━━━━\n"
            f"📊 Символов: {len(post_text)}\n"
            f"💳 Списано: {cost} токенов\n"
            f"💰 Баланс: {new_balance:,} токенов\n\n"
            "Опубликовать этот пост?"
        )
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(
                "📤 Опубликовать",
                callback_data=f"publish_post_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "🔄 Сгенерировать заново",
                callback_data=f"ai_post_confirm_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"platform_menu_{category_id}_{bot_id}_{platform_type}_{platform_id}"
            )
        )
        
    else:
        db.update_tokens(user_id, cost)  # Возвращаем токены
        text = (
            f"❌ <b>ОШИБКА ГЕНЕРАЦИИ</b>\n\n"
            f"Причина: {result.get('error', 'Неизвестная ошибка')}\n\n"
            "Токены возвращены. Попробуйте еще раз."
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"platform_menu_{category_id}_{bot_id}_{platform_type}_{platform_id}"
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("publish_post_"))
def handle_publish_post(call):
    """
    Обработчик публикации поста на платформу
    
    Формат: publish_post_{platform_type}_{category_id}_{bot_id}_{platform_id}
    """
    user_id = call.from_user.id
    parts = call.data.split("_")
    
    # Парсим параметры
    platform_type = parts[2]  # vk, pinterest, telegram, website
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = "_".join(parts[5:])
    
    # Получаем данные бота
    bot_data = db.get_bot(bot_id)
    if not bot_data or bot_data['user_id'] != user_id:
        bot.answer_callback_query(call.id, "❌ Нет доступа")
        return
    
    # Получаем сгенерированный текст из сообщения
    message_text = call.message.text or call.message.caption or ""
    
    # Извлекаем текст поста (между разделителями)
    post_text = ""
    if "━━━━━━━━━━━━━━" in message_text:
        lines = message_text.split("\n")
        in_post = False
        post_lines = []
        
        for line in lines:
            if "━━━━━━━━━━━━━━" in line:
                if not in_post:
                    in_post = True
                    continue
                else:
                    break
            if in_post and line.strip():
                post_lines.append(line)
        
        post_text = "\n".join(post_lines).strip()
    
    if not post_text:
        bot.answer_callback_query(call.id, "❌ Текст поста не найден")
        return
    
    # Показываем статус
    bot.edit_message_text(
        "🔄 <b>ПУБЛИКАЦИЯ НАЧАТА</b>\n\n"
        f"Платформа: {platform_type.upper()}\n"
        f"Категория ID: {category_id}\n\n"
        "⏳ Подготовка к публикации...",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML'
    )
    
    # В зависимости от платформы вызываем нужный метод
    if platform_type == "vk":
        # МИГРАЦИЯ: Используем готовую функцию которая уже мигрирована на unified_generator
        # КРИТИЧНО: Перезагружаем модуль
        import importlib
        import handlers.platform_category.vk_direct_publish
        importlib.reload(handlers.platform_category.vk_direct_publish)
        
        from handlers.platform_category.vk_direct_publish import publish_vk_directly
        publish_vk_directly(call, user_id, bot_id, platform_id, category_id, cost)
    elif platform_type == "pinterest":
        publish_to_pinterest(call, user_id, bot_id, platform_id, category_id, post_text)
    elif platform_type == "telegram":
        publish_to_telegram(call, user_id, bot_id, platform_id, category_id, post_text)
    elif platform_type == "website":
        publish_to_website(call, user_id, bot_id, platform_id, category_id, post_text)
    else:
        bot.edit_message_text(
            f"❌ <b>ОШИБКА</b>\n\n"
            f"Платформа '{platform_type}' не поддерживается",
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML'
        )


def publish_to_pinterest(call, user_id, bot_id, platform_id, category_id, post_text):
    """Публикация в Pinterest (TODO)"""
    bot.edit_message_text(
        "⚠️ Публикация в Pinterest пока не реализована",
        call.message.chat.id,
        call.message.message_id
    )


def _telegram_publish_post(call, category_id, bot_id, platform_id, topic_id=0, cost=50, new_balance=0, platform_info=None):
    """
    Публикация поста в Telegram с соблюдением ПРАВИЛА 11 КОНСТИТУЦИИ
    
    ОБЯЗАТЕЛЬНО:
    - 100 слов в тексте
    - Согласованность текста и изображения (одна фраза из описания)
    - Использование настроек платформы из категории
    - Единый стандарт для ВСЕХ путей публикации
    """
    from utils.generation_progress import show_generation_progress
    from handlers.auto_publish.platforms.telegram import TelegramPublisher
    
    user_id = call.from_user.id
    
    # Показываем прогресс
    progress = show_generation_progress(call.message.chat.id, "telegram", total_steps=3)
    progress.start("Подготовка к генерации...")
    
    try:
        # Шаг 1: Используем TelegramPublisher для генерации и публикации
        progress.update(1, "🤖 Генерирую контент...", "Создание текста и изображения")
        
        publisher = TelegramPublisher(
            user_id=user_id,
            category_id=category_id,
            platform_id=platform_id
        )
        
        # Валидация
        try:
            publisher.validate()
        except Exception as e:
            progress.finish(success=False)
            db.update_tokens(user_id, cost)  # Возвращаем токены
            bot.send_message(
                call.message.chat.id,
                f"❌ Ошибка валидации: {str(e)}"
            )
            return
        
        # Шаг 2: Публикация
        progress.update(2, "📤 Публикую в Telegram...", "Отправка поста в канал")
        
        try:
            post_url = publisher.publish()
            
            # Шаг 3: Успех
            progress.update(3, "✅ Готово!", "Пост опубликован")
            progress.finish(success=True)
            
            # Баланс уже обновлен при списании токенов до вызова функции
            # db.update_tokens уже был вызван в handle_ai_post_confirm
            
            # Показываем результат
            category = db.get_category(category_id)
            category_name = category.get('name', 'Без названия') if category else 'Без названия'
            
            result_text = (
                f"✅ <b>ПОСТ ОПУБЛИКОВАН В TELEGRAM</b>\n\n"
                f"📂 Категория: {escape_html(category_name)}\n"
                f"💰 Потрачено токенов: {cost}\n"
                f"💳 Новый баланс: {new_balance} токенов\n\n"
                f"🔗 <a href='{post_url}'>Открыть пост</a>"
            )
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "🔙 Назад в меню",
                    callback_data=f"platform_menu_{category_id}_{bot_id}_telegram_{platform_id}"
                )
            )
            
            bot.send_message(
                call.message.chat.id,
                result_text,
                reply_markup=markup,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
            
        except Exception as e:
            progress.finish(success=False)
            db.update_tokens(user_id, cost)  # Возвращаем токены
            
            error_msg = str(e)
            bot.send_message(
                call.message.chat.id,
                f"❌ <b>Ошибка публикации</b>\n\n{escape_html(error_msg)}\n\n💳 Токены возвращены",
                parse_mode='HTML'
            )
            
    except Exception as e:
        progress.finish(success=False)
        db.update_tokens(user_id, cost)  # Возвращаем токены
        bot.send_message(
            call.message.chat.id,
            f"❌ Критическая ошибка: {escape_html(str(e))}\n\n💳 Токены возвращены",
            parse_mode='HTML'
        )


def publish_to_telegram(call, user_id, bot_id, platform_id, category_id, post_text):
    """
    Публикация в Telegram (используется для ручной публикации с вводом текста)
    ВАЖНО: Теперь использует TelegramPublisher для единообразия
    """
    # Используем ту же функцию что и для быстрой публикации
    _telegram_publish_post(
        call,
        category_id=category_id,
        bot_id=bot_id,
        platform_id=platform_id,
        topic_id=0,
        cost=50,
        new_balance=0,
        platform_info=None
    )


def publish_to_website(call, user_id, bot_id, platform_id, category_id, post_text):
    """Публикация на сайт (TODO)"""
    bot.edit_message_text(
        "⚠️ Публикация на сайт пока не реализована",
        call.message.chat.id,
        call.message.message_id
    )



print("✅ platform_category/main_menu.py загружен")
