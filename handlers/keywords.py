"""
Обработчик подбора ключевых фраз для категории
"""
from telebot import types
from loader import bot
from database.database import db
from utils import escape_html, safe_answer_callback
from config import TOKEN_PRICES
import json
from datetime import datetime


# Состояния опроса для ключевых фраз (временное хранилище)
keywords_state = {}


def save_survey_answers_permanent(user_id, category_id, answers):
    """Сохранить ответы опроса НАВСЕГДА в категорию"""
    try:
        if not answers or not isinstance(answers, dict):
            print(f"⚠️ Нет ответов для сохранения")
            return False
        
        print(f"💾 Сохранение ответов опроса НАВСЕГДА для категории {category_id}")
        print(f"   Ответов: {len(answers)}")
        
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            print(f"⚠️ Категория {category_id} не найдена")
            return False
        
        # Получаем текущий media
        current_media = category.get('media', [])
        
        # Если media - список, преобразуем в словарь
        if isinstance(current_media, list):
            current_media = {'items': current_media}
        elif not isinstance(current_media, dict):
            current_media = {}
        
        # Сохраняем ответы в отдельное ПОСТОЯННОЕ поле
        current_media['survey_answers'] = answers
        current_media['survey_completed_at'] = datetime.now().isoformat()
        
        # Сохраняем
        json_string = json.dumps(current_media, ensure_ascii=False)
        json.loads(json_string)  # Проверка валидности
        
        db.cursor.execute(
            """
            UPDATE categories 
            SET media = %s::jsonb
            WHERE id = %s
            """,
            (json_string, category_id)
        )
        db.conn.commit()
        print(f"✅ Ответы опроса сохранены НАВСЕГДА")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка сохранения ответов: {e}")
        import traceback
        traceback.print_exc()
        
        try:
            db.conn.rollback()
        except Exception:
            pass
        
        return False


def load_survey_answers_permanent(user_id, category_id):
    """Загрузить постоянные ответы опроса"""
    try:
        category = db.get_category(category_id)
        if not category:
            return None
        
        media = category.get('media')
        
        if isinstance(media, dict) and 'survey_answers' in media:
            answers = media['survey_answers']
            if answers and isinstance(answers, dict):
                print(f"📂 Загружены постоянные ответы для категории {category_id}")
                print(f"   Ответов: {len(answers)}")
                return answers
        
        return None
        
    except Exception as e:
        print(f"❌ Ошибка загрузки ответов: {e}")
        return None


def save_survey_state(user_id, category_id, state_data):
    """Сохранить состояние опроса в БД"""
    try:
        # Проверяем что state_data валидный
        if not state_data or not isinstance(state_data, dict):
            print(f"⚠️ Невалидные данные состояния для категории {category_id}")
            print(f"   Тип данных: {type(state_data)}")
            return False
        
        # Очищаем state_data от несериализуемых объектов
        clean_state = {
            'category_id': state_data.get('category_id'),
            'step': state_data.get('step'),
            'question_index': state_data.get('question_index', 0),
            'answers': state_data.get('answers', {})
            # НЕ сохраняем last_message_id и другие временные данные
        }
        
        # Логируем что сохраняем
        print(f"💾 Сохранение состояния для категории {category_id}")
        print(f"   Вопрос: {clean_state['question_index']}/{len(KEYWORDS_QUESTIONS)}")
        print(f"   Ответов: {len(clean_state['answers'])}")
        
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            print(f"⚠️ Категория {category_id} не найдена")
            return False
        
        # Получаем текущий media
        current_media = category.get('media', [])
        
        # Если media - список, преобразуем в словарь
        if isinstance(current_media, list):
            current_media = {'items': current_media}
        elif not isinstance(current_media, dict):
            current_media = {}
        
        # Добавляем состояние опроса
        current_media['survey_state'] = clean_state
        
        # ВАЖНО: json.dumps превращает dict в JSON-строку
        json_string = json.dumps(current_media, ensure_ascii=False)
        
        # Проверяем что JSON валидный
        json.loads(json_string)  # Тест десериализации
        
        # Сохраняем (::jsonb превращает JSON-строку в JSONB)
        db.cursor.execute(
            """
            UPDATE categories 
            SET media = %s::jsonb
            WHERE id = %s
            """,
            (json_string, category_id)
        )
        db.conn.commit()
        print(f"✅ Состояние опроса успешно сохранено")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка сохранения состояния: {e}")
        import traceback
        traceback.print_exc()
        
        # ВАЖНО: откатываем транзакцию
        try:
            db.conn.rollback()
            print(f"🔄 Транзакция откачена")
        except Exception as rollback_error:
            print(f"⚠️ Ошибка отката: {rollback_error}")
        
        return False


def load_survey_state(user_id, category_id):
    """Загрузить состояние опроса из БД"""
    try:
        category = db.get_category(category_id)
        if not category:
            print(f"⚠️ Категория {category_id} не найдена")
            return None
        
        # Получаем media
        media = category.get('media')
        
        # Проверяем что media - это словарь и есть survey_state
        if isinstance(media, dict) and 'survey_state' in media:
            state_data = media['survey_state']
            if state_data and isinstance(state_data, dict):
                print(f"📂 Состояние опроса загружено для категории {category_id}")
                print(f"   Прогресс: вопрос {state_data.get('question_index', 0)}/{len(KEYWORDS_QUESTIONS)}")
                return state_data
        
        print(f"⚠️ Состояние опроса не найдено для категории {category_id}")
        return None
        
    except Exception as e:
        print(f"❌ Ошибка загрузки состояния: {e}")
        # Откатываем транзакцию если есть ошибка
        try:
            db.conn.rollback()
        except Exception:
            pass
        return None


