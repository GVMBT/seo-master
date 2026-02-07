"""
Universal Platform Settings - Универсальные настройки для всех платформ
Ссылка на сайт, места публикации и т.д.
"""
from telebot import types
from loader import bot, db
from utils import escape_html, safe_answer_callback
import json


# Хранилище состояний для ввода ссылки
platform_link_state = {}

# Названия платформ
PLATFORM_NAMES = {
    'pinterest': 'Pinterest',
    'vk': 'VK',
    'telegram': 'Telegram',
    'website': 'Website'
}


# ═══════════════════════════════════════════════════════════════
# ССЫЛКА НА САЙТ (ДЛЯ ВСЕХ ПЛАТФОРМ)
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith('platform_link_')
                            and not call.data.startswith('platform_link_edit_')
                            and not call.data.startswith('platform_link_delete_'))
def handle_platform_link(call):
    """Настройка ссылки на сайт для любой платформы"""
    try:
        parts = call.data.split('_')
        # platform_link_pinterest_123_456_789
        platform_type = parts[2]
        category_id = int(parts[3])
        bot_id = int(parts[4])
        platform_id = "_".join(parts[5:]) if len(parts) > 5 else "default"
        
        user_id = call.from_user.id
        
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
            return
        
        category_name = category.get('name', 'Без названия')
        platform_name = PLATFORM_NAMES.get(platform_type, platform_type.upper())
        
        # Получаем текущую ссылку
        settings = category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        current_link = settings.get(f'{platform_type}_link', '')
        
        # Текст
        if current_link:
            link_text = f"<code>{escape_html(current_link)}</code>"
        else:
            link_text = "Не указана"
        
        text = (
            f"🔗 <b>ССЫЛКА НА САЙТ</b>\n"
            f"📱 Платформа: {platform_name}\n"
            f"📂 Категория: {escape_html(category_name)}\n"
            "━━━━━━━━━━━━━━\n\n"
            f"<b>Текущая ссылка:</b>\n{link_text}\n\n"
            "Эта ссылка будет добавлена ко всем постам.\n"
            "Пользователи смогут перейти на ваш сайт.\n\n"
            "💡 <b>Выберите действие:</b>"
        )
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        markup.add(
            types.InlineKeyboardButton(
                "✏️ Изменить ссылку",
                callback_data=f"platform_link_edit_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            )
        )
        
        if current_link:
            markup.add(
                types.InlineKeyboardButton(
                    "❌ Удалить ссылку",
                    callback_data=f"platform_link_delete_{platform_type}_{category_id}_{bot_id}_{platform_id}"
                )
            )
        
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"platform_menu_{category_id}_{bot_id}_{platform_type}_{platform_id}"
            )
        )
        
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='HTML'
        )
        
        safe_answer_callback(bot, call.id)
        
    except Exception as e:
        print(f"❌ Ошибка в handle_platform_link: {e}")
        import traceback
        traceback.print_exc()
        safe_answer_callback(bot, call.id, "❌ Ошибка", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith('platform_link_edit_'))
def handle_platform_link_edit(call):
    """Начало редактирования ссылки"""
    try:
        parts = call.data.split('_')
        platform_type = parts[3]
        category_id = int(parts[4])
        bot_id = int(parts[5])
        platform_id = "_".join(parts[6:]) if len(parts) > 6 else "default"
        
        user_id = call.from_user.id
        
        # Сохраняем состояние
        platform_link_state[user_id] = {
            'platform_type': platform_type,
            'category_id': category_id,
            'bot_id': bot_id,
            'platform_id': platform_id,
            'message_id': call.message.message_id
        }
        
        platform_name = PLATFORM_NAMES.get(platform_type, platform_type.upper())
        
        text = (
            "🔗 <b>ВВОД ССЫЛКИ</b>\n"
            f"📱 Платформа: {platform_name}\n"
            "━━━━━━━━━━━━━━\n\n"
            "Введите ссылку на ваш сайт.\n\n"
            "<b>Примеры:</b>\n"
            "• <code>https://example.com</code>\n"
            "• <code>https://mysite.ru/products</code>\n"
            "• <code>https://shop.com</code>\n\n"
            "💡 Ссылка должна начинаться с <code>http://</code> или <code>https://</code>"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "❌ Отмена",
                callback_data=f"platform_link_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            )
        )
        
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='HTML'
        )
        
        bot.register_next_step_handler(call.message, process_platform_link, user_id)
        
        safe_answer_callback(bot, call.id)
        
    except Exception as e:
        print(f"❌ Ошибка в handle_platform_link_edit: {e}")
        import traceback
        traceback.print_exc()
        safe_answer_callback(bot, call.id, "❌ Ошибка", show_alert=True)


