"""
Профиль пользователя - баланс, статистика, история операций
"""
from telebot import types
from loader import bot
from database.database import db
from config import ADMIN_ID
from utils import escape_html, safe_answer_callback


@bot.message_handler(func=lambda message: message.text == "👤 Профиль")
def show_profile(message):
    """Показать профиль пользователя"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        bot.send_message(message.chat.id, "⚠️ Ошибка. Нажмите /start")
        return
    
    # Получаем данные пользователя
    username = user.get('username', 'Guest')
    first_name = user.get('first_name', 'Пользователь')
    tokens = user.get('tokens', 0)
    created_at = str(user.get('created_at', ''))[:10]
    
    # Получаем статистику
    bots = db.get_user_bots(user_id)
    bots_count = len(bots) if bots else 0
    
    categories_count = 0
    for bot_item in (bots or []):
        categories = db.get_bot_categories(bot_item['id'])
        categories_count += len(categories) if categories else 0
    
    # ═══════════════════════════════════════════════════════════════
    # ПОЛНАЯ БУХГАЛТЕРИЯ - РАСЧЁТ ЗАТРАТ НА АВТОПОСТИНГ
    # ═══════════════════════════════════════════════════════════════
    from handlers.global_scheduler import _get_platform_scheduler
    
    total_bots_with_scheduler = 0
    total_categories_with_scheduler = 0
    total_active_platforms = 0
    total_posts_per_week = 0
    total_posts_per_month = 0
    total_tokens_per_week = 0
    total_tokens_per_month = 0
    
    bots_stats = []  # Статистика по каждому боту
    
    for bot_item in (bots or []):
        bot_id = bot_item['id']
        bot_name = bot_item['name']
        categories = db.get_bot_categories(bot_id)
        
        bot_posts_week = 0
        bot_platforms = 0
        bot_categories_active = 0
        
        # Получаем подключения бота
        bot_connections = bot_item.get('connected_platforms', {})
        if isinstance(bot_connections, str):
            try:
                import json
                bot_connections = json.loads(bot_connections)
            except Exception:
                bot_connections = {}
        
        for category in (categories or []):
            category_id = category['id']
            category_has_scheduler = False
            
            # Проверяем все платформы этой категории
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
                    
                    schedule = _get_platform_scheduler(category_id, platform_type, platform_id)
                    
                    if schedule.get('enabled', False):
                        category_has_scheduler = True
                        total_active_platforms += 1
                        bot_platforms += 1
                        
                        days = schedule.get('days', [])
                        posts_per_day = schedule.get('posts_per_day', 1) or 1
                        
                        posts_week = len(days) * posts_per_day if days else 0
                        
                        total_posts_per_week += posts_week
                        bot_posts_week += posts_week
            
            if category_has_scheduler:
                bot_categories_active += 1
                total_categories_with_scheduler += 1
        
        if bot_posts_week > 0:
            total_bots_with_scheduler += 1
            bots_stats.append({
                'name': bot_name,
                'platforms': bot_platforms,
                'categories': bot_categories_active,
                'posts_week': bot_posts_week
            })
    
    total_posts_per_month = total_posts_per_week * 4
    total_tokens_per_week = total_posts_per_week * 40
    total_tokens_per_month = total_posts_per_month * 40
    
    # Пока показываем 0, но в будущем здесь будет реальная история
    total_spent = 0
    
    # Логика GOD MODE
    if str(user_id) == str(ADMIN_ID):
        role = "👑 GOD (Админ)"
        token_display = "♾ (Безлимит)"
        # Для GOD показываем прогноз затрат (как если бы платил)
        show_cost_warnings = False  # Не показываем предупреждения о балансе
    else:
        role = "👤 Пользователь"
        token_display = f"{tokens} 💎"
        show_cost_warnings = True
    
    # Формируем текст профиля
    text = (
        f"👤 <b>ПРОФИЛЬ</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Имя: <b>{escape_html(first_name)}</b>\n"
        f"🔑 Роль: <b>{role}</b>\n"
        f"📅 Регистрация: <code>{created_at}</code>\n\n"
        
        f"💰 <b>БАЛАНС</b>\n"
        f"💎 Токены: <b>{token_display}</b>\n"
    )
    
    # Предупреждения о балансе (только для обычных пользователей)
    if show_cost_warnings:
        if tokens < 20:
            text += "🚨 <i>Критически низкий баланс!</i>\n"
        elif tokens < 100:
            text += "⚠️ <i>Рекомендуем пополнить токены</i>\n"
    
    text += (
        f"\n📊 <b>СТАТИСТИКА</b>\n"
        f"🤖 Ботов создано: <code>{bots_count}</code>\n"
        f"📂 Категорий: <code>{categories_count}</code>\n"
    )
    
    # Показываем историю затрат если есть
    if total_spent > 0:
        text += f"💸 Потрачено токенов: <code>{total_spent}</code>\n"
    
    # ПОЛНАЯ БУХГАЛТЕРИЯ АВТОПОСТИНГА
    if total_active_platforms > 0:
        text += (
            f"\n💰 <b>БУХГАЛТЕРИЯ АВТОПОСТИНГА</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"🤖 Ботов с планировщиком: <code>{total_bots_with_scheduler}</code>\n"
            f"📂 Категорий активно: <code>{total_categories_with_scheduler}</code>\n"
            f"📱 Платформ подключено: <code>{total_active_platforms}</code>\n\n"
            
            f"📅 <b>Публикации:</b>\n"
            f"   • Постов в неделю: <b>{total_posts_per_week}</b>\n"
            f"   • Постов в месяц: <b>{total_posts_per_month}</b>\n\n"
            
            f"💎 <b>Расход токенов:</b>\n"
            f"   • Неделя: <b>{total_tokens_per_week}</b> токенов\n"
            f"   • Месяц: <b>{total_tokens_per_month}</b> токенов\n"
        )
        
        # Добавляем информацию о балансе
        if show_cost_warnings:
            # Для обычных пользователей - предупреждения
            weeks_available = tokens / total_tokens_per_week if total_tokens_per_week > 0 else 999
            
            if weeks_available < 1:
                text += f"\n🚨 <b>ВНИМАНИЕ!</b> Токенов хватит менее чем на неделю!\n"
            elif weeks_available < 2:
                text += f"\n⚠️ Токенов хватит на ~{int(weeks_available)} недели\n"
            else:
                text += f"\n✅ Токенов хватит на ~{int(weeks_available)} недель\n"
        else:
            # Для GOD MODE - показываем прогноз (как если бы платил)
            if total_tokens_per_week > 0:
                text += f"\n💰 <b>Прогноз затрат</b> (если бы платили):\n"
                text += f"   • ~{int(total_tokens_per_week)} токенов/неделю\n"
                text += f"   • ~{int(total_tokens_per_month)} токенов/месяц\n"
        
        # Статистика по ботам
        if bots_stats:
            text += f"\n📊 <b>По ботам:</b>\n"
            for bot_stat in bots_stats[:5]:  # Показываем топ-5
                bot_name_short = escape_html(bot_stat['name'][:20])
                text += (
                    f"   • <b>{bot_name_short}</b>\n"
                    f"      {bot_stat['platforms']} платф, "
                    f"{bot_stat['categories']} катег, "
                    f"{bot_stat['posts_week']}/нед\n"
                )
    else:
        text += f"\n💤 <b>Автопостинг не настроен</b>\n"
    
    # Если есть боты, показываем последние 3
    if bots:
        text += f"\n📋 <b>ВАШИ БОТЫ:</b>\n"
        for bot_item in bots[:3]:
            bot_name = escape_html(bot_item['name'][:30])
            bot_id = bot_item['id']
            
            # Считаем категории этого бота
            cats = db.get_bot_categories(bot_id)
            cat_count = len(cats) if cats else 0
            
            text += f"• <b>{bot_name}</b> ({cat_count} кат.)\n"
        
        if bots_count > 3:
            text += f"<i>... и ещё {bots_count - 3}</i>\n"
    
    # Кнопки
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("💸 История расходов", callback_data="show_expenses"),
        types.InlineKeyboardButton("💎 Пополнить", callback_data="topup_balance")
    )
    markup.add(
        types.InlineKeyboardButton("🎁 Реферальная программа", callback_data="referral_program")
    )
    
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')


@bot.callback_query_handler(func=lambda call: call.data == "show_expenses")
def show_user_expenses(call):
    """История расходов токенов"""
    user_id = call.from_user.id
    
    # Получаем последние 20 операций
    db.cursor.execute("""
        SELECT amount, action, created_at, bot_id, category_id
        FROM token_expenses
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT 20
    """, (user_id,))
    
    expenses = db.cursor.fetchall()
    
    if not expenses:
        text = (
            "💸 <b>ИСТОРИЯ РАСХОДОВ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "У вас пока нет расходов токенов.\n\n"
            "<i>Расходы появятся после использования платных функций бота.</i>"
        )
    else:
        # Считаем общую сумму
        total = sum(e[0] for e in expenses)
        
        text = (
            "💸 <b>ИСТОРИЯ РАСХОДОВ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"📊 Всего потрачено: <b>{total}</b> 💎\n"
            f"📋 Последние {len(expenses)} операций:\n\n"
        )
        
        # Названия действий
        action_names = {
            'keywords_50': '🔑 Ключевые фразы (50)',
            'keywords_100': '🔑 Ключевые фразы (100)',
            'keywords_150': '🔑 Ключевые фразы (150)',
            'keywords_200': '🔑 Ключевые фразы (200)',
            'text_generation': '✍️ Генерация текста',
            'image_generation': '🎨 Генерация изображения',
            'tech_audit': '🔧 Технический аудит',
            'seo_audit': '📊 SEO аудит',
        }
        
        for exp in expenses:
            amount = exp[0]
            action = exp[1]
            date = str(exp[2])[:16] if exp[2] else ''
            
            action_name = action_names.get(action, action)
            
            text += f"• <code>{date}</code>\n"
            text += f"  {action_name}: <b>-{amount}</b> 💎\n\n"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 К профилю", callback_data="back_to_profile"))
    
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


@bot.callback_query_handler(func=lambda call: call.data == "referral_program")
def show_referral_program(call):
    """Реферальная программа"""
    from config import BOT_USERNAME
    user_id = call.from_user.id
    
    # Генерируем реферальную ссылку
    referral_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    
    # Получаем статистику рефералов (заглушка)
    total_referrals = 0
    earned_tokens = 0
    
    text = (
        "🎁 <b>РЕФЕРАЛЬНАЯ ПРОГРАММА</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        
        "💰 <b>КАК ЭТО РАБОТАЕТ:</b>\n\n"
        
        "1️⃣ Пригласите друга по вашей ссылке\n"
        "2️⃣ Друг регистрируется и получает бонус\n"
        "3️⃣ Вы получаете <b>10%</b> от его покупок!\n\n"
        
        "━━━━━━━━━━━━━━\n\n"
        
        f"📊 <b>ВАША СТАТИСТИКА:</b>\n"
        f"👥 Приглашено: <code>{total_referrals}</code> чел.\n"
        f"💎 Заработано: <code>{earned_tokens}</code> токенов\n\n"
        
        f"🔗 <b>ВАША ССЫЛКА:</b>\n"
        f"<code>{referral_link}</code>\n\n"
        
        "<i>Скопируйте ссылку и отправьте друзьям!</i>"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📤 Поделиться", callback_data="referral_share"),
        types.InlineKeyboardButton("🔙 К профилю", callback_data="back_to_profile")
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
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML', disable_web_page_preview=True)
    
    safe_answer_callback(bot, call.id)


@bot.callback_query_handler(func=lambda call: call.data == "referral_share")
def show_referral_share(call):
    """Показать текст для приглашения друзей с кнопкой поделиться"""
    user_id = call.from_user.id
    
    # Получаем имя бота из bot.get_me()
    from config import BOT_USERNAME
    try:
        bot_info = bot.get_me()
        bot_username = bot_info.username
    except Exception:
        bot_username = BOT_USERNAME
    
    referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    
    share_text = (
        "🤖 Попробуй AI Bot Creator!\n\n"
        "Умный бот для создания контента с AI:\n"
        "✅ Подбор ключевых фраз\n"
        "✅ Генерация текстов\n"
        "✅ Анализ сайтов\n"
        "✅ Подключение WordPress\n\n"
        f"🎁 Регистрируйся и получи 1500 токенов в подарок!\n\n"
        f"👉 {referral_link}"
    )
    
    # Создаём кнопку для шаринга
    markup = types.InlineKeyboardMarkup()
    
    # URL-encoded текст для шаринга
    import urllib.parse
    encoded_text = urllib.parse.quote(share_text)
    share_url = f"https://t.me/share/url?url={encoded_text}"
    
    markup.add(
        types.InlineKeyboardButton("📤 Поделиться", url=share_url)
    )
    
    bot.send_message(
        call.message.chat.id,
        share_text,
        reply_markup=markup,
        parse_mode=None,
        disable_web_page_preview=True
    )
    
    safe_answer_callback(bot, call.id, "✅ Отправьте друзьям!")


@bot.callback_query_handler(func=lambda call: call.data == "back_to_profile")
def back_to_profile(call):
    """Возврат к профилю"""
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    # Создаем fake message для вызова show_profile
    fake_msg = type('obj', (object,), {
        'from_user': type('obj', (object,), {'id': call.from_user.id})(),
        'chat': type('obj', (object,), {'id': call.message.chat.id})(),
        'text': '👤 Профиль'
    })()
    
    show_profile(fake_msg)
    safe_answer_callback(bot, call.id)


print("✅ handlers/profile.py загружен")
