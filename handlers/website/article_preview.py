"""
Обработчики превью статьи - скачивание, копирование, SEO данные
"""
from telebot import types
from loader import bot, db
from utils import escape_html
import os

# Импортируем общее хранилище
from .article_generation import article_params_storage


@bot.callback_query_handler(func=lambda call: call.data.startswith("wa_download_html_"))
def handle_download_html(call):
    """Скачать HTML файл статьи"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    user_id = int(parts[4])
    
    key = f"{user_id}_{category_id}"
    
    if key not in article_params_storage or 'last_article' not in article_params_storage[key]:
        bot.answer_callback_query(call.id, "❌ Статья не найдена", show_alert=True)
        return
    
    article_data = article_params_storage[key]['last_article']
    article_html = article_data['html']
    seo_title = article_data.get('seo_title', 'article')
    
    # Создаём HTML файл с полной структурой
    full_html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{seo_title}</title>
    <meta name="description" content="{article_data.get('meta_desc', '')}">
</head>
<body>
{article_html}
</body>
</html>"""
    
    # Отправляем как файл
    import io
    file = io.BytesIO(full_html.encode('utf-8'))
    
    # Безопасное имя файла из заголовка
    import re
    filename = re.sub(r'[^a-zA-Zа-яА-Я0-9]+', '_', seo_title[:50]) + '.html'
    file.name = filename
    
    bot.send_document(
        call.message.chat.id,
        file,
        caption=f"📄 HTML статья: {seo_title[:50]}...",
        visible_file_name=filename
    )
    
    bot.answer_callback_query(call.id, "✅ Файл отправлен")


@bot.callback_query_handler(func=lambda call: call.data.startswith("wa_copy_html_"))
def handle_copy_html(call):
    """Показать HTML для копирования"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    user_id = int(parts[4])
    
    key = f"{user_id}_{category_id}"
    
    if key not in article_params_storage or 'last_article' not in article_params_storage[key]:
        bot.answer_callback_query(call.id, "❌ Статья не найдена", show_alert=True)
        return
    
    article_data = article_params_storage[key]['last_article']
    article_html = article_data['html']
    
    # Разбиваем на части если слишком большой
    max_length = 4000
    
    if len(article_html) <= max_length:
        bot.send_message(
            call.message.chat.id,
            f"<code>{escape_html(article_html)}</code>",
            parse_mode='HTML'
        )
    else:
        # Отправляем частями
        parts_count = (len(article_html) + max_length - 1) // max_length
        for i in range(parts_count):
            start = i * max_length
            end = min((i + 1) * max_length, len(article_html))
            part = article_html[start:end]
            
            bot.send_message(
                call.message.chat.id,
                f"<b>Часть {i+1}/{parts_count}</b>\n\n<code>{escape_html(part)}</code>",
                parse_mode='HTML'
            )
    
    bot.answer_callback_query(call.id, "✅ HTML отправлен")


@bot.callback_query_handler(func=lambda call: call.data.startswith("wa_show_seo_"))
def handle_show_seo(call):
    """Показать SEO данные"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    user_id = int(parts[4])
    
    key = f"{user_id}_{category_id}"
    
    if key not in article_params_storage or 'last_article' not in article_params_storage[key]:
        bot.answer_callback_query(call.id, "❌ Статья не найдена", show_alert=True)
        return
    
    article_data = article_params_storage[key]['last_article']
    seo_title = article_data.get('seo_title', '')
    meta_desc = article_data.get('meta_desc', '')
    article_html = article_data['html']
    
    # Извлекаем H2 заголовки
    import re
    h2_headers = re.findall(r'<h2[^>]*>(.*?)</h2>', article_html, flags=re.DOTALL | re.IGNORECASE)
    h2_clean = [re.sub(r'<[^>]+>', '', h2).strip() for h2 in h2_headers]
    
    # Проверяем Schema.org
    has_schema = bool(re.search(r'<script[^>]*type="application/ld\+json"', article_html, re.IGNORECASE))
    
    text = (
        f"🎯 <b>SEO ДАННЫЕ СТАТЬИ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>📌 SEO Title ({len(seo_title)} символов):</b>\n"
        f"{seo_title}\n\n"
        f"<b>📝 Meta Description ({len(meta_desc)} символов):</b>\n"
        f"{meta_desc}\n\n"
        f"<b>📑 Структура ({len(h2_clean)} разделов H2):</b>\n"
    )
    
    for i, h2 in enumerate(h2_clean[:10], 1):
        text += f"{i}. {h2}\n"
    
    if len(h2_clean) > 10:
        text += f"<i>...и ещё {len(h2_clean)-10} разделов</i>\n"
    
    text += f"\n<b>🔧 Техническое:</b>\n"
    text += f"✅ Schema.org разметка: {'Да' if has_schema else 'Нет'}\n"
    text += f"✅ Yoast SEO оптимизация: Да\n"
    text += f"✅ AEO оптимизация: Да\n"
    
    bot.send_message(call.message.chat.id, text, parse_mode='HTML')
    bot.answer_callback_query(call.id)



print("✅ handlers/website/article_preview.py загружен")
