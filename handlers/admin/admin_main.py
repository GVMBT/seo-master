# -*- coding: utf-8 -*-
"""
Главная панель администратора - дашборд со статистикой
"""
import logging

logger = logging.getLogger(__name__)

from telebot import types

from loader import bot

from database.database import db

from config import ADMIN_ID

from utils import escape_html


print(f"\n{'='*60}")
print(f"🔧 ЗАГРУЗКА handlers/admin/admin_main.py")
print(f"   ADMIN_ID из config: {ADMIN_ID}")
print(f"{'='*60}\n")


# --- ГЛАВНАЯ ПАНЕЛЬ (ОБНОВЛЕННАЯ) ---
print("📝 Регистрация хендлера admin_panel для кнопки '🔐 АДМИНКА'...")
@bot.message_handler(func=lambda message: message.text == "🔐 АДМИНКА")
def admin_panel(message):
    """Обработчик кнопки АДМИНКА"""
    print(f"\n{'='*60}")
    print(f"🔥 ADMIN HANDLER TRIGGERED!")
    print(f"{'='*60}\n")
    
    user_id = message.from_user.id
    
    # Логирование для отладки
    print(f"\n{'='*60}")
    print(f"🔐 ПОПЫТКА ДОСТУПА К АДМИНКЕ")
    print(f"{'='*60}")
    print(f"User ID: {user_id} (type: {type(user_id)})")
    print(f"ADMIN_ID: {ADMIN_ID} (type: {type(ADMIN_ID)})")
    print(f"ADMIN_ID is None: {ADMIN_ID is None}")
    print(f"Сравнение str: '{str(user_id)}' == '{str(ADMIN_ID)}': {str(user_id) == str(ADMIN_ID)}")
    print(f"{'='*60}\n")
    
    # 1. Проверка что ADMIN_ID установлен
    if ADMIN_ID is None or ADMIN_ID == '':
        error_msg = (
            "⚠️ <b>ADMIN_ID не установлен!</b>\n\n"
            "Для доступа к админ-панели нужно:\n\n"
            "1️⃣ Узнать свой Telegram ID (бот @userinfobot)\n"
            "2️⃣ Добавить в .env файл:\n"
            "<code>ADMIN_ID=ваш_id</code>\n"
            "3️⃣ Перезапустить бота\n\n"
            f"📝 Ваш ID: <code>{user_id}</code>\n"
            "Скопируйте и добавьте в .env"
        )
        bot.send_message(message.chat.id, error_msg, parse_mode='HTML')
        print("❌ ADMIN_ID не установлен - отказано в доступе")
        return
    
    # 2. Проверка прав
    if str(user_id) != str(ADMIN_ID):
        bot.send_message(message.chat.id, f"⛔️ Доступ запрещен.\n\nВаш ID: {user_id}\nТребуется ID: {ADMIN_ID}")
        print(f"❌ Доступ запрещен: {user_id} != {ADMIN_ID}")
        return
    
    print(f"✅ Доступ разрешен для админа {user_id}")
    bot.send_chat_action(message.chat.id, 'typing')

    # 2. Сбор данных
    try:
        stats = db.get_bot_stats() or {'users': 0, 'projects': 0}
        money = db.get_financial_stats() or 0
        users_by_status = db.get_users_by_status() or {}
        last_payments = db.get_last_payments(5) or []
        
        # НОВОЕ: Статистика бесплатных vs платных пользователей
        free_users = db.get_free_users_count() or 0
        paid_users = db.get_paid_users_count() or 0
        
        # НОВОЕ: Статистика рефералов
        referral_stats = db.get_referral_stats_admin() or {
            'total_activations': 0,
            'total_bonuses': 0,
            'doubled_deposits': 0
        }
        
        # НОВОЕ: Быстрая проверка AI статуса
        try:
            from utils.system_monitor import check_claude_api, check_imagen_api
            claude_status = check_claude_api()
            imagen_status = check_imagen_api()
            
            # Определяем эмодзи и модели
            claude_emoji = "✅" if claude_status.get('status') == 'ok' else "❌"
            claude_model = claude_status.get('model', 'N/A') if claude_status.get('status') == 'ok' else 'Offline'
            
            imagen_emoji = "✅" if imagen_status.get('status') == 'ok' else ("⚪️" if imagen_status.get('status') == 'not_configured' else "❌")
            imagen_model = imagen_status.get('model', 'N/A') if imagen_status.get('status') == 'ok' else 'Offline'
        except Exception as e:
            print(f"⚠️ Ошибка проверки AI: {e}")
            claude_emoji = "❓"
            imagen_emoji = "❓"
            claude_model = 'Unknown'
            imagen_model = 'Unknown'
        
    except Exception as e:
        print(f"⚠️ Ошибка сбора статистики в админке: {e}")
        import traceback
        traceback.print_exc()
        bot.send_message(message.chat.id, f"⚠️ Ошибка БД: {e}")
        return

    # 3. Формирование отчета с расширенной статистикой
    text = (
        "🕴 <b>ADMIN DASHBOARD (GOD MODE)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "🤖 <b>AI СЕРВИСЫ:</b>\n"
        f"   ├─ Claude: {claude_emoji} <code>{claude_model}</code>\n"
        f"   └─ Nano Banana Pro: {imagen_emoji} <code>{imagen_model}</code>\n\n"
        
        "📊 <b>ГЛАВНЫЕ ЦИФРЫ</b>\n"
        f"👥 Всего юзеров: <code>{stats['users']}</code>\n"
        f"   ├─ 🆓 Халявщики: <code>{free_users}</code>\n"
        f"   └─ 💎 Платные: <code>{paid_users}</code>\n"
        f"📂 Проектов: <code>{stats['projects']}</code>\n"
        f"💰 Выручка: <code>{money} ₽</code>\n\n"
        
        "🔗 <b>РЕФЕРАЛЬНАЯ ПРОГРАММА:</b>\n"
        f"👥 Всего активаций: <code>{referral_stats.get('total_activations', 0)}</code>\n"
        f"💰 Выплачено бонусов: <code>{referral_stats.get('total_bonuses', 0)}</code> токенов\n"
        f"🎁 Удвоенных депозитов: <code>{referral_stats.get('doubled_deposits', 0)}</code>\n\n"
        
        "💎 <b>ПО ТАРИФАМ:</b>\n"
        f"👤 Free: <code>{users_by_status.get('free', 0)}</code>\n"
        f"🚗 Тест-драйв: <code>{users_by_status.get('test_drive', 0)}</code>\n"
        f"🚀 СЕО Старт: <code>{users_by_status.get('seo_start', 0)}</code>\n"
        f"⭐ СЕО Профи: <code>{users_by_status.get('seo_pro', 0)}</code>\n"
        f"🕵 PBN Агент: <code>{users_by_status.get('pbn_agent', 0)}</code>\n\n"
        
        "💵 <b>ПОСЛЕДНИЕ ОПЛАТЫ</b>\n"
    )

    if last_payments:
        for p in last_payments:
            d = str(p['date']).split('.')[0]
            text += f"• {d}: +{p['amount']}₽ ({p['tariff']})\n"
    else:
        text += "• Транзакций пока нет\n"

    # Завершаем текст
    text += "\n━━━━━━━━━━━━━━━━━━━━"

    # 4. Кнопки управления
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🖥 Мониторинг систем", callback_data="admin_system_monitor"),
        types.InlineKeyboardButton("📢 Сообщения всем", callback_data="admin_broadcast_menu")
    )
    markup.add(
        types.InlineKeyboardButton("🔑 Настройки API", callback_data="admin_api_settings"),
        types.InlineKeyboardButton("👥 Посетители", callback_data="admin_visitors")
    )
    markup.add(
        types.InlineKeyboardButton("📨 Расписание сообщений", callback_data="admin_messaging"),
        types.InlineKeyboardButton("🔔 Уведомления", callback_data="admin_notification_settings")
    )
    markup.add(
        types.InlineKeyboardButton("💵 Затраты API ($)", callback_data="admin_api_costs"),
        types.InlineKeyboardButton("📝 Логи ошибок", callback_data="admin_error_logs")
    )
    
    # Безопасная отправка с обработкой ошибок
    # Отправляем GIF с текстом и кнопками
    gif_url = "https://ecosteni.ru/wp-content/uploads/2026/01/202601220357.gif"
    
    try:
        bot.send_animation(
            message.chat.id,
            gif_url,
            caption=text,
            reply_markup=markup,
            parse_mode='HTML'
        )
    except Exception as e:
        print(f"⚠️ Ошибка отправки GIF в admin_panel: {e}")
        # Fallback - отправляем без GIF
        try:
            bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')
        except Exception as e2:
            print(f"⚠️ Ошибка отправки текста: {e2}")

