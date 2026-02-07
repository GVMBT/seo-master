"""
Обработчик создания нового бота с красивым опросом и умными подсказками
"""
from telebot import types
from loader import bot
from database.database import db
from utils import escape_html, safe_answer_callback
import json


# Вопросы опроса с подсказками и примерами
COMPANY_QUESTIONS = [
    {
        'key': 'company_name',
        'emoji': '🏢',
        'title': 'Название компании',
        'question': '<b>Как называется ваша компания?</b>',
        'hint': 'Это может быть официальное название или бренд',
        'examples': [
            'ООО "Стройком"',
            'Пекарня "Хлеб да соль"',
            'Студия красоты "Эльза"'
        ],
        'placeholder': 'Например: Кофейня "Аромат"',
        'can_skip': False,
        'validation': 'min_length:2'
    },
    {
        'key': 'city',
        'emoji': '🏙',
        'title': 'Город',
        'question': '<b>В каком городе вы работаете?</b>',
        'hint': 'Укажите основной город или несколько городов',
        'examples': [
            'Москва',
            'Санкт-Петербург',
            'Казань, Нижний Новгород'
        ],
        'placeholder': 'Например: Екатеринбург',
        'can_skip': True
    },
    {
        'key': 'address',
        'emoji': '📍',
        'title': 'Адрес',
        'question': '<b>Где вас найти?</b>',
        'hint': 'Укажите точный адрес вашего офиса или магазина',
        'examples': [
            'ул. Ленина, 25, оф. 301',
            'проспект Мира, 15',
            'ТЦ "Европа", 3 этаж'
        ],
        'placeholder': 'Например: ул. Пушкина, д. 10',
        'can_skip': True
    },
    {
        'key': 'phone',
        'emoji': '📞',
        'title': 'Телефон',
        'question': '<b>Как с вами связаться?</b>',
        'hint': 'Укажите основной номер телефона для клиентов',
        'examples': [
            '+7 (999) 123-45-67',
            '8-800-555-35-35',
            '+7 922 123 45 67'
        ],
        'placeholder': 'Например: +7 (999) 123-45-67',
        'can_skip': True
    },
    {
        'key': 'email',
        'emoji': '📧',
        'title': 'E-mail',
        'question': '<b>Ваша электронная почта</b>',
        'hint': 'Email для связи с клиентами или приема заказов',
        'examples': [
            'info@company.ru',
            'hello@mybrand.com',
            'order@shop.ru'
        ],
        'placeholder': 'Например: info@mycompany.ru',
        'can_skip': True
    },
    {
        'key': 'website',
        'emoji': '🌐',
        'title': 'Сайт',
        'question': '<b>У вас есть сайт?</b>',
        'hint': 'Укажите адрес вашего сайта или лендинга',
        'examples': [
            'https://mycompany.ru',
            'www.mybrand.com',
            'shop.ru'
        ],
        'placeholder': 'Например: mycompany.ru',
        'can_skip': True
    },
    {
        'key': 'instagram',
        'emoji': '📸',
        'title': 'Instagram',
        'question': '<b>Профиль в Instagram</b>',
        'hint': 'Ссылка на ваш бизнес-аккаунт или просто username',
        'examples': [
            '@mycompany',
            'instagram.com/mycompany',
            'https://instagram.com/mycompany'
        ],
        'placeholder': 'Например: @mybrand',
        'can_skip': True
    },
    {
        'key': 'vk',
        'emoji': '💙',
        'title': 'ВКонтакте',
        'question': '<b>Страница ВКонтакте</b>',
        'hint': 'Ссылка на группу или публичную страницу',
        'examples': [
            'vk.com/mycompany',
            'https://vk.com/mybrand',
            '@mycompany'
        ],
        'placeholder': 'Например: vk.com/mycompany',
        'can_skip': True
    },
    {
        'key': 'pinterest',
        'emoji': '📌',
        'title': 'Pinterest',
        'question': '<b>Профиль в Pinterest</b>',
        'hint': 'Если вы используете Pinterest для продвижения',
        'examples': [
            'pinterest.com/mycompany',
            'https://pinterest.com/mybrand'
        ],
        'placeholder': 'Например: pinterest.com/mybrand',
        'can_skip': True
    },
    {
        'key': 'telegram',
        'emoji': '✈️',
        'title': 'Telegram',
        'question': '<b>Telegram канал или группа</b>',
        'hint': 'Ссылка на ваш канал, группу или бота',
        'examples': [
            't.me/mycompany',
            '@mycompany',
            'https://t.me/mybrand'
        ],
        'placeholder': 'Например: @mycompany',
        'can_skip': True
    },
    {
        'key': 'specialization',
        'emoji': '💼',
        'title': 'Специализация',
        'question': '<b>Чем вы занимаетесь?</b>',
        'hint': 'Кратко опишите основной вид деятельности',
        'examples': [
            'Ремонт квартир под ключ',
            'Производство мебели на заказ',
            'Доставка еды'
        ],
        'placeholder': 'Например: Веб-разработка и дизайн',
        'can_skip': True
    },
    {
        'key': 'experience',
        'emoji': '⏰',
        'title': 'Опыт работы',
        'question': '<b>Как давно вы на рынке?</b>',
        'hint': 'Укажите опыт работы компании',
        'examples': [
            'Более 10 лет',
            '5 лет',
            'С 2015 года'
        ],
        'placeholder': 'Например: 7 лет на рынке',
        'can_skip': True
    },
    {
        'key': 'advantages',
        'emoji': '⭐️',
        'title': 'Преимущества',
        'question': '<b>Почему клиенты выбирают вас?</b>',
        'hint': 'Укажите ваши главные преимущества',
        'examples': [
            'Быстрая доставка, гарантия качества',
            'Собственное производство, низкие цены',
            'Индивидуальный подход к каждому клиенту'
        ],
        'placeholder': 'Например: Опыт 10+ лет, гарантия 5 лет',
        'can_skip': True
    },
    {
        'key': 'description',
        'emoji': '📝',
        'title': 'Описание компании',
        'question': '<b>Расскажите о вашей компании</b>',
        'hint': 'Развернутое описание: что делаете, для кого, чем отличаетесь',
        'examples': [
            'Мы занимаемся комплексным ремонтом квартир. Работаем с 2010 года. Выполнили более 500 проектов.',
            'Кофейня с авторскими напитками. Используем зерна из Бразилии и Колумбии. Уютная атмосфера для встреч.'
        ],
        'placeholder': 'Например: Студия веб-разработки. Создаем сайты и приложения для бизнеса...',
        'can_skip': True,
        'multiline': True
    }
]


