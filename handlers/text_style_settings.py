"""
Text Style Settings - Настройка стиля текста и текста на изображениях
"""
from telebot import types
from loader import bot, db
from utils import escape_html, safe_answer_callback
import json


# ═══════════════════════════════════════════════════════════════
# СТИЛИ ТЕКСТА
# ═══════════════════════════════════════════════════════════════

TEXT_STYLES = {
    'sales': {
        'name': '💰 Рекламный',
        'description': 'Продающий текст с призывом к действию'
    },
    'motivational': {
        'name': '🔥 Мотивационный',
        'description': 'Вдохновляющий текст с энергией'
    },
    'friendly': {
        'name': '😊 Дружелюбный',
        'description': 'Тёплый и близкий стиль общения'
    },
    'conversational': {
        'name': '💬 Разговорный',
        'description': 'Простой разговорный язык'
    },
    'professional': {
        'name': '👔 Профессиональный',
        'description': 'Деловой и формальный стиль'
    },
    'creative': {
        'name': '🎨 Креативный',
        'description': 'Яркий и необычный текст'
    },
    'informative': {
        'name': '📚 Информативный',
        'description': 'Фактический и образовательный'
    },
    'humorous': {
        'name': '😄 С юмором',
        'description': 'Лёгкий юмористический стиль'
    },
    'masculine': {
        'name': '💪 Мужской',
        'description': 'Уверенный и прямой стиль'
    },
    'feminine': {
        'name': '💅 Женский',
        'description': 'Мягкий и элегантный стиль'
    }
}


# ═══════════════════════════════════════════════════════════════
# ТЕКСТ НА ИЗОБРАЖЕНИИ
# ═══════════════════════════════════════════════════════════════

TEXT_ON_IMAGE_OPTIONS = {
    'with_text': {
        'name': '📝 С текстом',
        'prompt': 'text overlay, typography, branded text, promotional text on image',
        'description': 'AI добавит текст/надписи на изображение'
    },
    'without_text': {
        'name': '🖼 Без текста',
        'prompt': 'no text, clean image, no typography, no letters, no words',
        'description': 'Чистое изображение без текста и надписей'
    },
    'random': {
        'name': '🎲 Случайно',
        'prompt': None,  # Выбирается случайно при генерации
        'description': 'Случайно выбирает (с текстом или без)'
    }
}


@bot.callback_query_handler(func=lambda call: call.data.startswith('platform_style_'))
def handle_text_style_main(call):
    """Главное меню стиля текста - множественный выбор стилей"""
    try:
        parts = call.data.split('_')
        # platform_style_pinterest_123_456
        platform_type = parts[2]
        category_id = int(parts[3])
        bot_id = int(parts[4])
        
        user_id = call.from_user.id
        
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
            return
        
        # Получаем бота для platform_id
        bot_data = db.get_bot(bot_id)
        if not bot_data:
            safe_answer_callback(bot, call.id, "❌ Бот не найден", show_alert=True)
            return
        
        # Получаем platform_id из подключенных платформ
        connected_platforms = bot_data.get('connected_platforms', {})
        if isinstance(connected_platforms, str):
            import json
            connected_platforms = json.loads(connected_platforms)
        
        platform_id = 'default'
        
        # Проверяем новую структуру (без 's')
        if platform_type in connected_platforms:
            platform_list = connected_platforms[platform_type]
            if isinstance(platform_list, list) and platform_list:
                if isinstance(platform_list[0], dict):
                    platform_id = platform_list[0].get('id', 'default')
                else:
                    platform_id = platform_list[0]
        
        # Проверяем старую структуру (с 's')
        if platform_id == 'default':
            platforms_key = platform_type + 's'
            if platforms_key in connected_platforms:
                platform_list = connected_platforms[platforms_key]
                if isinstance(platform_list, list) and platform_list:
                    platform_id = platform_list[0]
        
        category_name = category.get('name', 'Без названия')
        
        # Получаем текущие настройки
        settings = category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        # Стили текста теперь массив
        selected_styles = settings.get(f'{platform_type}_text_styles', ['conversational'])
        if not isinstance(selected_styles, list):
            selected_styles = [selected_styles]  # Обратная совместимость
        
        # Формируем текст выбранных стилей
        if selected_styles:
            selected_names = [TEXT_STYLES.get(s, {}).get('name', s) for s in selected_styles]
            styles_text = ', '.join(selected_names)
        else:
            styles_text = 'Не выбрано'
        
        # Текст
        text = (
            f"✍️ <b>СТИЛЬ ТЕКСТА</b>\n"
            f"📱 Платформа: {platform_type.upper()}\n"
            f"📂 Категория: {escape_html(category_name)}\n"
            "━━━━━━━━━━━━━━\n\n"
            f"<b>Выбранные стили:</b> {styles_text}\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "<b>💡 ВЫБЕРИТЕ СТИЛИ ТЕКСТА:</b>\n\n"
            "Можно выбрать несколько стилей.\n"
            "При генерации будет случайно выбран один из отмеченных.\n\n"
            "Стиль определяет тон и манеру написания постов."
        )
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        # Кнопки стилей текста (по 2 в ряд) только с ✅
        buttons = []
        for style_code, style_data in TEXT_STYLES.items():
            is_selected = style_code in selected_styles
            checkmark = " ✅" if is_selected else ""
            
            buttons.append(
                types.InlineKeyboardButton(
                    f"{style_data['name']}{checkmark}",
                    callback_data=f"text_style_toggle_{platform_type}_{category_id}_{bot_id}_{style_code}"
                )
            )
        
        # Добавляем кнопки по 2 в ряд
        for i in range(0, len(buttons), 2):
            if i + 1 < len(buttons):
                markup.row(buttons[i], buttons[i + 1])
            else:
                markup.row(buttons[i])
        
        # Кнопка назад - возврат в ГЛАВНОЕ МЕНЮ ПЛАТФОРМЫ
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
        print(f"❌ Ошибка в handle_text_style_main: {e}")
        import traceback
        traceback.print_exc()
        safe_answer_callback(bot, call.id, "❌ Ошибка", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith('text_style_toggle_'))
