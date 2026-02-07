"""
Модуль анализа сайта - технический аудит и SEO анализ
"""
from telebot import types
from loader import bot
from database.database import db
from utils import escape_html, safe_answer_callback
import time
import requests
from bs4 import BeautifulSoup
import re


# Состояние анализа
analysis_state = {}


def update_progress(chat_id, message_id, percent, text, title="АНАЛИЗ"):
    """Обновление прогресс-бара"""
    bar_len = 12
    filled = int(bar_len * percent / 100)
    
    bar = ""
    for i in range(bar_len):
        if i < filled:
            if i < bar_len * 0.25:
                bar += "🟥"
            elif i < bar_len * 0.5:
                bar += "🟧"
            elif i < bar_len * 0.75:
                bar += "🟨"
            else:
                bar += "🟩"
        else:
            bar += "⬜"
    
    try:
        new_text = f"⏳ <b>{title}</b>\n{bar} <b>{percent}%</b>\n<i>{text}</i>"
        bot.edit_message_text(
            new_text,
            chat_id,
            message_id,
            parse_mode='HTML'
        )
        time.sleep(0.15)
    except Exception:
        pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("analyze_site_"))
def handle_analyze_site(call):
    """Начало анализа сайта"""
    bot_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    # Проверяем доступ
    bot_data = db.get_bot(bot_id)
    if not bot_data or bot_data['user_id'] != user_id:
        safe_answer_callback(bot, call.id, "❌ Ошибка доступа")
        return
    
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except Exception:
        pass
    
    text = (
        "🔎 <b>АНАЛИЗ САЙТА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Выберите тип анализа:"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🛠 Технический аудит", callback_data=f"tech_audit_{bot_id}"),
        types.InlineKeyboardButton("📊 SEO анализ", callback_data=f"seo_audit_{bot_id}"),
        types.InlineKeyboardButton("🤖 AI-анализ контента", callback_data=f"ai_content_{bot_id}"),
        types.InlineKeyboardButton("🔙 Назад", callback_data=f"open_bot_{bot_id}")
    )
    
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')
    safe_answer_callback(bot, call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("tech_audit_"))
def handle_tech_audit(call):
    """Технический аудит сайта"""
    bot_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    # Инициализируем состояние
    analysis_state[user_id] = {
        'bot_id': bot_id,
        'type': 'tech_audit'
    }
    
    text = (
        "🛠 <b>ТЕХНИЧЕСКИЙ АУДИТ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔍 <b>Что проверим:</b>\n"
        "• Доступность сайта\n"
        "• Скорость загрузки\n"
        "• SSL сертификат\n"
        "• Meta теги\n"
        "• Заголовки\n"
        "• Структура страницы\n"
        "• Мобильная адаптация\n\n"
        "🔗 <b>Введите URL сайта:</b>\n\n"
        "<i>Например: https://example.com</i>"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data=f"analyze_site_{bot_id}"))
    
    msg = bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    analysis_state[user_id]['last_message_id'] = msg.message_id
    
    safe_answer_callback(bot, call.id)


@bot.message_handler(func=lambda m: m.from_user.id in analysis_state 
                     and analysis_state[m.from_user.id]['type'] == 'tech_audit')