print("✅ Хендлер admin_panel зарегистрирован успешно!")

# ═══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ОБРАБОТЧИКИ
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data == "back_to_admin")
def back_to_admin(call):
    """Возврат в главное меню админки"""
    bot.delete_message(call.message.chat.id, call.message.message_id)
    # Создаем фейковое сообщение для вызова admin_panel
    fake_msg = type('obj', (object,), {
        'from_user': type('obj', (object,), {'id': call.from_user.id})(),
        'chat': type('obj', (object,), {'id': call.message.chat.id})(),
        'text': '🔐 АДМИНКА'
    })()
    admin_panel(fake_msg)


@bot.callback_query_handler(func=lambda call: call.data == "admin_api_costs")
def admin_api_costs(call):
    """Показать статистику затрат на API"""
    user_id = call.from_user.id
    
    if str(user_id) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "⛔️ Доступ запрещен", show_alert=True)
        return
    
    try:
        from utils.api_cost_tracker import format_costs_report
        text = format_costs_report(30)
    except Exception as e:
        text = f"💵 <b>ЗАТРАТЫ НА API</b>\n\n⚠️ Ошибка: {e}\n\n<i>Данные начнут собираться после следующих запросов к API.</i>"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📅 7 дней", callback_data="admin_api_costs_7"),
        types.InlineKeyboardButton("📅 30 дней", callback_data="admin_api_costs_30")
    )
    markup.add(
        types.InlineKeyboardButton("📅 90 дней", callback_data="admin_api_costs_90")
    )
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                             reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_api_costs_"))
def admin_api_costs_period(call):
    """Показать затраты за выбранный период"""
    user_id = call.from_user.id
    
    if str(user_id) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "⛔️ Доступ запрещен", show_alert=True)
        return
    
    days = int(call.data.split("_")[-1])
    
    try:
        from utils.api_cost_tracker import format_costs_report
        text = format_costs_report(days)
    except Exception as e:
        text = f"💵 <b>ЗАТРАТЫ НА API ({days} дней)</b>\n\n⚠️ Ошибка: {e}"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📅 7 дней", callback_data="admin_api_costs_7"),
        types.InlineKeyboardButton("📅 30 дней", callback_data="admin_api_costs_30")
    )
    markup.add(
        types.InlineKeyboardButton("📅 90 дней", callback_data="admin_api_costs_90")
    )
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                             reply_markup=markup, parse_mode='HTML')
    except Exception:
        pass
    
    bot.answer_callback_query(call.id)
