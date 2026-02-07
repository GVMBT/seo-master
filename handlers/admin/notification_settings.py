# -*- coding: utf-8 -*-
"""
Настройки уведомлений для администратора
Управление автоматическими рассылками
"""
import logging
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from loader import bot
from database.database import db

logger = logging.getLogger(__name__)

# ID администраторов (можно вынести в config.py)
ADMIN_IDS = [123456789]  # Замените на реальные ID админов


def is_admin(user_id):
    """Проверка, является ли пользователь администратором"""
    return user_id in ADMIN_IDS


def get_notification_settings():
    """
    Получает настройки уведомлений из БД
    
    Returns:
        dict: Настройки уведомлений
    """
    try:
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT setting_key, setting_value, enabled
            FROM notification_settings
        """)
        
        settings = {}
        rows = cursor.fetchall()
        
        for row in rows:
            settings[row[0]] = {
                'value': row[1],
                'enabled': row[2]
            }
        
        cursor.close()
        return settings
        
    except Exception as e:
        logger.error(f"Ошибка получения настроек уведомлений: {e}")
        # Возвращаем настройки по умолчанию
        return {
            'new_payments': {'enabled': True, 'value': 'on'},
            'new_users': {'enabled': True, 'value': 'on'},
            'system_errors': {'enabled': True, 'value': 'on'},
            'ai_status': {'enabled': True, 'value': 'on'},
            'low_balance': {'enabled': True, 'value': 'on'}
        }


def update_notification_setting(setting_key, enabled):
    """
    Обновляет настройку уведомления
    
    Args:
        setting_key: Ключ настройки
        enabled: Включено или нет
    
    Returns:
        bool: Успешность операции
    """
    try:
        cursor = db.conn.cursor()
        cursor.execute("""
            INSERT INTO notification_settings (setting_key, enabled, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (setting_key) 
            DO UPDATE SET enabled = %s, updated_at = NOW()
        """, (setting_key, enabled, enabled))
        
        db.conn.commit()
        cursor.close()
        
        logger.info(f"✅ Настройка {setting_key} обновлена: {enabled}")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка обновления настройки {setting_key}: {e}")
        return False


def show_notification_settings_menu(message):
    """
    Показывает меню настроек уведомлений
    
    Args:
        message: Сообщение от пользователя
    """
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.send_message(user_id, "❌ У вас нет доступа к этой функции")
        return
    
    settings = get_notification_settings()
    
    text = """
🔔 <b>НАСТРОЙКИ УВЕДОМЛЕНИЙ</b>

Настройте уведомления для админа:

"""
    
    # Формируем список настроек
    settings_list = [
        ('new_payments', '💰 Новые оплаты'),
        ('new_users', '👥 Новые пользователи'),
        ('system_errors', '⚠️ Ошибки системы'),
        ('ai_status', '🤖 Статус AI сервисов'),
        ('low_balance', '💎 Низкий баланс API')
    ]
    
    for key, label in settings_list:
        setting = settings.get(key, {'enabled': False})
        status = "✅ ВКЛ" if setting['enabled'] else "❌ ВЫКЛ"
        text += f"{label}: {status}\n"
    
    text += "\n<i>Нажмите на кнопку, чтобы изменить настройку</i>"
    
    # Создаём клавиатуру
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    for key, label in settings_list:
        setting = settings.get(key, {'enabled': False})
        status_icon = "✅" if setting['enabled'] else "❌"
        
        keyboard.add(
            InlineKeyboardButton(
                f"{status_icon} {label}",
                callback_data=f"admin_notif_toggle_{key}"
            )
        )
    
    keyboard.add(
        InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")
    )
    
    bot.send_message(
        user_id,
        text,
        parse_mode='HTML',
        reply_markup=keyboard
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_notif_toggle_'))
def handle_notification_toggle(call: CallbackQuery):
    """
    Обработчик переключения настроек уведомлений
    
    Args:
        call: Callback query
    """
    user_id = call.from_user.id
    
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "❌ Нет доступа")
        return
    
    # Извлекаем ключ настройки
    setting_key = call.data.replace('admin_notif_toggle_', '')
    
    # Получаем текущие настройки
    settings = get_notification_settings()
    current_setting = settings.get(setting_key, {'enabled': False})
    
    # Переключаем значение
    new_enabled = not current_setting['enabled']
    
    # Обновляем в БД
    if update_notification_setting(setting_key, new_enabled):
        status = "включено" if new_enabled else "выключено"
        bot.answer_callback_query(
            call.id,
            f"✅ Уведомление {status}",
            show_alert=False
        )
        
        # Обновляем меню
        settings = get_notification_settings()
        
        text = """
🔔 <b>НАСТРОЙКИ УВЕДОМЛЕНИЙ</b>

Настройте уведомления для админа:

"""
        
        settings_list = [
            ('new_payments', '💰 Новые оплаты'),
            ('new_users', '👥 Новые пользователи'),
            ('system_errors', '⚠️ Ошибки системы'),
            ('ai_status', '🤖 Статус AI сервисов'),
            ('low_balance', '💎 Низкий баланс API')
        ]
        
        for key, label in settings_list:
            setting = settings.get(key, {'enabled': False})
            status = "✅ ВКЛ" if setting['enabled'] else "❌ ВЫКЛ"
            text += f"{label}: {status}\n"
        
        text += "\n<i>Нажмите на кнопку, чтобы изменить настройку</i>"
        
        # Обновляем клавиатуру
        keyboard = InlineKeyboardMarkup(row_width=1)
        
        for key, label in settings_list:
            setting = settings.get(key, {'enabled': False})
            status_icon = "✅" if setting['enabled'] else "❌"
            
            keyboard.add(
                InlineKeyboardButton(
                    f"{status_icon} {label}",
                    callback_data=f"admin_notif_toggle_{key}"
                )
            )
        
        keyboard.add(
            InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")
        )
        
        bot.edit_message_text(
            text,
            user_id,
            call.message.message_id,
            parse_mode='HTML',
            reply_markup=keyboard
        )
    else:
        bot.answer_callback_query(
            call.id,
            "❌ Ошибка обновления настройки",
            show_alert=True
        )


def send_admin_notification(notification_type, message_text):
    """
    Отправляет уведомление админу (если включено)
    
    Args:
        notification_type: Тип уведомления (new_payments, new_users, etc.)
        message_text: Текст уведомления
    
    Returns:
        bool: Успешность отправки
    """
    try:
        settings = get_notification_settings()
        setting = settings.get(notification_type, {'enabled': False})
        
        # Проверяем, включено ли уведомление
        if not setting['enabled']:
            logger.info(f"Уведомление {notification_type} отключено, не отправляем")
            return False
        
        # Отправляем всем админам
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(
                    admin_id,
                    message_text,
                    parse_mode='HTML'
                )
                logger.info(f"✅ Уведомление {notification_type} отправлено админу {admin_id}")
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления админу {admin_id}: {e}")
        
        return True
        
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления {notification_type}: {e}")
        return False


# Примеры использования в других модулях:

def notify_new_payment(user_id, amount, tariff_name):
    """Уведомление о новой оплате"""
    text = f"""
💰 <b>Новая оплата!</b>

👤 Пользователь: <code>{user_id}</code>
💵 Сумма: {amount}₽
📦 Тариф: {tariff_name}

<i>{datetime.now().strftime('%d.%m.%Y %H:%M')}</i>
"""
    send_admin_notification('new_payments', text)


def notify_new_user(user_id, username):
    """Уведомление о новом пользователе"""
    text = f"""
👥 <b>Новый пользователь!</b>

ID: <code>{user_id}</code>
Username: @{username if username else 'не указан'}

<i>{datetime.now().strftime('%d.%m.%Y %H:%M')}</i>
"""
    send_admin_notification('new_users', text)


def notify_system_error(error_message, module_name=None):
    """Уведомление об ошибке системы"""
    text = f"""
⚠️ <b>Ошибка системы!</b>

"""
    if module_name:
        text += f"Модуль: <code>{module_name}</code>\n"
    
    text += f"""
Ошибка: <code>{error_message[:200]}</code>

<i>{datetime.now().strftime('%d.%m.%Y %H:%M')}</i>
"""
    send_admin_notification('system_errors', text)


def notify_ai_status_change(service_name, status, details=None):
    """Уведомление об изменении статуса AI сервиса"""
    status_icon = "✅" if status == "online" else "❌"
    
    text = f"""
🤖 <b>Статус AI сервиса</b>

Сервис: {service_name}
Статус: {status_icon} {status}
"""
    
    if details:
        text += f"\nДетали: {details}"
    
    text += f"\n\n<i>{datetime.now().strftime('%d.%m.%Y %H:%M')}</i>"
    
    send_admin_notification('ai_status', text)


def notify_low_api_balance(service_name, balance, threshold):
    """Уведомление о низком балансе API"""
    text = f"""
💎 <b>Низкий баланс API!</b>

Сервис: {service_name}
Баланс: {balance}
Порог: {threshold}

⚠️ Рекомендуется пополнить баланс

<i>{datetime.now().strftime('%d.%m.%Y %H:%M')}</i>
"""
    send_admin_notification('low_balance', text)


print("✅ handlers/admin/notification_settings.py загружен")