def process_tech_audit(message):
    """Выполнение технического аудита"""
    user_id = message.from_user.id
    state = analysis_state.get(user_id)
    
    if not state:
        return
    
    url = message.text.strip()
    
    # Валидация URL
    if not url.startswith('http'):
        url = 'https://' + url
    
    # Удаляем сообщения
    try:
        bot.delete_message(message.chat.id, state['last_message_id'])
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass
    
    # Запускаем анализ
    progress_msg = bot.send_message(message.chat.id, "⏳ Начинаю анализ...")
    
    try:
        # Шаг 1: Проверка доступности
        update_progress(message.chat.id, progress_msg.message_id, 10, "Проверка доступности сайта...", "ТЕХНИЧЕСКИЙ АУДИТ")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        start_time = time.time()
        response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        load_time = time.time() - start_time
        
        # Шаг 2: Анализ заголовков
        update_progress(message.chat.id, progress_msg.message_id, 30, "Анализ HTTP заголовков...", "ТЕХНИЧЕСКИЙ АУДИТ")
        
        status_code = response.status_code
        has_ssl = url.startswith('https://')
        
        # Шаг 3: Парсинг HTML
        update_progress(message.chat.id, progress_msg.message_id, 50, "Парсинг HTML структуры...", "ТЕХНИЧЕСКИЙ АУДИТ")
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Meta теги
        title = soup.find('title')
        title_text = title.get_text() if title else "Отсутствует"
        
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        desc_text = meta_desc.get('content', 'Отсутствует') if meta_desc else "Отсутствует"
        
        # Заголовки
        h1_tags = soup.find_all('h1')
        h1_count = len(h1_tags)
        
        # Изображения
        img_tags = soup.find_all('img')
        img_total = len(img_tags)
        img_without_alt = len([img for img in img_tags if not img.get('alt')])
        
        # Ссылки
        links = soup.find_all('a')
        internal_links = len([link for link in links if link.get('href', '').startswith('/')])
        external_links = len([link for link in links if link.get('href', '').startswith('http')])
        
        # Шаг 4: Проверка адаптивности
        update_progress(message.chat.id, progress_msg.message_id, 70, "Проверка мобильной адаптации...", "ТЕХНИЧЕСКИЙ АУДИТ")
        
        viewport = soup.find('meta', attrs={'name': 'viewport'})
        is_responsive = viewport is not None
        
        # Шаг 5: Формирование отчета
        update_progress(message.chat.id, progress_msg.message_id, 90, "Генерация отчета...", "ТЕХНИЧЕСКИЙ АУДИТ")
        
        # Оценка
        score = 0
        max_score = 10
        
        if status_code == 200:
            score += 2
        if has_ssl:
            score += 2
        if load_time < 3:
            score += 2
        if h1_count == 1:
            score += 1
        if title_text != "Отсутствует" and len(title_text) > 10:
            score += 1
        if desc_text != "Отсутствует":
            score += 1
        if is_responsive:
            score += 1
        
        score_percent = int((score / max_score) * 100)
        
        # Эмодзи для оценки
        if score_percent >= 80:
            score_emoji = "✅"
            score_text = "Отлично"
        elif score_percent >= 60:
            score_emoji = "⚠️"
            score_text = "Хорошо"
        else:
            score_emoji = "❌"
            score_text = "Требует улучшения"
        
        # Формируем отчет
        report = (
            f"🛠 <b>ТЕХНИЧЕСКИЙ АУДИТ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🌐 <b>URL:</b> <code>{escape_html(url)}</code>\n"
            f"📊 <b>Оценка:</b> {score_emoji} <b>{score_percent}%</b> ({score_text})\n\n"
            
            f"<b>🔍 ОСНОВНЫЕ ПОКАЗАТЕЛИ:</b>\n\n"
            
            f"<b>Доступность:</b>\n"
            f"  • HTTP код: {'✅' if status_code == 200 else '❌'} {status_code}\n"
            f"  • SSL: {'✅ Есть' if has_ssl else '❌ Отсутствует'}\n"
            f"  • Скорость: {'✅' if load_time < 3 else '⚠️'} {load_time:.2f}с\n\n"
            
            f"<b>SEO теги:</b>\n"
            f"  • Title: {'✅' if title_text != 'Отсутствует' else '❌'} {escape_html(title_text[:50])}...\n"
            f"  • Description: {'✅' if desc_text != 'Отсутствует' else '❌'}\n"
            f"  • H1 заголовков: {'✅' if h1_count == 1 else '⚠️' if h1_count > 0 else '❌'} {h1_count}\n\n"
            
            f"<b>Контент:</b>\n"
            f"  • Изображений: {img_total}\n"
            f"  • Без ALT: {'⚠️' if img_without_alt > 0 else '✅'} {img_without_alt}\n"
            f"  • Внутренних ссылок: {internal_links}\n"
            f"  • Внешних ссылок: {external_links}\n\n"
            
            f"<b>Адаптивность:</b>\n"
            f"  • Viewport: {'✅ Настроен' if is_responsive else '❌ Отсутствует'}\n\n"
            
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Анализ завершен за {load_time:.1f}с</i>"
        )
        
        # Удаляем прогресс
        try:
            bot.delete_message(message.chat.id, progress_msg.message_id)
        except Exception:
            pass
        
        # Отправляем отчет
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 К анализу", callback_data=f"analyze_site_{state['bot_id']}"))
        
        bot.send_message(message.chat.id, report, reply_markup=markup, parse_mode='HTML')
        
    except Exception as e:
        try:
            bot.delete_message(message.chat.id, progress_msg.message_id)
        except Exception:
            pass
        
        error_text = (
            f"❌ <b>ОШИБКА АНАЛИЗА</b>\n\n"
            f"Не удалось проанализировать сайт:\n"
            f"<code>{escape_html(str(e))}</code>\n\n"
            f"<i>Проверьте правильность URL</i>"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 Попробовать снова", callback_data=f"tech_audit_{state['bot_id']}"))
        
        bot.send_message(message.chat.id, error_text, reply_markup=markup, parse_mode='HTML')
    
    # Очищаем состояние
    del analysis_state[user_id]


@bot.callback_query_handler(func=lambda call: call.data.startswith("seo_audit_"))
def handle_seo_audit(call):
    """SEO анализ (заглушка)"""
    bot_id = int(call.data.split("_")[-1])
    
    text = (
        "📊 <b>SEO АНАЛИЗ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<i>Раздел в разработке</i>\n\n"
        "Будет доступно:\n"
        "• Глубокий анализ структуры\n"
        "• Проверка микроразметки\n"
        "• Анализ внутренней перелинковки\n"
        "• Проверка robots.txt и sitemap\n"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"analyze_site_{bot_id}"))
    
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("ai_content_"))
def handle_ai_content_analysis(call):
    """AI анализ контента (заглушка)"""
    bot_id = int(call.data.split("_")[-1])
    
    text = (
        "🤖 <b>AI-АНАЛИЗ КОНТЕНТА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<i>Раздел в разработке</i>\n\n"
        "Будет доступно:\n"
        "• Анализ тональности контента\n"
        "• Определение целевой аудитории\n"
        "• Выявление ключевых тем\n"
        "• Рекомендации по улучшению\n"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"analyze_site_{bot_id}"))
    
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


print("✅ handlers/site_analysis.py загружен")