print("✅ handlers/admin/admin_main.py загружен")


# ═══════════════════════════════════════════════════════════════
# МОНИТОРИНГ СИСТЕМ
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data == "admin_system_monitor")
def admin_system_monitor(call):
    """Мониторинг систем"""
    user_id = call.from_user.id
    
    if str(user_id) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "⛔️ Доступ запрещен", show_alert=True)
        return
    
    bot.answer_callback_query(call.id, "🔍 Проверяю системы...")
    
    try:
        from utils.system_monitor import check_claude_api, check_imagen_api, check_database, check_telegram
        import psutil
        import os
        
        # Проверяем AI сервисы
        claude = check_claude_api()
        imagen = check_imagen_api()
        
        # Проверяем БД
        db_status = check_database()
        
        # Проверяем Telegram
        tg_status = check_telegram(bot)
        
        # Системные ресурсы
        cpu = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        # Статус эмодзи
        def status_emoji(status):
            if status == 'ok': return '✅'
            elif status == 'not_configured': return '⚪️'
            else: return '❌'
        
        text = (
            "🖥 <b>МОНИТОРИНГ СИСТЕМ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            
            "🤖 <b>AI СЕРВИСЫ:</b>\n"
            f"{status_emoji(claude['status'])} <b>Claude AI</b>\n"
            f"   └─ Модель: <code>{claude.get('model', 'N/A')}</code>\n"
            f"   └─ Статус: {claude.get('message', 'Unknown')}\n\n"
            
            f"{status_emoji(imagen['status'])} <b>Nano Banana Pro (Nano Banana Pro)</b>\n"
            f"   └─ Модель: <code>{imagen.get('model', 'N/A')}</code>\n"
            f"   └─ Статус: {imagen.get('message', 'Unknown')}\n\n"
            
            "💾 <b>БАЗА ДАННЫХ:</b>\n"
            f"{status_emoji(db_status['status'])} PostgreSQL\n"
            f"   └─ Подключение: {db_status.get('message', 'Unknown')}\n"
            f"   └─ Версия: <code>{db_status.get('version', 'N/A')}</code>\n\n"
            
            "✈️ <b>TELEGRAM API:</b>\n"
            f"{status_emoji(tg_status['status'])} Telegram Bot API\n"
            f"   └─ Бот: @{tg_status.get('username', 'Unknown')}\n"
            f"   └─ ID: <code>{tg_status.get('bot_id', 'N/A')}</code>\n\n"
            
            "💻 <b>СЕРВЕР:</b>\n"
            f"🔹 CPU: <code>{cpu}%</code>\n"
            f"🔹 RAM: <code>{memory.percent}%</code> ({memory.used // (1024**3)}GB / {memory.total // (1024**3)}GB)\n"
            f"🔹 Диск: <code>{disk.percent}%</code> ({disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB)\n"
            f"🔹 Процесс: <code>PID {os.getpid()}</code>\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ Обновлено: сейчас"
        )
        
    except Exception as e:
        text = f"🖥 <b>МОНИТОРИНГ СИСТЕМ</b>\n\n⚠️ Ошибка: {str(e)[:200]}"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🔄 Обновить", callback_data="admin_system_monitor"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")
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


