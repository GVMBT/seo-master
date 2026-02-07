"""
Обработчик настройки топиков Telegram для категорий
"""
import logging
from telebot import types
from loader import bot, db
from utils import escape_html, safe_answer_callback

logger = logging.getLogger(__name__)


@bot.callback_query_handler(func=lambda call: call.data.startswith("telegram_topics_") 
                                              and not call.data.startswith("telegram_topics_help_")
                                              and not call.data.startswith("add_telegram_topic_")
                                              and not call.data.startswith("clear_telegram_topics_"))
def telegram_topics_menu(call):
    """Меню настройки топиков Telegram"""
    parts = call.data.split("_")
    
    # Проверяем формат: telegram_topics_{category_id}_{bot_id}_{platform_id}
    if len(parts) < 4:
        safe_answer_callback(bot, call.id, "❌ Неверный формат данных")
        return
    
    try:
        category_id = int(parts[2])
        bot_id = int(parts[3])
    except (ValueError, IndexError):
        safe_answer_callback(bot, call.id, "❌ Ошибка обработки данных")
        return
    
    platform_id = "_".join(parts[4:]) if len(parts) > 4 else ""
    
    category = db.get_category(category_id)
    if not category:
        safe_answer_callback(bot, call.id, "❌ Категория не найдена")
        return
    
    # Получаем топики
    telegram_topics = category.get('telegram_topics', [])
    
    # Логируем для отладки
    logger.debug(f" Category {category_id} data:")
    print(f"   telegram_topics raw: {category.get('telegram_topics')}")
    print(f"   telegram_topics type: {type(telegram_topics)}")
    print(f"   telegram_topics value: {telegram_topics}")
    
    # КРИТИЧЕСКАЯ ПРОВЕРКА: если telegram_topics не список - сбрасываем!
    if not isinstance(telegram_topics, list):
        print(f"⚠️ WARNING: telegram_topics не список! Тип: {type(telegram_topics)}")
        print(f"⚠️ Сбрасываем в пустой список")
        telegram_topics = []
        # Сразу сохраняем правильный формат
        db.update_category(category_id, telegram_topics=[])
    
    text = (
        f"📡 <b>НАСТРОЙКА ТОПИКОВ TELEGRAM</b>\n"
        f"📂 Категория: {escape_html(category.get('name', 'Без названия'))}\n"
        "━━━━━━━━━━━━━━\n\n"
    )
    
    if telegram_topics:
        text += "📌 <b>Добавленные топики:</b>\n\n"
        for i, topic in enumerate(telegram_topics, 1):
            topic_id = topic.get('topic_id', 'N/A')
            topic_name = topic.get('topic_name', 'Без названия')
            text += f"{i}. <code>{topic_id}</code> — {escape_html(topic_name)}\n"
        text += "\n"
    else:
        text += "📭 <i>Топики не добавлены</i>\n\n"
    
    text += (
        "━━━━━━━━━━━━━━\n"
        "💡 <b>Что такое топики?</b>\n\n"
        "Топики (темы) — это разделы в Telegram группах и супергруппах.\n"
        "Бот будет публиковать посты в выбранный топик.\n\n"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    markup.add(
        types.InlineKeyboardButton(
            "➕ Добавить топик",
            callback_data=f"add_telegram_topic_{category_id}_{bot_id}_{platform_id}"
        )
    )
    
    if telegram_topics:
        markup.add(
            types.InlineKeyboardButton(
                "🗑 Удалить все топики",
                callback_data=f"clear_telegram_topics_{category_id}_{bot_id}_{platform_id}"
            )
        )
    
    markup.add(
        types.InlineKeyboardButton(
            "📖 Инструкция",
            callback_data=f"telegram_topics_help_{category_id}_{bot_id}_{platform_id}"
        )
    )
    
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_menu_{category_id}_{bot_id}_telegram_{platform_id}"
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("telegram_topics_help_"))
def telegram_topics_help(call):
    """Инструкция по настройке топиков"""
    parts = call.data.split("_")
    
    try:
        category_id = int(parts[3])
        bot_id = int(parts[4])
        platform_id = "_".join(parts[5:]) if len(parts) > 5 else ""
    except (ValueError, IndexError):
        safe_answer_callback(bot, call.id, "❌ Ошибка обработки данных")
        return
    
    text = (
        "📖 <b>КАК НАЙТИ ID ТОПИКА</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "<b>Шаг 1: Откройте топик в Telegram</b>\n"
        "• Откройте ваш канал/группу\n"
        "• Выберите нужную тему (топик)\n\n"
        
        "<b>Шаг 2: Найдите ID</b>\n"
        "• Откройте топик в Telegram Web (веб-версия)\n"
        "• Посмотрите в адресной строке URL\n"
        "• Формат: <code>t.me/c/XXXXXX/YYYY</code>\n"
        "• <b>YYYY</b> — это ID топика!\n\n"
        
        "━━━━━━━━━━━━━━\n"
        "<b>Формат записи:</b>\n"
        "<code>ID / Название топика</code>\n\n"
        
        "<b>Примеры:</b>\n"
        "• <code>6 / Кейсы и фото работ</code>\n"
        "• <code>123 / Новости компании</code>\n"
        "• <code>45 / Акции и скидки</code>\n\n"
        
        "⚠️ <b>Важно:</b>\n"
        "• Бот должен быть администратором\n"
        "• Слэш (/) обязателен между ID и названием\n"
        "• ID — это просто число\n"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"telegram_topics_{category_id}_{bot_id}_{platform_id}"
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


# Словарь для хранения состояний добавления топиков
user_states = {}


@bot.callback_query_handler(func=lambda call: call.data.startswith("add_telegram_topic_"))
def add_telegram_topic_start(call):
    """Начало добавления топика"""
    parts = call.data.split("_")
    
    try:
        category_id = int(parts[3])
        bot_id = int(parts[4])
        platform_id = "_".join(parts[5:]) if len(parts) > 5 else ""
    except (ValueError, IndexError):
        safe_answer_callback(bot, call.id, "❌ Ошибка обработки данных")
        return
    
    user_id = call.from_user.id
    
    # Сохраняем состояние
    user_states[user_id] = {
        'action': 'add_telegram_topic',
        'category_id': category_id,
        'bot_id': bot_id,
        'platform_id': platform_id
    }
    
    text = (
        "📌 <b>ДОБАВЛЕНИЕ ТОПИКОВ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Отправьте топики в формате:\n"
        "<code>ID / Название</code>\n\n"
        
        "<b>📋 Вариант 1: Один топик</b>\n"
        "<code>6 / Кейсы и фото работ</code>\n\n"
        
        "<b>📋 Вариант 2: Несколько сразу</b>\n"
        "Каждый топик с новой строки:\n"
        "<code>3 / Кейсы и фото работ\n"
        "6 / Полезные советы\n"
        "14 / Актуальное\n"
        "8 / Вдохновение</code>\n\n"
        
        "💡 ID топика можно найти в URL веб-версии Telegram"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "❌ Отмена",
            callback_data=f"telegram_topics_{category_id}_{bot_id}_{platform_id}"
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


@bot.message_handler(func=lambda message: message.from_user.id in user_states and user_states[message.from_user.id].get('action') == 'add_telegram_topic')
def add_telegram_topic_process(message):
    """Обработка ввода данных топика в формате 'ID / Название'"""
    user_id = message.from_user.id
    
    # КРИТИЧЕСКИ ВАЖНО: Сначала получаем state, потом СРАЗУ удаляем!
    state = user_states.pop(user_id, None)
    
    if not state:
        return
    
    category_id = state['category_id']
    bot_id = state['bot_id']
    platform_id = state['platform_id']
    
    # Парсим формат "ID / Название"
    input_text = message.text.strip()
    
    # Разделяем на строки (поддержка множественного ввода)
    lines = [line.strip() for line in input_text.split('\n') if line.strip()]
    
    if not lines:
        bot.send_message(
            message.chat.id,
            "❌ Пустое сообщение!"
        )
        return
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        bot.send_message(message.chat.id, "❌ Ошибка: категория не найдена")
        # Состояние уже удалено в начале функции
        return
    
    # Получаем текущие топики
    telegram_topics = category.get('telegram_topics', [])
    
    # КРИТИЧЕСКАЯ ПРОВЕРКА: если telegram_topics не список - сбрасываем!
    if not isinstance(telegram_topics, list):
        print(f"⚠️ WARNING при добавлении: telegram_topics не список! Тип: {type(telegram_topics)}")
        print(f"⚠️ Значение: {telegram_topics}")
        telegram_topics = []
    
    # Обрабатываем каждую строку
    added_topics = []
    errors = []
    
    for line_num, line in enumerate(lines, 1):
        # Проверяем наличие разделителя
        if ' / ' not in line:
            errors.append(f"Строка {line_num}: неверный формат (нужен ' / ')")
            continue
        
        # Разделяем по " / "
        parts = line.split(' / ', 1)
        
        if len(parts) != 2:
            errors.append(f"Строка {line_num}: неверный формат")
            continue
        
        topic_id_str = parts[0].strip()
        topic_name = parts[1].strip()
        
        # Проверяем ID
        try:
            topic_id = int(topic_id_str)
        except ValueError:
            errors.append(f"Строка {line_num}: ID должен быть числом")
            continue
        
        # Проверяем название
        if len(topic_name) < 2:
            errors.append(f"Строка {line_num}: название слишком короткое")
            continue
        
        if len(topic_name) > 100:
            errors.append(f"Строка {line_num}: название слишком длинное")
            continue
        
        # Проверяем что такого ID еще нет
        already_exists = False
        for topic in telegram_topics:
            if topic.get('topic_id') == topic_id:
                errors.append(f"Строка {line_num}: ID {topic_id} уже существует")
                already_exists = True
                break
        
        if already_exists:
            continue
        
        # Добавляем топик
        telegram_topics.append({
            'topic_id': topic_id,
            'topic_name': topic_name
        })
        added_topics.append(f"{topic_id} / {topic_name}")
    
    # Если ничего не добавлено
    if not added_topics:
        error_text = "❌ <b>НЕ УДАЛОСЬ ДОБАВИТЬ ТОПИКИ</b>\n\n"
        error_text += "\n".join(f"• {err}" for err in errors)
        error_text += "\n\n<b>Формат:</b> <code>ID / Название</code>"
        
        bot.send_message(
            message.chat.id,
            error_text,
            parse_mode='HTML'
        )
        return
    
    print(f"✅ Добавлено топиков: {len(added_topics)}")
    print(f"✅ Весь список топиков теперь: {telegram_topics}")
    
    # Сохраняем
    db.update_category(category_id, telegram_topics=telegram_topics)
    
    # Состояние уже удалено в начале функции!
    
    # Формируем сообщение об успехе
    text = (
        f"✅ <b>{'ТОПИК ДОБАВЛЕН' if len(added_topics) == 1 else 'ТОПИКИ ДОБАВЛЕНЫ'}!</b>\n"
        "━━━━━━━━━━━━━━\n\n"
    )
    
    for topic_str in added_topics:
        text += f"📌 <code>{escape_html(topic_str)}</code>\n"
    
    if errors:
        text += f"\n⚠️ <b>Ошибки ({len(errors)}):</b>\n"
        for err in errors[:5]:  # показываем первые 5 ошибок
            text += f"• {err}\n"
    
    text += "\nТеперь вы можете публиковать посты в эти топики!"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "🔙 К настройкам топиков",
            callback_data=f"telegram_topics_{category_id}_{bot_id}_{platform_id}"
        )
    )
    
    bot.send_message(
        message.chat.id,
        text,
        reply_markup=markup,
        parse_mode='HTML'
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("clear_telegram_topics_"))
def clear_telegram_topics(call):
    """Удаление всех топиков"""
    parts = call.data.split("_")
    
    try:
        category_id = int(parts[3])
        bot_id = int(parts[4])
        platform_id = "_".join(parts[5:]) if len(parts) > 5 else ""
    except (ValueError, IndexError):
        safe_answer_callback(bot, call.id, "❌ Ошибка обработки данных")
        return
    
    # Очищаем топики
    db.update_category(category_id, telegram_topics=[])
    
    safe_answer_callback(bot, call.id, "✅ Все топики удалены", show_alert=True)
    
    # Возвращаем в меню
    telegram_topics_menu(call)


print("✅ handlers/telegram_topics.py загружен")
