# -*- coding: utf-8 -*-
"""
Глобальный планировщик публикаций
Публикует контент со всех категорий на все платформы по расписанию
"""
import logging
from telebot import types
from loader import bot, db
from utils import escape_html, safe_answer_callback

# psycopg2/3 compatibility
try:
    import psycopg
    from psycopg.rows import dict_row
    PSYCOPG_VERSION = 3
except ImportError:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG_VERSION = 2

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С БД
# ═══════════════════════════════════════════════════════════════

def _get_platform_scheduler(category_id, platform_type, platform_id):
    """
    Получить настройки планировщика для платформы из БД
    Совместимость со старым API
    """
    try:
        # Создаём cursor с поддержкой dict_row
        if PSYCOPG_VERSION == 3:
            cursor = db.conn.cursor(row_factory=dict_row)
        else:
            cursor = db.conn.cursor(row_factory=dict_row) if PSYCOPG_VERSION == 3 else db.conn.cursor(cursor_factory=RealDictCursor)
            
        cursor.execute("""
            SELECT schedule_days, schedule_times, posts_per_day, enabled, post_frequency
            FROM platform_schedules
            WHERE category_id = %s AND platform_type = %s AND platform_id = %s
        """, (category_id, platform_type, platform_id))
        result = cursor.fetchone()
        cursor.close()
        
        if result:
            return {
                'days': result.get('schedule_days', []) or [],
                'times': result.get('schedule_times', []) or [],
                'posts_per_day': result.get('posts_per_day', 1) or 1,
                'enabled': result.get('enabled', False),
                'frequency': result.get('post_frequency', 'daily')
            }
        return {}
    except Exception as e:
        logger.error(f"Ошибка _get_platform_scheduler: {e}")
        try:
            db.conn.rollback()
        except Exception:
            pass
        return {}


def _save_platform_scheduler(category_id, platform_type, platform_id, schedule_data):
    """
    Сохранить настройки планировщика в БД
    Совместимость со старым API
    """
    try:
        cursor = db.conn.cursor()
        
        days = schedule_data.get('days', [])
        times = schedule_data.get('times', [])
        posts_per_day = schedule_data.get('posts_per_day', 1)
        enabled = schedule_data.get('enabled', False)
        frequency = schedule_data.get('frequency', 'daily')
        
        cursor.execute("""
            INSERT INTO platform_schedules 
            (category_id, platform_type, platform_id, schedule_days, schedule_times, posts_per_day, enabled, post_frequency)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (category_id, platform_type, platform_id)
            DO UPDATE SET 
                schedule_days = EXCLUDED.schedule_days,
                schedule_times = EXCLUDED.schedule_times,
                posts_per_day = EXCLUDED.posts_per_day,
                enabled = EXCLUDED.enabled,
                post_frequency = EXCLUDED.post_frequency
        """, (category_id, platform_type, platform_id, days, times, posts_per_day, enabled, frequency))
        
        db.conn.commit()
        cursor.close()
        return True
    except Exception as e:
        logger.error(f"Ошибка _save_platform_scheduler: {e}")
        try:
            db.conn.rollback()
        except Exception:
            pass
        return False


# ═══════════════════════════════════════════════════════════════
# ОБРАБОТЧИКИ CALLBACK
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("global_scheduler_platform_"))
def show_global_scheduler_platform(call):
    """Обработчик для кнопки "Назад" из настройки расписания к платформе"""
    # Парсим: global_scheduler_platform_{category_id}_{bot_id}_{platform_type}_{platform_id}
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_type = parts[5]
    platform_id = parts[6] if len(parts) > 6 else parts[5]
    
    # Перенаправляем на обработчик настроек платформы
    call.data = f"gs_platform_{category_id}_{bot_id}_{platform_type}_{platform_id}"
    handle_platform_settings(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("global_scheduler_"))