def handle_text_style_toggle(call):
    """Переключение выбора стиля текста (чекбокс)"""
    try:
        parts = call.data.split('_')
        # text_style_toggle_pinterest_123_456_sales
        platform_type = parts[3]
        category_id = int(parts[4])
        bot_id = int(parts[5])
        style_code = parts[6]
        
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
            return
        
        # Получаем настройки
        settings = category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        # Получаем текущие выбранные стили
        selected_styles = settings.get(f'{platform_type}_text_styles', ['conversational'])
        if not isinstance(selected_styles, list):
            selected_styles = [selected_styles]  # Обратная совместимость
        
        # Переключаем стиль
        if style_code in selected_styles:
            # Убираем стиль (но оставляем хотя бы один)
            if len(selected_styles) > 1:
                selected_styles.remove(style_code)
                action = "убран"
            else:
                safe_answer_callback(bot, call.id, "⚠️ Должен быть выбран хотя бы один стиль", show_alert=True)
                return
        else:
            # Добавляем стиль
            selected_styles.append(style_code)
            action = "добавлен"
        
        # Сохраняем
        settings[f'{platform_type}_text_styles'] = selected_styles
        
        # Обновляем в БД
        db.cursor.execute("""
            UPDATE categories
            SET settings = %s::jsonb
            WHERE id = %s
        """, (json.dumps(settings), category_id))
        db.conn.commit()
        
        style_name = TEXT_STYLES[style_code]['name']
        bot.answer_callback_query(
            call.id,
            f"{'✅' if action == 'добавлен' else '❌'} {style_name} {action}"
        )
        
        # Обновляем интерфейс
        call.data = f"platform_style_{platform_type}_{category_id}_{bot_id}"
        handle_text_style_main(call)
        
    except Exception as e:
        print(f"❌ Ошибка в handle_text_style_toggle: {e}")
        import traceback
        traceback.print_exc()
        safe_answer_callback(bot, call.id, "❌ Ошибка", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith('text_styles_all_'))
def handle_text_styles_all(call):
    """Выбрать все стили"""
    try:
        parts = call.data.split('_')
        # text_styles_all_pinterest_123_456
        platform_type = parts[3]
        category_id = int(parts[4])
        bot_id = int(parts[5])
        
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
            return
        
        # Получаем настройки
        settings = category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        # Выбираем все стили
        all_styles = list(TEXT_STYLES.keys())
        settings[f'{platform_type}_text_styles'] = all_styles
        
        # Обновляем в БД
        db.cursor.execute("""
            UPDATE categories
            SET settings = %s::jsonb
            WHERE id = %s
        """, (json.dumps(settings), category_id))
        db.conn.commit()
        
        safe_answer_callback(bot, call.id, "✅ Выбраны все стили")
        
        # Обновляем интерфейс
        call.data = f"platform_style_{platform_type}_{category_id}_{bot_id}"
        handle_text_style_main(call)
        
    except Exception as e:
        print(f"❌ Ошибка в handle_text_styles_all: {e}")
        import traceback
        traceback.print_exc()
        safe_answer_callback(bot, call.id, "❌ Ошибка", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith('text_styles_clear_'))
