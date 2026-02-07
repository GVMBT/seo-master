"""
Карточка бота - просмотр информации и управление
"""
from telebot import types
from loader import bot
from database.database import db
from utils import escape_html, safe_answer_callback
import json


@bot.callback_query_handler(func=lambda call: call.data.startswith("open_bot_"))
def handle_open_bot(call):
    """Открытие карточки бота"""
    bot_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    # Получаем бота из БД
    bot_data = db.get_bot(bot_id)
    
    if not bot_data:
        safe_answer_callback(bot, call.id, "❌ Бот не найден")
        return
    
    # Проверяем что бот принадлежит пользователю
    if bot_data['user_id'] != user_id:
        safe_answer_callback(bot, call.id, "❌ Нет доступа")
        return
    
    bot_name = bot_data['name']
    company_data = bot_data.get('company_data', {})
    
    # Получаем категории
    categories = db.get_bot_categories(bot_id)
    cat_count = len(categories) if categories else 0
    
    # Формируем текст карточки
    text = (
        f"🤖 <b>БОТ: {escape_html(bot_name)}</b>\n"
        "━━━━━━━━━━━━━━\n\n"
    )
    
    # Показываем основную информацию о компании
    if company_data:
        text += "<b>📋 ДАННЫЕ КОМПАНИИ:</b>\n"
        
        if company_data.get('company_name'):
            text += f"🏢 Компания: {escape_html(company_data['company_name'])}\n"
        if company_data.get('city'):
            text += f"🏙 Город: {escape_html(company_data['city'])}\n"
        if company_data.get('phone'):
            text += f"📞 Телефон: {escape_html(company_data['phone'])}\n"
        if company_data.get('email'):
            text += f"📧 Email: {escape_html(company_data['email'])}\n"
        
        # Социальные сети
        socials = []
        if company_data.get('instagram'):
            socials.append('Instagram')
        if company_data.get('vk'):
            socials.append('ВК')
        if company_data.get('pinterest'):
            socials.append('Pinterest')
        if company_data.get('telegram'):
            socials.append('Telegram')
        
        if socials:
            text += f"📱 Соцсети: {', '.join(socials)}\n"
        
        text += "\n"
    
    # Показываем статистику
    text += "<b>📊 СТАТИСТИКА:</b>\n"
    text += f"📂 Категорий: {cat_count}\n"
    
    # Создаем клавиатуру
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Редактирование данных компании
    markup.add(
        types.InlineKeyboardButton("📝 Редактировать данные", callback_data=f"edit_bot_info_{bot_id}")
    )
    
    # Основные действия
    if cat_count > 0:
        markup.add(
            types.InlineKeyboardButton("📂 Управление категориями", callback_data=f"manage_categories_{bot_id}")
        )
    
    markup.add(
        types.InlineKeyboardButton("➕ Создать категорию", callback_data=f"create_category_{bot_id}")
    )
    
    # Настройки и планировщик
    markup.add(
        types.InlineKeyboardButton("⚙️ Настройки бота", callback_data=f"bot_settings_{bot_id}")
    )
    markup.add(
        types.InlineKeyboardButton("📅 Планировщик публикаций", callback_data=f"global_scheduler_{bot_id}")
    )
    
    # Удаление и возврат
    markup.add(
        types.InlineKeyboardButton("🗑 Удалить бота", callback_data=f"delete_bot_{bot_id}")
    )
    markup.add(
        types.InlineKeyboardButton("🔙 К списку ботов", callback_data="show_projects")
    )
    
    # Отправляем или обновляем сообщение
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='HTML',
            disable_web_page_preview=True  # Отключаем превью ссылок!
        )
    except Exception:
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        bot.send_message(
            call.message.chat.id,
            text,
            reply_markup=markup,
            parse_mode='HTML',
            disable_web_page_preview=True  # Отключаем превью ссылок!
        )
    
    safe_answer_callback(bot, call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("bot_settings_"))
