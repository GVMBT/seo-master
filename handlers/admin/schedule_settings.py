# -*- coding: utf-8 -*-
"""
Интерфейс управления расписанием автоматических рассылок
Позволяет админу настраивать время и типы рассылок
"""
import logging
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from loader import bot
from database.database import db
from config import ADMIN_ID

logger = logging.getLogger(__name__)


def get_schedule_settings():
    """
    Получает настройки расписания из БД
    
    Returns:
        dict: Настройки расписания
    """
    try:
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT schedule_type, enabled, schedule_time, frequency
            FROM schedule_settings
            ORDER BY schedule_type
        """)
        
        settings = {}
        rows = cursor.fetchall()
        
        for row in rows:
            settings[row[0]] = {
                'enabled': row[1],
                'time': row[2],
                'frequency': row[3]
            }
        
        cursor.close()
        return settings
        
    except Exception as e:
        logger.error(f"Ошибка получения настроек расписания: {e}")
        # Возвращаем настройки по умолчанию
        return {
            'welcome': {'enabled': True, 'time': '09:00', 'frequency': 'immediate'},
            'low_balance': {'enabled': True, 'time': '10:00', 'frequency': 'daily'},
            'weekly_news': {'enabled': False, 'time': '10:00', 'frequency': 'weekly'},
            'reactivation': {'enabled': True, 'time': '11:00', 'frequency': 'weekly'}
        }


def update_schedule_setting(schedule_type, enabled=None, time=None, frequency=None):
    """
    Обновляет настройку расписания
    
    Args:
        schedule_type: Тип рассылки
        enabled: Включено или нет
        time: Время отправки
        frequency: Частота (daily, weekly, monthly)
    
    Returns:
        bool: Успешность операции
    """
    try:
        cursor = db.conn.cursor()
        
        # Формируем запрос динамически
        updates = []
        values = []
        
        if enabled is not None:
            updates.append("enabled = %s")
            values.append(enabled)
        
        if time is not None:
            updates.append("schedule_time = %s")
            values.append(time)
        
        if frequency is not None:
            updates.append("frequency = %s")
            values.append(frequency)
        
        updates.append("updated_at = NOW()")
        
        if not updates:
            return False
        
        values.append(schedule_type)
        
        query = f"""
            INSERT INTO schedule_settings (schedule_type, enabled, schedule_time, frequency, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (schedule_type) 
            DO UPDATE SET {', '.join(updates)}
        """
        
        # Для INSERT нужны все значения
        if enabled is not None and time is not None and frequency is not None:
            cursor.execute(query, [schedule_type, enabled, time, frequency] + values)
        else:
            # Для UPDATE используем только изменяемые поля
            cursor.execute(f"""
                UPDATE schedule_settings 
                SET {', '.join(updates)}
                WHERE schedule_type = %s
            """, values)
        
        db.conn.commit()
        cursor.close()
        
        logger.info(f"✅ Настройка расписания {schedule_type} обновлена")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка обновления расписания {schedule_type}: {e}")
        try:
            db.conn.rollback()
        except Exception:
            pass
        return False


@bot.callback_query_handler(func=lambda call: call.data == "admin_messaging")
def show_schedule_menu(call: CallbackQuery):
    """
    Показывает меню расписания рассылок
    
    Args:
        call: Callback query
    """
    user_id = call.from_user.id
    
    if str(user_id) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "❌ Нет доступа")
        return
    
    settings = get_schedule_settings()
    
    text = """
📨 <b>РАСПИСАНИЕ СООБЩЕНИЙ</b>

Здесь можно настроить автоматические рассылки:

"""
    
    # Формируем список рассылок
    schedule_list = [
        ('welcome', '🎉 Поздравления с регистрацией', 'Сразу при регистрации'),
        ('low_balance', '💎 Напоминания о низком балансе', 'Ежедневно'),
        ('weekly_news', '📰 Еженедельные новости', 'Раз в неделю'),
        ('reactivation', '😔 Реактивация неактивных', 'Раз в неделю')
    ]
    
    for key, label, freq_text in schedule_list:
        setting = settings.get(key, {'enabled': False, 'time': '10:00'})
        status = "✅" if setting['enabled'] else "❌"
        time = setting.get('time', '10:00')
        text += f"{status} <b>{label}</b>\n"
        text += f"   └ Время: {time}, {freq_text}\n\n"
    
    text += "<i>Нажмите на кнопку для изменения настроек</i>"
    
    # Создаём клавиатуру
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    for key, label, _ in schedule_list:
        setting = settings.get(key, {'enabled': False})
        status_icon = "✅" if setting['enabled'] else "❌"
        
        keyboard.add(
            InlineKeyboardButton(
                f"{status_icon} {label}",
                callback_data=f"schedule_edit_{key}"
            )
        )
    
    keyboard.add(
        InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")
    )
    
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML',
            reply_markup=keyboard
        )
    except Exception:
        bot.send_message(
            call.message.chat.id,
            text,
            parse_mode='HTML',
            reply_markup=keyboard
        )
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('schedule_edit_'))
def edit_schedule_item(call: CallbackQuery):
    """
    Редактирование отдельной рассылки
    
    Args:
        call: Callback query
    """
    user_id = call.from_user.id
    
    if str(user_id) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "❌ Нет доступа")
        return
    
    # Извлекаем тип рассылки
    schedule_type = call.data.replace('schedule_edit_', '')
    
    settings = get_schedule_settings()
    setting = settings.get(schedule_type, {'enabled': False, 'time': '10:00', 'frequency': 'daily'})
    
    # Названия для отображения
    names = {
        'welcome': '🎉 Поздравления с регистрацией',
        'low_balance': '💎 Напоминания о низком балансе',
        'weekly_news': '📰 Еженедельные новости',
        'reactivation': '😔 Реактивация неактивных'
    }
    
    name = names.get(schedule_type, 'Рассылка')
    status_text = "Включено ✅" if setting['enabled'] else "Выключено ❌"
    
    text = f"""
📝 <b>НАСТРОЙКА РАССЫЛКИ</b>

<b>{name}</b>

📊 Статус: {status_text}
⏰ Время: {setting.get('time', '10:00')}
📅 Частота: {setting.get('frequency', 'daily')}

<i>Выберите действие:</i>
"""
    
    # Создаём клавиатуру
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    # Кнопка включения/выключения
    toggle_text = "❌ Выключить" if setting['enabled'] else "✅ Включить"
    keyboard.add(
        InlineKeyboardButton(
            toggle_text,
            callback_data=f"schedule_toggle_{schedule_type}"
        )
    )
    
    # Кнопки изменения времени
    keyboard.add(
        InlineKeyboardButton("⏰ 09:00", callback_data=f"schedule_time_{schedule_type}_09:00"),
        InlineKeyboardButton("⏰ 10:00", callback_data=f"schedule_time_{schedule_type}_10:00")
    )
    keyboard.add(
        InlineKeyboardButton("⏰ 11:00", callback_data=f"schedule_time_{schedule_type}_11:00"),
        InlineKeyboardButton("⏰ 12:00", callback_data=f"schedule_time_{schedule_type}_12:00")
    )
    keyboard.add(
        InlineKeyboardButton("⏰ 15:00", callback_data=f"schedule_time_{schedule_type}_15:00"),
        InlineKeyboardButton("⏰ 18:00", callback_data=f"schedule_time_{schedule_type}_18:00")
    )
    
    keyboard.add(
        InlineKeyboardButton("🔙 Назад", callback_data="admin_messaging")
    )
    
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML',
            reply_markup=keyboard
        )
    except Exception:
        bot.send_message(
            call.message.chat.id,
            text,
            parse_mode='HTML',
            reply_markup=keyboard
        )
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('schedule_toggle_'))
def toggle_schedule(call: CallbackQuery):
    """
    Переключение включения/выключения рассылки
    
    Args:
        call: Callback query
    """
    user_id = call.from_user.id
    
    if str(user_id) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "❌ Нет доступа")
        return
    
    schedule_type = call.data.replace('schedule_toggle_', '')
    
    settings = get_schedule_settings()
    current = settings.get(schedule_type, {'enabled': False})
    new_enabled = not current['enabled']
    
    if update_schedule_setting(schedule_type, enabled=new_enabled):
        status = "включена" if new_enabled else "выключена"
        bot.answer_callback_query(call.id, f"✅ Рассылка {status}")
        
        # Обновляем меню
        edit_schedule_item(call)
    else:
        bot.answer_callback_query(call.id, "❌ Ошибка обновления", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith('schedule_time_'))
def change_schedule_time(call: CallbackQuery):
    """
    Изменение времени рассылки
    
    Args:
        call: Callback query
    """
    user_id = call.from_user.id
    
    if str(user_id) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "❌ Нет доступа")
        return
    
    # Парсим данные: schedule_time_welcome_09:00
    parts = call.data.replace('schedule_time_', '').split('_')
    schedule_type = parts[0]
    new_time = parts[1]
    
    if update_schedule_setting(schedule_type, time=new_time):
        bot.answer_callback_query(call.id, f"✅ Время изменено на {new_time}")
        
        # Обновляем меню
        edit_schedule_item(call)
    else:
        bot.answer_callback_query(call.id, "❌ Ошибка обновления", show_alert=True)


print("✅ handlers/admin/schedule_settings.py загружен")