def clear_survey_state(user_id, category_id):
    """Очистить сохраненное состояние опроса"""
    try:
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            return False
        
        # Получаем текущий media
        current_media = category.get('media')
        
        # Если media - словарь и есть survey_state
        if isinstance(current_media, dict) and 'survey_state' in current_media:
            # Удаляем survey_state
            del current_media['survey_state']
            
            # Сохраняем обратно
            db.cursor.execute(
                """
                UPDATE categories 
                SET media = %s::jsonb
                WHERE id = %s
                """,
                (json.dumps(current_media), category_id)
            )
            db.conn.commit()
            print(f"🧹 Состояние опроса очищено для категории {category_id}")
            return True
        else:
            print(f"⚠️ Нечего очищать для категории {category_id}")
            return True
            
    except Exception as e:
        print(f"⚠️ Ошибка очистки состояния: {e}")
        # Откатываем транзакцию
        try:
            db.conn.rollback()
        except Exception:
            pass
        return False


# Вопросы опроса для подбора ключевых фраз (СОКРАЩЕНО ДО 2)
KEYWORDS_QUESTIONS = [
    {
        'key': 'products_services',
        'question': (
            '🛍 <b>1. КАКИЕ ТОВАРЫ ИЛИ УСЛУГИ ВЫ ПРОДАЁТЕ?</b>\n\n'
            'Опишите максимально подробно, что именно вы предлагаете.\n\n'
            '<i>Например: "Интерьерные стеновые панели WPC 8мм и 5мм" или '
            '"Натяжные потолки: тканевые и ПВХ" или '
            '"Ремонт квартир под ключ, отделка, дизайн"</i>\n\n'
            '💡 <b>Это обязательный вопрос</b>'
        ),
        'can_skip': False
    },
    {
        'key': 'geography',
        'question': (
            '🌍 <b>2. ГДЕ ВЫ РАБОТАЕТЕ ГЕОГРАФИЧЕСКИ?</b>\n\n'
            'Укажите города, регионы или страны.\n\n'
            '<i>Например: "Москва и МО", "Вся Россия", '
            '"Санкт-Петербург", "Краснодар и Краснодарский край"</i>\n\n'
            '💡 <b>Это обязательный вопрос</b>'
        ),
        'can_skip': False
    }
]


@bot.callback_query_handler(func=lambda call: call.data.startswith("category_keywords_"))
def handle_category_keywords(call):
    """Начало работы с ключевыми фразами"""
    category_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        safe_answer_callback(bot, call.id, "❌ Категория не найдена")
        return
    
    # Проверяем доступ
    bot_data = db.get_bot(category['bot_id'])
    if not bot_data or bot_data['user_id'] != user_id:
        safe_answer_callback(bot, call.id, "❌ Ошибка доступа")
        return
    
    category_name = category.get('name', 'Без названия')
    existing_keywords = category.get('keywords', [])
    
    # Если ключевые фразы уже есть - показываем их
    if existing_keywords:
        show_existing_keywords(call, category_id, category_name, existing_keywords)
        return
    
    # Если нет - предлагаем подобрать
    text = (
        f"🔑 <b>КЛЮЧЕВЫЕ ФРАЗЫ</b>\n"
        f"📂 Категория: {escape_html(category_name)}\n"
        "━━━━━━━━━━━━━━\n\n"
        "У вас пока нет ключевых фраз для этой категории.\n\n"
        "🤖 <b>Я помогу подобрать ключевые фразы с помощью AI!</b>\n\n"
        "Процесс займёт несколько минут:\n"
        "1️⃣ Ответите на 6 вопросов о бизнесе\n"
        "2️⃣ AI подберет релевантные ключевые фразы\n"
        "3️⃣ Вы сможете выбрать количество: 50/100/150/200\n\n"
        "💰 <b>Стоимость:</b>\n"
        "• 50 фраз - 50 токенов\n"
        "• 100 фраз - 100 токенов\n"
        "• 150 фраз - 150 токенов\n"
        "• 200 фраз - 200 токенов\n\n"
        "👇 Готовы начать?"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✅ Начать подбор", callback_data=f"start_keywords_survey_{category_id}"),
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"open_category_{category_id}")
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