# ═══════════════════════════════════════════════════════════════
# РАССЫЛКА СООБЩЕНИЙ
# ═══════════════════════════════════════════════════════════════

# Временное хранилище для рассылки
admin_broadcast_data = {}

@bot.callback_query_handler(func=lambda call: call.data == "admin_broadcast_menu")
def admin_broadcast_menu(call):
    """Меню рассылки"""
    user_id = call.from_user.id
    
    if str(user_id) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "⛔️ Доступ запрещен", show_alert=True)
        return
    
    # Статистика пользователей
    try:
        db.cursor.execute("SELECT COUNT(*) FROM users")
        total_users = db.cursor.fetchone()[0]
        
        db.cursor.execute("SELECT COUNT(*) FROM users WHERE last_activity >= NOW() - INTERVAL '7 days'")
        active_7d = db.cursor.fetchone()[0]
        
        db.cursor.execute("SELECT COUNT(*) FROM users WHERE last_activity >= NOW() - INTERVAL '30 days'")
        active_30d = db.cursor.fetchone()[0]
    except Exception:
        total_users = 0
        active_7d = 0
        active_30d = 0
    
    text = (
        "📢 <b>РАССЫЛКА СООБЩЕНИЙ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "📊 <b>АУДИТОРИЯ:</b>\n"
        f"👥 Всего пользователей: <code>{total_users}</code>\n"
        f"🟢 Активны 7 дней: <code>{active_7d}</code>\n"
        f"🟡 Активны 30 дней: <code>{active_30d}</code>\n\n"
        
        "Выберите кому отправить:\n"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(f"👥 Всем пользователям ({total_users})", callback_data="broadcast_all"),
        types.InlineKeyboardButton(f"🟢 Активным за 7 дней ({active_7d})", callback_data="broadcast_7d"),
        types.InlineKeyboardButton(f"💎 Платным пользователям", callback_data="broadcast_paid"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")
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
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("broadcast_"))
def admin_broadcast_start(call):
    """Начало рассылки"""
    user_id = call.from_user.id
    
    if str(user_id) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "⛔️ Доступ запрещен", show_alert=True)
        return
    
    broadcast_type = call.data.split("_")[-1]
    
    # Сохраняем тип рассылки
    admin_broadcast_data[user_id] = {
        'type': broadcast_type,
        'awaiting_message': True
    }
    
    type_names = {
        'all': '👥 Всем пользователям',
        '7d': '🟢 Активным за 7 дней',
        'paid': '💎 Платным пользователям'
    }
    
    text = (
        "📝 <b>ТЕКСТ РАССЫЛКИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Аудитория: {type_names.get(broadcast_type, 'Выбранная группа')}\n\n"
        "Отправьте сообщение которое нужно разослать.\n\n"
        "<i>Можно отправить текст, фото с подписью или документ.</i>"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("❌ Отмена", callback_data="admin_broadcast_menu")
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
    
    bot.answer_callback_query(call.id, "📝 Ожидаю сообщение для рассылки...")


@bot.message_handler(func=lambda message: message.from_user.id in admin_broadcast_data and admin_broadcast_data[message.from_user.id].get('awaiting_message'))
def admin_broadcast_execute(message):
    """Выполнение рассылки"""
    user_id = message.from_user.id
    
    if str(user_id) != str(ADMIN_ID):
        return
    
    broadcast_type = admin_broadcast_data[user_id]['type']
    
    # Получаем список пользователей
    try:
        if broadcast_type == 'all':
            db.cursor.execute("SELECT telegram_id FROM users")
        elif broadcast_type == '7d':
            db.cursor.execute("SELECT telegram_id FROM users WHERE last_activity >= NOW() - INTERVAL '7 days'")
        elif broadcast_type == 'paid':
            db.cursor.execute("SELECT telegram_id FROM users WHERE balance > 1500")  # Купили токены
        
        users = [row[0] for row in db.cursor.fetchall()]
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка получения пользователей: {e}")
        del admin_broadcast_data[user_id]
        return
    
    # Убираем из ожидания
    del admin_broadcast_data[user_id]
    
    # Подтверждение
    text = (
        "⚠️ <b>ПОДТВЕРЖДЕНИЕ РАССЫЛКИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Будет отправлено: <code>{len(users)}</code> пользователям\n\n"
        "Подтвердите отправку:"
    )
    
    # Сохраняем данные для подтверждения
    admin_broadcast_data[user_id] = {
        'users': users,
        'message': message
    }
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Отправить", callback_data="confirm_broadcast"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="admin_broadcast_menu")
    )
    
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')