# ═══════════════════════════════════════════════════════════════
# НАЧАЛО СОЗДАНИЯ БОТА
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data == "create_bot")
def start_bot_creation(call):
    """Начало создания бота с проверкой незавершенных"""
    user_id = call.from_user.id
    
    # Проверяем есть ли незавершенный бот
    bots = db.get_user_bots(user_id)
    incomplete_bot = None
    
    if bots:
        for b in bots:
            company_data = b.get('company_data', {})
            if isinstance(company_data, str):
                try:
                    company_data = json.loads(company_data)
                except Exception:
                    company_data = {}
            
            # Проверяем есть ли незаданные вопросы
            # Если не все ключи из COMPANY_QUESTIONS присутствуют в company_data - бот незавершен
            all_keys = set(q['key'] for q in COMPANY_QUESTIONS)
            existing_keys = set(company_data.keys())
            
            if not all_keys.issubset(existing_keys):
                # Есть вопросы которые не задавались - бот незавершен
                incomplete_bot = b
                break
    
    if incomplete_bot:
        # Считаем сколько заполнено
        filled = sum(1 for k, v in company_data.items() if v and v != '')
        
        text = (
            "🔄 <b>НЕЗАВЕРШЕННЫЙ ПРОЕКТ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "У вас есть незавершенный проект.\n\n"
            f"📊 Заполнено: <b>{filled} из {len(COMPANY_QUESTIONS)}</b> полей\n\n"
            "🤔 <b>Что делать?</b>\n\n"
            "<b>▶️ Продолжить</b> - продолжить заполнение с места остановки\n\n"
            "<b>🗑 Удалить</b> - удалить незавершенный и создать новый проект\n\n"
            "<i>💡 Все ваши ответы сохранены и не потеряются</i>"
        )
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("▶️ Продолжить заполнение", callback_data=f"continue_bot_{incomplete_bot['id']}"),
            types.InlineKeyboardButton("🗑 Удалить и создать новый", callback_data=f"delete_and_create_{incomplete_bot['id']}"),
            types.InlineKeyboardButton("🔙 Отмена", callback_data="show_projects")
        )
    else:
        # Спрашиваем название проекта перед созданием
        text = (
            "🎉 <b>СОЗДАНИЕ НОВОГО ПРОЕКТА</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Отлично! Сейчас я задам вам несколько вопросов о вашей компании.\n\n"
            "📝 <b>Всего вопросов:</b> 14\n"
            "⏱ <b>Займет:</b> 3-5 минут\n\n"
            "✨ <b>Что вас ждет:</b>\n"
            "• Умные подсказки и примеры\n"
            "• Можно пропустить любой вопрос\n"
            "• Прогресс автоматически сохраняется\n"
            "• Можно прервать в любой момент\n\n"
            "💡 <b>Совет:</b> Заполните хотя бы основные поля (название, контакты) - это поможет создать качественный контент для ваших площадок.\n\n"
            "<i>Готовы начать?</i>"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("▶️ Да, начнем!", callback_data="ask_bot_name"),
            types.InlineKeyboardButton("❌ Отмена", callback_data="show_projects")
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


@bot.callback_query_handler(func=lambda call: call.data == "ask_bot_name")
def ask_bot_name(call):
    """Спросить название проекта"""
    text = (
        "🏷 <b>НАЗВАНИЕ ПРОЕКТА</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "<b>Как назовем ваш проект?</b>\n\n"
        "💡 <i>Это название бота для вашего удобства.</i>\n"
        "<i>У одной компании может быть несколько проектов (ботов) с разными названиями.</i>\n\n"
        "📋 <b>Примеры:</b>\n"
        "   • Основной бот\n"
        "   • Бот для соцсетей\n"
        "   • Акции и скидки\n"
        "   • Проект \"Стройка\"\n\n"
        "✏️ Например: Мой первый проект\n\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("❌ Отмена", callback_data="show_projects")
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
        save_bot_name_and_start,
        call.from_user.id
    )
    
    safe_answer_callback(bot, call.id, "🏷 Ожидаю название...")


def save_bot_name_and_start(message, user_id):
    """Сохранить название проекта и начать опрос"""
    bot_name = message.text.strip()
    
    # Валидация
    if len(bot_name) < 2:
        bot.send_message(
            message.chat.id,
            "⚠️ Название слишком короткое. Минимум 2 символа.",
            parse_mode='HTML'
        )
        # Спрашиваем снова через callback
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("🔄 Ввести название снова", callback_data="ask_bot_name"),
            types.InlineKeyboardButton("❌ Отмена", callback_data="show_projects")
        )
        bot.send_message(
            message.chat.id,
            "Нажмите кнопку чтобы ввести название:",
            reply_markup=markup
        )
        return
    
    # Создаем бота с указанным названием (НЕ меняем его потом!)
    bot_id = db.create_bot(user_id, bot_name)
    
    if not bot_id:
        bot.send_message(message.chat.id, "❌ Ошибка создания проекта")
        return
    
    # Отправляем подтверждение
    text = (
        f"✨ <b>Проект «{escape_html(bot_name)}» создан!</b>\n\n"
        f"Теперь заполним информацию о компании.\n\n"
        f"<i>Начинаем опрос...</i>"
    )
    
    bot.send_message(message.chat.id, text, parse_mode='HTML')
    
    # Начинаем опрос
    ask_next_unanswered_question(message.chat.id, user_id, bot_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("continue_bot_"))
