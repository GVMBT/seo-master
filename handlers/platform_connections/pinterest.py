"""
Подключение Pinterest
"""
from telebot import types
from loader import bot, db
from utils import escape_html
from .utils import check_global_platform_uniqueness, user_adding_platform
from datetime import datetime
import json


@bot.callback_query_handler(func=lambda call: call.data == "add_platform_pinterest")
def add_platform_pinterest_with_instruction(call):
    """Pinterest OAuth авторизация"""
    user_id = call.from_user.id
    
    # State = просто user_id (как в оригинальном проекте)
    state = str(user_id)
    
    text = (
        "📌 <b>ПОДКЛЮЧЕНИЕ PINTEREST</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "<b>OAuth авторизация:</b>\n\n"
        "<b>📋 Инструкция:</b>\n\n"
        "1️⃣ Нажмите \"🔐 Авторизоваться\"\n"
        "2️⃣ Войдите в Pinterest и разрешите доступ\n"
        "3️⃣ Вы увидите страницу \"Pinterest подключен!\"\n"
        "4️⃣ Нажмите \"Вернуться в бота\"\n"
        "5️⃣ Готово! Pinterest подключен ✅\n\n"
        "<b>🔒 Безопасность:</b>\n"
        "• Ваш пароль остается у Pinterest\n"
        "• Вы можете отозвать доступ в любой момент\n"
        "• Мы получаем только разрешение на публикацию\n\n"
        "<i>💡 OAuth - это безопасный стандарт авторизации</i>"
    )
    
    # Сохраняем state в БД для проверки после редиректа
    user = db.get_user(user_id)
    if not user:
        bot.answer_callback_query(call.id, "❌ Ошибка: пользователь не найден")
        return
    
    # Сохраняем state в platform_connections как временные данные
    connections = user.get('platform_connections', {})
    if not isinstance(connections, dict):
        connections = {}
    
    connections['_pinterest_oauth_state'] = {
        'state': state,
        'timestamp': datetime.now().isoformat(),
        'user_id': user_id
    }
    
    db.cursor.execute("""
        UPDATE users 
        SET platform_connections = %s::jsonb
        WHERE id = %s
    """, (json.dumps(connections), user_id))
    db.conn.commit()
    
    # Pinterest OAuth URL
    from config import PINTEREST_APP_ID, PINTEREST_REDIRECT_URI
    oauth_url = (
        f"https://www.pinterest.com/oauth/?"
        f"client_id={PINTEREST_APP_ID}"
        f"&redirect_uri={PINTEREST_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=boards:read,boards:write,pins:read,pins:write,user_accounts:read"
        f"&state={state}"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🔐 Авторизоваться в Pinterest", url=oauth_url),
        types.InlineKeyboardButton("📖 Подробная инструкция", callback_data="show_instruction_pinterest"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="add_platform_menu")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("pinterest_enter_code_"))
def pinterest_enter_code(call):
    """Запрос кода авторизации Pinterest"""
    user_id = call.from_user.id
    
    text = (
        "📌 <b>ВВОД КОДА PINTEREST</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Отправьте код авторизации, который вы получили от Pinterest.\n\n"
        "<b>Где найти код:</b>\n"
        "После авторизации Pinterest перенаправит вас на страницу.\n"
        "В адресной строке браузера будет URL вида:\n"
        "<code>https://...?code=AQBx7Vh8LmK9...&state=...</code>\n\n"
        "Скопируйте всё что после <code>code=</code> и до <code>&</code>\n\n"
        "<b>Пример кода:</b>\n"
        "<code>AQBx7Vh8LmK9K3zQxRy...</code>\n\n"
        "Отправьте этот код сюда:"
    )
    
    # Сохраняем состояние ожидания кода
    user_adding_platform[user_id] = {
        'type': 'pinterest',
        'step': 'code'
    }
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("❌ Отмена", callback_data="add_platform_menu")
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
    
    bot.answer_callback_query(call.id, "📝 Ожидаю код...")


@bot.callback_query_handler(func=lambda call: call.data == "begin_connect_pinterest")
def begin_pinterest_connection(call):
    """Редирект на новый OAuth процесс"""
    call.data = "add_platform_pinterest"
    add_platform_pinterest_with_instruction(call)


@bot.callback_query_handler(func=lambda call: call.data == "show_instruction_pinterest")
def show_pinterest_instruction(call):
    """Показать подробную инструкцию Pinterest OAuth"""
    text = (
        "📌 <b>ИНСТРУКЦИЯ: PINTEREST OAUTH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>Что такое OAuth авторизация?</b>\n\n"
        "OAuth - это безопасный способ подключения вашего Pinterest "
        "аккаунта без ввода пароля. Используется Google, Facebook и другими сервисами.\n\n"
        "<b>📋 Пошаговая инструкция:</b>\n\n"
        "<b>Шаг 1: Подготовка</b>\n"
        "Убедитесь что у вас есть аккаунт Pinterest (желательно бизнес-аккаунт)\n\n"
        "<b>Шаг 2: Нажмите \"Авторизоваться\"</b>\n"
        "После нажатия кнопки откроется страница Pinterest\n\n"
        "<b>Шаг 3: Войдите в аккаунт</b>\n"
        "Введите email и пароль от вашего Pinterest\n\n"
        "<b>Шаг 4: Разрешите доступ</b>\n"
        "Pinterest покажет какие разрешения запрашивает бот:\n"
        "• Просмотр ваших досок\n"
        "• Создание досок\n"
        "• Просмотр пинов\n"
        "• Создание пинов\n\n"
        "Нажмите <b>\"Разрешить\"</b> или <b>\"Allow\"</b>\n\n"
        "<b>Шаг 5: Готово!</b>\n"
        "Pinterest перенаправит вас обратно и покажет подтверждение.\n"
        "Ваш аккаунт будет подключен автоматически.\n\n"
        "<b>🔒 Безопасность:</b>\n\n"
        "✅ Ваш пароль остается только у Pinterest\n"
        "✅ Бот получает только разрешение на публикацию\n"
        "✅ Вы можете отозвать доступ в любой момент\n"
        "✅ Никто не увидит ваш пароль или личные данные\n\n"
        "<b>❓ Как отозвать доступ:</b>\n\n"
        "1. Зайдите на Pinterest.com\n"
        "2. Настройки → Безопасность → Приложения\n"
        "3. Найдите наше приложение\n"
        "4. Нажмите \"Отозвать доступ\"\n\n"
        "<b>💡 Совет:</b>\n"
        "Используйте бизнес-аккаунт Pinterest для лучшей аналитики и функций!"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🔙 Назад к подключению", callback_data="add_platform_pinterest"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="add_platform_menu")
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
# TELEGRAM CHANNEL
# ═══════════════════════════════════════════════════════════════


print("✅ handlers/platform_connections/pinterest.py загружен")
