# -*- coding: utf-8 -*-
"""
Базовый класс для обработки настроек изображений
Используется в platform_category и website модулях
"""
from telebot import types
from loader import bot, db
import logging

logger = logging.getLogger(__name__)


class ImageSettingsHandler:
    """Базовый класс для обработки настроек изображений"""
    
    def __init__(self, prefix='pc'):
        """
        Args:
            prefix: Префикс для callback_data ('pc' для platform_category, 'ws' для website)
        """
        self.prefix = prefix
    
    def get_style_name(self, style: str) -> str:
        """Получить русское название стиля"""
        styles_map = {
            'photorealistic': '📸 Фотореалистичный',
            'artistic': '🎨 Художественный',
            'minimalistic': '⚪ Минималистичный',
            'vintage': '📼 Винтажный',
            'modern': '🔲 Современный'
        }
        return styles_map.get(style, style)
    
    def get_tone_name(self, tone: str) -> str:
        """Получить русское название тональности"""
        tones_map = {
            'bright': '☀️ Яркая',
            'dark': '🌙 Тёмная',
            'neutral': '⚪ Нейтральная',
            'warm': '🔥 Тёплая',
            'cold': '❄️ Холодная'
        }
        return tones_map.get(tone, tone)
    
    def get_camera_name(self, camera: str) -> str:
        """Получить русское название ракурса"""
        cameras_map = {
            'front': '👁 Фронтально',
            'top': '⬆️ Сверху',
            'side': '↔️ Сбоку',
            'diagonal': '↗️ Диагональ',
            'close-up': '🔍 Крупный план'
        }
        return cameras_map.get(camera, camera)
    
    def create_style_menu(self, call, category_id: int, bot_id: int, current_style: str = 'photorealistic'):
        """
        Создать меню выбора стиля
        
        Args:
            call: Callback query
            category_id: ID категории
            bot_id: ID бота
            current_style: Текущий стиль
        """
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        styles = ['photorealistic', 'artistic', 'minimalistic', 'vintage', 'modern']
        
        for style in styles:
            # Отмечаем текущий стиль
            prefix_mark = '✅ ' if style == current_style else ''
            button_text = f"{prefix_mark}{self.get_style_name(style)}"
            
            callback = f"{self.prefix}_set_style_{style}_{category_id}_{bot_id}"
            markup.add(types.InlineKeyboardButton(button_text, callback_data=callback))
        
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"{self.prefix}_image_adv_{category_id}_{bot_id}"
            )
        )
        
        try:
            bot.edit_message_text(
                "🎨 Выберите стиль изображения:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        except Exception as e:
            logger.error(f"Ошибка создания меню стиля: {e}")
    
    def create_tone_menu(self, call, category_id: int, bot_id: int, current_tone: str = 'neutral'):
        """Создать меню выбора тональности"""
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        tones = ['bright', 'dark', 'neutral', 'warm', 'cold']
        
        for tone in tones:
            prefix_mark = '✅ ' if tone == current_tone else ''
            button_text = f"{prefix_mark}{self.get_tone_name(tone)}"
            
            callback = f"{self.prefix}_set_tone_{tone}_{category_id}_{bot_id}"
            markup.add(types.InlineKeyboardButton(button_text, callback_data=callback))
        
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"{self.prefix}_image_adv_{category_id}_{bot_id}"
            )
        )
        
        try:
            bot.edit_message_text(
                "🎨 Выберите тональность:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        except Exception as e:
            logger.error(f"Ошибка создания меню тональности: {e}")
    
    def create_camera_menu(self, call, category_id: int, bot_id: int, current_camera: str = 'front'):
        """Создать меню выбора ракурса камеры"""
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        cameras = ['front', 'top', 'side', 'diagonal', 'close-up']
        
        for camera in cameras:
            prefix_mark = '✅ ' if camera == current_camera else ''
            button_text = f"{prefix_mark}{self.get_camera_name(camera)}"
            
            callback = f"{self.prefix}_set_camera_{camera}_{category_id}_{bot_id}"
            markup.add(types.InlineKeyboardButton(button_text, callback_data=callback))
        
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"{self.prefix}_image_adv_{category_id}_{bot_id}"
            )
        )
        
        try:
            bot.edit_message_text(
                "📐 Выберите ракурс камеры:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        except Exception as e:
            logger.error(f"Ошибка создания меню ракурса: {e}")
    
    def create_collage_menu(self, call, category_id: int, bot_id: int, current_percent: int = 0):
        """Создать меню настройки коллажа"""
        markup = types.InlineKeyboardMarkup(row_width=3)
        
        percents = [0, 20, 40, 60, 80, 100]
        
        for percent in percents:
            prefix_mark = '✅ ' if percent == current_percent else ''
            button_text = f"{prefix_mark}{percent}%"
            
            callback = f"{self.prefix}_collage_{percent}_{category_id}_{bot_id}"
            markup.add(types.InlineKeyboardButton(button_text, callback_data=callback))
        
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"{self.prefix}_image_adv_{category_id}_{bot_id}"
            )
        )
        
        text = f"🖼 Вероятность коллажа: {current_percent}%\n\n"
        text += "Коллаж - это изображение из нескольких элементов."
        
        try:
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        except Exception as e:
            logger.error(f"Ошибка создания меню коллажа: {e}")
    
    def save_setting(self, category_id: int, bot_id: int, setting_name: str, value):
        """
        Сохранить настройку в БД
        
        Args:
            category_id: ID категории
            bot_id: ID бота
            setting_name: Название настройки
            value: Значение
        
        Returns:
            bool: True если успешно
        """
        try:
            # Здесь должна быть логика сохранения в БД
            # В зависимости от prefix (pc или ws) сохраняем в разные поля
            
            cursor = db.conn.cursor()
            
            # Получаем текущие настройки
            cursor.execute("""
                SELECT platform_image_settings 
                FROM categories 
                WHERE id = %s
            """, (category_id,))
            
            result = cursor.fetchone()
            settings = result[0] if result and result[0] else {}
            
            # Обновляем настройку
            settings[setting_name] = value
            
            # Сохраняем
            cursor.execute("""
                UPDATE categories 
                SET platform_image_settings = %s 
                WHERE id = %s
            """, (settings, category_id))
            
            db.conn.commit()
            cursor.close()
            
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения настройки: {e}")
            try:
                db.conn.rollback()
            except Exception:
                pass
            return False


# Создаём экземпляры для разных префиксов
platform_category_handler = ImageSettingsHandler(prefix='pc')
website_handler = ImageSettingsHandler(prefix='ws')