def show_existing_keywords(call, category_id, category_name, keywords):
    """Показать существующие ключевые фразы"""
    user_id = call.from_user.id
    keywords_count = len(keywords) if isinstance(keywords, list) else 0
    
    # Показываем первые 10 фраз
    keywords_preview = keywords[:10] if isinstance(keywords, list) else []
    keywords_text = '\n'.join([f"• {escape_html(kw)}" for kw in keywords_preview])
    
    if keywords_count > 10:
        keywords_text += f"\n<i>... и ещё {keywords_count - 10} фраз</i>"
    
    # Проверяем есть ли сохраненные ответы опроса
    saved_answers = load_survey_answers_permanent(user_id, category_id)
    
    text = (
        f"🔑 <b>КЛЮЧЕВЫЕ ФРАЗЫ</b>\n"
        f"📂 Категория: {escape_html(category_name)}\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📊 Всего фраз: <b>{keywords_count}</b>\n\n"
        f"{keywords_text}\n\n"
    )
    
    if saved_answers:
        text += "✅ <i>Ответы на опрос сохранены</i>\n\n"
    
    text += "👇 Выберите действие:"
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📋 Посмотреть все фразы", callback_data=f"view_all_keywords_{category_id}"),
        types.InlineKeyboardButton("➕ Добавить ещё фразы", callback_data=f"start_keywords_survey_{category_id}")
    )
    
    # Кнопки скачивания/загрузки
    if keywords_count > 0:
        markup.add(
            types.InlineKeyboardButton("💾 Скачать фразы (TXT)", callback_data=f"download_keywords_{category_id}")
        )
    
    markup.add(
        types.InlineKeyboardButton("📤 Загрузить свои фразы", callback_data=f"upload_keywords_{category_id}")
    )
    
    # Если есть сохраненные ответы - добавляем кнопку редактирования
    if saved_answers:
        markup.add(
            types.InlineKeyboardButton("✏️ Изменить ответы на опрос", callback_data=f"edit_survey_answers_{category_id}")
        )
    
    markup.add(
        types.InlineKeyboardButton("🗑 Удалить все фразы", callback_data=f"delete_keywords_{category_id}"),
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"open_category_{category_id}")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("view_all_keywords_"))
def handle_view_all_keywords(call):
    """Просмотр всех ключевых фраз"""
    category_id = int(call.data.split("_")[-1])
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
        return
    
    keywords = category.get('keywords', [])
    if not keywords or not isinstance(keywords, list):
        safe_answer_callback(bot, call.id, "❌ Нет ключевых фраз", show_alert=True)
        return
    
    category_name = category.get('name', 'Без названия')
    
    # Формируем текст со всеми фразами
    text = (
        f"🔑 <b>ВСЕ КЛЮЧЕВЫЕ ФРАЗЫ</b>\n"
        f"📂 Категория: {escape_html(category_name)}\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📊 Всего: <b>{len(keywords)}</b> фраз\n\n"
    )
    
    # Добавляем все фразы с нумерацией
    for i, kw in enumerate(keywords, 1):
        text += f"{i}. {escape_html(kw)}\n"
    
    text += "\n━━━━━━━━━━━━━━"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"category_keywords_{category_id}")
    )
    
    # Удаляем предыдущее сообщение
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    # Отправляем новое (может быть очень длинным)
    try:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    except Exception as e:
        # Если слишком длинное - разбиваем на части
        if "message is too long" in str(e).lower():
            # Отправляем первые 50 фраз
            short_text = (
                f"🔑 <b>КЛЮЧЕВЫЕ ФРАЗЫ (первые 50)</b>\n"
                f"📂 Категория: {escape_html(category_name)}\n"
                "━━━━━━━━━━━━━━\n\n"
                f"📊 Всего: <b>{len(keywords)}</b> фраз\n\n"
            )
            for i, kw in enumerate(keywords[:50], 1):
                short_text += f"{i}. {escape_html(kw)}\n"
            
            short_text += f"\n<i>... и ещё {len(keywords) - 50} фраз</i>\n\n━━━━━━━━━━━━━━"
            
            bot.send_message(call.message.chat.id, short_text, reply_markup=markup, parse_mode='HTML')
        else:
            safe_answer_callback(bot, call.id, f"❌ Ошибка: {e}", show_alert=True)
    
    safe_answer_callback(bot, call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_keywords_"))
def handle_delete_keywords(call):
    """Удаление всех ключевых фраз"""
    category_id = int(call.data.split("_")[-1])
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
        return
    
    category_name = category.get('name', 'Без названия')
    keywords = category.get('keywords', [])
    keywords_count = len(keywords) if isinstance(keywords, list) else 0
    
    # Подтверждение удаления
    text = (
        f"🗑 <b>УДАЛЕНИЕ КЛЮЧЕВЫХ ФРАЗ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📂 Категория: {escape_html(category_name)}\n"
        f"🔑 Фраз: <b>{keywords_count}</b>\n\n"
        "⚠️ <b>Вы уверены?</b>\n"
        "Все ключевые фразы будут удалены безвозвратно!"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_keywords_{category_id}"),
        types.InlineKeyboardButton("❌ Отмена", callback_data=f"category_keywords_{category_id}")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_delete_keywords_"))
def handle_confirm_delete_keywords(call):
    """Подтверждение удаления ключевых фраз"""
    category_id = int(call.data.split("_")[-1])
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
        return
    
    category_name = category.get('name', 'Без названия')
    
    # Удаляем ключевые фразы
    try:
        db.cursor.execute("""
            UPDATE categories 
            SET keywords = '[]'::jsonb
            WHERE id = %s
        """, (category_id,))
        db.conn.commit()
        
        text = (
            "✅ <b>КЛЮЧЕВЫЕ ФРАЗЫ УДАЛЕНЫ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"📂 Категория: {escape_html(category_name)}\n\n"
            "Все ключевые фразы успешно удалены."
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("🔙 К категории", callback_data=f"open_category_{category_id}")
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
        
        safe_answer_callback(bot, call.id, "✅ Удалено")
        
    except Exception as e:
        print(f"❌ Ошибка удаления ключевых фраз: {e}")
        safe_answer_callback(bot, call.id, "❌ Ошибка удаления", show_alert=True)
        try:
            db.conn.rollback()
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("download_keywords_"))
def handle_download_keywords(call):
    """Скачивание ключевых фраз в TXT"""
    category_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
        return
    
    keywords = category.get('keywords', [])
    if not keywords or not isinstance(keywords, list):
        safe_answer_callback(bot, call.id, "❌ Нет ключевых фраз", show_alert=True)
        return
    
    category_name = category.get('name', 'keywords')
    
    # Создаём TXT файл
    import tempfile
    import os
    from datetime import datetime
    
    try:
        # Создаём временный файл
        fd, filepath = tempfile.mkstemp(suffix='.txt', prefix='keywords_')
        
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(f"# Ключевые фразы\n")
            f.write(f"# Категория: {category_name}\n")
            f.write(f"# Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Всего фраз: {len(keywords)}\n")
            f.write(f"#\n")
            f.write(f"# Формат: одна фраза на строку\n")
            f.write(f"#{'=' * 50}\n\n")
            
            for keyword in keywords:
                f.write(f"{keyword}\n")
        
        # Отправляем файл
        with open(filepath, 'rb') as f:
            filename = f"keywords_{category_name.replace(' ', '_')}.txt"
            bot.send_document(
                call.message.chat.id,
                f,
                caption=f"🔑 Ключевые фразы: {category_name}\n📊 Всего: {len(keywords)} фраз",
                visible_file_name=filename
            )
        
        # Удаляем временный файл
        os.unlink(filepath)
        
        safe_answer_callback(bot, call.id, "✅ Файл отправлен")
        
    except Exception as e:
        print(f"❌ Ошибка создания файла: {e}")
        safe_answer_callback(bot, call.id, "❌ Ошибка создания файла", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith("upload_keywords_"))
def handle_upload_keywords(call):
    """Инструкция по загрузке ключевых фраз"""
    category_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
        return
    
    category_name = category.get('name', 'Без названия')
    
    # Устанавливаем состояние ожидания файла
    keywords_state[user_id] = {
        'category_id': category_id,
        'step': 'waiting_file'
    }
    
    text = (
        f"📤 <b>ЗАГРУЗКА КЛЮЧЕВЫХ ФРАЗ</b>\n"
        f"📂 Категория: {escape_html(category_name)}\n"
        "━━━━━━━━━━━━━━\n\n"
        "📝 <b>Формат файла:</b>\n"
        "• TXT файл\n"
        "• Каждая фраза на отдельной строке\n"
        "• Строки начинающиеся с # игнорируются\n\n"
        "<b>Пример содержимого:</b>\n"
        "<code># Мои ключевые фразы\n"
        "купить панели wpc\n"
        "стеновые панели москва\n"
        "панели для спальни</code>\n\n"
        "⚠️ <b>ВАЖНО:</b>\n"
        "• Новые фразы <b>ДОБАВЯТСЯ</b> к существующим\n"
        "• Дубликаты будут пропущены\n\n"
        "👇 Отправьте TXT файл с фразами:"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("❌ Отмена", callback_data=f"category_keywords_{category_id}")
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


@bot.message_handler(content_types=['document'], func=lambda message: message.from_user.id in keywords_state 
                     and keywords_state[message.from_user.id].get('step') == 'waiting_file')
def handle_keywords_file_upload(message):
    """Обработка загруженного TXT файла с ключевыми фразами"""
    user_id = message.from_user.id
    
    state = keywords_state.get(user_id)
    if not state:
        return
    
    category_id = state['category_id']
    
    # Проверяем что это TXT файл
    if not message.document.file_name.endswith('.txt'):
        bot.send_message(
            message.chat.id,
            "❌ Пожалуйста, отправьте TXT файл"
        )
        return
    
    try:
        # Скачиваем файл
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Декодируем содержимое
        content = downloaded_file.decode('utf-8')
        
        # Парсим ключевые фразы
        new_keywords = []
        for line in content.split('\n'):
            line = line.strip()
            # Пропускаем пустые строки и комментарии
            if line and not line.startswith('#'):
                new_keywords.append(line)
        
        if not new_keywords:
            bot.send_message(
                message.chat.id,
                "❌ В файле не найдено ключевых фраз"
            )
            return
        
        # Получаем существующие фразы
        category = db.get_category(category_id)
        existing_keywords = category.get('keywords', [])
        if not isinstance(existing_keywords, list):
            existing_keywords = []
        
        # Объединяем и убираем дубликаты
        all_keywords = list(set(existing_keywords + new_keywords))
        added_count = len(all_keywords) - len(existing_keywords)
        
        # Сохраняем в БД
        db.cursor.execute("""
            UPDATE categories 
            SET keywords = %s::jsonb
            WHERE id = %s
        """, (json.dumps(all_keywords, ensure_ascii=False), category_id))
        db.conn.commit()
        
        # Очищаем состояние
        del keywords_state[user_id]
        
        text = (
            "✅ <b>КЛЮЧЕВЫЕ ФРАЗЫ ЗАГРУЖЕНЫ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"📊 Загружено фраз из файла: <b>{len(new_keywords)}</b>\n"
            f"➕ Добавлено новых: <b>{added_count}</b>\n"
            f"📈 Всего фраз в категории: <b>{len(all_keywords)}</b>\n"
        )
        
        if added_count < len(new_keywords):
            text += f"\n⚠️ Пропущено дубликатов: <b>{len(new_keywords) - added_count}</b>"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("🔙 К фразам", callback_data=f"category_keywords_{category_id}")
        )
        
        bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')
        
    except Exception as e:
        print(f"❌ Ошибка обработки файла: {e}")
        import traceback
        traceback.print_exc()
        
        bot.send_message(
            message.chat.id,
            f"❌ Ошибка обработки файла: {e}"
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("start_keywords_survey_"))
def handle_start_keywords_survey(call):
    """Начало опроса для подбора ключевых фраз"""
    category_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    # Удаляем предыдущее сообщение
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    # ВАЖНО: Очищаем состояние создания категории если оно есть
    from handlers.categories import category_creation_state
    if user_id in category_creation_state:
        del category_creation_state[user_id]
        print(f"🧹 Очищено состояние category_creation для {user_id}")
    
    # СНАЧАЛА проверяем есть ли ПОСТОЯННЫЕ сохраненные ответы (survey_answers)
    saved_answers = load_survey_answers_permanent(user_id, category_id)
    
    if saved_answers and len(saved_answers) > 0:
        # Есть постоянные ответы - предлагаем использовать или пройти заново
        text = (
            "✅ <b>ОТВЕТЫ НА ОПРОС УЖЕ СОХРАНЕНЫ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"📝 Ответов: {len(saved_answers)}/{len(KEYWORDS_QUESTIONS)}\n\n"
            "Вы можете:\n"
            "• <b>Использовать сохраненные ответы</b> для генерации новых фраз\n"
            "• <b>Пройти опрос заново</b> и обновить ответы\n\n"
            "Что вы хотите сделать?"
        )
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("✅ Использовать сохраненные ответы", callback_data=f"use_saved_answers_{category_id}"),
            types.InlineKeyboardButton("🔄 Пройти опрос заново", callback_data=f"restart_survey_{category_id}"),
            types.InlineKeyboardButton("🔙 Отмена", callback_data=f"category_keywords_{category_id}")
        )
        
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
        safe_answer_callback(bot, call.id)
        return
    
    # Проверяем есть ли временное сохраненное состояние в БД (незавершенный опрос)
    saved_state = load_survey_state(user_id, category_id)
    
    if saved_state and saved_state.get('answers'):
        # Есть незавершенный опрос - предлагаем продолжить или начать заново
        answers_count = len(saved_state.get('answers', {}))
        total_questions = len(KEYWORDS_QUESTIONS)
        
        text = (
            "📋 <b>НАЙДЕН НЕЗАВЕРШЕННЫЙ ОПРОС</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"Вы уже ответили на {answers_count} из {total_questions} вопросов.\n\n"
            "Что вы хотите сделать?"
        )
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("▶️ Продолжить опрос", callback_data=f"continue_survey_{category_id}"),
            types.InlineKeyboardButton("🔄 Начать заново", callback_data=f"restart_survey_{category_id}"),
            types.InlineKeyboardButton("🔙 Отмена", callback_data=f"category_keywords_{category_id}")
        )
        
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
        safe_answer_callback(bot, call.id)
        return
    
    # Нет сохраненных ответов - начинаем новый опрос
    keywords_state[user_id] = {
        'category_id': category_id,
        'step': 'survey',
        'question_index': 0,
        'answers': {}
    }
    
    # Сохраняем начальное состояние в БД
    save_survey_state(user_id, category_id, keywords_state[user_id])
    
    # Задаем первый вопрос
    ask_keywords_question(call.message.chat.id, user_id)
    
    safe_answer_callback(bot, call.id, "📝 Начинаем опрос")