@bot.callback_query_handler(func=lambda call: call.data == "confirm_broadcast")
def admin_broadcast_confirm(call):
    """Подтверждение и отправка рассылки"""
    user_id = call.from_user.id
    
    if str(user_id) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "⛔️ Доступ запрещен", show_alert=True)
        return
    
    if user_id not in admin_broadcast_data:
        bot.answer_callback_query(call.id, "❌ Данные рассылки не найдены")
        return
    
    users = admin_broadcast_data[user_id]['users']
    source_message = admin_broadcast_data[user_id]['message']
    
    bot.answer_callback_query(call.id, f"📤 Начинаю рассылку {len(users)} пользователям...")
    
    # Удаляем сообщение с подтверждением
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    # Статусное сообщение
    status_msg = bot.send_message(
        call.message.chat.id,
        f"📤 Рассылка: 0/{len(users)}"
    )
    
    # Рассылка
    success = 0
    failed = 0
    
    for idx, target_id in enumerate(users, 1):
        try:
            # Копируем сообщение
            bot.copy_message(
                target_id,
                source_message.chat.id,
                source_message.message_id
            )
            success += 1
        except Exception as e:
            failed += 1
            print(f"Ошибка отправки {target_id}: {e}")
        
        # Обновляем статус каждые 10 сообщений
        if idx % 10 == 0:
            try:
                bot.edit_message_text(
                    f"📤 Рассылка: {idx}/{len(users)}\n✅ Успешно: {success}\n❌ Ошибок: {failed}",
                    call.message.chat.id,
                    status_msg.message_id
                )
            except Exception:
                pass
    
    # Финальный отчет
    text = (
        "✅ <b>РАССЫЛКА ЗАВЕРШЕНА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Всего: <code>{len(users)}</code>\n"
        f"✅ Успешно: <code>{success}</code>\n"
        f"❌ Ошибок: <code>{failed}</code>"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🔙 В админку", callback_data="back_to_admin")
    )
    
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            status_msg.message_id,
            reply_markup=markup,
            parse_mode='HTML'
        )
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    
    # Очищаем данные
    if user_id in admin_broadcast_data:
        del admin_broadcast_data[user_id]


