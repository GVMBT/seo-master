"""
Подключение Website - меню выбора
"""
from telebot import types
from loader import bot, db
from utils import escape_html
from .utils import check_global_platform_uniqueness
from cms_platforms import SUPPORTED_CMS
import json


@bot.callback_query_handler(func=lambda call: call.data == "add_website_menu")
def add_website_menu(call):
    """Подменю выбора CMS для WEB сайта"""
    text = (
        "🌐 <b>WEB САЙТ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Выберите CMS вашего сайта:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Добавляем все поддерживаемые CMS
    buttons = []
    for cms_id, cms_info in SUPPORTED_CMS.items():
        buttons.append(
            types.InlineKeyboardButton(
                f"{cms_info['emoji']} {cms_info['name']}", 
                callback_data=f"add_cms_{cms_id}"
            )
        )
    
    # Добавляем кнопки по 2 в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.add(buttons[i], buttons[i + 1])
        else:
            markup.add(buttons[i])
    
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data="add_platform_menu")
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
# УНИВЕРСАЛЬНОЕ ПОДКЛЮЧЕНИЕ CMS
# ═══════════════════════════════════════════════════════════════


print("✅ handlers/platform_connections/website_menu.py загружен")