def process_platform_link(message, user_id):
    """Обработка введённой ссылки"""
    try:
        if user_id not in platform_link_state:
            bot.send_message(message.chat.id, "❌ Сессия истекла")
            return
        
        state = platform_link_state[user_id]
        platform_type = state['platform_type']
        category_id = state['category_id']
        bot_id = state['bot_id']
        platform_id = state['platform_id']
        
        # Проверяем отмену
        if message.text.startswith('/') or message.text == "❌ Отмена":
            del platform_link_state[user_id]
            bot.send_message(message.chat.id, "❌ Отменено")
            return
        
        link = message.text.strip()
        
        # Валидация ссылки
        if not link.startswith('http://') and not link.startswith('https://'):
            bot.send_message(
                message.chat.id,
                "❌ Неверный формат ссылки!\n\n"
                "Ссылка должна начинаться с <code>http://</code> или <code>https://</code>\n\n"
                "Попробуйте ещё раз:",
                parse_mode='HTML'
            )
            bot.register_next_step_handler(message, process_platform_link, user_id)
            return
        
        # Сохраняем ссылку
        category = db.get_category(category_id)
        if not category:
            del platform_link_state[user_id]
            bot.send_message(message.chat.id, "❌ Категория не найдена")
            return
        
        settings = category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        settings[f'{platform_type}_link'] = link
        
        # Обновляем в БД
        db.cursor.execute("""
            UPDATE categories
            SET settings = %s::jsonb
            WHERE id = %s
        """, (json.dumps(settings), category_id))
        db.conn.commit()
        
        # Очищаем состояние
        del platform_link_state[user_id]
        
        platform_name = PLATFORM_NAMES.get(platform_type, platform_type.upper())
        
        # Показываем результат
        text = (
            "✅ <b>ССЫЛКА СОХРАНЕНА!</b>\n"
            f"📱 Платформа: {platform_name}\n\n"
            f"Ссылка: <code>{escape_html(link)}</code>\n\n"
            "Теперь все посты будут содержать эту ссылку."
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад к настройкам",
                callback_data=f"platform_link_{platform_type}_{category_id}_{bot_id}_{platform_id}"
            )
        )
        
        bot.send_message(
            message.chat.id,
            text,
            reply_markup=markup,
            parse_mode='HTML'
        )
        
    except Exception as e:
        print(f"❌ Ошибка в process_platform_link: {e}")
        import traceback
        traceback.print_exc()
        if user_id in platform_link_state:
            del platform_link_state[user_id]
        bot.send_message(message.chat.id, f"❌ Ошибка сохранения: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith('platform_link_delete_'))
def handle_platform_link_delete(call):
    """Удаление ссылки"""
    try:
        parts = call.data.split('_')
        platform_type = parts[3]
        category_id = int(parts[4])
        bot_id = int(parts[5])
        platform_id = "_".join(parts[6:]) if len(parts) > 6 else "default"
        
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
            return
        
        # Удаляем ссылку
        settings = category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        link_key = f'{platform_type}_link'
        if link_key in settings:
            del settings[link_key]
        
        # Обновляем в БД
        db.cursor.execute("""
            UPDATE categories
            SET settings = %s::jsonb
            WHERE id = %s
        """, (json.dumps(settings), category_id))
        db.conn.commit()
        
        safe_answer_callback(bot, call.id, "✅ Ссылка удалена")
        
        # Возвращаемся к настройкам
        call.data = f"platform_link_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        handle_platform_link(call)
        
    except Exception as e:
        print(f"❌ Ошибка в handle_platform_link_delete: {e}")
        import traceback
        traceback.print_exc()
        safe_answer_callback(bot, call.id, "❌ Ошибка", show_alert=True)


print("✅ handlers/universal_platform_settings.py загружен")