def handle_text_styles_clear(call):
    """Сбросить выбор стилей (оставить только разговорный)"""
    try:
        parts = call.data.split('_')
        # text_styles_clear_pinterest_123_456
        platform_type = parts[3]
        category_id = int(parts[4])
        bot_id = int(parts[5])
        
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
            return
        
        # Получаем настройки
        settings = category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        # Сбрасываем на разговорный по умолчанию
        settings[f'{platform_type}_text_styles'] = ['conversational']
        
        # Обновляем в БД
        db.cursor.execute("""
            UPDATE categories
            SET settings = %s::jsonb
            WHERE id = %s
        """, (json.dumps(settings), category_id))
        db.conn.commit()
        
        safe_answer_callback(bot, call.id, "✅ Выбран только 💬 Разговорный")
        
        # Обновляем интерфейс
        call.data = f"platform_style_{platform_type}_{category_id}_{bot_id}"
        handle_text_style_main(call)
        
    except Exception as e:
        print(f"❌ Ошибка в handle_text_styles_clear: {e}")
        import traceback
        traceback.print_exc()
        safe_answer_callback(bot, call.id, "❌ Ошибка", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith('text_on_image_menu_'))
def handle_text_on_image_menu(call):
    """Меню выбора текста на изображении"""
    try:
        parts = call.data.split('_')
        # text_on_image_menu_pinterest_123_456
        platform_type = parts[4]
        category_id = int(parts[5])
        bot_id = int(parts[6])
        
        user_id = call.from_user.id
        
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
            return
        
        # Получаем бота для platform_id
        bot_data = db.get_bot(bot_id)
        if not bot_data:
            safe_answer_callback(bot, call.id, "❌ Бот не найден", show_alert=True)
            return
        
        # Получаем platform_id из подключенных платформ
        connected_platforms = bot_data.get('connected_platforms', {})
        if isinstance(connected_platforms, str):
            connected_platforms = json.loads(connected_platforms)
        
        platform_id = 'default'
        
        # Проверяем новую структуру (без 's')
        if platform_type in connected_platforms:
            platform_list = connected_platforms[platform_type]
            if isinstance(platform_list, list) and platform_list:
                if isinstance(platform_list[0], dict):
                    platform_id = platform_list[0].get('id', 'default')
                else:
                    platform_id = platform_list[0]
        
        # Проверяем старую структуру (с 's')
        if platform_id == 'default':
            platforms_key = platform_type + 's'
            if platforms_key in connected_platforms:
                platform_list = connected_platforms[platforms_key]
                if isinstance(platform_list, list) and platform_list:
                    platform_id = platform_list[0]
        
        category_name = category.get('name', 'Без названия')
        
        # Получаем текущие настройки
        settings = category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        current_text_on_image = settings.get(f'{platform_type}_text_on_image', 'without_text')
        
        # Название опции
        option_name = TEXT_ON_IMAGE_OPTIONS.get(current_text_on_image, {}).get('name', 'Не выбрано')
        
        # Текст
        text = (
            f"🖼 <b>ТЕКСТ НА ИЗОБРАЖЕНИИ</b>\n"
            f"📱 Платформа: {platform_type.upper()}\n"
            f"📂 Категория: {escape_html(category_name)}\n"
            "━━━━━━━━━━━━━━\n\n"
            f"<b>Текущая настройка:</b> {option_name}\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "<b>💡 ТЕКСТ НА ИЗОБРАЖЕНИИ</b>\n\n"
            "Выберите, как AI должен генерировать изображения:\n\n"
            "📝 <b>С текстом</b>\n"
            "AI добавит текст/надписи на изображение.\n"
            "Подходит для: рекламных постов, акций, брендинга.\n\n"
            "🖼 <b>Без текста</b>\n"
            "Чистое изображение без текста и надписей.\n"
            "Подходит для: каталогов, Pinterest, эстетики.\n\n"
            "🎲 <b>Случайно</b>\n"
            "При каждой генерации случайно выбирает (с текстом или без).\n"
            "Для разнообразия контента.\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "💡 <b>Рекомендация для Pinterest:</b>\n"
            "Лучше выбрать «Без текста» - Pinterest не любит изображения с текстом."
        )
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        # Кнопки выбора
        for option_code, option_data in TEXT_ON_IMAGE_OPTIONS.items():
            is_selected = option_code == current_text_on_image
            button_text = f"✅ {option_data['name']}" if is_selected else f"☐ {option_data['name']}"
            
            markup.add(
                types.InlineKeyboardButton(
                    button_text,
                    callback_data=f"text_on_image_{platform_type}_{category_id}_{bot_id}_{option_code}"
                )
            )
        
        # Кнопка назад - возврат к выбору стилей текста
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"platform_style_{platform_type}_{category_id}_{bot_id}_{platform_id}"
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
        print(f"❌ Ошибка в handle_text_on_image_menu: {e}")
        import traceback
        traceback.print_exc()
        safe_answer_callback(bot, call.id, "❌ Ошибка", show_alert=True)
