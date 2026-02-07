"""
Планировщик и медиа библиотека для платформ
"""
import logging

logger = logging.getLogger(__name__)

from telebot import types

from loader import bot, db

from utils import escape_html

import json

from datetime import datetime


# Безопасное логирование
try:
    from debug_logger import debug
except Exception:
    class SimpleDebug:
        def header(self, *args): pass
        def info(self, *args): pass
        def success(self, *args): pass
        def warning(self, *args): pass
        def error(self, *args): pass
        def debug(self, *args): pass
        def dict_dump(self, *args, **kwargs): pass
        def footer(self): pass
    debug = SimpleDebug()


@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_scheduler_"))
def handle_platform_scheduler(call):
    """Открытие планировщика для платформы и категории"""
    parts = call.data.split("_")
    
    platform_type = parts[2]
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = "_".join(parts[5:])
    
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    category_name = category.get('name', 'Без названия')
    
    text = (
        f"📅 <b>ПЛАНИРОВЩИК ПУБЛИКАЦИЙ</b>\n"
        f"📂 Категория: {escape_html(category_name)}\n"
        f"📱 Платформа: {platform_type.upper()}\n"
        "━━━━━━━━━━━━━━\n\n"
        "Настройте автоматическую публикацию контента:\n\n"
        "<b>Доступные функции:</b>\n"
        "• Расписание публикаций (дни, время)\n"
        "• Частота постинга\n"
        "• Автогенерация контента\n"
        "• Использование готовых материалов\n\n"
        "⚙️ Функция в разработке\n"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    markup.add(
        types.InlineKeyboardButton(
            "⏰ Настроить расписание",
            callback_data=f"scheduler_setup_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        )
    )
    
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_menu_{category_id}_{bot_id}_{platform_type}_{platform_id}"
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
    
    bot.answer_callback_query(call.id)



@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_media_"))
def handle_platform_media(call):
    """Переход к медиа категории из меню платформы"""
    parts = call.data.split("_")
    platform_type = parts[2]
    category_id = int(parts[3])
    bot_id = int(parts[4])
    
    # Импортируем обработчик медиа
    from handlers.category_sections import handle_category_media
    
    # Создаем фейковый call с нужным callback_data
    call.data = f"category_media_{category_id}"
    
    # Вызываем оригинальный обработчик
    handle_category_media(call)


# ═══════════════════════════════════════════════════════════════
# ПУБЛИКАЦИЯ В TELEGRAM
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("telegram_publish_topic_"))
def telegram_publish_topic_handler(call):
    """Публикация в выбранный топик Telegram"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = parts[5]
    topic_id = int(parts[6])
    
    user_id = call.from_user.id
    
    # Получаем текущий баланс (токены уже списаны)
    new_balance = db.get_user_tokens(user_id)
    cost = 40  # было списано ранее (10 текст + 30 изображение)
    
    # Получаем platform_info
    platform_names = {
        'telegram': {
            'title': 'ПОСТА',
            'noun_gen': 'поста',
            'platform_name': 'Telegram'
        }
    }
    platform_info = platform_names['telegram']
    
    bot.answer_callback_query(call.id, "🤖 Генерирую и публикую...")
    
    # ВАЖНО: Удаляем меню с кнопками чтобы не было путаницы
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        # Если не получилось удалить - редактируем
        try:
            bot.edit_message_text(
                "⏳ Генерирую пост...",
                call.message.chat.id,
                call.message.message_id
            )
        except Exception:
            pass
    
    _telegram_publish_post(
        call,
        category_id,
        bot_id,
        platform_id,
        topic_id,
        cost,
        new_balance,
        platform_info
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("telegram_cancel_publish_"))
def telegram_cancel_publish(call):
    """Отмена публикации и возврат токенов"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    platform_id = parts[5]
    cost = int(parts[6])
    
    user_id = call.from_user.id
    
    # Возвращаем токены
    db.update_tokens(user_id, cost)
    new_balance = db.get_user_tokens(user_id)
    
    text = (
        "❌ <b>ПУБЛИКАЦИЯ ОТМЕНЕНА</b>\n\n"
        f"💰 Токены возвращены: +{cost}\n"
        f"💳 Баланс: {new_balance:,} токенов"
    )
    
    markup = types.InlineKeyboardMarkup()
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
    
    bot.answer_callback_query(call.id)


def _telegram_publish_post(call, category_id, bot_id, platform_id, topic_id, cost, new_balance, platform_info):
    """Внутренняя функция для публикации в Telegram"""
    
    # КРИТИЧЕСКИ ВАЖНО: Импортируем random В НАЧАЛЕ!
    import random
    
    # Инициализируем прогресс-бар с GIF (10 шагов)
    from utils.generation_progress import show_generation_progress
    progress = show_generation_progress(call.message.chat.id, "telegram", total_steps=10)
    
    # ШАГ 1/10
    progress.start("🔧 Инициализация системы...")
    
    # ШАГ 2/10
    progress.update(2, "📂 Загружаю категорию...", f"Получение настроек")
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        progress.finish()
        db.update_tokens(call.from_user.id, cost)
        bot.send_message(call.message.chat.id, "❌ Ошибка: категория не найдена. Токены возвращены.")
        return
    
    category_name = category.get('name', 'Без названия')
    description = category.get('description', '')
    telegram_topics = category.get('telegram_topics', [])
    
    # ШАГ 3/10
    progress.update(3, "🎯 Выбираю контент...", f"📝 {category_name}")
    
    # Находим название топика если публикуем в топик
    topic_name = None
    if topic_id and topic_id > 0:
        for topic in telegram_topics:
            if topic.get('topic_id') == topic_id:
                topic_name = topic.get('topic_name')
                break
    
    # ═══════════════════════════════════════════════════════════════
    # КРИТИЧЕСКИ ВАЖНО: Выбираем ЕДИНУЮ фразу для текста И изображения!
    # (Правило 10.1 и 11 Конституции)
    # ═══════════════════════════════════════════════════════════════
    
    selected_content_phrase = None
    
    # 10% шанс использовать описание БОТА (для разнообразия)
    use_bot_description = random.random() < 0.1
    
    if use_bot_description:
        # Получаем описание бота
        bot_info = db.get_bot(bot_id)
        bot_description = bot_info.get('description', '') if bot_info else ''
        
        if bot_description and len(bot_description) > 20:
            bot_phrases = [s.strip() for s in bot_description.split(',') if s.strip() and len(s.strip()) > 10]
            if bot_phrases:
                selected_content_phrase = random.choice(bot_phrases)
                print(f"🎲 Используем описание БОТА: {selected_content_phrase[:80]}...")
            else:
                use_bot_description = False
        else:
            use_bot_description = False
    
    # Если НЕ используем описание бота - берём из описания категории
    if not use_bot_description and description:
        desc_phrases = [s.strip() for s in description.split(',') if s.strip() and len(s.strip()) > 10]
        if desc_phrases:
            selected_content_phrase = random.choice(desc_phrases)
            print(f"📝 Выбрана ЕДИНАЯ фраза для контента: {selected_content_phrase[:80]}...")
    
    # ═══════════════════════════════════════════════════════════════
    # ГЕНЕРАЦИЯ ТЕКСТА (использует selected_content_phrase)
    # ═══════════════════════════════════════════════════════════════
    
    # ШАГ 4/10: Генерация текста
    progress.update(4, "✍️ Генерирую текст...", f"Claude создаёт описание")
    
    # МИГРАЦИЯ: Используем unified_generator вместо старого API
    from ai.unified_generator import generate_for_platform
    
    # Формируем фразу с учётом топика
    phrase = selected_content_phrase or ""
    if topic_name:
        phrase = f"{topic_name}. {phrase}" if phrase else topic_name
    
    # ШАГ 5/10: Генерация изображения
    progress.update(5, "🎨 Генерирую изображение...", f"Nano Banana Pro создаёт картинку")
    
    result = generate_for_platform(
        platform='telegram',
        category_name=category_name,
        selected_phrase=phrase,
        style='conversational'  # Вовлекающий стиль для Telegram
    )
    
    if not result.get('success'):
        progress.finish()
        db.update_tokens(call.from_user.id, cost)
        bot.send_message(
            call.message.chat.id,
            f"❌ Ошибка генерации текста: {result.get('error', 'Неизвестная ошибка')}\n\n"
            "Токены возвращены."
        )
        return
    
    # Получаем текст И изображение из первой генерации
    post_text = result['text']
    image_bytes = result['image_bytes']  # ← КРИТИЧНО: Берём из первой генерации!
    
    # Убираем markdown символы (но оставляем # для хэштегов!)
    post_text = post_text.replace('**', '').replace('__', '')
    post_text = post_text.replace('```', '').replace('`', '')
    
    # Разбиваем на абзацы (двойной перенос)
    paragraphs = [p.strip() for p in post_text.split('\n\n') if p.strip()]
    
    # ИСПРАВЛЕНИЕ: Если получился только ОДИН абзац (весь текст слитый)
    # Разбиваем по одинарным переносам
    if len(paragraphs) == 1 and len(paragraphs[0]) > 300:
        single_para = paragraphs[0]
        paragraphs = [p.strip() for p in single_para.split('\n') if p.strip() and len(p.strip()) > 10]
        
        # Если всё ещё один длинный абзац - разбиваем по предложениям
        if len(paragraphs) == 1 and len(paragraphs[0]) > 300:
            sentences = []
            text = paragraphs[0]
            for sep in ['. ', '! ', '? ']:
                text = text.replace(sep, sep + '|||')
            parts = [s.strip() for s in text.split('|||') if s.strip()]
            paragraphs = parts if len(parts) > 1 else paragraphs
    
    if not paragraphs:
        post_text = "✨ Контент создан"
    else:
        formatted_parts = []
        
        # ══════════════════════════════════════════════════════════
        # ЗАГОЛОВОК (первый абзац) - ЖИРНЫЙ + ПОДЧЁРКНУТЫЙ + ЭМОДЗИ
        # ══════════════════════════════════════════════════════════
        if paragraphs:
            title = paragraphs[0]
            
            # ИСПРАВЛЕНО: Берём весь первый абзац, НЕ обрезаем до первого предложения!
            # Ограничиваем только по длине
            if len(title) > 200:
                # Если слишком длинный - ищем конец предложения
                if '.' in title[:200]:
                    sentences = title.split('.')
                    title = sentences[0].strip() + '.'
                else:
                    title = title[:200].strip() + '...'
            
            # СУПЕР ЗАГОЛОВОК
            formatted_parts.append(f"<u><b>🔥 {title}</b></u>")
            formatted_parts.append("")  # Отступ после заголовка
        
        # ══════════════════════════════════════════════════════════
        # ОБРАБАТЫВАЕМ ОСТАЛЬНЫЕ АБЗАЦЫ
        # ══════════════════════════════════════════════════════════
        for para_idx, para in enumerate(paragraphs[1:], 1):
            lines = [line.strip() for line in para.split('\n') if line.strip()]
            
            para_content = []
            
            for line in lines:
                # Пропускаем слишком короткие строки
                if len(line) < 5:
                    continue
                
                # ══════════════════════════════════════════════════
                # ВОПРОС → Жирный + курсив + эмодзи
                # ══════════════════════════════════════════════════
                if '?' in line:
                    para_content.append(f"<b><i>❓ {line}</i></b>")
                
                # ══════════════════════════════════════════════════
                # ПОДЗАГОЛОВОК (заканчивается на :) → Жирный + эмодзи
                # ══════════════════════════════════════════════════
                elif line.endswith(':'):
                    # Добавляем отступ перед подзаголовком если это не первая строка
                    if para_content:
                        para_content.append("")
                    para_content.append(f"<b>💎 {line}</b>")
                
                # ══════════════════════════════════════════════════
                # СПИСОК (начинается с маркера) → КАЖДЫЙ С НОВОЙ СТРОКИ
                # ══════════════════════════════════════════════════
                elif line.startswith(('•', '-', '—', '*', '·', '▪')) or (line[0].isdigit() and any(x in line[:5] for x in ['.', ')'])):
                    # Убираем маркеры
                    import re
                    clean_line = re.sub(r'^[•\-—*·▪\d\.\)]+\s*', '', line).strip()
                    para_content.append(f"  <code>▫️ {clean_line}</code>")
                
                # ══════════════════════════════════════════════════
                # ЦЕНЫ/ЦИФРЫ → Моноширинный + жирный + эмодзи
                # ══════════════════════════════════════════════════
                elif any(char.isdigit() for char in line) and any(word in line.lower() for word in ['₽', '$', '€', 'руб', 'цен', 'стоим', 'тысяч', 'миллион', '%', 'раз', 'метр']):
                    para_content.append(f"<b><code>💰 {line}</code></b>")
                
                # ══════════════════════════════════════════════════
                # КОРОТКАЯ ФРАЗА (акцент) → Курсив + эмодзи
                # ══════════════════════════════════════════════════
                elif len(line) < 80:
                    # Добавляем эмодзи если его нет
                    if not any(emoji in line for emoji in ['💎', '🔥', '✨', '⚡', '🎯', '💫', '🌟', '❤️', '👌', '🎨']):
                        para_content.append(f"<i>✨ {line}</i>")
                    else:
                        para_content.append(f"<i>{line}</i>")
                
                # ══════════════════════════════════════════════════
                # ОБЫЧНЫЙ ТЕКСТ
                # ══════════════════════════════════════════════════
                else:
                    para_content.append(line)
            
            # Добавляем абзац с отступом после
            if para_content:
                formatted_parts.append('\n'.join(para_content))
                formatted_parts.append("")  # Отступ между абзацами
        
        # Собираем финальный текст
        post_text = '\n'.join(formatted_parts)
        
        # Убираем лишние пустые строки (более 2 подряд)
        import re
        post_text = re.sub(r'\n{3,}', '\n\n', post_text)
        
        # Убираем пустую строку в самом конце
        post_text = post_text.rstrip('\n')
    
    # ВАЖНО: Telegram лимит caption = 1024 символа!
    MAX_CAPTION_LENGTH = 1024
    
    if len(post_text) > MAX_CAPTION_LENGTH:
        print(f"⚠️  Caption слишком длинный ({len(post_text)} символов), обрезаем до {MAX_CAPTION_LENGTH}")
        
        # УМНАЯ обрезка
        truncated = post_text[:MAX_CAPTION_LENGTH-50]
        
        # Ищем последнюю точку или двойной перенос
        last_period = truncated.rfind('.')
        last_newline = truncated.rfind('\n\n')
        cut_point = max(last_period, last_newline)
        
        if cut_point > 0:
            post_text = truncated[:cut_point + 1]
            
            # Проверяем незаконченные пункты списка
            lines = post_text.split('\n')
            if lines:
                last_line = lines[-1].strip()
                if last_line and (last_line[0] in '✨💎🔥📌⭐🎨' or last_line.startswith(('-', '•'))):
                    if not last_line.endswith(('.', '!', '?', ')')):
                        lines = lines[:-1]
                        post_text = '\n'.join(lines)
                        print("✂️  Удален незаконченный пункт списка")
            
            post_text = post_text.rstrip()
        else:
            post_text = truncated.rsplit(' ', 1)[0] + '...'
        
        print(f"✂️  Caption обрезан до {len(post_text)} символов")
    
    # ШАГ 6/10: Проверка текста
    progress.update(6, "📝 Проверяю текст...", f"Валидация и форматирование")
    
    # [здесь идёт форматирование текста - не трогаем]
    
    # Сохраняем изображение из ПЕРВОЙ генерации (НЕ генерируем заново!)
    import tempfile
    import os as os_module
    
    try:
        temp_dir = tempfile.gettempdir()
        image_path = os_module.path.join(temp_dir, f"telegram_post_{call.from_user.id}.jpg")
        
        with open(image_path, 'wb') as f:
            f.write(image_bytes)
        
        print(f"✅ Изображение сохранено: {image_path}")
        
    except Exception as e:
        progress.finish()
        db.update_tokens(call.from_user.id, cost)
        bot.send_message(
            call.message.chat.id,
            f"❌ Ошибка сохранения изображения: {str(e)}\n\nТокены возвращены."
        )
        return
    
    # ШАГ 7/10: Сохранение изображения
    progress.update(7, "🖼️ Сохраняю изображение...", f"Подготовка к отправке")
    
    # ШАГ 8/10: Подключение к Telegram
    progress.update(8, "🔗 Подключаюсь к боту...", f"Авторизация")
    
    # 3. Публикуем в Telegram
    try:
        # ШАГ 9/10: Отправка поста
        progress.update(9, "📤 Отправляю пост...", f"Публикация в канал")
        
        # Получаем данные канала
        user_id = call.from_user.id
        user = db.get_user(user_id)
        
        if not user:
            raise Exception("Пользователь не найден")
        
        platform_connections = user.get('platform_connections', {})
        
        # Структура: {'telegrams': [{'channel': '@ecosteni', 'channel_id': '-1002...'}]}
        telegrams = platform_connections.get('telegrams', [])
        
        # Ищем канал по platform_id (это username канала, например @ecosteni)
        telegram_data = None
        for tg in telegrams:
            if tg.get('channel', '') == platform_id:
                telegram_data = tg
                break
        
        if not telegram_data:
            raise Exception(f"Telegram канал {platform_id} не найден в подключениях")
        
        channel_id = telegram_data.get('channel_id')
        bot_token = telegram_data.get('bot_token')
        
        if not channel_id:
            raise Exception("ID канала не найден. Переподключите канал.")
        
        if not bot_token:
            raise Exception("Токен бота не найден. Переподключите канал.")
        
        # КРИТИЧНО: Создаём отдельный экземпляр бота с токеном из базы!
        import telebot
        publishing_bot = telebot.TeleBot(bot_token)
        
        # Проверяем какой это бот
        try:
            bot_info = publishing_bot.get_me()
            print(f"🤖 Используем бота: @{bot_info.username} (ID: {bot_info.id})")
            print(f"   Токен: {bot_token[:20]}...")
        except Exception as bot_check_error:
            raise Exception(f"Не могу получить информацию о боте: {bot_check_error}")
        
        # ОТЛАДКА
        logger.debug("DEBUG публикация:")
        print(f"   Platform ID: {platform_id}")
        print(f"   Channel ID (from DB): {channel_id}")
        print(f"   Topic ID: {topic_id}")
        
        # Проверяем что бот имеет доступ к каналу
        try:
            chat_info = publishing_bot.get_chat(channel_id)
            print(f"   Chat type: {chat_info.type}")
            print(f"   Chat title: {chat_info.title if hasattr(chat_info, 'title') else 'N/A'}")
            
            # КРИТИЧНО: Используем реальный числовой ID чата!
            actual_chat_id = chat_info.id
            print(f"   Actual Chat ID: {actual_chat_id}")
            
            # Проверяем права бота
            try:
                bot_member = publishing_bot.get_chat_member(channel_id, bot_info.id)
                print(f"   Bot status: {bot_member.status}")
                
                if hasattr(bot_member, 'can_post_messages'):
                    print(f"   Can post messages: {bot_member.can_post_messages}")
                if hasattr(bot_member, 'can_edit_messages'):
                    print(f"   Can edit messages: {bot_member.can_edit_messages}")
                
                if bot_member.status not in ['administrator', 'creator']:
                    raise Exception(f"Бот не является администратором! Статус: {bot_member.status}")
                    
            except Exception as rights_error:
                print(f"⚠️ Ошибка проверки прав: {rights_error}")
            
            # Если в базе сохранён username (@ecosteni), заменяем на числовой ID
            if isinstance(channel_id, str) and channel_id.startswith('@'):
                print(f"⚠️  Используем числовой ID вместо username")
                channel_id = actual_chat_id
                
        except Exception as check_error:
            raise Exception(f"Не могу получить информацию о канале: {check_error}")
        
        # Отправляем пост с изображением
        print(f"📤 Пытаемся опубликовать:")
        print(f"   chat_id: {channel_id}")
        print(f"   topic_id: {topic_id}")
        print(f"   text length: {len(post_text)}")
        
        try:
            with open(image_path, 'rb') as photo:
                if topic_id and topic_id > 0:
                    # Публикуем в топик
                    print(f"📤 Публикуем в топик {topic_id}...")
                    sent_message = publishing_bot.send_photo(
                        chat_id=channel_id,
                        photo=photo,
                        caption=post_text,
                        message_thread_id=topic_id,
                        parse_mode='HTML'
                    )
                else:
                    # Публикуем в основной чат
                    print(f"📤 Публикуем в основной чат...")
                    sent_message = publishing_bot.send_photo(
                        chat_id=channel_id,
                        photo=photo,
                        caption=post_text,
                        parse_mode='HTML'
                    )
            
            print(f"✅ Пост опубликован! Message ID: {sent_message.message_id}")
            
            # ШАГ 10/10: Завершение
            progress.update(10, "✅ Готово!", f"Пост опубликован")
            
        except Exception as send_error:
            print(f"❌ Ошибка отправки: {send_error}")
            raise Exception(f"Ошибка отправки поста: {send_error}")
        
        # Удаляем временный файл
        import os
        try:
            os.unlink(image_path)
        except Exception:
            pass
        
        # Удаляем прогресс-бар
        progress.finish()
        
        # Формируем ссылку на пост
        post_url = None
        if hasattr(sent_message, 'message_id'):
            # Пытаемся получить username канала
            try:
                if hasattr(chat_info, 'username') and chat_info.username:
                    post_url = f"https://t.me/{chat_info.username}/{sent_message.message_id}"
            except Exception:
                pass
        
        # Успех!
        
        # Формируем детали платформы (топик)
        platform_detail = None
        if topic_id and topic_id > 0:
            telegram_topics = category.get('telegram_topics', [])
            for topic in telegram_topics:
                if topic.get('topic_id') == topic_id:
                    topic_name = topic.get('topic_name')
                    if topic_name:
                        platform_detail = f'Топик: {topic_name}'
                    break
        
        # Используем универсальное сообщение успеха
        from utils.success_message import send_unified_success_message
        
        send_unified_success_message(
            bot=bot,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            platform_type='telegram',
            category_name=category_name,
            cost=cost,
            new_balance=new_balance,
            word_count=len(post_text.split()),
            post_url=post_url,
            platform_detail=platform_detail,
            category_id=category_id,
            bot_id=bot_id,
            platform_id=platform_id
        )
    
    except Exception as e:
        # Удаляем прогресс-бар
        progress.finish()
        
        # Возвращаем токены при ошибке
        db.update_tokens(call.from_user.id, cost)
        
        error_msg = str(e)
        
        # Специальная обработка для ошибки 403
        if "403" in error_msg or "Forbidden" in error_msg or "not a member" in error_msg:
            error_text = (
                "❌ <b>БОТ НЕ ДОБАВЛЕН В КАНАЛ</b>\n\n"
                f"💰 Токены возвращены: +{cost}\n"
                f"💳 Баланс: {db.get_user_tokens(call.from_user.id):,} токенов\n\n"
                "<b>📋 Инструкция:</b>\n\n"
                "1️⃣ Откройте ваш Telegram канал/группу\n"
                "2️⃣ Нажмите на название → Администраторы\n"
                "3️⃣ Добавьте бота как администратора\n"
                "4️⃣ Дайте права:\n"
                "   • Публикация сообщений ✅\n"
                "   • Управление сообщениями ✅\n\n"
                f"<b>Имя бота:</b> @{bot.get_me().username}\n\n"
                "После добавления попробуйте опубликовать снова!"
            )
        else:
            error_text = (
                "❌ <b>ОШИБКА ПУБЛИКАЦИИ</b>\n\n"
                f"Причина: {error_msg}\n\n"
                f"💰 Токены возвращены: +{cost}\n"
                f"💳 Баланс: {db.get_user_tokens(call.from_user.id):,} токенов\n\n"
                "Проверьте:\n"
                "• Бот добавлен в канал как администратор\n"
                "• У бота есть права на публикацию\n"
                "• ID топика указан верно"
            )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"platform_menu_{category_id}_{bot_id}_telegram_{platform_id}"
            )
        )
        
        try:
            bot.edit_message_text(
                error_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup,
                parse_mode='HTML'
            )
        except Exception:
            bot.send_message(
                call.message.chat.id,
                error_text,
                reply_markup=markup,
                parse_mode='HTML'
            )


print("✅ handlers/platform_category_menu.py загружен")


# ═══════════════════════════════════════════════════════════════
# ПОДМЕНЮ: НАСТРОЙКИ ИЗОБРАЖЕНИЙ
# ═══════════════════════════════════════════════════════════════


print("✅ platform_category/scheduler_media.py загружен")
