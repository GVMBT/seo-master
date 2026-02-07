"""
Тарифы - отображение пакетов токенов и цен (обновленная версия)
"""
from telebot import types
from loader import bot
from database.database import db
from config import TOKEN_PRICES
from utils import escape_html, safe_answer_callback


# Пакеты токенов с ценами (обновленные по скриншоту)
TOKEN_PACKAGES = {
    'mini': {
        'name': '🚀 Мини',
        'emoji': '🚀',
        'tokens': 1000,
        'bonus': 0,
        'price_rub': 1000,
        'description': 'Для начала'
    },
    'starter': {
        'name': '🎯 Старт',
        'emoji': '🎯',
        'tokens': 3000,
        'bonus': 500,
        'price_rub': 3000,
        'description': 'Базовый пакет'
    },
    'professional': {
        'name': '⚡ Профи',
        'emoji': '⚡',
        'tokens': 6000,
        'bonus': 1200,
        'price_rub': 6000,
        'description': 'Для профессионалов'
    },
    'business': {
        'name': '📦 Бизнес',
        'emoji': '📦',
        'tokens': 15000,
        'bonus': 3000,
        'price_rub': 15000,
        'description': 'Для компаний'
    },
    'enterprise': {
        'name': '🔥 Максимум',
        'emoji': '🔥',
        'tokens': 40000,
        'bonus': 10000,
        'price_rub': 40000,
        'description': 'Безлимитные возможности'
    }
}


@bot.message_handler(func=lambda message: message.text == "💎 Тарифы")
def show_tariffs(message):
    """Показать тарифы и пакеты токенов"""
    user_id = message.from_user.id
    
    # Получаем текущий баланс
    user = db.get_user(user_id)
    current_tokens = user.get('tokens', 0) if user else 0
    
    text = (
        "💎 <b>ПАКЕТЫ ТОКЕНОВ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🎁 <b>При первом входе:</b> 1500 токенов в подарок!\n\n"
    )
    
    # Показываем все пакеты
    for key, pkg in TOKEN_PACKAGES.items():
        emoji = pkg['emoji']
        name = pkg['name']
        tokens = pkg['tokens']
        bonus = pkg['bonus']
        price = pkg['price_rub']
        total = tokens + bonus
        
        text += (
            f"{emoji} <b>{name}</b>\n"
            f"💰 Цена: <b>{price}₽</b>\n"
            f"💎 Токенов: <code>{tokens:,}</code>"
        )
        
        if bonus > 0:
            text += f" + <code>{bonus:,}</code> бонус"
        
        text += (
            f"\n"
            f"📦 Итого: <code>{total:,}</code> 💎\n\n"
        )
    
    # Примеры использования
    text += (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📋 <b>ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ:</b>\n\n"
        "✍️ Генерация текста (100 слов) — <code>10</code> 💎\n"
        "🎨 Генерация изображения — <code>30</code> 💎\n"
        "🔧 Технический аудит — <code>50</code> 💎\n"
        "💬 SEO-консультация (100 слов) — <code>10</code> 💎\n"
        "🔑 Подбор ключевого слова — <code>1</code> 💎\n\n"
        "💡 Полный список: /actions\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 <b>Важно:</b> 1 токен = 1 рубль при покупке пакета"
    )
    
    # Кнопки
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💳 Пополнить баланс", callback_data="topup_balance")
    )
    
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')