# ═══════════════════════════════════════════════════════════════
# НАСТРОЙКИ API
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data == "admin_api_settings")
def admin_api_settings(call):
    """Настройки API ключей"""
    user_id = call.from_user.id
    
    if str(user_id) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "⛔️ Доступ запрещен", show_alert=True)
        return
    
    from config import ANTHROPIC_API_KEY as anthropic_key, GOOGLE_API_KEY as google_key
    
    # Проверяем наличие ключей (используем из config, а не напрямую из os.getenv)
    anthropic_key = anthropic_key or ""
    google_key = google_key or ""
    
    anthropic_status = "✅ Настроен" if anthropic_key and not anthropic_key.startswith("your_") else "❌ Не настроен"
    google_status = "✅ Настроен" if google_key and not google_key.startswith("your_") else "❌ Не настроен"
    
    # Маскируем ключи
    def mask_key(key):
        if not key or len(key) < 10:
            return "не указан"
        return key[:6] + "..." + key[-4:]
    
    text = (
        "🔑 <b>НАСТРОЙКИ API</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "<b>🤖 Anthropic API (Claude):</b>\n"
        f"Статус: {anthropic_status}\n"
        f"Ключ: <code>{mask_key(anthropic_key)}</code>\n\n"
        
        "<b>🍌 Nano Banana Pro API:</b>\n"
        f"Статус: {google_status}\n"
        f"Ключ: <code>{mask_key(google_key)}</code>\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<i>Для изменения API ключей отредактируйте файл .env на сервере.</i>"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")
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
    
    bot.answer_callback_query(call.id)


# ═══════════════════════════════════════════════════════════════
# ПОСЕТИТЕЛИ
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data == "admin_visitors")
def admin_visitors(call):
    """Статистика посетителей"""
    user_id = call.from_user.id
    
    if str(user_id) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "⛔️ Доступ запрещен", show_alert=True)
        return
    
    try:
        # Последние 10 пользователей (используем balance, НЕ tokens!)
        db.cursor.execute("""
            SELECT id, first_name, username, last_activity, balance
            FROM users
            ORDER BY last_activity DESC NULLS LAST
            LIMIT 10
        """)
        users = db.cursor.fetchall()
        
        # Статистика по дням
        db.cursor.execute("""
            SELECT 
                DATE(last_activity) as date,
                COUNT(*) as count
            FROM users
            WHERE last_activity >= NOW() - INTERVAL '7 days'
            GROUP BY DATE(last_activity)
            ORDER BY date DESC
        """)
        daily_stats = db.cursor.fetchall()
        
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Ошибка БД", show_alert=True)
        print(f"❌ Ошибка admin_visitors: {e}")
        return
    
    text = (
        "👥 <b>ПОСЕТИТЕЛИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "<b>📊 Новые пользователи за 7 дней:</b>\n"
    )
    
    for date, count in daily_stats:
        text += f"• {date}: <code>{count}</code> чел.\n"
    
    text += "\n<b>👤 Последние пользователи:</b>\n\n"
    
    if not users:
        text += "<i>Пользователей пока нет</i>\n"
    
    for u in users:
        try:
            # ВАЖНО: cursor возвращает dict, а не tuple!
            tg_id = u.get('id') or u.get('telegram_id')
            first = u.get('first_name')
            username = u.get('username')
            activity = u.get('last_activity')
            balance = u.get('balance')
            
            name = first or "Без имени"
            username_str = f"@{username}" if username else f"ID:{tg_id}"
            
            # Форматируем дату
            activity_str = str(activity).split('.')[0] if activity else 'никогда'
            
            text += f"• {name} ({username_str})\n"
            text += f"  💎 {balance or 0} токенов | ⏰ {activity_str}\n\n"
        except Exception as e:
            print(f"❌ Ошибка обработки пользователя {u}: {e}")
            text += f"• Ошибка отображения\n\n"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")
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
    
    bot.answer_callback_query(call.id)