def continue_bot_creation(call):
    """Продолжить заполнение незавершенного бота"""
    bot_id = int(call.data.split("_")[-1])
    ask_next_unanswered_question(call.message.chat.id, call.from_user.id, bot_id)
    safe_answer_callback(bot, call.id, "▶️ Продолжаем...")


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_and_create_"))
def delete_and_create_new(call):
    """Удалить незавершенный и создать новый"""
    bot_id = int(call.data.split("_")[-1])
    db.delete_bot(bot_id)
    start_bot_creation(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_and_create_"))
def delete_and_create_new(call):
    """Удалить незавершенный и создать новый"""
    bot_id = int(call.data.split("_")[-1])
    db.delete_bot(bot_id)
    start_bot_creation(call)


# ═══════════════════════════════════════════════════════════════
# ПРОЦЕСС ЗАПОЛНЕНИЯ С КРАСИВЫМ ОФОРМЛЕНИЕМ
# ═══════════════════════════════════════════════════════════════

def ask_next_unanswered_question(chat_id, user_id, bot_id):
    """Задать следующий незаполненный вопрос с красивым оформлением"""
    bot_data = db.get_bot(bot_id)
    
    if not bot_data:
        bot.send_message(chat_id, "❌ Ошибка: проект не найден")
        return
    
    company_data = bot_data.get('company_data', {})
    if isinstance(company_data, str):
        try:
            company_data = json.loads(company_data)
        except Exception:
            company_data = {}
    
    # Ищем первый незаполненный вопрос
    # ВАЖНО: если ключ есть в company_data - значит вопрос УЖЕ задавался (пропущен или заполнен)
    current_question = None
    question_index = 0
    
    for idx, q in enumerate(COMPANY_QUESTIONS):
        if q['key'] not in company_data:
            # Вопрос НЕ задавался - задаем его
            current_question = q
            question_index = idx
            break
    
    # Если все вопросы заполнены
    if not current_question:
        finish_bot_creation(chat_id, user_id, bot_id)
        return
    
    # Считаем прогресс
    filled = sum(1 for k, v in company_data.items() if v and v != '')
    progress_bar = create_progress_bar(filled, len(COMPANY_QUESTIONS))
    progress_percent = int((filled / len(COMPANY_QUESTIONS)) * 100)
    
    # Формируем красивый текст вопроса
    text = (
        f"┏━━━━━━━━━━━━━━━━━━━━\n"
        f"┃ <b>Вопрос {question_index + 1}</b> из {len(COMPANY_QUESTIONS)}\n"
        f"┗━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{progress_bar}\n\n"
        f"{current_question['emoji']} {current_question['question']}\n\n"
    )
    
    # Добавляем подсказку
    if current_question.get('hint'):
        text += f"💡 <i>{current_question['hint']}</i>\n\n"
    
    # Добавляем примеры
    if current_question.get('examples'):
        text += "📋 <b>Примеры:</b>\n"
        for example in current_question['examples'][:3]:  # Показываем до 3 примеров
            text += f"   • <code>{escape_html(example)}</code>\n"
        text += "\n"
    
    # Добавляем placeholder
    if current_question.get('placeholder'):
        text += f"✏️ {current_question['placeholder']}\n\n"
    
    # Специальная подсказка для многострочных полей
    if current_question.get('multiline'):
        text += "📝 <i>Можете написать несколько предложений</i>\n\n"
    
    text += "━━━━━━━━━━━━━━━━━━━━"
    
    # Кнопки
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    if current_question['can_skip']:
        markup.add(
            types.InlineKeyboardButton("⏭ Пропустить", callback_data=f"skip_q_{bot_id}_{current_question['key']}"),
            types.InlineKeyboardButton("❌ Прервать", callback_data=f"cancel_creation_{bot_id}")
        )
    else:
        markup.add(
            types.InlineKeyboardButton("❌ Прервать опрос", callback_data=f"cancel_creation_{bot_id}")
        )
    
    # Отправляем вопрос
    bot.send_message(
        chat_id,
        text,
        reply_markup=markup,
        parse_mode='HTML',
        disable_web_page_preview=True
    )
    
    # Регистрируем обработчик ответа
    bot.register_next_step_handler_by_chat_id(
        chat_id,
        process_answer,
        bot_id,
        current_question['key']
    )


def create_progress_bar(current, total, length=10):
    """Создать красивый прогресс-бар из кружков"""
    # Для 14 вопросов используем специальный формат
    if total == 14:
        # Создаем строку из кружков
        circles = []
        for i in range(total):
            if i < current:
                circles.append("🟢")  # Заполненный зеленый
            else:
                circles.append("⚪️")  # Пустой белый
        
        # Разбиваем на две строки по 7 кружков
        line1 = " ".join(circles[:7])
        line2 = " ".join(circles[7:])
        
        return f"{line1}\n   {line2}"
    else:
        # Стандартный прогресс-бар для других случаев
        filled = int((current / total) * length)
        empty = length - filled
        bar = "█" * filled + "░" * empty
        return f"[{bar}]"


def process_answer(message, bot_id, question_key):
    """Обработать ответ на вопрос с валидацией"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    answer = message.text.strip()
    
    # Находим вопрос для валидации
    question = next((q for q in COMPANY_QUESTIONS if q['key'] == question_key), None)
    
    # Валидация
    if question and question.get('validation'):
        validation = question['validation']
        
        if validation.startswith('min_length:'):
            min_len = int(validation.split(':')[1])
            if len(answer) < min_len:
                bot.send_message(
                    chat_id,
                    f"⚠️ Ответ слишком короткий. Минимум {min_len} символа.",
                    parse_mode='HTML'
                )
                # Задаем вопрос снова
                ask_next_unanswered_question(chat_id, user_id, bot_id)
                return
    
    # Сохраняем ответ в БД
    bot_data = db.get_bot(bot_id)
    
    if not bot_data:
        bot.send_message(chat_id, "❌ Ошибка: проект не найден")
        return
    
    company_data = bot_data.get('company_data', {})
    if isinstance(company_data, str):
        try:
            company_data = json.loads(company_data)
        except Exception:
            company_data = {}
    
    # Обновляем данные
    company_data[question_key] = answer
    
    # Сохраняем в БД (название бота НЕ меняем!)
    db.update_bot(bot_id, company_data=company_data)
    
    # Если это первый вопрос - отправляем мотивирующее сообщение
    if question_key == 'company_name':
        bot.send_message(
            chat_id,
            f"✨ <b>Отлично!</b>\n\n"
            f"Продолжаем заполнение информации о компании...",
            parse_mode='HTML'
        )
    
    # Переходим к следующему вопросу
    ask_next_unanswered_question(chat_id, user_id, bot_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("skip_q_"))
def skip_question(call):
    """Пропустить вопрос"""
    parts = call.data.split("_")
    bot_id = int(parts[2])
    question_key = "_".join(parts[3:])
    
    # ВАЖНО: Очищаем зарегистрированный обработчик
    try:
        bot.clear_step_handler_by_chat_id(call.message.chat.id)
    except Exception:
        pass
    
    # Сохраняем пустое значение
    bot_data = db.get_bot(bot_id)
    
    if bot_data:
        company_data = bot_data.get('company_data', {})
        if isinstance(company_data, str):
            try:
                company_data = json.loads(company_data)
            except Exception:
                company_data = {}
        
        company_data[question_key] = ''
        db.update_bot(bot_id, company_data=company_data)
    
    # Удаляем сообщение
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    # Следующий вопрос
    ask_next_unanswered_question(call.message.chat.id, call.from_user.id, bot_id)
    safe_answer_callback(bot, call.id, "⏭ Пропущено")


@bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_creation_"))
def cancel_creation(call):
    """Прервать создание (бот остается в БД)"""
    bot_id = int(call.data.split("_")[-1])
    
    # ВАЖНО: Очищаем зарегистрированный обработчик
    try:
        bot.clear_step_handler_by_chat_id(call.message.chat.id)
    except Exception:
        pass
    
    bot_data = db.get_bot(bot_id)
    company_data = bot_data.get('company_data', {}) if bot_data else {}
    if isinstance(company_data, str):
        try:
            company_data = json.loads(company_data)
        except Exception:
            company_data = {}
    
    filled = sum(1 for k, v in company_data.items() if v and v != '')
    
    text = (
        "⏸ <b>СОЗДАНИЕ ПРИОСТАНОВЛЕНО</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Заполнено: <b>{filled} из {len(COMPANY_QUESTIONS)}</b> полей\n\n"
        "✅ <b>Все ваши ответы сохранены!</b>\n\n"
        "Вы можете:\n"
        "• Продолжить заполнение сейчас\n"
        "• Вернуться к этому позже\n"
        "• Редактировать ответы в любое время\n\n"
        "<i>💡 Проект не пропадет и будет ждать вас</i>"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("▶️ Продолжить заполнение", callback_data=f"continue_bot_{bot_id}"),
        types.InlineKeyboardButton("🤖 Открыть проект", callback_data=f"open_bot_{bot_id}"),
        types.InlineKeyboardButton("📁 К списку проектов", callback_data="show_projects")
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


# ═══════════════════════════════════════════════════════════════
# ЗАВЕРШЕНИЕ СОЗДАНИЯ С ПОЗДРАВЛЕНИЕМ
# ═══════════════════════════════════════════════════════════════

def finish_bot_creation(chat_id, user_id, bot_id):
    """Завершить создание бота с красивым поздравлением"""
    bot_data = db.get_bot(bot_id)
    
    if not bot_data:
        bot.send_message(chat_id, "❌ Ошибка: проект не найден")
        return
    
    company_data = bot_data.get('company_data', {})
    if isinstance(company_data, str):
        try:
            company_data = json.loads(company_data)
        except Exception:
            company_data = {}
    
    bot_name = bot_data.get('name', 'Новый проект')
    
    # Подсчитываем заполненные поля
    filled = sum(1 for k, v in company_data.items() if v and v != '')
    total = len(COMPANY_QUESTIONS)
    percent = int((filled / total) * 100)
    
    # Определяем уровень заполненности
    if percent >= 80:
        emoji = "🎉"
        status = "Отлично!"
        comment = "Ваш проект заполнен максимально полно!"
    elif percent >= 50:
        emoji = "👍"
        status = "Хорошо!"
        comment = "Достаточно информации для старта."
    else:
        emoji = "✅"
        status = "Готово!"
        comment = "Рекомендуем заполнить больше полей позже."
    
    # Создаем визуальный прогресс из кружков
    progress_circles = []
    for i in range(total):
        if i < filled:
            progress_circles.append("🟢")
        else:
            progress_circles.append("⚪️")
    
    # Разбиваем на 2 строки по 7 кружков
    line1 = " ".join(progress_circles[:7])
    line2 = " ".join(progress_circles[7:])
    progress_visual = f"   {line1}\n   {line2}"
    
    text = (
        f"{emoji} <b>{status.upper()}</b>\n"
        f"<b>ПРОЕКТ «{escape_html(bot_name)}» СОЗДАН!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>Заполнено:</b> {filled} из {total} полей ({percent}%)\n\n"
        f"{progress_visual}\n\n"
        f"💬 <i>{comment}</i>\n\n"
        "🎯 <b>Что дальше?</b>\n\n"
        "✨ <b>Создайте категории</b>\n"
        "   Добавьте товары или услуги\n\n"
        "🔑 <b>Сгенерируйте ключевые фразы</b>\n"
        "   AI подберет SEO-запросы\n\n"
        "📝 <b>Создайте контент</b>\n"
        "   Описания с помощью Claude AI\n\n"
        "🖼 <b>Добавьте изображения</b>\n"
        "   Загрузите или сгенерируйте с Nano Banana Pro\n\n"
        "🔌 <b>Подключите площадки</b>\n"
        "   Настройте автопостинг\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<i>💡 Совет: начните с создания категорий</i>"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(f"🚀 Открыть {bot_name}", callback_data=f"open_bot_{bot_id}"),
        types.InlineKeyboardButton("📝 Дополнить информацию", callback_data=f"edit_bot_info_{bot_id}"),
        types.InlineKeyboardButton("📁 К списку проектов", callback_data="show_projects")
    )
    
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')


print("✅ handlers/bot_creation.py (с красивым опросом) загружен")