@bot.callback_query_handler(func=lambda call: call.data.startswith("continue_survey_"))
def handle_continue_survey(call):
    """Продолжить незавершенный опрос"""
    category_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    # Загружаем состояние из БД
    saved_state = load_survey_state(user_id, category_id)
    
    if not saved_state:
        safe_answer_callback(bot, call.id, "❌ Состояние не найдено", show_alert=True)
        return
    
    # Восстанавливаем состояние в память
    keywords_state[user_id] = saved_state
    
    # Удаляем сообщение с выбором
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    # Продолжаем с текущего вопроса
    ask_keywords_question(call.message.chat.id, user_id)
    
    safe_answer_callback(bot, call.id, "▶️ Продолжаем опрос")


@bot.callback_query_handler(func=lambda call: call.data.startswith("use_saved_answers_"))
def handle_use_saved_answers(call):
    """Использовать сохраненные ответы для генерации"""
    category_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    # Загружаем сохраненные ответы
    saved_answers = load_survey_answers_permanent(user_id, category_id)
    
    if not saved_answers:
        safe_answer_callback(bot, call.id, "❌ Ответы не найдены", show_alert=True)
        return
    
    # Устанавливаем состояние с завершенным опросом
    keywords_state[user_id] = {
        'category_id': category_id,
        'step': 'survey',
        'question_index': len(KEYWORDS_QUESTIONS),  # Все вопросы пройдены
        'answers': saved_answers
    }
    
    # Удаляем сообщение
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    # Сразу переходим к выбору количества фраз
    show_keywords_count_selection(call.message.chat.id, user_id, saved_answers)
    
    safe_answer_callback(bot, call.id, "✅ Используем сохраненные ответы")