# ═══════════════════════════════════════════════════════════════
# РАСПИСАНИЕ СООБЩЕНИЙ (ПОЛНЫЙ ФУНКЦИОНАЛ)
# ═══════════════════════════════════════════════════════════════
# Обработчик находится в handlers/admin/schedule_settings.py


# ═══════════════════════════════════════════════════════════════
# УВЕДОМЛЕНИЯ (ПОЛНЫЙ ФУНКЦИОНАЛ)
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data == "admin_notification_settings")
def admin_notification_settings_callback(call):
    """Настройки уведомлений - callback обработчик"""
    user_id = call.from_user.id
    
    if str(user_id) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "⛔️ Доступ запрещен", show_alert=True)
        return
    
    try:
        from handlers.admin.notification_settings import get_notification_settings
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        settings = get_notification_settings()
        
        text = """
🔔 <b>НАСТРОЙКИ УВЕДОМЛЕНИЙ</b>

Настройте уведомления для админа:

"""
        
        # Формируем список настроек
        settings_list = [
            ('new_payments', '💰 Новые оплаты'),
            ('new_users', '👥 Новые пользователи'),
            ('system_errors', '⚠️ Ошибки системы'),
            ('ai_status', '🤖 Статус AI сервисов'),
            ('low_balance', '💎 Низкий баланс API')
        ]
        
        for key, label in settings_list:
            setting = settings.get(key, {'enabled': False})
            status = "✅ ВКЛ" if setting['enabled'] else "❌ ВЫКЛ"
            text += f"{label}: {status}\n"
        
        text += "\n<i>Нажмите на кнопку, чтобы изменить настройку</i>"
        
        # Создаём клавиатуру
        keyboard = InlineKeyboardMarkup(row_width=1)
        
        for key, label in settings_list:
            setting = settings.get(key, {'enabled': False})
            status_icon = "✅" if setting['enabled'] else "❌"
            
            keyboard.add(
                InlineKeyboardButton(
                    f"{status_icon} {label}",
                    callback_data=f"admin_notif_toggle_{key}"
                )
            )
        
        keyboard.add(
            InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")
        )
        
        try:
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
        except Exception:
            bot.send_message(call.message.chat.id, text, reply_markup=keyboard, parse_mode='HTML')
        
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        logger.error(f"Ошибка в admin_notification_settings: {e}")
        bot.answer_callback_query(call.id, "❌ Ошибка загрузки настроек", show_alert=True)