def handle_bot_settings(call):
    """Настройки бота"""
    bot_id = int(call.data.split("_")[-1])
    
    bot_data = db.get_bot(bot_id)
    if not bot_data:
        safe_answer_callback(bot, call.id, "❌ Бот не найден")
        return
    
    bot_name = bot_data['name']
    company_data = bot_data.get('company_data', {})
    
    # Подсчитываем заполненные поля
    filled_fields = len([v for v in company_data.values() if v])
    total_fields = 15  # Всего вопросов в опросе
    
    text = (
        f"⚙️ <b>НАСТРОЙКИ БОТА</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"🤖 <b>Название:</b> {escape_html(bot_name)}\n"
        f"📊 <b>Заполнено:</b> {filled_fields}/{total_fields} полей\n\n"
        "<b>Что вы хотите сделать?</b>"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📝 Редактировать данные компании", callback_data=f"edit_company_data_{bot_id}"),
        types.InlineKeyboardButton("🔄 Переименовать бота", callback_data=f"rename_bot_{bot_id}"),
        types.InlineKeyboardButton("🔙 Назад к боту", callback_data=f"open_bot_{bot_id}")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_bot_"))
def handle_delete_bot_confirm(call):
    """Подтверждение удаления бота"""
    bot_id = int(call.data.split("_")[-1])
    
    bot_data = db.get_bot(bot_id)
    if not bot_data:
        safe_answer_callback(bot, call.id, "❌ Бот не найден")
        return
    
    bot_name = bot_data['name']
    
    text = (
        f"⚠️ <b>УДАЛЕНИЕ БОТА</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"Вы действительно хотите удалить бота <b>{escape_html(bot_name)}</b>?\n\n"
        "🗑 Будут удалены:\n"
        "• Все категории\n"
        "• Все данные компании\n"
        "• Вся статистика\n\n"
        "<b>Это действие нельзя отменить!</b>"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_bot_{bot_id}"),
        types.InlineKeyboardButton("❌ Отмена", callback_data=f"open_bot_{bot_id}")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_delete_bot_"))
def handle_delete_bot_execute(call):
    """Выполнение удаления бота"""
    bot_id = int(call.data.split("_")[-1])
    
    # Удаляем бота
    if db.delete_bot(bot_id):
        text = (
            "✅ <b>БОТ УДАЛЕН</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Бот и все связанные данные успешно удалены."
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📁 К списку ботов", callback_data="show_projects"))
        
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
        
        safe_answer_callback(bot, call.id, "✅ Удалено")
    else:
        safe_answer_callback(bot, call.id, "❌ Ошибка удаления", show_alert=True)


print("✅ handlers/bot_card.py загружен")


# ═══════════════════════════════════════════════════════════════
# РЕДАКТИРОВАНИЕ ДАННЫХ КОМПАНИИ
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_bot_info_"))
def edit_bot_info_menu(call):
    """Меню редактирования данных компании"""
    bot_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    # Очищаем обработчик если был
    try:
        bot.clear_step_handler_by_chat_id(call.message.chat.id)
    except Exception:
        pass
    
    bot_data = db.get_bot(bot_id)
    
    if not bot_data or bot_data['user_id'] != user_id:
        safe_answer_callback(bot, call.id, "❌ Нет доступа")
        return
    
    company_data = bot_data.get('company_data', {})
    if isinstance(company_data, str):
        try:
            company_data = json.loads(company_data)
        except Exception:
            company_data = {}
    
    bot_name = bot_data['name']
    
    # Импортируем вопросы из bot_creation
    from handlers.bot_creation import COMPANY_QUESTIONS
    
    # Формируем список полей для редактирования
    text = (
        f"📝 <b>РЕДАКТИРОВАНИЕ: {escape_html(bot_name)}</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Выберите поле для изменения:\n\n"
    )
    
    # Показываем текущие значения
    filled_count = 0
    for q in COMPANY_QUESTIONS:
        value = company_data.get(q['key'], '')
        if value:
            filled_count += 1
            # Обрезаем длинные значения
            display_value = value if len(value) <= 30 else value[:27] + "..."
            text += f"{q['emoji']} <b>{q['title']}:</b> {escape_html(display_value)}\n"
        else:
            text += f"{q['emoji']} <b>{q['title']}:</b> <i>не указано</i>\n"
    
    text += f"\n📊 Заполнено: {filled_count}/{len(COMPANY_QUESTIONS)}"
    
    # Кнопки для каждого поля
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    for q in COMPANY_QUESTIONS:
        has_value = "✅" if company_data.get(q['key']) else "⚪️"
        markup.add(
            types.InlineKeyboardButton(
                f"{has_value} {q['emoji']} {q['title']}",
                callback_data=f"edit_field_{bot_id}_{q['key']}"
            )
        )
    
    markup.add(
        types.InlineKeyboardButton("🔙 Назад к боту", callback_data=f"open_bot_{bot_id}")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_field_"))
def edit_field_start(call):
    """Начать редактирование поля"""
    parts = call.data.split("_")
    bot_id = int(parts[2])
    field_key = "_".join(parts[3:])
    user_id = call.from_user.id
    
    bot_data = db.get_bot(bot_id)
    
    if not bot_data or bot_data['user_id'] != user_id:
        safe_answer_callback(bot, call.id, "❌ Нет доступа")
        return
    
    company_data = bot_data.get('company_data', {})
    if isinstance(company_data, str):
        try:
            company_data = json.loads(company_data)
        except Exception:
            company_data = {}
    
    # Находим вопрос
    from handlers.bot_creation import COMPANY_QUESTIONS
    
    question = next((q for q in COMPANY_QUESTIONS if q['key'] == field_key), None)
    
    if not question:
        safe_answer_callback(bot, call.id, "❌ Поле не найдено")
        return
    
    current_value = company_data.get(field_key, '')
    
    text = (
        f"✏️ <b>РЕДАКТИРОВАНИЕ ПОЛЯ</b>\n"
        f"{question['emoji']} <b>{question['title']}</b>\n"
        "━━━━━━━━━━━━━━\n\n"
    )
    
    if current_value:
        text += f"<b>Текущее значение:</b>\n{escape_html(current_value)}\n\n"
    else:
        text += "<i>Сейчас не заполнено</i>\n\n"
    
    text += "Отправьте новое значение:"
    
    markup = types.InlineKeyboardMarkup()
    
    if current_value:
        markup.add(
            types.InlineKeyboardButton("🗑 Очистить поле", callback_data=f"clear_field_{bot_id}_{field_key}")
        )
    
    markup.add(
        types.InlineKeyboardButton("❌ Отмена", callback_data=f"edit_bot_info_{bot_id}")
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
    
    # Регистрируем обработчик ответа
    bot.register_next_step_handler_by_chat_id(
        call.message.chat.id,
        save_field_value,
        bot_id,
        field_key
    )
    
    safe_answer_callback(bot, call.id, "✏️ Ожидаю новое значение...")


def save_field_value(message, bot_id, field_key):
    """Сохранить новое значение поля"""
    user_id = message.from_user.id
    new_value = message.text.strip()
    
    bot_data = db.get_bot(bot_id)
    
    if not bot_data or bot_data['user_id'] != user_id:
        bot.send_message(message.chat.id, "❌ Ошибка доступа")
        return
    
    company_data = bot_data.get('company_data', {})
    if isinstance(company_data, str):
        try:
            company_data = json.loads(company_data)
        except Exception:
            company_data = {}
    
    # Обновляем поле
    company_data[field_key] = new_value
    
    # Если это company_name - обновляем название бота
    if field_key == 'company_name':
        db.update_bot(bot_id, name=new_value, company_data=company_data)
    else:
        db.update_bot(bot_id, company_data=company_data)
    
    # Находим название поля
    from handlers.bot_creation import COMPANY_QUESTIONS
    question = next((q for q in COMPANY_QUESTIONS if q['key'] == field_key), None)
    field_title = question['title'] if question else field_key
    
    text = (
        "✅ <b>ПОЛЕ ОБНОВЛЕНО</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📝 Поле: <b>{field_title}</b>\n"
        f"✨ Новое значение: {escape_html(new_value)}"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("📝 Редактировать другие поля", callback_data=f"edit_bot_info_{bot_id}"),
        types.InlineKeyboardButton("🤖 К карточке бота", callback_data=f"open_bot_{bot_id}")
    )
    
    bot.send_message(
        message.chat.id,
        text,
        reply_markup=markup,
        parse_mode='HTML'
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("clear_field_"))
def clear_field(call):
    """Очистить поле"""
    parts = call.data.split("_")
    bot_id = int(parts[2])
    field_key = "_".join(parts[3:])
    user_id = call.from_user.id
    
    # Очищаем обработчик
    try:
        bot.clear_step_handler_by_chat_id(call.message.chat.id)
    except Exception:
        pass
    
    bot_data = db.get_bot(bot_id)
    
    if not bot_data or bot_data['user_id'] != user_id:
        safe_answer_callback(bot, call.id, "❌ Нет доступа")
        return
    
    company_data = bot_data.get('company_data', {})
    if isinstance(company_data, str):
        try:
            company_data = json.loads(company_data)
        except Exception:
            company_data = {}
    
    # Очищаем поле
    company_data[field_key] = ''
    db.update_bot(bot_id, company_data=company_data)
    
    # Возвращаемся к меню редактирования
    from handlers.bot_creation import COMPANY_QUESTIONS
    question = next((q for q in COMPANY_QUESTIONS if q['key'] == field_key), None)
    field_title = question['title'] if question else field_key
    
    safe_answer_callback(bot, call.id, f"🗑 Поле '{field_title}' очищено")
    
    # Обновляем меню
    edit_bot_info_menu(call)


# ═══════════════════════════════════════════════════════════════
# ПЕРЕИМЕНОВАНИЕ БОТА
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("rename_bot_"))
def rename_bot_start(call):
    """Начать переименование бота"""
    bot_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    bot_data = db.get_bot(bot_id)
    
    if not bot_data or bot_data['user_id'] != user_id:
        safe_answer_callback(bot, call.id, "❌ Нет доступа")
        return
    
    current_name = bot_data['name']
    
    text = (
        "🔄 <b>ПЕРЕИМЕНОВАНИЕ БОТА</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Текущее название:</b> {escape_html(current_name)}\n\n"
        "Введите новое название для бота:\n\n"
        "💡 <i>Это название проекта для вашего удобства.</i>\n\n"
        "📋 <b>Примеры:</b>\n"
        "   • Основной бот\n"
        "   • Бот для соцсетей\n"
        "   • Проект \"Акции\"\n\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("❌ Отмена", callback_data=f"bot_settings_{bot_id}")
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
    
    # Регистрируем обработчик ответа
    bot.register_next_step_handler_by_chat_id(
        call.message.chat.id,
        save_new_bot_name,
        bot_id,
        user_id
    )
    
    safe_answer_callback(bot, call.id, "🔄 Ожидаю новое название...")


def save_new_bot_name(message, bot_id, user_id):
    """Сохранить новое название бота"""
    new_name = message.text.strip()
    
    # Валидация
    if len(new_name) < 2:
        bot.send_message(
            message.chat.id,
            "⚠️ Название слишком короткое. Минимум 2 символа.",
            parse_mode='HTML'
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("🔄 Попробовать снова", callback_data=f"rename_bot_{bot_id}"),
            types.InlineKeyboardButton("❌ Отмена", callback_data=f"bot_settings_{bot_id}")
        )
        bot.send_message(
            message.chat.id,
            "Нажмите кнопку:",
            reply_markup=markup
        )
        return
    
    # Обновляем название
    db.update_bot(bot_id, name=new_name)
    
    text = (
        "✅ <b>НАЗВАНИЕ ОБНОВЛЕНО!</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🤖 <b>Новое название:</b> {escape_html(new_name)}"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("⚙️ Настройки бота", callback_data=f"bot_settings_{bot_id}"),
        types.InlineKeyboardButton("🤖 К карточке бота", callback_data=f"open_bot_{bot_id}")
    )
    
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_company_data_"))
def edit_company_data_redirect(call):
    """Редирект на редактирование данных компании"""
    bot_id = int(call.data.split("_")[-1])
    
    # Перенаправляем на существующее меню редактирования
    # Меняем callback_data чтобы использовать существующий обработчик
    call.data = f"edit_bot_info_{bot_id}"
    edit_bot_info_menu(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("toggle_platform_"))
def toggle_platform_connection(call):
    """Переключить подключение площадки к боту (подключить/отключить)"""
    parts = call.data.split("_")
    
    # Проверяем формат: toggle_platform_cat_{category_id}_{bot_id}_{platform_type}_{platform_id}
    # или старый формат: toggle_platform_{bot_id}_{platform_type}_{platform_id}
    
    if parts[2] == "cat":
        # Новый формат из категории
        category_id = int(parts[3])
        bot_id = int(parts[4])
        platform_type = parts[5]
        platform_id = "_".join(parts[6:])
        from_category = True
    else:
        # Старый формат из карточки бота
        category_id = None
        bot_id = int(parts[2])
        platform_type = parts[3]
        platform_id = "_".join(parts[4:])
        from_category = False
    
    user_id = call.from_user.id
    
    # Получаем бота
    bot_data = db.get_bot(bot_id)
    
    if not bot_data or bot_data['user_id'] != user_id:
        safe_answer_callback(bot, call.id, "❌ Нет доступа")
        return
    
    # Получаем текущие подключения бота
    bot_connections = bot_data.get('connected_platforms', {})
    if isinstance(bot_connections, str):
        try:
            bot_connections = json.loads(bot_connections)
        except Exception:
            bot_connections = {}
    
    if not isinstance(bot_connections, dict):
        bot_connections = {}
    
    # Получаем список площадок этого типа
    platforms_list = bot_connections.get(platform_type + 's', [])  # websites, pinterests, telegrams
    if not isinstance(platforms_list, list):
        platforms_list = []
    
    # Переключаем подключение
    if platform_id in platforms_list:
        # Отключаем
        platforms_list.remove(platform_id)
        action = "отключена"
        icon = "❌"
    else:
        # Подключаем
        platforms_list.append(platform_id)
        action = "подключена"
        icon = "🟢"
    
    bot_connections[platform_type + 's'] = platforms_list
    
    # Сохраняем в БД
    db.update_bot(bot_id, connected_platforms=bot_connections)
    
    # Возвращаемся туда откуда пришли
    if from_category and category_id:
        # Возвращаемся в категорию
        call.data = f"open_category_{category_id}"
        from handlers.categories import handle_open_category
        handle_open_category(call)
    else:
        # Возвращаемся в карточку бота
        call.data = f"open_bot_{bot_id}"
        handle_open_bot(call)
    
    safe_answer_callback(bot, call.id, f"{icon} Площадка {action}")


print("✅ handlers/bot_card.py (с редактированием) загружен")
