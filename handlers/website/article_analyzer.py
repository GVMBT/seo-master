# -*- coding: utf-8 -*-
"""
Анализатор SEO качества статей
"""
from telebot import types
from loader import bot
import requests
from bs4 import BeautifulSoup
import re


def analyze_seo_content(html_content, url):
    """
    Анализ SEO контента статьи
    Возвращает оценку 0-100 и детальный отчет
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    score = 100
    issues = []
    warnings = []
    positives = []
    
    # ==========================================
    # 1. ЗАГОЛОВКИ (H1, H2, H3)
    # ==========================================
    h1_tags = soup.find_all('h1')
    h2_tags = soup.find_all('h2')
    h3_tags = soup.find_all('h3')
    
    # H1 - должен быть один
    if len(h1_tags) == 0:
        issues.append("❌ Отсутствует заголовок H1")
        score -= 15
    elif len(h1_tags) > 1:
        issues.append(f"❌ Слишком много H1 ({len(h1_tags)} шт). Должен быть один")
        score -= 10
    else:
        h1_text = h1_tags[0].get_text().strip()
        if len(h1_text) < 20:
            warnings.append(f"⚠️ H1 слишком короткий ({len(h1_text)} символов)")
            score -= 5
        elif len(h1_text) > 70:
            warnings.append(f"⚠️ H1 слишком длинный ({len(h1_text)} символов)")
            score -= 3
        else:
            positives.append(f"✅ H1 оптимальной длины ({len(h1_text)} символов)")
        
        # Проверка на переспам ключей в H1
        words = h1_text.lower().split()
        if len(words) != len(set(words)):
            issues.append("❌ В H1 повторяются слова (keyword stuffing)")
            score -= 10
    
    # H2 - должно быть 6-10 штук
    if len(h2_tags) < 4:
        warnings.append(f"⚠️ Мало подзаголовков H2 ({len(h2_tags)} шт). Рекомендуется 6-10")
        score -= 5
    elif len(h2_tags) > 12:
        warnings.append(f"⚠️ Слишком много H2 ({len(h2_tags)} шт)")
        score -= 3
    else:
        positives.append(f"✅ Оптимальное количество H2 ({len(h2_tags)} шт)")
    
    # Проверка emoji в заголовках
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"  # эмодзи лиц
        u"\U0001F300-\U0001F5FF"  # символы
        u"\U0001F680-\U0001F6FF"  # транспорт
        u"\U0001F1E0-\U0001F1FF"  # флаги
        u"\U00002700-\U000027BF"  # дингбаты
        "]+", flags=re.UNICODE)
    
    emoji_in_h2 = sum(1 for h2 in h2_tags if emoji_pattern.search(h2.get_text()))
    if emoji_in_h2 > 2:
        warnings.append(f"⚠️ Слишком много emoji в H2 ({emoji_in_h2} шт)")
        score -= 5
    
    # ==========================================
    # 2. КОНТЕНТ И ТЕКСТ
    # ==========================================
    
    # Извлекаем весь текст
    text = soup.get_text(separator=' ', strip=True)
    words = text.split()
    word_count = len(words)
    
    if word_count < 800:
        issues.append(f"❌ Слишком мало текста ({word_count} слов). Минимум 1000")
        score -= 10
    elif word_count < 1200:
        warnings.append(f"⚠️ Недостаточно текста ({word_count} слов). Рекомендуется 1500+")
        score -= 5
    elif word_count > 5000:
        warnings.append(f"⚠️ Очень много текста ({word_count} слов)")
        score -= 3
    else:
        positives.append(f"✅ Оптимальный объем ({word_count} слов)")
    
    # ==========================================
    # 3. ПЛОТНОСТЬ КЛЮЧЕВЫХ СЛОВ
    # ==========================================
    
    # Пытаемся определить основное ключевое слово из H1
    if h1_tags:
        h1_words = h1_tags[0].get_text().lower().split()
        # Берем 2-3 значимых слова (исключаем предлоги)
        stop_words = {'для', 'как', 'что', 'это', 'в', 'на', 'с', 'по', 'о', 'об', 'и', 'или'}
        keywords = [w for w in h1_words if w not in stop_words and len(w) > 3][:3]
        
        if keywords:
            # Считаем вхождения каждого ключевого слова
            text_lower = text.lower()
            for keyword in keywords:
                count = text_lower.count(keyword)
                density = (count / word_count) * 100 if word_count > 0 else 0
                
                if density > 2.5:
                    issues.append(f"❌ Переспам ключа '{keyword}': {count} раз ({density:.1f}%)")
                    score -= 15
                elif density > 1.5:
                    warnings.append(f"⚠️ Высокая плотность '{keyword}': {count} раз ({density:.1f}%)")
                    score -= 5
                elif density < 0.5 and count < 3:
                    warnings.append(f"⚠️ Мало упоминаний '{keyword}': всего {count} раз")
                    score -= 3
                else:
                    positives.append(f"✅ Плотность '{keyword}' оптимальна: {count} раз ({density:.1f}%)")
    
    # ==========================================
    # 4. AI-КЛИШЕ И ШАБЛОНЫ
    # ==========================================
    
    ai_phrases = [
        'давайте разберём',
        'давайте рассмотрим',
        'в современном мире',
        'как известно',
        'на сегодняшний день',
        'настоящим спасением',
        'идеальным решением',
        'стоит отметить',
        'важно понимать',
        'в заключение хочется сказать'
    ]
    
    text_lower = text.lower()
    found_phrases = [phrase for phrase in ai_phrases if phrase in text_lower]
    
    if len(found_phrases) > 5:
        issues.append(f"❌ Обнаружены AI-клише ({len(found_phrases)} шт): {', '.join(found_phrases[:3])}...")
        score -= 15
    elif len(found_phrases) > 2:
        warnings.append(f"⚠️ AI-клише ({len(found_phrases)} шт): {', '.join(found_phrases)}")
        score -= 8
    elif len(found_phrases) > 0:
        warnings.append(f"⚠️ Найдено клише: {', '.join(found_phrases)}")
        score -= 3
    else:
        positives.append("✅ AI-клише не обнаружены")
    
    # ==========================================
    # 5. СТРУКТУРА И ФОРМАТИРОВАНИЕ
    # ==========================================
    
    # Списки
    ul_tags = soup.find_all('ul')
    ol_tags = soup.find_all('ol')
    list_count = len(ul_tags) + len(ol_tags)
    
    if list_count < 2:
        warnings.append(f"⚠️ Мало списков ({list_count} шт)")
        score -= 5
    else:
        positives.append(f"✅ Есть списки ({list_count} шт)")
    
    # Таблицы
    tables = soup.find_all('table')
    if len(tables) > 0:
        positives.append(f"✅ Есть таблицы ({len(tables)} шт)")
    else:
        warnings.append("⚠️ Нет таблиц (рекомендуется для цен/сравнений)")
        score -= 3
    
    # Изображения
    images = soup.find_all('img')
    if len(images) < 2:
        warnings.append(f"⚠️ Мало изображений ({len(images)} шт)")
        score -= 5
    else:
        positives.append(f"✅ Есть изображения ({len(images)} шт)")
        
        # Проверка ALT-текста
        images_without_alt = sum(1 for img in images if not img.get('alt'))
        if images_without_alt > 0:
            warnings.append(f"⚠️ У {images_without_alt} изображений нет ALT-текста")
            score -= 3
    
    # ==========================================
    # 6. ВНУТРЕННИЕ ССЫЛКИ
    # ==========================================
    
    links = soup.find_all('a', href=True)
    internal_links = [link for link in links if link.get('href', '').startswith('/') or url.split('/')[2] in link.get('href', '')]
    
    if len(internal_links) < 2:
        warnings.append(f"⚠️ Мало внутренних ссылок ({len(internal_links)} шт)")
        score -= 5
    elif len(internal_links) > 10:
        warnings.append(f"⚠️ Слишком много ссылок ({len(internal_links)} шт)")
        score -= 3
    else:
        positives.append(f"✅ Внутренняя перелинковка ({len(internal_links)} ссылок)")
    
    # ==========================================
    # 7. СХЕМА РАЗМЕТКИ (Schema.org)
    # ==========================================
    
    schema_scripts = soup.find_all('script', type='application/ld+json')
    if len(schema_scripts) >= 2:
        positives.append(f"✅ Есть Schema.org разметка ({len(schema_scripts)} схем)")
    elif len(schema_scripts) == 1:
        warnings.append("⚠️ Только одна Schema.org схема (рекомендуется 2+)")
        score -= 3
    else:
        warnings.append("⚠️ Нет Schema.org разметки")
        score -= 5
    
    # ==========================================
    # 8. ЧИТАБЕЛЬНОСТЬ
    # ==========================================
    
    paragraphs = soup.find_all('p')
    if paragraphs:
        # Средняя длина абзаца
        avg_p_length = sum(len(p.get_text().split()) for p in paragraphs) / len(paragraphs)
        
        if avg_p_length > 100:
            warnings.append(f"⚠️ Слишком длинные абзацы (в среднем {int(avg_p_length)} слов)")
            score -= 5
        elif avg_p_length < 20:
            warnings.append(f"⚠️ Слишком короткие абзацы (в среднем {int(avg_p_length)} слов)")
            score -= 3
        else:
            positives.append(f"✅ Оптимальная длина абзацев ({int(avg_p_length)} слов)")
    
    # ==========================================
    # 9. CTA (Призывы к действию)
    # ==========================================
    
    cta_keywords = ['звоните', 'закажите', 'узнайте', 'оставьте заявку', 'бесплатно', 'консультация']
    cta_count = sum(text_lower.count(keyword) for keyword in cta_keywords)
    
    if cta_count < 2:
        warnings.append("⚠️ Мало призывов к действию")
        score -= 5
    else:
        positives.append(f"✅ Есть призывы к действию ({cta_count} шт)")
    
    # Ограничиваем score диапазоном 0-100
    score = max(0, min(100, score))
    
    return {
        'score': score,
        'word_count': word_count,
        'h1_count': len(h1_tags),
        'h2_count': len(h2_tags),
        'images_count': len(images),
        'links_count': len(internal_links),
        'issues': issues,
        'warnings': warnings,
        'positives': positives
    }


@bot.callback_query_handler(func=lambda call: call.data.startswith("analyze_article_"))
def handle_analyze_article(call):
    """Анализ опубликованной статьи"""
    parts = call.data.split("_")
    category_id = int(parts[2])
    bot_id = int(parts[3])
    url = "_".join(parts[4:])  # URL может содержать _
    
    user_id = call.from_user.id
    
    # Показываем процесс
    bot.answer_callback_query(call.id, "🔍 Анализирую статью...")
    
    try:
        # Отправляем временное сообщение
        analyzing_msg = bot.send_message(
            call.message.chat.id,
            "⏳ <b>Анализирую статью...</b>\n\n"
            "Проверяю:\n"
            "• SEO оптимизацию\n"
            "• Структуру контента\n"
            "• Плотность ключевых слов\n"
            "• AI-клише\n"
            "• Читабельность",
            parse_mode='HTML'
        )
        
        # Скачиваем страницу
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Анализируем
        analysis = analyze_seo_content(response.text, url)
        
        # Удаляем временное сообщение
        bot.delete_message(call.message.chat.id, analyzing_msg.message_id)
        
        # Формируем отчет
        score = analysis['score']
        
        # Определяем цвет оценки
        if score >= 80:
            score_emoji = "🟢"
            score_text = "Отлично"
        elif score >= 60:
            score_emoji = "🟡"
            score_text = "Хорошо"
        elif score >= 40:
            score_emoji = "🟠"
            score_text = "Удовлетворительно"
        else:
            score_emoji = "🔴"
            score_text = "Требует доработки"
        
        text = (
            f"📊 <b>ЭКСПЕРТНЫЙ АНАЛИЗ СТАТЬИ</b>\n\n"
            f"{score_emoji} <b>Оценка: {score}/100</b> — {score_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 <b>СТАТИСТИКА:</b>\n"
            f"• Слов: {analysis['word_count']:,}\n"
            f"• Заголовков H1: {analysis['h1_count']}\n"
            f"• Подзаголовков H2: {analysis['h2_count']}\n"
            f"• Изображений: {analysis['images_count']}\n"
            f"• Внутренних ссылок: {analysis['links_count']}\n\n"
        )
        
        # Критические проблемы
        if analysis['issues']:
            text += "🔴 <b>КРИТИЧЕСКИЕ ПРОБЛЕМЫ:</b>\n"
            for issue in analysis['issues'][:5]:  # Макс 5
                text += f"{issue}\n"
            text += "\n"
        
        # Предупреждения
        if analysis['warnings']:
            text += "🟡 <b>ПРЕДУПРЕЖДЕНИЯ:</b>\n"
            for warning in analysis['warnings'][:5]:  # Макс 5
                text += f"{warning}\n"
            text += "\n"
        
        # Сильные стороны
        if analysis['positives']:
            text += "🟢 <b>СИЛЬНЫЕ СТОРОНЫ:</b>\n"
            for positive in analysis['positives'][:5]:  # Макс 5
                text += f"{positive}\n"
            text += "\n"
        
        text += "━━━━━━━━━━━━━━━━━━━━━\n"
        
        # Рекомендации
        if score < 80:
            text += "💡 <b>РЕКОМЕНДАЦИИ:</b>\n"
            if score < 60:
                text += "• Исправьте критические проблемы\n"
                text += "• Добавьте уникального контента\n"
                text += "• Улучшите структуру статьи\n"
            else:
                text += "• Устраните предупреждения\n"
                text += "• Добавьте больше внутренних ссылок\n"
        else:
            text += "✨ <i>Статья соответствует требованиям SEO!</i>"
        
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("🌐 Открыть статью", url=url)
        )
        markup.row(
            types.InlineKeyboardButton("🔙 Назад", callback_data=f"platform_menu_manage_{category_id}_{bot_id}_website_main")
        )
        
        bot.send_message(
            call.message.chat.id,
            text,
            parse_mode='HTML',
            reply_markup=markup
        )
        
    except requests.exceptions.RequestException as e:
        bot.send_message(
            call.message.chat.id,
            f"❌ <b>Ошибка при загрузке страницы</b>\n\n"
            f"Не удалось получить содержимое статьи.\n"
            f"Проверьте, что страница доступна: {url}",
            parse_mode='HTML'
        )
    except Exception as e:
        bot.send_message(
            call.message.chat.id,
            f"❌ <b>Ошибка анализа</b>\n\n"
            f"Произошла ошибка: {str(e)}",
            parse_mode='HTML'
        )


print("✅ handlers/website/article_analyzer.py загружен")