@bot.callback_query_handler(func=lambda call: call.data == "topup_balance")
def handle_topup_balance(call):
    """Меню пополнения баланса"""
    user_id = call.from_user.id
    
    text = (
        "💳 <b>ПОПОЛНЕНИЕ БАЛАНСА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Выберите пакет токенов:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    # Кнопки для каждого пакета
    for key, pkg in TOKEN_PACKAGES.items():
        emoji = pkg['emoji']
        name = pkg['name'].replace(emoji + ' ', '')
        tokens = pkg['tokens']
        bonus = pkg['bonus']
        price = pkg['price_rub']
        total = tokens + bonus
        
        btn_text = f"{emoji} {name} — {total:,} 💎 за {price}₽"
        markup.add(
            types.InlineKeyboardButton(btn_text, callback_data=f"buy_package_{key}")
        )
    
    markup.add(
        types.InlineKeyboardButton("◀️ Назад к тарифам", callback_data="back_to_tariffs")
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


@bot.callback_query_handler(func=lambda call: call.data == "buy_tokens")
def handle_buy_tokens(call):
    """Алиас для buy_tokens - перенаправляем на пополнение"""
    handle_topup_balance(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_package_"))
def handle_buy_package(call):
    """Обработка покупки пакета"""
    package_key = call.data.split("_")[-1]
    user_id = call.from_user.id
    
    # Проверяем что пакет существует
    if package_key not in TOKEN_PACKAGES:
        safe_answer_callback(bot, call.id, "❌ Пакет не найден", show_alert=True)
        return
    
    pkg = TOKEN_PACKAGES[package_key]
    
    text = (
        "💳 <b>ОПЛАТА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 <b>Пакет:</b> {pkg['name']}\n"
        f"💎 <b>Токенов:</b> {pkg['tokens']:,}"
    )
    
    if pkg['bonus'] > 0:
        text += f" + {pkg['bonus']:,} бонус"
        text += (
            f"\n\n"
            f"🎁 <b>БОНУС!</b> Вы получите <code>{pkg['tokens'] + pkg['bonus']:,}</code> токенов\n"
        )
    
    text += (
        f"\n"
        f"💰 <b>Итого к оплате:</b> <b>{pkg['price_rub']}₽</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚠️ <b>ОЖИДАЕТ ОПЛАТЫ</b>\n\n"
        "Платёжная система находится в разработке.\n\n"
        "Для оплаты обратитесь к администратору:\n"
        "👉 Используйте кнопку \"👤 Профиль\" → \"💬 Поддержка\""
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("◀️ Назад", callback_data="topup_balance")
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


@bot.callback_query_handler(func=lambda call: call.data == "back_to_tariffs")
def back_to_tariffs(call):
    """Возврат к меню тарифов"""
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    # Создаем фейковое сообщение для вызова show_tariffs
    fake_msg = type('obj', (object,), {
        'from_user': type('obj', (object,), {'id': call.from_user.id})(),
        'chat': type('obj', (object,), {'id': call.message.chat.id})(),
        'text': '💎 Тарифы'
    })()
    
    show_tariffs(fake_msg)
    safe_answer_callback(bot, call.id)


@bot.message_handler(commands=['actions'])
def show_actions_cost(message):
    """Показать стоимость всех действий"""
    text = (
        "📋 <b>СТОИМОСТЬ ДЕЙСТВИЙ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "⚡ <b>ГЕНЕРАЦИЯ КОНТЕНТА:</b>\n"
        "✍️ Текст (100 слов) — <code>10</code> 💎\n"
        "🎨 AI-изображение — <code>30</code> 💎\n\n"
        
        "🔧 <b>АУДИТ И АНАЛИЗ:</b>\n"
        "🔍 Анализ фото — <code>10</code> 💎\n"
        "✨ Извлечение стиля из фото — <code>15</code> 💎\n"
        "🛠 Технический аудит — <code>50</code> 💎\n"
        "🌐 SEO-аудит страницы — <code>50</code> 💎\n"
        "📊 SEO-аудит сайта — <code>100</code> 💎\n\n"
        
        "🔑 <b>КЛЮЧЕВЫЕ СЛОВА:</b>\n"
        "• 1 ключевое слово — <code>1</code> 💎\n"
        "• 50 ключевых слов — <code>50</code> 💎\n"
        "• 100 ключевых слов — <code>100</code> 💎\n\n"
        
        "💬 <b>SEO-КОНСУЛЬТАЦИЯ:</b>\n"
        "• 100 слов — <code>10</code> 💎\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💡 <b>Важно:</b> 1 токен = 1 рубль при покупке пакета\n\n"
        "Вернуться: 💎 Тарифы"
    )
    
    bot.send_message(message.chat.id, text, parse_mode='HTML')


print("✅ handlers/tariffs.py загружен")
