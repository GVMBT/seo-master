"""
Подключение Telegram
"""
from telebot import types
from loader import bot, db
from utils import escape_html
from .utils import check_global_platform_uniqueness, user_adding_platform
import json


@bot.callback_query_handler(func=lambda call: call.data == "add_platform_telegram")
def add_platform_telegram_with_instruction(call):
    """Telegram - показ инструкции"""
    text = (
        "✈️ <b>ПОДКЛЮЧЕНИЕ TELEGRAM</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "<b>📋 ИНСТРУКЦИЯ ПО ПОДКЛЮЧЕНИЮ:</b>\n\n"
        
        "<b>Шаг 1: Создайте бота через @BotFather</b>\n"
        "1️⃣ Откройте Telegram и найдите @BotFather\n"
        "2️⃣ Отправьте команду /newbot\n"
        "3️⃣ Придумайте имя для бота (например: Мой Магазин Bot)\n"
        "4️⃣ Придумайте username для бота (должен заканчиваться на bot)\n"
        "   Пример: myshop_content_bot\n"
        "5️⃣ BotFather пришлёт вам токен бота\n"
        "   Формат: <code>1234567890:ABCdefGHIjklMNOpqrsTUVwxyz</code>\n\n"
        
        "<b>Шаг 2: Добавьте бота в канал</b>\n"
        "1️⃣ Откройте ваш канал или группу\n"
        "2️⃣ Нажмите на название канала → Администраторы\n"
        "3️⃣ Добавить администратора → найдите вашего бота\n"
        "4️⃣ Дайте боту права:\n"
        "   • Публикация сообщений ✅\n"
        "   • Редактирование сообщений ✅\n"
        "5️⃣ Сохраните изменения\n\n"
        
        "<b>Шаг 3: Подготовьте данные</b>\n"
        "Вам понадобится:\n"
        "• Ссылка на канал/группу (например: @myshop или https://t.me/myshop)\n"
        "• Токен бота от @BotFather\n\n"
        
        "💡 <b>Важно:</b> Для приватных каналов используйте ID канала вместо username\n"
        "(например: -1001234567890)"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✅ Начать подключение", callback_data="begin_connect_telegram"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="add_platform_menu")
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
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "begin_connect_telegram")
def begin_telegram_connection(call):
    """Начало подключения Telegram - запрос ссылки на канал"""
    user_id = call.from_user.id
    
    text = (
        "✈️ <b>ПОДКЛЮЧЕНИЕ TELEGRAM</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "<b>Шаг 1 из 2:</b> Ссылка на канал/группу\n\n"
        "Отправьте ссылку или username вашего канала:\n\n"
        "<b>Примеры:</b>\n"
        "• @myshop\n"
        "• https://t.me/myshop\n"
        "• -1001234567890 (для приватных)\n\n"
        "💡 <i>Username можно найти в настройках канала</i>"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("❌ Отмена", callback_data="add_platform_menu")
    )
    
    user_adding_platform[user_id] = {
        'type': 'telegram',
        'step': 'channel',
        'data': {}
    }
    
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
    
    bot.answer_callback_query(call.id, "📝 Ожидаю ссылку на канал...")


print("✅ handlers/platform_connections.py загружен")


# ═══════════════════════════════════════════════════════════════
# УПРАВЛЕНИЕ ПОДКЛЮЧЕНИЯМИ
# ═══════════════════════════════════════════════════════════════


print("✅ handlers/platform_connections/telegram.py загружен")
