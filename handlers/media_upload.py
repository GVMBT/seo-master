"""
Обработчики загрузки медиа-файлов в категории
"""
from telebot import types
from loader import bot
from database.database import db
from config import ADMIN_ID
from utils import escape_html, safe_answer_callback
import os
import json


# Временное хранилище для ожидания загрузки
user_awaiting_media = {}


def start_media_upload(call, category_id):
    """Начать процесс загрузки медиа"""
    user_id = call.from_user.id
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        safe_answer_callback(bot, call.id, "❌ Категория не найдена")
        return
    
    category_name = category.get('name', 'Без названия')
    
    text = (
        f"📤 <b>ЗАГРУЗКА МЕДИА</b>\n"
        f"📂 Категория: {escape_html(category_name)}\n"
        "━━━━━━━━━━━━━━\n\n"
        "Вы можете загрузить:\n\n"
        "📸 <b>Изображения:</b>\n"
        "• Фотографии товаров\n"
        "• Логотипы\n"
        "• Баннеры\n"
        "• Форматы: JPG, PNG, WEBP\n"
        "• До 10 МБ\n\n"
        "🎥 <b>Видео:</b>\n"
        "• Презентации\n"
        "• Обзоры\n"
        "• Форматы: MP4, MOV\n"
        "• До 50 МБ\n\n"
        "📄 <b>Документы:</b>\n"
        "• Прайс-листы (PDF, XLSX)\n"
        "• Каталоги (PDF)\n"
        "• До 20 МБ\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "Отправьте файл в этот чат, и я сохраню его в категорию."
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_upload_{category_id}")
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
    
    # Сохраняем состояние ожидания
    user_awaiting_media[user_id] = {
        'category_id': category_id,
        'category_name': category_name,
        'awaiting': True
    }
    
    safe_answer_callback(bot, call.id, "📤 Ожидаю файл...")


@bot.callback_query_handler(func=lambda call: call.data.startswith("upload_media_"))
def handle_upload_media(call):
    """Инициировать загрузку медиа"""
    category_id = int(call.data.split("_")[-1])
    start_media_upload(call, category_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_upload_"))
def handle_cancel_upload(call):
    """Отменить загрузку медиа"""
    category_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    # Убираем из ожидания
    if user_id in user_awaiting_media:
        del user_awaiting_media[user_id]
    
    safe_answer_callback(bot, call.id, "❌ Загрузка отменена")
    
    # Возвращаем к медиа
    from handlers.category_sections import handle_category_media
    
    # Создаем фейковый колбэк
    fake_call = type('obj', (object,), {
        'data': f'category_media_{category_id}',
        'from_user': call.from_user,
        'message': call.message,
        'id': call.id
    })()
    
    handle_category_media(fake_call)


@bot.message_handler(content_types=['photo'])
def handle_photo_upload(message):
    """Обработка загрузки фото"""
    user_id = message.from_user.id
    
    # Проверяем ожидание загрузки
    if user_id not in user_awaiting_media or not user_awaiting_media[user_id]['awaiting']:
        return
    
    category_id = user_awaiting_media[user_id]['category_id']
    category_name = user_awaiting_media[user_id]['category_name']
    
    # Получаем файл
    photo = message.photo[-1]  # Берем самый большой размер
    file_id = photo.file_id
    file_size = photo.file_size
    
    # Проверяем размер (10 МБ)
    if file_size > 10 * 1024 * 1024:
        bot.send_message(
            message.chat.id,
            "❌ Файл слишком большой! Максимум 10 МБ для изображений."
        )
        return
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        bot.send_message(message.chat.id, "❌ Категория не найдена")
        return
    
    # Получаем текущие медиа
    media = category.get('media', [])
    if not isinstance(media, list):
        media = []
    
    # Добавляем новое фото
    media_item = {
        'type': 'photo',
        'file_id': file_id,
        'file_size': file_size,
        'uploaded_at': 'NOW()'
    }
    
    media.append(media_item)
    
    # Сохраняем в БД
    db.cursor.execute("""
        UPDATE categories 
        SET media = %s::jsonb
        WHERE id = %s
    """, (json.dumps(media), category_id))
    db.conn.commit()
    
    # Убираем из ожидания
    del user_awaiting_media[user_id]
    
    # Отправляем подтверждение
    text = (
        "✅ <b>ФОТО ЗАГРУЖЕНО!</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📂 Категория: <b>{escape_html(category_name)}</b>\n"
        f"📸 Тип: Изображение\n"
        f"📦 Размер: {file_size / 1024:.1f} КБ\n\n"
        "Файл сохранен в медиа-галерею категории."
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📤 Загрузить ещё", callback_data=f"upload_media_{category_id}"),
        types.InlineKeyboardButton("📂 К медиа", callback_data=f"category_media_{category_id}"),
        types.InlineKeyboardButton("🔙 К категории", callback_data=f"open_category_{category_id}")
    )
    
    bot.send_message(
        message.chat.id,
        text,
        reply_markup=markup,
        parse_mode='HTML'
    )


@bot.message_handler(content_types=['video'])
def handle_video_upload(message):
    """Обработка загрузки видео"""
    user_id = message.from_user.id
    
    # Проверяем ожидание загрузки
    if user_id not in user_awaiting_media or not user_awaiting_media[user_id]['awaiting']:
        return
    
    category_id = user_awaiting_media[user_id]['category_id']
    category_name = user_awaiting_media[user_id]['category_name']
    
    # Получаем файл
    video = message.video
    file_id = video.file_id
    file_size = video.file_size
    duration = video.duration
    
    # Проверяем размер (50 МБ)
    if file_size > 50 * 1024 * 1024:
        bot.send_message(
            message.chat.id,
            "❌ Файл слишком большой! Максимум 50 МБ для видео."
        )
        return
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        bot.send_message(message.chat.id, "❌ Категория не найдена")
        return
    
    # Получаем текущие медиа
    media = category.get('media', [])
    if not isinstance(media, list):
        media = []
    
    # Добавляем новое видео
    media_item = {
        'type': 'video',
        'file_id': file_id,
        'file_size': file_size,
        'duration': duration,
        'uploaded_at': 'NOW()'
    }
    
    media.append(media_item)
    
    # Сохраняем в БД
    db.cursor.execute("""
        UPDATE categories 
        SET media = %s::jsonb
        WHERE id = %s
    """, (json.dumps(media), category_id))
    db.conn.commit()
    
    # Убираем из ожидания
    del user_awaiting_media[user_id]
    
    # Отправляем подтверждение
    text = (
        "✅ <b>ВИДЕО ЗАГРУЖЕНО!</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📂 Категория: <b>{escape_html(category_name)}</b>\n"
        f"🎥 Тип: Видео\n"
        f"📦 Размер: {file_size / 1024 / 1024:.1f} МБ\n"
        f"⏱ Длительность: {duration} сек\n\n"
        "Файл сохранен в медиа-галерею категории."
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📤 Загрузить ещё", callback_data=f"upload_media_{category_id}"),
        types.InlineKeyboardButton("📂 К медиа", callback_data=f"category_media_{category_id}"),
        types.InlineKeyboardButton("🔙 К категории", callback_data=f"open_category_{category_id}")
    )
    
    bot.send_message(
        message.chat.id,
        text,
        reply_markup=markup,
        parse_mode='HTML'
    )


@bot.message_handler(content_types=['document'])
def handle_document_upload(message):
    """Обработка загрузки документа"""
    user_id = message.from_user.id
    
    # Проверяем ожидание загрузки
    if user_id not in user_awaiting_media or not user_awaiting_media[user_id]['awaiting']:
        return
    
    category_id = user_awaiting_media[user_id]['category_id']
    category_name = user_awaiting_media[user_id]['category_name']
    
    # Получаем файл
    document = message.document
    file_id = document.file_id
    file_size = document.file_size
    file_name = document.file_name
    mime_type = document.mime_type
    
    # Проверяем размер (20 МБ)
    if file_size > 20 * 1024 * 1024:
        bot.send_message(
            message.chat.id,
            "❌ Файл слишком большой! Максимум 20 МБ для документов."
        )
        return
    
    # Проверяем тип файла
    allowed_types = ['application/pdf', 'application/vnd.ms-excel', 
                     'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']
    
    if mime_type not in allowed_types:
        bot.send_message(
            message.chat.id,
            "❌ Неподдерживаемый формат! Разрешены: PDF, XLS, XLSX"
        )
        return
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        bot.send_message(message.chat.id, "❌ Категория не найдена")
        return
    
    # Получаем текущие медиа
    media = category.get('media', [])
    if not isinstance(media, list):
        media = []
    
    # Добавляем новый документ
    media_item = {
        'type': 'document',
        'file_id': file_id,
        'file_size': file_size,
        'file_name': file_name,
        'mime_type': mime_type,
        'uploaded_at': 'NOW()'
    }
    
    media.append(media_item)
    
    # Сохраняем в БД
    db.cursor.execute("""
        UPDATE categories 
        SET media = %s::jsonb
        WHERE id = %s
    """, (json.dumps(media), category_id))
    db.conn.commit()
    
    # Убираем из ожидания
    del user_awaiting_media[user_id]
    
    # Отправляем подтверждение
    text = (
        "✅ <b>ДОКУМЕНТ ЗАГРУЖЕН!</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📂 Категория: <b>{escape_html(category_name)}</b>\n"
        f"📄 Файл: {escape_html(file_name)}\n"
        f"📦 Размер: {file_size / 1024:.1f} КБ\n\n"
        "Файл сохранен в медиа-галерею категории."
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📤 Загрузить ещё", callback_data=f"upload_media_{category_id}"),
        types.InlineKeyboardButton("📂 К медиа", callback_data=f"category_media_{category_id}"),
        types.InlineKeyboardButton("🔙 К категории", callback_data=f"open_category_{category_id}")
    )
    
    bot.send_message(
        message.chat.id,
        text,
        reply_markup=markup,
        parse_mode='HTML'
    )


print("✅ handlers/media_upload.py загружен")
