# -*- coding: utf-8 -*-
"""
Обработчик текстового ввода для настроек WordPress
ВАЖНО: Этот файл должен загружаться ПОСЛЕДНИМ чтобы не перехватывать команды!
"""
from loader import bot, db
from utils import escape_html

@bot.message_handler(func=lambda message: message.text and not message.text.startswith('/'), content_types=['text'])
def handle_wp_text_input(message):
    """Обработка ввода рубрик/меток/SEO настроек"""
    user_id = message.from_user.id
    
    from handlers.state_manager import get_user_state, clear_user_state
    state = get_user_state(user_id)
    
    # Обрабатываем только если есть активное состояние
    if not state:
        return
    
    state_type = state.get('state')
    state_data = state.get('data', {})
    
    # Обработка команды отмены
    if message.text == '/cancel':
        clear_user_state(user_id)
        bot.send_message(message.chat.id, "❌ Отменено")
        return
    
    if state_type == 'waiting_wp_categories':
        # Обработка ввода рубрик
        idx = state_data.get('idx')
        categories_text = message.text.strip()
        
        # Сохраняем рубрики
        user = db.get_user(user_id)
        connections = user.get('platform_connections', {})
        websites = connections.get('websites', [])
        
        if idx < len(websites):
            websites[idx]['wp_categories'] = categories_text
            
            if not isinstance(connections, dict):
                connections = {}
            connections['websites'] = websites
            
            db.update_user(user_id, {'platform_connections': connections})
            
            clear_user_state(user_id)
            
            # Попытка создать рубрики в WordPress сразу
            site = websites[idx]
            wp_url = site.get('url', '').rstrip('/')
            wp_login = site.get('username', '')
            wp_password = site.get('password', '')
            
            created_categories = []
            failed_categories = []
            
            if wp_url and wp_login and wp_password:
                from handlers.website.wordpress_api import create_wordpress_category, get_wordpress_categories
                
                # Получаем существующие категории
                existing_cats = get_wordpress_categories(wp_url, wp_login, wp_password)
                existing_names = [cat['name'].lower() for cat in existing_cats]
                
                # Создаем новые категории
                category_names = [c.strip() for c in categories_text.split(',') if c.strip()]
                
                for cat_name in category_names:
                    if cat_name.lower() not in existing_names:
                        result = create_wordpress_category(wp_url, wp_login, wp_password, cat_name)
                        if result:
                            created_categories.append(cat_name)
                        else:
                            failed_categories.append(cat_name)
            
            # Формируем сообщение
            message_parts = [f"✅ <b>Рубрики сохранены!</b>\n\n<code>{escape_html(categories_text)}</code>"]
            
            if created_categories:
                message_parts.append(f"\n\n✅ Созданы в WordPress:\n" + "\n".join([f"• {escape_html(c)}" for c in created_categories]))
            
            if failed_categories:
                message_parts.append(f"\n\n⚠️ Не удалось создать:\n" + "\n".join([f"• {escape_html(c)}" for c in failed_categories]))
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 К настройкам сайта", callback_data=f"view_website_{idx}"))
            
            bot.send_message(
                message.chat.id,
                "".join(message_parts),
                reply_markup=markup,
                parse_mode='HTML'
            )
        else:
            bot.send_message(message.chat.id, "❌ Ошибка: сайт не найден")
    
    elif state_type == 'waiting_wp_tags':
        # Обработка ввода меток
        idx = state_data.get('idx')
        tags_text = message.text.strip()
        
        # Сохраняем метки
        user = db.get_user(user_id)
        connections = user.get('platform_connections', {})
        websites = connections.get('websites', [])
        
        if idx < len(websites):
            websites[idx]['wp_tags'] = tags_text
            
            if not isinstance(connections, dict):
                connections = {}
            connections['websites'] = websites
            
            db.update_user(user_id, {'platform_connections': connections})
            
            clear_user_state(user_id)
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 К настройкам сайта", callback_data=f"view_website_{idx}"))
            
            bot.send_message(
                message.chat.id,
                f"✅ <b>Метки сохранены!</b>\n\n<code>{escape_html(tags_text)}</code>",
                reply_markup=markup,
                parse_mode='HTML'
            )
        else:
            bot.send_message(message.chat.id, "❌ Ошибка: сайт не найден")
    
    elif state_type == 'waiting_seo_canonical':
        # Обработка ввода Canonical URL
        idx = state_data.get('idx')
        canonical_url = message.text.strip()
        
        # Валидация URL
        if not canonical_url.startswith('http'):
            bot.send_message(
                message.chat.id,
                "❌ URL должен начинаться с http:// или https://\n\nПопробуйте ещё раз или отправьте /cancel"
            )
            return
        
        # Сохраняем Canonical URL
        user = db.get_user(user_id)
        connections = user.get('platform_connections', {})
        websites = connections.get('websites', [])
        
        if idx < len(websites):
            websites[idx]['seo_canonical'] = canonical_url
            
            if not isinstance(connections, dict):
                connections = {}
            connections['websites'] = websites
            
            db.update_user(user_id, {'platform_connections': connections})
            
            clear_user_state(user_id)
            
            bot.send_message(
                message.chat.id,
                f"✅ <b>Canonical URL сохранён!</b>\n\n<code>{escape_html(canonical_url)}</code>",
                parse_mode='HTML'
            )
        else:
            bot.send_message(message.chat.id, "❌ Ошибка: сайт не найден")
    
    elif state_type == 'waiting_external_links':
        # Обработка ввода внешних ссылок
        idx = state_data.get('idx')
        links_text = message.text.strip()
        
        # Валидация - проверяем что есть хотя бы одна ссылка
        if not ('http://' in links_text or 'https://' in links_text):
            bot.send_message(
                message.chat.id,
                "❌ Не найдено ни одной ссылки (должна начинаться с http:// или https://)\n\nПопробуйте ещё раз или отправьте /cancel"
            )
            return
        
        # Сохраняем внешние ссылки
        user = db.get_user(user_id)
        connections = user.get('platform_connections', {})
        websites = connections.get('websites', [])
        
        if idx < len(websites):
            websites[idx]['external_links'] = links_text
            
            if not isinstance(connections, dict):
                connections = {}
            connections['websites'] = websites
            
            db.update_user(user_id, {'platform_connections': connections})
            
            # Подсчитываем количество ссылок
            num_links = links_text.count('http')
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 К настройкам сайта", callback_data=f"view_website_{state['website_idx']}"))
            
            bot.send_message(
                message.chat.id,
                f"✅ <b>Внешние ссылки сохранены!</b>\n\n"
                f"Добавлено ссылок: {num_links}\n\n"
                f"<code>{escape_html(links_text[:200])}</code>",
                reply_markup=markup,
                parse_mode='HTML'
            )
            
            clear_user_state(user_id)
        else:
            bot.send_message(message.chat.id, "❌ Ошибка: сайт не найден")


print("✅ handlers/text_input_handler.py загружен (обработчик текстового ввода)")