@bot.callback_query_handler(func=lambda call: call.data.startswith("restart_survey_"))
def handle_restart_survey(call):
    """Начать опрос заново"""
    category_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    # Очищаем сохраненное состояние
    clear_survey_state(user_id, category_id)
    
    # Удаляем сообщение с выбором
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    # Инициализируем новое состояние
    keywords_state[user_id] = {
        'category_id': category_id,
        'step': 'survey',
        'question_index': 0,
        'answers': {}
    }
    
    # Сохраняем начальное состояние
    save_survey_state(user_id, category_id, keywords_state[user_id])
    
    # Задаем первый вопрос
    ask_keywords_question(call.message.chat.id, user_id)
    
    safe_answer_callback(bot, call.id, "🔄 Начинаем заново")


def ask_keywords_question(chat_id, user_id):
    """Задать следующий вопрос опроса"""
    state = keywords_state.get(user_id)
    if not state:
        return
    
    question_index = state['question_index']
    
    # Если вопросы закончились - предлагаем выбрать количество фраз
    if question_index >= len(KEYWORDS_QUESTIONS):
        show_keywords_count_selection(chat_id, user_id)
        return
    
    # Получаем текущий вопрос
    question_data = KEYWORDS_QUESTIONS[question_index]
    question_text = question_data['question']
    can_skip = question_data['can_skip']
    
    # Добавляем прогресс
    progress = f"\n\n📊 Прогресс: {question_index + 1}/{len(KEYWORDS_QUESTIONS)}"
    full_text = question_text + progress
    
    # Создаем клавиатуру
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    if can_skip:
        markup.add(types.InlineKeyboardButton("⏭ Пропустить", callback_data="skip_keywords_question"))
    
    markup.add(types.InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_keywords_survey_{state['category_id']}"))
    
    # Отправляем вопрос
    msg = bot.send_message(chat_id, full_text, reply_markup=markup, parse_mode='HTML')
    
    # Сохраняем ID сообщения
    state['last_message_id'] = msg.message_id


@bot.callback_query_handler(func=lambda call: call.data == "skip_keywords_question" 
                            and call.from_user.id in keywords_state)
def handle_skip_keywords_question(call):
    """Пропуск вопроса"""
    user_id = call.from_user.id
    
    state = keywords_state.get(user_id)
    if not state:
        return
    
    # Удаляем сообщение с вопросом
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    # Переходим к следующему вопросу
    state['question_index'] += 1
    
    # 💾 СОХРАНЯЕМ ПРОГРЕСС В БД после пропуска
    save_survey_state(user_id, state['category_id'], state)
    
    ask_keywords_question(call.message.chat.id, user_id)
    
    safe_answer_callback(bot, call.id, "⏭ Пропущено")


@bot.message_handler(func=lambda message: message.from_user.id in keywords_state
                     and keywords_state[message.from_user.id]['step'] == 'survey')
def handle_keywords_survey_answer(message):
    """Обработка ответа на вопрос опроса"""
    user_id = message.from_user.id
    
    state = keywords_state.get(user_id)
    if not state:
        return
    
    question_index = state['question_index']
    
    if question_index >= len(KEYWORDS_QUESTIONS):
        return
    
    # Получаем ключ вопроса
    question_key = KEYWORDS_QUESTIONS[question_index]['key']
    
    # Сохраняем ответ
    state['answers'][question_key] = message.text.strip()
    
    # Удаляем ТОЛЬКО сообщение с вопросом (кнопки), НЕ удаляем ответ пользователя
    try:
        bot.delete_message(message.chat.id, state['last_message_id'])
    except Exception:
        pass
    
    # НЕ удаляем сообщение пользователя - оставляем историю опроса!
    # try:
    #     bot.delete_message(message.chat.id, message.message_id)
    # except:
    #     pass
    
    # Переходим к следующему вопросу
    state['question_index'] += 1
    
    # 💾 СОХРАНЯЕМ ПРОГРЕСС В БД после каждого ответа
    save_survey_state(user_id, state['category_id'], state)
    
    ask_keywords_question(message.chat.id, user_id)


def show_keywords_count_selection(chat_id, user_id):
    """Показать выбор количества ключевых фраз"""
    state = keywords_state.get(user_id)
    if not state:
        return
    
    # Получаем баланс пользователя с детальной проверкой
    user_tokens = db.get_user_tokens(user_id)
    
    # Дополнительная проверка и логирование
    print(f"📊 show_keywords_count_selection для пользователя {user_id}")
    print(f"   Токены из БД: {user_tokens}")
    
    # Если None - устанавливаем 0
    if user_tokens is None:
        print(f"   ⚠️ Токены = None, используем 0")
        user_tokens = 0
    
    # Если 0 - пробуем получить пользователя напрямую
    if user_tokens == 0:
        user = db.get_user(user_id)
        if user:
            print(f"   🔍 Прямая проверка пользователя:")
            print(f"      ID: {user.get('id')}")
            print(f"      Username: {user.get('username')}")
            print(f"      Tokens: {user.get('tokens')}")
            
            # Если в базе есть токены, но метод вернул 0
            if user.get('tokens') and user.get('tokens') > 0:
                user_tokens = user.get('tokens')
                print(f"   ✅ Найдены токены напрямую: {user_tokens}")
    
    text = (
        "✅ <b>ОПРОС ЗАВЕРШЕН!</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Отлично! Теперь выберите количество ключевых фраз для подбора.\n\n"
        f"💎 <b>Ваш баланс:</b> {user_tokens} токенов\n\n"
        "📊 <b>Доступные варианты:</b>\n\n"
        "• <b>50 фраз</b> - 50 токенов\n"
        "• <b>100 фраз</b> - 100 токенов\n"
        "• <b>150 фраз</b> - 150 токенов\n"
        "• <b>200 фраз</b> - 200 токенов\n\n"
        "Чем больше фраз, тем шире охват и больше возможностей для продвижения! 🚀"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Добавляем кнопки в зависимости от баланса
    if user_tokens >= 50:
        markup.add(types.InlineKeyboardButton("50 фраз (50 💎)", callback_data="keywords_count_50"))
    if user_tokens >= 100:
        markup.add(types.InlineKeyboardButton("100 фраз (100 💎)", callback_data="keywords_count_100"))
    if user_tokens >= 150:
        markup.add(types.InlineKeyboardButton("150 фраз (150 💎)", callback_data="keywords_count_150"))
    if user_tokens >= 200:
        markup.add(types.InlineKeyboardButton("200 фраз (200 💎)", callback_data="keywords_count_200"))
    
    if user_tokens < 50:
        text += "\n\n❌ <b>Недостаточно токенов!</b>\nКупите токены чтобы продолжить."
        markup.add(types.InlineKeyboardButton("💎 Купить токены", callback_data="buy_tokens"))
    
    # Кнопка для просмотра ответов
    markup.row()
    markup.add(types.InlineKeyboardButton("📋 Посмотреть мои ответы", callback_data="view_keywords_answers"))
    markup.add(types.InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_keywords_survey_{state['category_id']}"))
    
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')


@bot.callback_query_handler(func=lambda call: call.data.startswith("keywords_count_"))
def handle_keywords_count_selection(call):
    """Обработка выбора количества фраз"""
    user_id = call.from_user.id
    count = int(call.data.split("_")[-1])
    
    state = keywords_state.get(user_id)
    if not state:
        safe_answer_callback(bot, call.id, "❌ Ошибка")
        return
    
    # Проверяем баланс
    user_tokens = db.get_user_tokens(user_id)
    cost = TOKEN_PRICES['keywords_collection'][f'cost_per_{count}']
    
    if user_tokens < cost:
        safe_answer_callback(bot, call.id, "❌ Недостаточно токенов!", show_alert=True)
        return
    
    # Сохраняем выбранное количество
    state['count'] = count
    state['cost'] = cost
    
    # Показываем процесс генерации
    try:
        bot.edit_message_text(
            "⏳ <b>ГЕНЕРАЦИЯ КЛЮЧЕВЫХ ФРАЗ...</b>\n\n"
            "🤖 AI анализирует ваши ответы и подбирает ключевые фразы.\n\n"
            "<i>Это может занять 10-30 секунд...</i>",
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML'
        )
    except Exception:
        pass
    
    safe_answer_callback(bot, call.id, "🚀 Начинаем генерацию...")
    
    # Запускаем генерацию
    generate_keywords(call.message.chat.id, user_id)


def generate_keywords(chat_id, user_id):
    """Генерация ключевых фраз через Claude AI"""
    from ai.keywords_generator import generate_keywords as ai_generate_keywords
    from ai.keywords_generator import generate_keywords_fallback
    
    state = keywords_state.get(user_id)
    if not state:
        return
    
    category_id = state['category_id']
    count = state['count']
    cost = state['cost']
    answers = state['answers']
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        bot.send_message(chat_id, "❌ Категория не найдена")
        return
    
    category_name = category.get('name', 'Без названия')
    
    # Собираем данные для AI
    niche = answers.get('business_type', category_name)
    target_audience = answers.get('target_audience', 'Широкая аудитория')
    products_services = answers.get('products_services', 'товары и услуги')
    location = answers.get('geography', 'Россия')
    goals = answers.get('promotion_goals', 'Привлечение клиентов')
    
    # Отправляем прогресс
    progress_msg = bot.send_message(
        chat_id,
        "🤖 <b>AI генерирует ключевые фразы...</b>\n\n"
        f"Категория: {escape_html(category_name)}\n"
        f"Количество: {count} фраз\n"
        f"Ниша: {escape_html(niche)}\n\n"
        "⏳ Пожалуйста, подождите...",
        parse_mode='HTML'
    )
    
    # Пытаемся сгенерировать через Claude
    result = ai_generate_keywords(
        category_name=category_name,
        niche=niche,
        target_audience=target_audience,
        products_services=products_services,
        location=location,
        goals=goals,
        quantity=count
    )
    
    # Если Claude не сработал, используем fallback
    if not result['success']:
        # Пробуем fallback
        result = generate_keywords_fallback(category_name, niche, count)
        fallback_used = True
    else:
        fallback_used = False
    
    keywords = result.get('keywords', [])
    
    # Удаляем прогресс
    try:
        bot.delete_message(chat_id, progress_msg.message_id)
    except Exception:
        pass
    
    if not keywords:
        bot.send_message(
            chat_id,
            "❌ <b>Ошибка генерации</b>\n\n"
            f"Причина: {result.get('error', 'Неизвестная ошибка')}\n\n"
            "Попробуйте позже или обратитесь в поддержку.",
            parse_mode='HTML'
        )
        return
    
    # Списываем токены
    db.update_tokens(user_id, -cost)
    
    # Сохраняем ключевые фразы в категорию
    existing = category.get('keywords', [])
    if isinstance(existing, list):
        keywords = existing + keywords
    
    # Обновляем категорию (keywords - JSONB, нужна сериализация)
    db.cursor.execute("""
        UPDATE categories 
        SET keywords = %s::jsonb
        WHERE id = %s
    """, (json.dumps(keywords, ensure_ascii=False), category_id))
    db.conn.commit()
    
    print(f"✅ Сохранено {len(keywords)} ключевых фраз в категорию {category_id}")
    
    # Логируем расход токенов (если таблица существует)
    try:
        db.cursor.execute("""
            INSERT INTO token_expenses (user_id, amount, action, category_id, created_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, (user_id, cost, f'keywords_{count}', category_id))
        db.conn.commit()
    except Exception as e:
        print(f"⚠️ Не удалось залогировать расход токенов: {e}")
        # Откатываем если была ошибка
        try:
            db.conn.rollback()
        except Exception:
            pass
    
    # Формируем сообщение об успехе
    text = (
        "✅ <b>КЛЮЧЕВЫЕ ФРАЗЫ СГЕНЕРИРОВАНЫ!</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📂 Категория: <b>{escape_html(category_name)}</b>\n"
        f"🔑 Получено фраз: <b>{len(keywords)}</b>\n"
        f"💎 Списано токенов: <b>{cost}</b>\n\n"
    )
    
    if fallback_used:
        text += "⚠️ <i>Использован резервный генератор (Claude API недоступен)</i>\n\n"
    
    text += "📋 <b>ПРИМЕРЫ ФРАЗ:</b>\n"
    for kw in keywords[:10]:
        text += f"• {escape_html(kw)}\n"
    
    if len(keywords) > 10:
        text += f"\n<i>... и ещё {len(keywords) - 10} фраз</i>\n"
    
    text += "\n━━━━━━━━━━━━━━\n"
    text += "Вы можете просмотреть все фразы в карточке категории."
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("📂 К категории", callback_data=f"open_category_{category_id}")
    )
    
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')
    
    # 💾 СОХРАНЯЕМ ОТВЕТЫ ОПРОСА НАВСЕГДА (в survey_answers)
    state = keywords_state.get(user_id)
    if state and state.get('answers'):
        save_survey_answers_permanent(user_id, category_id, state['answers'])
    
    # 🧹 Очищаем только ВРЕМЕННОЕ состояние (survey_state) из БД
    clear_survey_state(user_id, category_id)
    
    # Очищаем состояние из памяти
    if user_id in keywords_state:
        del keywords_state[user_id]


def show_keywords_result(chat_id, user_id, keywords, cost):
    """Показать результат генерации"""
    keywords_count = len(keywords)
    
    # Показываем первые 15 фраз
    keywords_preview = keywords[:15]
    keywords_text = '\n'.join([f"• {escape_html(kw)}" for kw in keywords_preview])
    
    if keywords_count > 15:
        keywords_text += f"\n<i>... и ещё {keywords_count - 15} фраз</i>"
    
    # Получаем обновленный баланс
    new_balance = db.get_user_tokens(user_id)
    
    text = (
        "✅ <b>КЛЮЧЕВЫЕ ФРАЗЫ ПОДОБРАНЫ!</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"🎯 Сгенерировано фраз: <b>{keywords_count}</b>\n"
        f"💰 Списано токенов: <b>{cost}</b>\n"
        f"💎 Новый баланс: <b>{new_balance}</b>\n\n"
        f"<b>Примеры ключевых фраз:</b>\n\n"
        f"{keywords_text}\n\n"
        "Эти фразы сохранены в категории и будут использоваться для генерации контента! 🚀"
    )
    
    markup = types.InlineKeyboardMarkup()
    state = keywords_state.get(user_id, {})
    category_id = state.get('category_id')
    if category_id:
        markup.add(types.InlineKeyboardButton("🔙 К категории", callback_data=f"open_category_{category_id}"))
    
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')


@bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_keywords_survey_"))
def handle_cancel_keywords_survey(call):
    """Отмена опроса"""
    category_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    # 🧹 Очищаем сохраненное состояние из БД
    clear_survey_state(user_id, category_id)
    
    # Очищаем состояние из памяти
    if user_id in keywords_state:
        del keywords_state[user_id]
    
    # Удаляем сообщение
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    # Возвращаем к категории
    text = "❌ Подбор ключевых фраз отменен"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 К категории", callback_data=f"open_category_{category_id}"))
    
    bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    safe_answer_callback(bot, call.id, "Отменено")


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_survey_answers_"))
def handle_edit_survey_answers(call):
    """Редактирование сохраненных ответов опроса"""
    category_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    # Загружаем сохраненные ответы
    saved_answers = load_survey_answers_permanent(user_id, category_id)
    
    if not saved_answers:
        safe_answer_callback(bot, call.id, "❌ Ответы не найдены", show_alert=True)
        return
    
    # Инициализируем состояние с сохраненными ответами
    keywords_state[user_id] = {
        'category_id': category_id,
        'step': 'survey',
        'question_index': len(KEYWORDS_QUESTIONS),  # Все вопросы пройдены
        'answers': saved_answers
    }
    
    # Показываем интерфейс редактирования (существующая функция)
    handle_view_keywords_answers(call)


@bot.callback_query_handler(func=lambda call: call.data == "view_keywords_answers" 
                            and call.from_user.id in keywords_state)
def handle_view_keywords_answers(call):
    """Просмотр ответов на вопросы опроса"""
    user_id = call.from_user.id
    
    state = keywords_state.get(user_id)
    if not state:
        safe_answer_callback(bot, call.id, "❌ Ошибка")
        return
    
    answers = state.get('answers', {})
    
    text = (
        "📋 <b>ВАШИ ОТВЕТЫ НА ОПРОС</b>\n"
        "━━━━━━━━━━━━━━\n\n"
    )
    
    # Формируем список ответов
    for i, question_data in enumerate(KEYWORDS_QUESTIONS):
        question_key = question_data['key']
        question_title = question_data['question'].split('\n')[0]  # Берем только заголовок
        answer = answers.get(question_key, '—')
        
        # Убираем HTML теги из заголовка
        question_title = question_title.replace('<b>', '').replace('</b>', '').replace('🛍 ', '').replace('🏢 ', '').replace('🌍 ', '').replace('🎯 ', '').replace('🏷 ', '').replace('📌 ', '')
        
        text += f"<b>{i + 1}. {question_title}</b>\n"
        text += f"➜ {escape_html(answer)}\n\n"
    
    text += "━━━━━━━━━━━━━━\n\n"
    text += "Вы можете изменить любой ответ, нажав на соответствующую кнопку."
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Кнопки для редактирования каждого ответа
    for i, question_data in enumerate(KEYWORDS_QUESTIONS):
        markup.add(
            types.InlineKeyboardButton(
                f"✏️ Изменить {i + 1}",
                callback_data=f"edit_keywords_answer_{i}"
            )
        )
    
    markup.row()
    markup.add(
        types.InlineKeyboardButton("🔙 Назад к выбору", callback_data="back_to_keywords_count")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_keywords_answer_")
                            and call.from_user.id in keywords_state)
def handle_edit_keywords_answer(call):
    """Начало редактирования конкретного ответа"""
    user_id = call.from_user.id
    question_index = int(call.data.split("_")[-1])
    
    state = keywords_state.get(user_id)
    if not state:
        safe_answer_callback(bot, call.id, "❌ Ошибка")
        return
    
    question_data = KEYWORDS_QUESTIONS[question_index]
    question_key = question_data['key']
    current_answer = state['answers'].get(question_key, '—')
    
    text = (
        f"✏️ <b>РЕДАКТИРОВАНИЕ ОТВЕТА #{question_index + 1}</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"{question_data['question']}\n\n"
        f"<b>Текущий ответ:</b>\n"
        f"➜ {escape_html(current_answer)}\n\n"
        "Отправьте новый ответ или нажмите 'Отменить' чтобы вернуться."
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("❌ Отменить", callback_data="view_keywords_answers")
    )
    
    # Устанавливаем режим редактирования
    state['editing_question'] = question_index
    state['step'] = 'editing'
    
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='HTML'
        )
    except Exception:
        msg = bot.send_message(
            call.message.chat.id,
            text,
            reply_markup=markup,
            parse_mode='HTML'
        )
        state['last_message_id'] = msg.message_id
    
    safe_answer_callback(bot, call.id)


@bot.message_handler(func=lambda message: message.from_user.id in keywords_state
                     and keywords_state[message.from_user.id].get('step') == 'editing')
def handle_edit_answer_text(message):
    """Обработка нового текста при редактировании"""
    user_id = message.from_user.id
    
    state = keywords_state.get(user_id)
    if not state:
        return
    
    question_index = state.get('editing_question')
    if question_index is None:
        return
    
    question_key = KEYWORDS_QUESTIONS[question_index]['key']
    category_id = state['category_id']
    
    # Обновляем ответ
    state['answers'][question_key] = message.text.strip()
    
    # 💾 СОХРАНЯЕМ ИЗМЕНЕНИЕ НАВСЕГДА
    save_survey_answers_permanent(user_id, category_id, state['answers'])
    
    # Возвращаемся в режим опроса
    state['step'] = 'survey'
    del state['editing_question']
    
    # Удаляем сообщение с формой редактирования
    try:
        bot.delete_message(message.chat.id, state.get('last_message_id'))
    except Exception:
        pass
    
    # Показываем обновленный список ответов
    bot.send_message(
        message.chat.id,
        f"✅ Ответ #{question_index + 1} обновлен и сохранен!"
    )
    
    # Создаем fake call для вызова view_keywords_answers
    class FakeCall:
        def __init__(self, user, chat, msg_id):
            self.from_user = user
            self.message = type('obj', (object,), {'chat': chat, 'message_id': msg_id})()
    
    fake_call = FakeCall(message.from_user, message.chat, message.message_id)
    
    # Немного подождем перед показом
    import time
    time.sleep(0.5)
    
    # Показываем меню с ответами
    handle_view_keywords_answers(fake_call)


@bot.callback_query_handler(func=lambda call: call.data == "back_to_keywords_count"
                            and call.from_user.id in keywords_state)
def handle_back_to_keywords_count(call):
    """Возврат к выбору количества ключевых фраз"""
    user_id = call.from_user.id
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    show_keywords_count_selection(call.message.chat.id, user_id)
    safe_answer_callback(bot, call.id)



print("✅ handlers/keywords.py загружен")