@bot.callback_query_handler(func=lambda call: call.data.startswith('text_on_image_'))
def handle_text_on_image_toggle(call):
    """Переключение настройки текста на изображении"""
    try:
        parts = call.data.split('_')
        # text_on_image_pinterest_123_456_with_text
        platform_type = parts[3]
        category_id = int(parts[4])
        bot_id = int(parts[5])
        option_code = parts[6]
        
        # Получаем категорию
        category = db.get_category(category_id)
        if not category:
            safe_answer_callback(bot, call.id, "❌ Категория не найдена", show_alert=True)
            return
        
        # Получаем настройки
        settings = category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        # Сохраняем выбор
        settings[f'{platform_type}_text_on_image'] = option_code
        
        # Обновляем в БД
        db.cursor.execute("""
            UPDATE categories
            SET settings = %s::jsonb
            WHERE id = %s
        """, (json.dumps(settings), category_id))
        db.conn.commit()
        
        bot.answer_callback_query(
            call.id,
            f"✅ Выбрано: {TEXT_ON_IMAGE_OPTIONS[option_code]['name']}"
        )
        
        # Возвращаемся в меню настройки текста на изображении
        call.data = f"text_on_image_menu_{platform_type}_{category_id}_{bot_id}"
        handle_text_on_image_menu(call)
        
    except Exception as e:
        print(f"❌ Ошибка в handle_text_on_image_toggle: {e}")
        import traceback
        traceback.print_exc()
        safe_answer_callback(bot, call.id, "❌ Ошибка", show_alert=True)


def get_text_on_image_prompt(category, platform_type):
    """
    Получить промпт для текста на изображении
    
    Args:
        category: dict - данные категории
        platform_type: str - тип платформы
        
    Returns:
        str or None: промпт для добавления в генерацию изображения
    """
    settings = category.get('settings', {})
    if isinstance(settings, str):
        settings = json.loads(settings)
    
    text_on_image = settings.get(f'{platform_type}_text_on_image', 'without_text')
    
    # Если выбрано "случайно", выбираем рандомно
    if text_on_image == 'random':
        import random
        text_on_image = random.choice(['with_text', 'without_text'])
    
    # Возвращаем промпт
    option_data = TEXT_ON_IMAGE_OPTIONS.get(text_on_image, {})
    return option_data.get('prompt')


def get_random_text_style(category, platform_type):
    """
    Получить случайный стиль текста из выбранных
    
    Args:
        category: dict - данные категории
        platform_type: str - тип платформы
        
    Returns:
        str: код стиля (sales, conversational и т.д.)
    """
    settings = category.get('settings', {})
    if isinstance(settings, str):
        settings = json.loads(settings)
    
    # Получаем выбранные стили
    selected_styles = settings.get(f'{platform_type}_text_styles', ['conversational'])
    
    # Обратная совместимость со старым форматом (одиночный стиль)
    if not isinstance(selected_styles, list):
        return selected_styles
    
    # Если список пустой, возвращаем разговорный
    if not selected_styles:
        return 'conversational'
    
    # Выбираем случайный стиль из списка
    import random
    return random.choice(selected_styles)


print("✅ handlers/text_style_settings.py загружен")
