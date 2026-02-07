"""
Style Selector - Выбор стилей изображения
Множественный выбор: фотореализм, аниме, акварель и т.д.
"""
print("="*80)
print("🔵 ИМПОРТИРУЕТСЯ: handlers/platform_settings/style_selector.py")
print("="*80)

from telebot import types
from loader import bot
from database.database import db
from .constants import IMAGE_STYLES, PLATFORM_NAMES
from .utils import get_platform_settings, save_platform_settings

print("✅ style_selector импортирован успешно!")
print(f"✅ Декораторы будут зарегистрированы для bot: {bot}")
print("="*80)


def show_style_selector(call, platform_type, category_id, bot_id):
    """
    Показать интерфейс выбора стилей изображения
    
    Args:
        call: callback query
        platform_type: str - pinterest/telegram/website
        category_id: int
        bot_id: int
    """
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    category_name = category.get('name', 'Без названия')
    
    # Получаем текущие настройки
    settings = get_platform_settings(category, platform_type)
    current_styles = settings['styles']
    
    platform_name = PLATFORM_NAMES.get(platform_type, platform_type.upper())
    
    # Получаем platform_id
    platforms = category.get('platforms', [])
    platform_id = 'main'
    for p in platforms:
        if p.get('type', '').lower() == platform_type.lower():
            platform_id = p.get('id', 'main')
            break
    
    # Текст
    selected_count = len(current_styles)
    
    text = (
        f"🎨 <b>СТИЛЬ ИЗОБРАЖЕНИЯ</b>\n\n"
        f"Выбрано: {selected_count}\n"
        f"Выберите стили (можно несколько):"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Функция для удаления эмодзи из начала строки
    def remove_emoji(text):
        if not text:
            return text
        parts = text.split(' ', 1)
        if len(parts) > 1:
            return parts[1]
        return text
    
    # Кнопки стилей в 2 столбца
    buttons = []
    for style_code, style_data in IMAGE_STYLES.items():
        is_selected = style_code in current_styles
        style_name = style_data['name']  # Оставляем эмодзи в кнопках
        
        if is_selected:
            button_text = f"{style_name} ✅"
        else:
            button_text = style_name
        
        buttons.append(
            types.InlineKeyboardButton(
                button_text,
                callback_data=f"toggle_style_{platform_type}_{category_id}_{bot_id}_{style_code}"
            )
        )
    
    # Добавляем кнопки по 2 в ряд
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])
    
    # Навигация
    markup.add(
        types.InlineKeyboardButton(
            "🔙 Назад",
            callback_data=f"platform_images_menu_{platform_type}_{category_id}_{bot_id}_{platform_id}"
        )
    )
    
    # Отправляем или редактируем
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


def handle_toggle_style(call, platform_type, category_id, bot_id, style_code):
    """
    Переключить стиль (добавить/удалить из списка)
    
    Args:
        call: callback query
        platform_type: str
        category_id: int
        bot_id: int
        style_code: str - например 'photorealistic'
    """
    print(f"\n{'='*80}")
    print(f"🎨 TOGGLE STYLE ВЫЗВАН!")
    print(f"   Platform: {platform_type}")
    print(f"   Category ID: {category_id}")
    print(f"   Bot ID: {bot_id}")
    print(f"   Style code: {style_code}")
    print(f"{'='*80}\n")
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        print(f"❌ Категория {category_id} не найдена!")
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    print(f"✅ Категория найдена: {category.get('name', 'unknown')}")
    
    # Получаем текущие стили
    settings = get_platform_settings(category, platform_type)
    current_styles = settings['styles'].copy()
    
    print(f"📊 Текущие стили: {current_styles}")
    
    # Переключаем стиль
    if style_code in current_styles:
        current_styles.remove(style_code)
        print(f"➖ Удалён стиль: {style_code}")
    else:
        current_styles.append(style_code)
        print(f"➕ Добавлен стиль: {style_code}")
    
    print(f"📊 Новые стили: {current_styles}")
    print(f"🔄 Вызываем save_platform_settings...")
    
    # Сохраняем (можно иметь 0 стилей - значит случайный)
    result = save_platform_settings(db, category_id, platform_type, styles=current_styles)
    
    print(f"💾 Результат сохранения: {result}")
    
    bot.answer_callback_query(call.id)
    
    # Обновляем интерфейс
    show_style_selector(call, platform_type, category_id, bot_id)


def handle_styles_all(call, platform_type, category_id, bot_id):
    """Выбрать все стили"""
    all_styles = list(IMAGE_STYLES.keys())
    
    # Сохраняем
    save_platform_settings(db, category_id, platform_type, styles=all_styles)
    
    bot.answer_callback_query(call.id, "✅ Все стили выбраны")
    
    # Обновляем интерфейс
    show_style_selector(call, platform_type, category_id, bot_id)


def handle_styles_clear(call, platform_type, category_id, bot_id):
    """Очистить выбор (случайный стиль)"""
    # Сохраняем пустой список
    save_platform_settings(db, category_id, platform_type, styles=[])
    
    bot.answer_callback_query(call.id, "✅ Стиль будет случайным")
    
    # Обновляем интерфейс
    show_style_selector(call, platform_type, category_id, bot_id)


# ═══════════════════════════════════════════════════════════════
# РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ
# ═══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("next_style_"))
def handle_next_style(call):
    """Переход к выбору стилей"""
    parts = call.data.split("_")
    platform_type = parts[2]
    category_id = int(parts[3])
    bot_id = int(parts[4])
    
    show_style_selector(call, platform_type, category_id, bot_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("toggle_style_"))
def callback_toggle_style(call):
    """Переключение стиля"""
    print(f"\n🔵 CALLBACK toggle_style получен!")
    print(f"   Данные: {call.data}")
    
    parts = call.data.split("_")
    # toggle_style_pinterest_123_456_oil_painting
    platform_type = parts[2]
    category_id = int(parts[3])
    bot_id = int(parts[4])
    style_code = "_".join(parts[5:])  # Собираем style_code с underscore
    
    print(f"   Parsed: platform={platform_type}, cat={category_id}, bot={bot_id}, style={style_code}")
    
    handle_toggle_style(call, platform_type, category_id, bot_id, style_code)

print("✅ Декоратор @bot.callback_query_handler для 'toggle_style_' зарегистрирован!")


@bot.callback_query_handler(func=lambda call: call.data.startswith("styles_all_"))
def callback_styles_all(call):
    """Выбрать все стили"""
    parts = call.data.split("_")
    platform_type = parts[2]
    category_id = int(parts[3])
    bot_id = int(parts[4])
    
    handle_styles_all(call, platform_type, category_id, bot_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("styles_clear_"))
def callback_styles_clear(call):
    """Очистить стили"""
    parts = call.data.split("_")
    platform_type = parts[2]
    category_id = int(parts[3])
    bot_id = int(parts[4])
    
    handle_styles_clear(call, platform_type, category_id, bot_id)


print("✅ platform_settings/style_selector.py загружен")