def show_global_scheduler(call):
    """Показать глобальный планировщик со всеми платформами"""
    parts = call.data.split("_")
    
    # Парсинг может быть: global_scheduler_{category_id}_{bot_id} или global_scheduler_{bot_id}
    if len(parts) >= 4:
        category_id = int(parts[2])
        bot_id = int(parts[3])
    else:
        # Старый формат: global_scheduler_{bot_id} - показываем список категорий
        bot_id = int(parts[2])
        
        # Получаем данные
        bot_data = db.get_bot(bot_id)
        if not bot_data or bot_data.get('user_id') != call.from_user.id:
            safe_answer_callback(bot, call.id, "❌ Доступ запрещен")
            return
        
        # Получаем все категории
        categories = db.get_bot_categories(bot_id)
        if not categories:
            safe_answer_callback(bot, call.id, "❌ Нет категорий")
            return
        
        # Если только одна категория - сразу открываем планировщик
        if len(categories) == 1:
            category_id = categories[0]['id']
        else:
            # Показываем список категорий для выбора
            text = (
                f"📅 <b>ПЛАНИРОВЩИК ПУБЛИКАЦИЙ</b>\n\n"
                f"<b>БОТ:</b> {escape_html(bot_data.get('name', ''))}\n\n"
                f"Выберите категорию для настройки планировщика:\n"
            )
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            
            for cat in categories:
                # БЕЗОПАСНОСТЬ: Проверяем что категория корректная
                if not cat or not isinstance(cat, dict):
                    continue
                
                cat_name = cat.get('name', 'Без названия')
                cat_id = cat.get('id')
                
                if not cat_id:
                    continue
                
                # Получаем количество активных планировщиков
                bot_connections = bot_data.get('connected_platforms', {})
                if isinstance(bot_connections, str):
                    try:
                        import json
                        bot_connections = json.loads(bot_connections)
                    except Exception:
                        bot_connections = {}
                
                # Подсчитываем активные планировщики
                active_count = 0
                from handlers.global_scheduler import _get_platform_scheduler
                
                for platform_type in ['website', 'pinterest', 'telegram']:
                    platforms = bot_connections.get(platform_type, [])
                    if isinstance(platforms, list):
                        for platform in platforms:
                            platform_id = platform.get('id') if isinstance(platform, dict) else platform
                            schedule = _get_platform_scheduler(cat_id, platform_type, platform_id)
                            if schedule.get('enabled'):
                                active_count += 1
                
                status_text = f" ({active_count} активных)" if active_count > 0 else ""
                
                markup.add(
                    types.InlineKeyboardButton(
                        f"📂 {cat_name}{status_text}",
                        callback_data=f"global_scheduler_{cat_id}_{bot_id}"
                    )
                )
            
            markup.add(
                types.InlineKeyboardButton(
                    "🔙 К боту",
                    callback_data=f"open_bot_{bot_id}"
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
            
            safe_answer_callback(bot, call.id)
            return
    
    # Получаем данные
    bot_data = db.get_bot(bot_id)
    if not bot_data or bot_data.get('user_id') != call.from_user.id:
        safe_answer_callback(bot, call.id, "❌ Доступ запрещен")
        return
    
    category = db.get_category(category_id)
    if not category:
        safe_answer_callback(bot, call.id, "❌ Категория не найдена")
        return
    
    # Получаем подключения бота
    bot_connections = bot_data.get('connected_platforms', {})
    if isinstance(bot_connections, str):
        try:
            import json
            bot_connections = json.loads(bot_connections)
        except Exception:
            bot_connections = {}
    
    # Собираем все подключенные платформы
    platforms_list = []
    
    # Website
    if 'website' in bot_connections or 'websites' in bot_connections:
        websites = bot_connections.get('website', bot_connections.get('websites', []))
        if isinstance(websites, list):
            for site in websites:
                site_id = site.get('id') if isinstance(site, dict) else site
                platforms_list.append({
                    'type': 'website',
                    'id': site_id,
                    'name': f"Website: {site_id}",
                    'icon': '🌐'
                })
    
    # Pinterest
    if 'pinterest' in bot_connections or 'pinterests' in bot_connections:
        pinterests = bot_connections.get('pinterest', bot_connections.get('pinterests', []))
        if isinstance(pinterests, list):
            for pinterest in pinterests:
                pinterest_id = pinterest.get('id') if isinstance(pinterest, dict) else pinterest
                platforms_list.append({
                    'type': 'pinterest',
                    'id': pinterest_id,
                    'name': f"Pinterest: {pinterest_id}",
                    'icon': '📌'
                })
    
    # Telegram
    if 'telegram' in bot_connections or 'telegrams' in bot_connections:
        telegrams = bot_connections.get('telegram', bot_connections.get('telegrams', []))
        if isinstance(telegrams, list):
            for tg in telegrams:
                tg_id = tg.get('id') if isinstance(tg, dict) else tg
                platforms_list.append({
                    'type': 'telegram',
                    'id': tg_id,
                    'name': f"Telegram: @{tg_id}",
                    'icon': '📱'
                })
    
    # VK - приоритет новому формату
    vks = []
    if 'vk' in bot_connections:
        # Новый формат - используем его
        vks = bot_connections.get('vk', [])
        logger.debug(f" Найден ключ 'vk' в bot_connections")
    elif 'vks' in bot_connections:
        # Старый формат - используем только если нет нового
        vks = bot_connections.get('vks', [])
        logger.debug(f" Найден ключ 'vks' в bot_connections")
    else:
        logger.debug(f" Ни 'vk', ни 'vks' не найдены в bot_connections")
        logger.debug(f" Ключи в bot_connections: {list(bot_connections.keys())}")
    
    if isinstance(vks, str):
        try:
            import json
            vks = json.loads(vks)
            logger.debug(f" vks был строкой, распарсили в список")
        except Exception:
            vks = []
            logger.debug(f" Ошибка парсинга vks из строки")
    
    logger.debug(f" Всего VK подключений: {len(vks)}")
    logger.debug(f" vks = {vks}")
    
    # Получаем полные данные VK из platform_connections пользователя
    user = db.get_user(call.from_user.id)
    user_connections = user.get('platform_connections', {}) if user else {}
    if isinstance(user_connections, str):
        try:
            user_connections = json.loads(user_connections)
        except Exception:
            user_connections = {}
    
    user_vks = user_connections.get('vks', [])
    if isinstance(user_vks, str):
        try:
            user_vks = json.loads(user_vks)
        except Exception:
            user_vks = []
    
    logger.debug(f" VK из platform_connections пользователя: {len(user_vks)}")
    
    # Создаем словарь для быстрого поиска полных данных VK по ID
    vk_full_data = {}
    if isinstance(user_vks, list):
        for user_vk in user_vks:
            if isinstance(user_vk, dict):
                vk_id = user_vk.get('id') or user_vk.get('user_id') or user_vk.get('group_id')
                if vk_id:
                    vk_full_data[str(vk_id)] = user_vk
                    logger.debug(f" Сохранили полные данные для VK ID {vk_id}")
    
    if isinstance(vks, list):
        # Используем set для отслеживания уже добавленных VK ID
        added_vk_ids = set()
        
        for idx, vk in enumerate(vks):
            logger.debug(f" Обрабатываем VK[{idx}]: {vk}")
            
            if isinstance(vk, dict):
                # Определяем тип VK
                vk_type = vk.get('type', 'user')
                
                # ВАЖНО: Если 'id' начинается с минуса - это ГРУППА
                vk_id = vk.get('id')
                if vk_id and str(vk_id).startswith('-'):
                    vk_type = 'group'
                
                logger.debug(f" VK type: {vk_type}")
                
                # Если 'id' не найден, ищем user_id или group_id
                if not vk_id:
                    if vk_type == 'group':
                        vk_id = vk.get('group_id')
                    else:
                        vk_id = vk.get('user_id')
                
                logger.debug(f" Определен VK ID: {vk_id}")
                
                # Фильтруем некорректные ID
                if vk_id in ['main', 'test', 'demo', '']:
                    logger.debug(f" VK ID '{vk_id}' некорректный, пропускаем")
                    continue
                
                # Проверяем что ID - это число (для личных страниц и групп VK ID всегда числовой)
                if not str(vk_id).replace('-', '').isdigit():
                    logger.debug(f" VK ID '{vk_id}' не числовой, пропускаем")
                    continue
                
                # Если ID не найден, пропускаем
                if not vk_id:
                    logger.debug(f" VK ID не найден, пропускаем")
                    continue
                
                # Проверяем не добавили ли уже этот VK
                if str(vk_id) in added_vk_ids:
                    logger.debug(f" VK ID {vk_id} уже добавлен, пропускаем дубль")
                    continue
                
                added_vk_ids.add(str(vk_id))
                
                # Получаем полные данные VK из словаря
                full_vk_data = vk_full_data.get(str(vk_id), vk)
                
                # Определяем имя
                if vk_type == 'group':
                    # Для группы ищем group_name в разных местах
                    vk_name = (
                        full_vk_data.get('group_name') or 
                        vk.get('group_name') or 
                        f'VK Группа {vk_id}'
                    )
                else:
                    # Для личной страницы используем имя пользователя
                    first_name = full_vk_data.get('first_name', '')
                    last_name = full_vk_data.get('last_name', '')
                    if first_name or last_name:
                        vk_name = f"{first_name} {last_name}".strip()
                    else:
                        # Если имени нет, используем просто ID
                        vk_name = vk_id
                
                logger.debug(f" VK name: {vk_name}")
                logger.debug(f" Добавляем VK ID {vk_id} в список платформ")
                
                icon = '👤' if vk_type == 'user' else '📝'
                
                platforms_list.append({
                    'type': 'vk',
                    'id': vk_id,
                    'name': f"VK: {vk_name}",
                    'icon': icon
                })
            elif isinstance(vk, str):
                # Старый формат - строка
                logger.debug(f" VK как строка: {vk}")
                if vk not in added_vk_ids:
                    added_vk_ids.add(vk)
                    platforms_list.append({
                    'type': 'vk',
                    'id': vk,
                    'name': f"VK: {vk}",
                    'icon': '👤'
                })
                else:
                    logger.debug(f" VK {vk} уже добавлен, пропускаем")
    
    logger.debug(f" Итого VK платформ добавлено: {len([p for p in platforms_list if p['type'] == 'vk'])}")
    
    if not platforms_list:
        text = (
            f"📅 <b>ГЛОБАЛЬНЫЙ ПЛАНИРОВЩИК</b>\n\n"
            f"<b>БОТ:</b> {escape_html(bot_data.get('name', ''))}\n"
            f"<b>Категория:</b> {escape_html(category.get('name', ''))}\n\n"
            f"⚠️ <b>Нет подключенных платформ</b>\n\n"
            f"💡 Подключите платформы в категории,\n"
            f"чтобы настроить планировщик."
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton(
                "🔙 К категории",
                callback_data=f"open_category_{category_id}"
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
        return
    
    # Текст заголовка
    text = (
        f"📅 <b>ГЛОБАЛЬНЫЙ ПЛАНИРОВЩИК</b>\n\n"
        f"<b>БОТ:</b> {escape_html(bot_data.get('name', ''))}\n"
        f"<b>Категория:</b> {escape_html(category.get('name', ''))}\n\n"
    )
    
    # Собираем расписание на неделю
    from datetime import datetime, timedelta
    now = datetime.now()
    
    # Получаем все активные расписания
    all_schedules = []
    for platform in platforms_list:
        from handlers.global_scheduler import _get_platform_scheduler
        schedule = _get_platform_scheduler(category_id, platform['type'], platform['id'])
        
        if schedule.get('enabled'):
            all_schedules.append({
                'platform': platform,
                'schedule': schedule
            })
    
    if all_schedules:
        # Генерируем расписание только на СЕГОДНЯ
        today_schedule = []
        
        # Маппинг дней (поддержка обоих форматов)
        days_map_full = {
            'monday': 'Пн',
            'tuesday': 'Вт', 
            'wednesday': 'Ср',
            'thursday': 'Чт',
            'friday': 'Пт',
            'saturday': 'Сб',
            'sunday': 'Вс'
        }
        
        days_map_short = {
            'mon': 'monday',
            'tue': 'tuesday',
            'wed': 'wednesday',
            'thu': 'thursday',
            'fri': 'friday',
            'sat': 'saturday',
            'sun': 'sunday'
        }
        
        # Проверяем только сегодняшний день
        check_date = now
        day_name_en = check_date.strftime('%A').lower()
        day_name_ru = days_map_full.get(day_name_en, day_name_en)
        date_str = check_date.strftime('%d.%m')
        
        day_posts = []
        
        # Проверяем каждую платформу
        for sched_item in all_schedules:
            platform = sched_item['platform']
            schedule = sched_item['schedule']
            
            days = schedule.get('days', [])
            times = schedule.get('times', [])
            
            # Проверяем, запланированы ли посты на сегодня
            # Поддерживаем оба формата: 'monday' и 'mon'
            day_match = False
            for day in days:
                day_lower = day.lower()
                # Если сокращенный формат - конвертируем в полный
                if day_lower in days_map_short:
                    day_lower = days_map_short[day_lower]
                
                if day_lower == day_name_en:
                    day_match = True
                    break
            
            if day_match:
                for time_str in times:
                    post_datetime = datetime.combine(check_date.date(), datetime.strptime(time_str, '%H:%M').time())
                    day_posts.append({
                        'datetime': post_datetime,
                        'time': time_str,
                        'platform': platform,
                        'is_future': post_datetime > now
                    })
        
        # Сортируем по времени
        day_posts.sort(key=lambda x: x['datetime'])
        
        if day_posts:
            today_schedule.append({
                'date': check_date,
                'day_name': day_name_ru,
                'posts': day_posts
            })
        
        # Находим следующий пост
        next_post = None
        for post in day_posts:
            if post['is_future']:
                next_post = post
                break
        
        # Выводим расписание
        if today_schedule:
            text += f"<b>📆 РАСПИСАНИЕ НА СЕГОДНЯ ({day_name_ru}, {date_str}):</b>\n"
            text += "━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            for post in day_posts:
                platform_icon = post['platform']['icon']
                platform_name = post['platform']['name'].split(': ')[1] if ': ' in post['platform']['name'] else post['platform']['name']
                
                # Выделяем следующий пост
                if next_post and post['datetime'] == next_post['datetime']:
                    text += f"<b>⏰ {post['time']} - {platform_icon} {platform_name}</b> ← СЛЕДУЮЩИЙ\n"
                else:
                    if post['is_future']:
                        text += f"• {post['time']} - {platform_icon} {platform_name}\n"
                    else:
                        text += f"✓ {post['time']} - {platform_icon} {platform_name}\n"
            
            text += "\n"
        else:
            text += f"<b>📆 РАСПИСАНИЕ НА СЕГОДНЯ ({day_name_ru}, {date_str}):</b>\n"
            text += "━━━━━━━━━━━━━━━━━━━━━\n\n"
            text += "⚪ <i>Нет запланированных публикаций на сегодня</i>\n\n"
    
    text += f"<b>🔌 Подключенные платформы:</b>\n"
    
    # Кнопки для каждой платформы
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for platform in platforms_list:
        # Получаем настройки планировщика для этой платформы
        from handlers.global_scheduler import _get_platform_scheduler
        schedule = _get_platform_scheduler(category_id, platform['type'], platform['id'])
        
        is_enabled = schedule.get('enabled', False)
        status_icon = "🟢" if is_enabled else "⚪"
        
        # Статус планировщика (кратко)
        if is_enabled:
            days = schedule.get('days', [])
            times = schedule.get('times', [])
            
            text += f"{status_icon} {platform['icon']} {platform['name']}\n"
            text += f"   └ Дней: {len(days)}, Постов: {len(times)} в день\n"
        else:
            text += f"{status_icon} {platform['icon']} {platform['name']} - <i>Не настроен</i>\n"
        
        # Кнопка для настройки
        markup.add(
            types.InlineKeyboardButton(
                f"{platform['icon']} {platform['name']} {'✅' if is_enabled else ''}",
                callback_data=f"gs_platform_{category_id}_{bot_id}_{platform['type']}_{platform['id']}"
            )
        )
    
    text += "\n"
    text += (
        f"💡 <b>Глобальный планировщик позволяет:</b>\n"
        f"• Публиковать контент на все платформы автоматически\n"
        f"• Настраивать расписание для каждой платформы отдельно\n"
        f"• Выбирать случайные категории для разнообразия\n"
        f"• Экономить время на ручных публикациях\n"
    )
    
    # Кнопка "Статистика публикаций"
    markup.add(
        types.InlineKeyboardButton(
            "📊 Статистика публикаций",
            callback_data=f"gs_stats_{category_id}_{bot_id}"
        )
    )
    
    # Кнопка "Назад"
    markup.add(
        types.InlineKeyboardButton(
            "🏠 К боту",
            callback_data=f"open_bot_{bot_id}"
        )
    )
    
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    except Exception:
        bot.send_message(
            call.message.chat.id,
            text,
            reply_markup=markup,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    
    safe_answer_callback(bot, call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("gs_select_platforms_"))
def select_platforms(call):
    """Выбор платформ для планировщика"""
    bot_id = int(call.data.split("_")[3])
    
    # Получаем подключенные платформы
    user = db.get_user(call.from_user.id)
    connections = user.get('platform_connections', {})
    
    connected_platforms = {}
    if connections.get('telegram'):
        connected_platforms['telegram'] = '📱 Telegram'
    if connections.get('pinterest'):
        connected_platforms['pinterest'] = '📌 Pinterest'
    if connections.get('vk'):
        connected_platforms['vk'] = '🔵 VK'
    if connections.get('websites'):
        connected_platforms['website'] = '🌐 Website'
    
    # Получаем текущие выбранные платформы
    bot_data = db.get_bot(bot_id)
    scheduler_settings = bot_data.get('global_scheduler', {})
    selected_platforms = scheduler_settings.get('platforms', [])
    
    text = (
        "🔌 <b>ВЫБОР ПЛАТФОРМ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Выберите платформы для автоматической публикации:\n\n"
        "✅ — Включена\n"
        "⚪ — Выключена\n\n"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for platform_key, platform_name in connected_platforms.items():
        is_selected = platform_key in selected_platforms
        status = "✅" if is_selected else "⚪"
        
        markup.add(
            types.InlineKeyboardButton(
                f"{status} {platform_name}",
                callback_data=f"gs_toggle_platform_{bot_id}_{platform_key}"
            )
        )
    
    text += f"<b>Выбрано платформ:</b> {len(selected_platforms)}/{len(connected_platforms)}\n"
    
    # Кнопка продолжить (если выбрана хотя бы одна)
    if selected_platforms:
        markup.add(
            types.InlineKeyboardButton("➡️ Далее: Расписание", callback_data=f"gs_schedule_{bot_id}")
        )
    
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"global_scheduler_{bot_id}")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("gs_toggle_platform_"))
def toggle_platform(call):
    """Переключение платформы"""
    parts = call.data.split("_")
    bot_id = int(parts[3])
    platform_key = parts[4]
    
    # Получаем текущие настройки
    bot_data = db.get_bot(bot_id)
    scheduler_settings = bot_data.get('global_scheduler', {})
    selected_platforms = scheduler_settings.get('platforms', [])
    
    # Переключаем
    if platform_key in selected_platforms:
        selected_platforms.remove(platform_key)
    else:
        selected_platforms.append(platform_key)
    
    # Сохраняем
    scheduler_settings['platforms'] = selected_platforms
    db.update_bot(bot_id, {'global_scheduler': scheduler_settings})
    
    # Обновляем меню
    call.data = f"gs_select_platforms_{bot_id}"
    select_platforms(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("gs_enable_") or call.data.startswith("gs_schedule_"))
def show_schedule_menu(call):
    """Меню выбора расписания"""
    parts = call.data.split("_")
    
    # Проверяем формат callback
    if call.data.startswith("gs_enable_platform_"):
        # gs_enable_platform_category_bot_platform_platformid
        # parts = ['gs', 'enable', 'platform', category_id, bot_id, platform_type, platform_id]
        category_id = int(parts[3])
        bot_id = int(parts[4])
        platform_type = parts[5]
        platform_id = "_".join(parts[6:])
        
        # Включаем планировщик в БД
        try:
            cursor = db.conn.cursor()
            cursor.execute("""
                UPDATE platform_schedules
                SET enabled = true
                WHERE category_id = %s AND platform_type = %s AND platform_id = %s
            """, (category_id, platform_type, platform_id))
            db.conn.commit()
            cursor.close()
            
            safe_answer_callback(bot, call.id, "✅ Планировщик включен!")
            
            # Возвращаемся к настройке расписания
            call.data = f"scheduler_setup_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            handle_scheduler_setup(call)
        except Exception as e:
            logger.error(f"Ошибка включения планировщика: {e}")
            try:
                db.conn.rollback()
            except Exception:
                pass
            safe_answer_callback(bot, call.id, "❌ Ошибка включения")
        return
    elif call.data.startswith("gs_schedule_"):
        # gs_schedule_bot_id
        bot_id = int(parts[2])
    else:
        # Неизвестный формат callback
        logger.error(f"Неизвестный формат callback: {call.data}")
        safe_answer_callback(bot, call.id, "❌ Ошибка")
        return
    
    # Проверяем что выбраны платформы
    bot_data = db.get_bot(bot_id)
    scheduler_settings = bot_data.get('global_scheduler', {})
    selected_platforms = scheduler_settings.get('platforms', [])
    
    if not selected_platforms:
        safe_answer_callback(bot, call.id, "⚠️ Сначала выберите платформы!", show_alert=True)
        call.data = f"gs_select_platforms_{bot_id}"
        select_platforms(call)
        return
    
    text = (
        "📅 <b>НАСТРОЙКА РАСПИСАНИЯ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Выберите сколько дней в неделю публиковать контент:\n\n"
        "• Минимум: 1 день в неделю\n"
        "• Максимум: 7 дней в неделю\n"
        "• Каждый день — случайная категория\n"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for days in [1, 2, 3, 4, 5, 6, 7]:
        day_word = "день" if days == 1 else "дня" if days < 5 else "дней"
        markup.add(
            types.InlineKeyboardButton(
                f"{days} {day_word} в неделю",
                callback_data=f"gs_set_days_{bot_id}_{days}"
            )
        )
    
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"gs_select_platforms_{bot_id}")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("gs_set_days_"))
def set_scheduler_days(call):
    """Выбор количества дней и постов в день"""
    parts = call.data.split("_")
    bot_id = int(parts[3])
    days_count = int(parts[4])
    
    # Если выбрано 7 дней - предлагаем выбрать количество постов в день
    if days_count == 7:
        text = (
            "📊 <b>ПОСТОВ В ДЕНЬ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Вы выбрали публикацию каждый день недели.\n\n"
            "Сколько постов публиковать в день?\n\n"
            "• 1 пост = минимальная нагрузка\n"
            "• 5 постов = максимальное покрытие\n"
        )
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        for posts in [1, 2, 3, 4, 5]:
            post_word = "пост" if posts == 1 else "поста" if posts < 5 else "постов"
            markup.add(
                types.InlineKeyboardButton(
                    f"{posts} {post_word} в день",
                    callback_data=f"gs_confirm_schedule_{bot_id}_{days_count}_{posts}"
                )
            )
        
        markup.add(
            types.InlineKeyboardButton("🔙 Назад", callback_data=f"gs_schedule_{bot_id}")
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
    else:
        # Для остальных дней - 1 пост в день
        call.data = f"gs_confirm_schedule_{bot_id}_{days_count}_1"
        confirm_schedule(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("gs_confirm_schedule_"))
def confirm_schedule(call):
    """Подтверждение и сохранение расписания"""
    parts = call.data.split("_")
    bot_id = int(parts[3])
    days_count = int(parts[4])
    posts_per_day = int(parts[5])
    
    # Генерируем расписание
    days_list = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    schedule = days_list[:days_count]
    
    # Получаем текущие настройки
    bot_data = db.get_bot(bot_id)
    scheduler_settings = bot_data.get('global_scheduler', {})
    selected_platforms = scheduler_settings.get('platforms', [])
    
    # Сохраняем настройки
    scheduler_settings = {
        'enabled': True,
        'platforms': selected_platforms,
        'days': schedule,
        'posts_per_day': posts_per_day,
        'time': '10:00',
        'last_run': None
    }
    
    db.update_bot(bot_id, {'global_scheduler': scheduler_settings})
    
    total_posts_per_week = days_count * posts_per_day
    
    text = (
        "✅ <b>ПЛАНИРОВЩИК АКТИВИРОВАН!</b>\n\n"
        f"📅 Расписание: {days_count} {'день' if days_count == 1 else 'дня' if days_count < 5 else 'дней'} в неделю\n"
        f"📊 Постов в день: {posts_per_day}\n"
        f"📈 Всего постов в неделю: {total_posts_per_week}\n"
        f"🕐 Время публикации: 10:00 (UTC+3)\n"
        f"🔌 Платформ: {len(selected_platforms)}\n\n"
        f"<b>Дни публикации:</b>\n"
    )
    
    for day in schedule:
        text += f"• {day}\n"
    
    text += (
        "\n💡 <b>Как работает:</b>\n"
        f"• Каждый день из расписания выбирается {posts_per_day} случайных категорий\n"
        f"• Генерируется контент для выбранных платформ\n"
        f"• Публикация происходит автоматически в 10:00\n"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🔙 К планировщику", callback_data=f"global_scheduler_{bot_id}")
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
    
    safe_answer_callback(bot, call.id, "✅ Планировщик активирован!")


@bot.callback_query_handler(func=lambda call: call.data.startswith("gs_disable_"))
def disable_global_scheduler(call):
    """Отключение глобального планировщика"""
    bot_id = int(call.data.split("_")[2])
    
    # Отключаем планировщик
    bot_data = db.get_bot(bot_id)
    if bot_data:
        scheduler_settings = bot_data.get('global_scheduler', {})
        scheduler_settings['enabled'] = False
        db.update_bot(bot_id, {'global_scheduler': scheduler_settings})
    
    safe_answer_callback(bot, call.id, "🔴 Планировщик отключен")
    
    # Возвращаем в меню планировщика
    show_global_scheduler(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("gs_edit_schedule_"))
def edit_scheduler_settings(call):
    """Редактирование расписания"""
    bot_id = int(call.data.split("_")[3])
    
    # Показываем меню выбора дней
    call.data = f"gs_schedule_{bot_id}"
    show_schedule_menu(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("gs_stats_"))
def show_scheduler_stats(call):
    """Статистика глобального планировщика"""
    bot_id = int(call.data.split("_")[2])
    user_id = call.from_user.id
    
    # Получаем статистику за 30 дней
    stats = db.get_publication_stats(user_id, bot_id, days=30)
    
    general = stats['general']
    platforms = stats['platforms']
    daily = stats['daily']
    
    # Формируем текст
    text = (
        "📊 <b>СТАТИСТИКА ПУБЛИКАЦИЙ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📅 <b>За последние 30 дней:</b>\n\n"
    )
    
    # Общая статистика
    total_posts = general.get('total_posts', 0)
    success_posts = general.get('success_posts', 0)
    failed_posts = general.get('failed_posts', 0)
    total_tokens = general.get('total_tokens', 0) or 0
    total_words = general.get('total_words', 0) or 0
    
    if total_posts == 0:
        text += (
            "📭 <b>Пока нет публикаций</b>\n\n"
            "Статистика начнёт собираться после первых публикаций."
        )
    else:
        # Процент успеха
        success_rate = round((success_posts / total_posts) * 100) if total_posts > 0 else 0
        
        text += (
            f"📝 <b>Публикаций:</b> {total_posts}\n"
            f"   ✅ Успешных: {success_posts}\n"
        )
        
        if failed_posts > 0:
            text += f"   ❌ Ошибок: {failed_posts}\n"
        
        text += (
            f"   📊 Успех: {success_rate}%\n\n"
            f"💰 <b>Токенов потрачено:</b> {total_tokens:,}\n"
        )
        
        if total_words > 0:
            text += f"📄 <b>Слов сгенерировано:</b> {total_words:,}\n"
        
        # Статистика по платформам
        if platforms:
            text += "\n━━━━━━━━━━━━━━\n"
            text += "📱 <b>ПО ПЛАТФОРМАМ:</b>\n\n"
            
            platform_icons = {
                'pinterest': '📌',
                'telegram': '✈️',
                'vk': '🔵',
                'website': '🌐',
            }
            
            platform_names = {
                'pinterest': 'Pinterest',
                'telegram': 'Telegram',
                'vk': 'VK',
                'website': 'Сайт',
            }
            
            for platform in platforms:
                platform_type = platform.get('platform_type', '')
                posts_count = platform.get('posts_count', 0)
                tokens_spent = platform.get('tokens_spent', 0) or 0
                
                icon = platform_icons.get(platform_type, '📱')
                name = platform_names.get(platform_type, platform_type.title())
                
                text += f"{icon} <b>{name}:</b> {posts_count} постов"
                
                if tokens_spent > 0:
                    text += f" ({tokens_spent:,} токенов)"
                
                text += "\n"
        
        # График активности за последние 7 дней
        if daily:
            text += "\n━━━━━━━━━━━━━━\n"
            text += "📈 <b>АКТИВНОСТЬ (последние 7 дней):</b>\n\n"
            
            from datetime import datetime
            
            # Сортируем по дате (от старых к новым)
            daily_sorted = sorted(daily, key=lambda x: x['date'])
            
            max_posts = max([d.get('posts_count', 0) for d in daily_sorted]) if daily_sorted else 1
            
            for day_stat in daily_sorted:
                date = day_stat.get('date')
                posts_count = day_stat.get('posts_count', 0)
                
                # Форматируем дату
                if isinstance(date, str):
                    date_obj = datetime.strptime(date, '%Y-%m-%d')
                else:
                    date_obj = date
                
                day_name = date_obj.strftime('%d.%m')
                
                # Визуальный график (до 10 блоков)
                blocks = int((posts_count / max_posts) * 10) if max_posts > 0 else 0
                bar = "█" * blocks + "░" * (10 - blocks)
                
                text += f"{day_name}: {bar} {posts_count}\n"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"global_scheduler_{bot_id}")
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



@bot.callback_query_handler(func=lambda call: call.data.startswith("gs_platform_"))
def handle_platform_settings(call):
    """Настройка отдельной платформы в глобальном планировщике"""
    parts = call.data.split("_")
    # gs_platform_{category_id}_{bot_id}_{platform_type}_{platform_id}
    category_id = int(parts[2])
    bot_id = int(parts[3])
    platform_type = parts[4]
    platform_id = "_".join(parts[5:])
    
    # Получаем данные
    category = db.get_category(category_id)
    bot_data = db.get_bot(bot_id)
    
    if not category or not bot_data:
        safe_answer_callback(bot, call.id, "❌ Ошибка")
        return
    
    # Получаем настройки планировщика
    from handlers.global_scheduler import _get_platform_scheduler
    schedule = _get_platform_scheduler(category_id, platform_type, platform_id)
    
    is_enabled = schedule.get('enabled', False)
    posts_per_day = schedule.get('posts_per_day', 1)
    
    # Иконки платформ
    platform_icons = {
        'website': '🌐',
        'pinterest': '📌',
        'telegram': '📱',
        'vk': '🔵'
    }
    icon = platform_icons.get(platform_type, '📋')
    
    # Названия платформ
    platform_names = {
        'website': 'Website',
        'pinterest': 'Pinterest',
        'telegram': 'Telegram',
        'vk': 'VK'
    }
    platform_name = platform_names.get(platform_type, platform_type.upper())
    
    text = (
        f"{icon} <b>{platform_name}</b>\n"
        f"<b>Категория:</b> {escape_html(category.get('name', 'Без названия'))}\n\n"
        f"<b>Статус:</b> {'🟢 Активен' if is_enabled else '⚪ Не настроен'}\n\n"
    )
    
    text += f"✅ <b>Платформа активна для этой категории</b>\n\n"
    
    text += f"<b>Доступные действия:</b>\n"
    text += f"• Настроить расписание публикаций\n"
    text += f"• Отключить планировщик\n"
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    # Кнопки планировщика одинаковые для ВСЕХ платформ
    if is_enabled:
        markup.add(
            types.InlineKeyboardButton(
                "⚙️ Изменить расписание",
                callback_data=f"scheduler_setup_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            ),
            types.InlineKeyboardButton(
                "🔴 Отключить планировщик",
                callback_data=f"gs_disable_platform_{category_id}_{bot_id}_{platform_type}_{platform_id}"
            )
        )
    else:
        markup.add(
            types.InlineKeyboardButton(
                "🟢 Настроить планировщик",
                callback_data=f"scheduler_setup_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            )
        )
    
    # Кнопка "К планировщику" (убрана кнопка "Отключить платформу")
    markup.add(
        types.InlineKeyboardButton(
            "🔙 К планировщику",
            callback_data=f"global_scheduler_{category_id}_{bot_id}"
        )
    )
    
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    except Exception:
        bot.send_message(
            call.message.chat.id,
            text,
            reply_markup=markup,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    
    safe_answer_callback(bot, call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("gs_disable_platform_"))
def disable_platform_scheduler(call):
    """Отключить планировщик для платформы"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_type = parts[5]
    platform_id = "_".join(parts[6:])
    
    # Отключаем планировщик
    from handlers.global_scheduler import _save_platform_scheduler
    _save_platform_scheduler(category_id, platform_type, platform_id, {
        'enabled': False,
        'frequency': 1,
        'posts_per_day': 1
    })
    
    safe_answer_callback(bot, call.id, "✅ Планировщик отключен")
    
    # Возвращаемся к настройкам платформы
    call.data = f"gs_platform_{category_id}_{bot_id}_{platform_type}_{platform_id}"
    handle_platform_settings(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("gs_stats_"))
def show_category_scheduler_stats(call):
    """Показать статистику публикаций"""
    parts = call.data.split("_")
    category_id = int(parts[2])
    bot_id = int(parts[3])
    
    try:
        category = db.get_category(category_id)
        if not category:
            safe_answer_callback(bot, call.id, "❌ Категория не найдена")
            return
        
        # Получаем статистику из БД
        cursor = db.conn.cursor()
        
        # Статистика за последние 7 дней
        cursor.execute("""
            SELECT 
                platform_type,
                COUNT(*) as total_posts,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as failed
            FROM publication_logs
            WHERE category_id = %s 
                AND created_at >= NOW() - INTERVAL '7 days'
            GROUP BY platform_type
        """, (category_id,))
        
        platform_stats = cursor.fetchall()
        
        # Статистика по расходу токенов
        cursor.execute("""
            SELECT 
                SUM(tokens_spent) as total_tokens,
                COUNT(*) as total_posts
            FROM publication_logs
            WHERE category_id = %s 
                AND created_at >= NOW() - INTERVAL '7 days'
        """, (category_id,))
        
        tokens_result = cursor.fetchone()
        total_tokens = tokens_result[0] if tokens_result and tokens_result[0] else 0
        total_posts_week = tokens_result[1] if tokens_result and tokens_result[1] else 0
        
        # Статистика за месяц
        cursor.execute("""
            SELECT COUNT(*) 
            FROM publication_logs
            WHERE category_id = %s 
                AND created_at >= NOW() - INTERVAL '30 days'
        """, (category_id,))
        
        month_result = cursor.fetchone()
        total_posts_month = month_result[0] if month_result else 0
        
        cursor.close()
        
        # Формируем текст
        text = f"""
📊 <b>СТАТИСТИКА ПУБЛИКАЦИЙ</b>

📂 Категория: {escape_html(category.get('name', 'Без названия'))}

<b>📅 За последние 7 дней:</b>
Всего публикаций: {total_posts_week}
Расход токенов: {total_tokens}

<b>📈 По платформам:</b>
"""
        
        platform_icons = {
            'website': '🌐',
            'pinterest': '📌',
            'telegram': '📱',
            'vk': '🔵'
        }
        
        if platform_stats:
            for platform_type, total, successful, failed in platform_stats:
                icon = platform_icons.get(platform_type, '📋')
                success_rate = (successful / total * 100) if total > 0 else 0
                text += f"\n{icon} {platform_type.upper()}: {total} постов"
                text += f"\n   └ Успешно: {successful} ({success_rate:.0f}%)"
                if failed > 0:
                    text += f", Ошибок: {failed}"
        else:
            text += "\nПубликаций пока не было"
        
        text += f"\n\n<b>📆 За последние 30 дней:</b>\nВсего публикаций: {total_posts_month}"
        
        text += "\n\n<i>Статистика обновляется в реальном времени</i>"
        
    except Exception as e:
        logger.warning(f"Таблица publication_logs не существует или ошибка: {e}")
        text = f"""
📊 <b>СТАТИСТИКА ПУБЛИКАЦИЙ</b>

<b>Скоро здесь будет:</b>
• Количество опубликованных постов
• Статистика по платформам
• График активности
• Расход токенов

<i>Статистика начнет собираться после первых публикаций</i>
"""
    
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"global_scheduler_{category_id}_{bot_id}"
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("scheduler_setup_"))
def handle_scheduler_setup(call):
    """
    Настройка расписания публикаций для платформы
    Шаг 1: Выбор дней недели
    """
    try:
        parts = call.data.split("_")
        platform_type = parts[2]
        category_id = int(parts[3])
        bot_id = int(parts[4])
        platform_id = parts[5] if len(parts) > 5 else platform_type
        
        # Получаем данные из БД
        category = db.get_category(category_id)
        bot_data = db.get_bot(bot_id)
        
        if not category or not bot_data:
            safe_answer_callback(bot, call.id, "❌ Данные не найдены")
            return
        
        # Получаем текущее расписание
        try:
            cursor = db.conn.cursor(row_factory=dict_row) if PSYCOPG_VERSION == 3 else db.conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT schedule_days, posts_per_day, schedule_times, enabled 
                FROM platform_schedules
                WHERE category_id = %s AND platform_type = %s AND platform_id = %s
            """, (category_id, platform_type, platform_id))
            schedule = cursor.fetchone()
            cursor.close()
            
            if schedule:
                selected_days = schedule.get('schedule_days', []) or []
                posts_per_day = schedule.get('posts_per_day', 1) or 1
                selected_times = schedule.get('schedule_times', []) or []
                is_enabled = schedule.get('enabled', False)
            else:
                selected_days = []
                posts_per_day = 1
                selected_times = []
                is_enabled = False
        except Exception:
            try:
                db.conn.rollback()
            except Exception:
                pass
            selected_days = []
            posts_per_day = 1
            selected_times = []
            is_enabled = False
        
        days_names = {
            'mon': 'Пн', 'tue': 'Вт', 'wed': 'Ср', 'thu': 'Чт',
            'fri': 'Пт', 'sat': 'Сб', 'sun': 'Вс'
        }
        
        # Правильный порядок дней
        days_order = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
        sorted_selected_days = sorted(selected_days, key=lambda d: days_order.index(d) if d in days_order else 999)
        
        selected_days_text = ", ".join([days_names[d] for d in sorted_selected_days]) if sorted_selected_days else "Не выбраны"
        
        # Формируем текст с прогрессом настройки
        progress = []
        if selected_days:
            progress.append(f"✅ Дни: {selected_days_text}")
        else:
            progress.append(f"1️⃣ Выберите дни недели")
        
        if selected_days and posts_per_day:
            progress.append(f"✅ Частота: {posts_per_day} раз в день")
        elif selected_days:
            progress.append(f"2️⃣ Выберите частоту")
        
        if selected_days and posts_per_day and len(selected_times) == posts_per_day:
            times_text = ", ".join(selected_times)
            progress.append(f"✅ Время: {times_text}")
        elif selected_days and posts_per_day:
            progress.append(f"3️⃣ Выберите время ({len(selected_times)}/{posts_per_day})")
        
        text = f"""
⏰ <b>НАСТРОЙКА РАСПИСАНИЯ</b>

📂 Категория: {escape_html(category.get('name', 'Без названия'))}
🌐 Платформа: {platform_type.upper()}

<b>Прогресс настройки:</b>
{chr(10).join(progress)}

<i>Настройте параметры публикации шаг за шагом</i>
"""
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        # Кнопка выбора дней (всегда доступна)
        markup.add(
            types.InlineKeyboardButton(
                "📆 Выбрать дни недели" + (" ✅" if selected_days else ""),
                callback_data=f"schedule_days_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            )
        )
        
        # Кнопка частоты (доступна после выбора дней)
        if selected_days:
            markup.add(
                types.InlineKeyboardButton(
                    f"🔢 Частота публикаций ({posts_per_day}/день)" + (" ✅" if posts_per_day else ""),
                    callback_data=f"schedule_frequency_{platform_type}_{category_id}_{bot_id}_{platform_id}"
                )
            )
        
        # Кнопка времени (доступна после выбора частоты)
        if selected_days and posts_per_day:
            markup.add(
                types.InlineKeyboardButton(
                    f"🕐 Выбрать время ({len(selected_times)}/{posts_per_day})" + (" ✅" if len(selected_times) == posts_per_day else ""),
                    callback_data=f"schedule_times_{platform_type}_{category_id}_{bot_id}_{platform_id}_{posts_per_day}"
                )
            )
        
        # Кнопка активации (доступна когда всё настроено)
        if selected_days and posts_per_day and len(selected_times) == posts_per_day:
            if is_enabled:
                markup.add(
                    types.InlineKeyboardButton(
                        "🔴 Отключить планировщик",
                        callback_data=f"gs_disable_platform_{category_id}_{bot_id}_{platform_type}_{platform_id}"
                    )
                )
            else:
                markup.add(
                    types.InlineKeyboardButton(
                        "🟢 Включить планировщик",
                        callback_data=f"gs_enable_platform_{category_id}_{bot_id}_{platform_type}_{platform_id}"
                    )
                )
        
        # Кнопка "Назад"
        markup.add(
            types.InlineKeyboardButton(
                "🔙 К планировщику",
                callback_data=f"global_scheduler_{category_id}_{bot_id}"
            )
        )
        
        try:
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
        except Exception as edit_error:
            # Игнорируем ошибку "message is not modified" - это нормально
            if "message is not modified" not in str(edit_error).lower():
                raise  # Пробрасываем другие ошибки
        
        safe_answer_callback(bot, call.id)
        
    except Exception as e:
        logger.error(f"Ошибка в handle_scheduler_setup: {e}")
        # Откатываем транзакцию
        try:
            db.conn.rollback()
        except Exception:
            pass
        safe_answer_callback(bot, call.id, "❌ Ошибка загрузки настроек")


@bot.callback_query_handler(func=lambda call: call.data.startswith("schedule_days_"))
def handle_schedule_days(call):
    """Выбор дней недели для публикаций"""
    try:
        parts = call.data.split("_")
        platform_type = parts[2]
        category_id = int(parts[3])
        bot_id = int(parts[4])
        platform_id = parts[5]
        
        text = """
📆 <b>ВЫБОР ДНЕЙ НЕДЕЛИ</b>

Выберите дни, когда нужно публиковать контент:
"""
        
        # Получаем текущие выбранные дни
        try:
            cursor = db.conn.cursor()
            cursor.execute("""
                SELECT schedule_days FROM platform_schedules
                WHERE category_id = %s AND platform_type = %s AND platform_id = %s
            """, (category_id, platform_type, platform_id))
            result = cursor.fetchone()
            selected_days = result[0] if result and result[0] else []
            cursor.close()
        except Exception:
            try:
                db.conn.rollback()
            except Exception:
                pass
            selected_days = []
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        days = [
            ('mon', 'Пн'), ('tue', 'Вт'), ('wed', 'Ср'), ('thu', 'Чт'),
            ('fri', 'Пт'), ('sat', 'Сб'), ('sun', 'Вс')
        ]
        
        # Создаём кнопки для дней - по 4 в ряд для компактности
        buttons = []
        for day_key, day_name in days:
            icon = "✅" if day_key in selected_days else "⬜"
            buttons.append(
                types.InlineKeyboardButton(
                    f"{icon} {day_name}",
                    callback_data=f"toggle_day_{day_key}_{platform_type}_{category_id}_{bot_id}_{platform_id}"
                )
            )
        
        # Добавляем по 4 кнопки в ряд (Пн-Чт, Пт-Вс)
        markup.row(*buttons[0:4])  # Пн, Вт, Ср, Чт
        markup.row(*buttons[4:7])  # Пт, Сб, Вс
        
        markup.add(
            types.InlineKeyboardButton(
                "💾 Сохранить",
                callback_data=f"save_days_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"scheduler_setup_{platform_type}_{category_id}_{bot_id}_{platform_id}"
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
        logger.error(f"Ошибка в handle_schedule_days: {e}")
        safe_answer_callback(bot, call.id, "❌ Ошибка")


@bot.callback_query_handler(func=lambda call: call.data.startswith("toggle_day_"))
def toggle_schedule_day(call):
    """Переключение выбора дня недели"""
    try:
        parts = call.data.split("_")
        day_key = parts[2]
        platform_type = parts[3]
        category_id = int(parts[4])
        bot_id = int(parts[5])
        platform_id = parts[6]
        
        # Получаем текущие дни
        try:
            cursor = db.conn.cursor()
            cursor.execute("""
                SELECT schedule_days FROM platform_schedules
                WHERE category_id = %s AND platform_type = %s AND platform_id = %s
            """, (category_id, platform_type, platform_id))
            result = cursor.fetchone()
            selected_days = list(result[0]) if result and result[0] else []
            
            # Переключаем день
            if day_key in selected_days:
                selected_days.remove(day_key)
            else:
                selected_days.append(day_key)
            
            # Сохраняем
            cursor.execute("""
                INSERT INTO platform_schedules (category_id, platform_type, platform_id, schedule_days)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (category_id, platform_type, platform_id)
                DO UPDATE SET schedule_days = %s
            """, (category_id, platform_type, platform_id, selected_days, selected_days))
            
            db.conn.commit()
            cursor.close()
        except Exception:
            try:
                db.conn.rollback()
            except Exception:
                pass
        
        # Обновляем меню
        call.data = f"schedule_days_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        handle_schedule_days(call)
        
    except Exception as e:
        logger.error(f"Ошибка в toggle_schedule_day: {e}")
        safe_answer_callback(bot, call.id, "❌ Ошибка")


@bot.callback_query_handler(func=lambda call: call.data.startswith("schedule_times_"))
def handle_schedule_times(call):
    """Выбор времени для публикаций с ограничением"""
    try:
        parts = call.data.split("_")
        platform_type = parts[2]
        category_id = int(parts[3])
        bot_id = int(parts[4])
        platform_id = parts[5]
        posts_per_day = int(parts[6]) if len(parts) > 6 else 1
        
        # Получаем текущие выбранные времена
        try:
            cursor = db.conn.cursor(row_factory=dict_row) if PSYCOPG_VERSION == 3 else db.conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT schedule_times FROM platform_schedules
                WHERE category_id = %s AND platform_type = %s AND platform_id = %s
            """, (category_id, platform_type, platform_id))
            result = cursor.fetchone()
            selected_times = result['schedule_times'] if result and result['schedule_times'] else []
            cursor.close()
        except Exception:
            try:
                db.conn.rollback()
            except Exception:
                pass
            selected_times = []
        
        text = f"""
🕐 <b>ВЫБОР ВРЕМЕНИ ПУБЛИКАЦИЙ</b>

Выберите {posts_per_day} временных слота для публикации:
Выбрано: {len(selected_times)}/{posts_per_day}

⚠️ <b>Важно:</b> Ваш пост будет опубликован <b>ориентировочно</b> в выбранное время. 
При высокой нагрузке публикация может сдвинуться на 5-10 минут для распределения нагрузки.

<i>Нажмите на время для выбора:</i>
"""
        
        markup = types.InlineKeyboardMarkup(row_width=3)
        
        times = ['06:00', '07:00', '08:00', '09:00', '10:00', '11:00', 
                 '12:00', '13:00', '14:00', '15:00', '16:00', '17:00',
                 '18:00', '19:00', '20:00', '21:00', '22:00', '23:00']
        
        buttons = []
        for time in times:
            is_selected = time in selected_times
            can_select = len(selected_times) < posts_per_day or is_selected
            
            if is_selected:
                icon = "✅"
            elif can_select:
                icon = "⬜"
            else:
                icon = "🔒"  # Заблокировано - лимит достигнут
            
            buttons.append(
                types.InlineKeyboardButton(
                    f"{icon} {time}",
                    callback_data=f"toggle_time_{time}_{platform_type}_{category_id}_{bot_id}_{platform_id}_{posts_per_day}"
                )
            )
        
        # Добавляем по 3 кнопки в ряд
        for i in range(0, len(buttons), 3):
            markup.row(*buttons[i:i+3])
        
        # Кнопка сохранения (доступна только если выбрано нужное количество)
        if len(selected_times) == posts_per_day:
            markup.add(
                types.InlineKeyboardButton(
                    "💾 Сохранить",
                    callback_data=f"save_times_{platform_type}_{category_id}_{bot_id}_{platform_id}"
                )
            )
        
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"scheduler_setup_{platform_type}_{category_id}_{bot_id}_{platform_id}"
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
        logger.error(f"Ошибка в handle_schedule_times: {e}")
        safe_answer_callback(bot, call.id, "❌ Ошибка")
@bot.callback_query_handler(func=lambda call: call.data.startswith("toggle_time_"))
def toggle_schedule_time(call):
    """Переключение выбора времени с проверкой лимита"""
    try:
        parts = call.data.split("_")
        # toggle_time_09:00_pinterest_1_3_3designservice_1
        # parts: ['toggle', 'time', '09:00', 'pinterest', '1', '3', '3designservice', '1']
        time = parts[2]  # 09:00
        platform_type = parts[3]  # pinterest
        category_id = int(parts[4])  # 1
        bot_id = int(parts[5])  # 3
        
        # posts_per_day всегда последний элемент (если число)
        posts_per_day = int(parts[-1]) if parts[-1].isdigit() else 1
        
        # platform_id - всё между bot_id и posts_per_day
        # Если есть posts_per_day (число в конце), берём parts[6:-1]
        # Если нет, берём parts[6:]
        if parts[-1].isdigit() and len(parts) > 7:
            platform_id = "_".join(parts[6:-1])
        else:
            platform_id = "_".join(parts[6:]) if len(parts) > 6 else ""
        
        # Получаем текущие времена
        try:
            cursor = db.conn.cursor(row_factory=dict_row) if PSYCOPG_VERSION == 3 else db.conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT schedule_times FROM platform_schedules
                WHERE category_id = %s AND platform_type = %s AND platform_id = %s
            """, (category_id, platform_type, platform_id))
            result = cursor.fetchone()
            selected_times = list(result['schedule_times']) if result and result['schedule_times'] else []
            
            # Переключаем время с проверкой лимита
            if time in selected_times:
                # Убираем время
                selected_times.remove(time)
            else:
                # Добавляем только если не превышен лимит
                if len(selected_times) < posts_per_day:
                    selected_times.append(time)
                    selected_times.sort()  # Сортируем по времени
                else:
                    safe_answer_callback(bot, call.id, f"❌ Лимит: {posts_per_day} раз в день", show_alert=True)
                    cursor.close()
                    return
            
            # Сохраняем
            cursor.execute("""
                INSERT INTO platform_schedules (category_id, platform_type, platform_id, schedule_times)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (category_id, platform_type, platform_id)
                DO UPDATE SET schedule_times = %s
            """, (category_id, platform_type, platform_id, selected_times, selected_times))
            
            db.conn.commit()
            cursor.close()
        except Exception as e:
            logger.error(f"Ошибка сохранения времени: {e}")
            try:
                db.conn.rollback()
            except Exception:
                pass
        
        # Обновляем меню
        call.data = f"schedule_times_{platform_type}_{category_id}_{bot_id}_{platform_id}_{posts_per_day}"
        handle_schedule_times(call)
        
    except Exception as e:
        logger.error(f"Ошибка в toggle_schedule_time: {e}")
        safe_answer_callback(bot, call.id, "❌ Ошибка")
@bot.callback_query_handler(func=lambda call: call.data.startswith("schedule_frequency_"))
def handle_schedule_frequency_select(call):
    """Выбор частоты публикаций в день (1-5)"""
    try:
        parts = call.data.split("_")
        platform_type = parts[2]
        category_id = int(parts[3])
        bot_id = int(parts[4])
        platform_id = parts[5]
        
        text = """
🔢 <b>ЧАСТОТА ПУБЛИКАЦИЙ</b>

Сколько раз в день публиковать контент?

<i>Выберите количество публикаций:</i>
"""
        
        markup = types.InlineKeyboardMarkup(row_width=3)
        
        # Кнопки частоты 1-5
        buttons = []
        for i in range(1, 6):
            buttons.append(
                types.InlineKeyboardButton(
                    f"{i} раз",
                    callback_data=f"set_frequency_{i}_{platform_type}_{category_id}_{bot_id}_{platform_id}"
                )
            )
        
        # Добавляем по 3 кнопки в ряд
        markup.row(*buttons[0:3])  # 1, 2, 3
        markup.row(*buttons[3:5])  # 4, 5
        
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"scheduler_setup_{platform_type}_{category_id}_{bot_id}_{platform_id}"
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
        logger.error(f"Ошибка в handle_schedule_frequency_select: {e}")
        safe_answer_callback(bot, call.id, "❌ Ошибка")


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_frequency_"))
def set_frequency(call):
    """Установка частоты публикаций"""
    try:
        parts = call.data.split("_")
        frequency = int(parts[2])  # 1-5
        platform_type = parts[3]
        category_id = int(parts[4])
        bot_id = int(parts[5])
        platform_id = parts[6]
        
        # Сохраняем частоту в БД
        try:
            cursor = db.conn.cursor()
            cursor.execute("""
                INSERT INTO platform_schedules (category_id, platform_type, platform_id, posts_per_day)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (category_id, platform_type, platform_id)
                DO UPDATE SET posts_per_day = %s, schedule_times = NULL
            """, (category_id, platform_type, platform_id, frequency, frequency))
            
            db.conn.commit()
            cursor.close()
            
            safe_answer_callback(bot, call.id, f"✅ Частота: {frequency} раз в день")
        except Exception as e:
            logger.error(f"Ошибка сохранения частоты: {e}")
            try:
                db.conn.rollback()
            except Exception:
                pass
            safe_answer_callback(bot, call.id, "❌ Ошибка сохранения")
        
        # Возвращаемся к настройке расписания
        call.data = f"scheduler_setup_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        handle_scheduler_setup(call)
        
    except Exception as e:
        logger.error(f"Ошибка в set_frequency: {e}")
        safe_answer_callback(bot, call.id, "❌ Ошибка")
@bot.callback_query_handler(func=lambda call: call.data.startswith("save_days_"))
def save_schedule_days(call):
    """Сохранение выбранных дней и возврат к настройке расписания"""
    try:
        parts = call.data.split("_")
        platform_type = parts[2]
        category_id = int(parts[3])
        bot_id = int(parts[4])
        platform_id = parts[5]
        
        safe_answer_callback(bot, call.id, "✅ Дни сохранены")
        
        # Возвращаемся к главному меню настройки расписания
        call.data = f"scheduler_setup_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        handle_scheduler_setup(call)
        
    except Exception as e:
        logger.error(f"Ошибка в save_schedule_days: {e}")
        safe_answer_callback(bot, call.id, "❌ Ошибка")


@bot.callback_query_handler(func=lambda call: call.data.startswith("save_times_"))
def save_schedule_times(call):
    """Сохранение выбранного времени и возврат к настройке расписания"""
    try:
        parts = call.data.split("_")
        platform_type = parts[2]
        category_id = int(parts[3])
        bot_id = int(parts[4])
        platform_id = parts[5]
        
        safe_answer_callback(bot, call.id, "✅ Время сохранено")
        
        # Возвращаемся к главному меню настройки расписания
        call.data = f"scheduler_setup_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        handle_scheduler_setup(call)
        
    except Exception as e:
        logger.error(f"Ошибка в save_schedule_times: {e}")
        safe_answer_callback(bot, call.id, "❌ Ошибка")


# Экспорт функций для обратной совместимости
get_platform_scheduler = _get_platform_scheduler

print("✅ handlers/global_scheduler.py загружен")