# ═══════════════════════════════════════════════════════════════
# СБОР ЛОГОВ ОШИБОК
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data == "admin_error_logs")
def admin_error_logs_menu(call):
    """Главное меню логов ошибок"""
    user_id = call.from_user.id
    
    if str(user_id) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "⛔️ Доступ запрещен", show_alert=True)
        return
    
    try:
        # Читаем последние 50 строк из bot.log
        import os
        log_path = 'bot.log'
        
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                last_lines = lines[-50:] if len(lines) > 50 else lines
            
            # Фильтруем только ERROR и CRITICAL
            error_lines = [line for line in last_lines if 'ERROR' in line or 'CRITICAL' in line]
            
            if error_lines:
                text = (
                    "📋 <b>ПОСЛЕДНИЕ ОШИБКИ</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"<code>{''.join(error_lines[-20:])}</code>\n\n"
                    f"Показано: {len(error_lines[-20:])} из {len(error_lines)} ошибок"
                )
            else:
                text = (
                    "✅ <b>ЛОГИ ОШИБОК</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    "Ошибок не обнаружено! 🎉"
                )
        else:
            text = "⚠️ Файл логов не найден"
            
    except Exception as e:
        text = f"⚠️ <b>ОШИБКА ЧТЕНИЯ ЛОГОВ</b>\n\n{str(e)}"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📥 Скачать отчет (24ч)", callback_data="admin_download_logs_24"),
        types.InlineKeyboardButton("📥 Скачать отчет (7д)", callback_data="admin_download_logs_168")
    )
    markup.add(
        types.InlineKeyboardButton("🔄 Обновить", callback_data="admin_error_logs")
    )
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")
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
    
    bot.answer_callback_query(call.id, "📊 Логи обновлены")


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_download_logs_"))
def admin_download_error_logs(call):
    """Скачать файл с логами ошибок"""
    user_id = call.from_user.id
    
    if str(user_id) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "⛔️ Доступ запрещен", show_alert=True)
        return
    
    # Показываем индикатор загрузки
    bot.answer_callback_query(call.id, "⏳ Формирование отчета...", show_alert=False)
    bot.send_chat_action(call.message.chat.id, 'upload_document')
    
    # Парсим параметры
    parts = call.data.split("_")
    
    # Получаем количество часов
    if parts[-1] == "24":
        period_name = "24 часа"
    elif parts[-1] == "168":
        period_name = "7 дней"
    else:
        period_name = "24 часа"
    
    try:
        import os
        from datetime import datetime
        
        log_path = 'bot.log'
        
        if not os.path.exists(log_path):
            bot.send_message(
                call.message.chat.id,
                "⚠️ Файл логов не найден."
            )
            return
        
        # Создаем временную копию лога
        temp_file = f"error_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(f"📋 ОТЧЕТ ПО ЛОГАМ\n")
            f.write(f"Период: {period_name}\n")
            f.write(f"Дата формирования: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*60 + "\n\n")
            f.write(content)
        
        # Отправляем файл
        with open(temp_file, 'rb') as f:
            bot.send_document(
                call.message.chat.id,
                f,
                caption=f"📊 Логи за {period_name}"
            )
        
        # Удаляем временный файл
        os.remove(temp_file)
        
    except Exception as e:
        bot.send_message(
            call.message.chat.id,
            f"❌ Ошибка формирования отчета:\n<code>{str(e)}</code>",
            parse_mode='HTML'
        )


print("✅ handlers/admin/admin_main.py полностью загружен")
