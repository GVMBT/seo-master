"""
Обработчик публикации статьи на WordPress
"""
from telebot import types
from loader import bot, db
from utils import escape_html
import os

# Импортируем общее хранилище
from .article_generation import article_params_storage


@bot.callback_query_handler(func=lambda call: call.data.startswith("wa_publish_wp_"))
def handle_publish_wordpress(call):
    """Опубликовать статью на WordPress"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    bot_id = int(parts[4])
    user_id = int(parts[5])
    
    key = f"{user_id}_{category_id}"
    
    if key not in article_params_storage or 'last_article' not in article_params_storage[key]:
        bot.answer_callback_query(call.id, "❌ Статья не найдена", show_alert=True)
        return
    
    article_data = article_params_storage[key]['last_article']
    
    # Получаем данные WordPress
    bot_data = db.get_bot(bot_id)
    if not bot_data:
        bot.answer_callback_query(call.id, "❌ Бот не найден", show_alert=True)
        return
    
    wp_creds = bot_data.get('wordpress_credentials', {})
    if not wp_creds or not wp_creds.get('url'):
        bot.answer_callback_query(call.id, "❌ WordPress не подключен", show_alert=True)
        return
    
    bot.answer_callback_query(call.id, "🚀 Публикую на WordPress...")
    
    # Показываем прогресс
    try:
        bot.edit_message_caption(
            f"🚀 <b>ПУБЛИКАЦИЯ НА WORDPRESS...</b>\n\n"
            f"⏳ Загружаю изображения...\n"
            f"⏳ Создаю пост...\n\n"
            f"Подождите 10-20 секунд...",
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML'
        )
    except Exception:
        pass
    
    # Публикуем
    from .wordpress_api import publish_article_to_wordpress
    
    # Путь к обложке
    cover_path = article_data.get('cover_path')
    images_paths = [cover_path] if cover_path else []
    
    result = publish_article_to_wordpress(
        wp_credentials=wp_creds,
        article_html=article_data['html'],
        seo_title=article_data['seo_title'],
        meta_description=article_data['meta_desc'],
        images_paths=images_paths,
        status='draft'  # По умолчанию черновик
    )
    
    if result.get('success'):
        text = (
            f"✅ <b>СТАТЬЯ ОПУБЛИКОВАНА!</b>\n\n"
            f"🔗 <b>URL:</b>\n{result.get('post_url', '')}\n\n"
            f"💡 <i>Статья создана как черновик.\nВы можете отредактировать и опубликовать её в WordPress.</i>"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("🌐 Открыть статью", url=result.get('post_url', ''))
        )
        
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    else:
        bot.send_message(
            call.message.chat.id,
            f"❌ <b>Ошибка публикации:</b>\n{result.get('message', 'Неизвестная ошибка')}",
            parse_mode='HTML'
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("wa_show_html_"))
def handle_show_html(call):
    """Показать HTML код статьи"""
    parts = call.data.split("_")
    category_id = int(parts[3])
    user_id = int(parts[4])
    
    key = f"{user_id}_{category_id}"
    
    if key not in article_params_storage or 'last_article' not in article_params_storage[key]:
        bot.answer_callback_query(call.id, "❌ Статья не найдена", show_alert=True)
        return
    
    article_data = article_params_storage[key]['last_article']
    article_html = article_data['html']
    
    # Отправляем HTML как файл (если большой)
    if len(article_html) > 4000:
        import io
        file = io.BytesIO(article_html.encode('utf-8'))
        file.name = "article.html"
        
        bot.send_document(
            call.message.chat.id,
            file,
            caption="📄 HTML код статьи"
        )
    else:
        # Отправляем как текст
        bot.send_message(
            call.message.chat.id,
            f"<code>{escape_html(article_html[:4000])}</code>",
            parse_mode='HTML'
        )
    
    bot.answer_callback_query(call.id)


print("✅ handlers/website/article_publishing.py загружен")
