"""
Telegram Publisher (Refactored)
================================
Publisher ТОЛЬКО публикует контент.
Генерацию делает unified_generator.

ПРИНЦИП:
1. Получить категорию и выбрать единую фразу
2. Вызвать unified_generator для генерации контента
3. Опубликовать готовый контент в Telegram
"""

import logging
import tempfile
import os
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)


class TelegramPublisher:
    """
    Publisher для Telegram каналов
    
    Использует:
    - config/telegram/text_rules.py для правил текста
    - config/telegram/image_rules.py для правил изображений
    - ai/unified_generator.py для генерации контента
    """
    
    def __init__(self, category_id: str, platform_id: str, user_id: int = None):
        """
        Args:
            category_id: ID категории
            platform_id: ID канала Telegram (например @channel)
            user_id: ID пользователя (для получения из БД)
        """
        self.category_id = category_id
        self.platform_id = platform_id
        self.user_id = user_id
        
        self.category = None
        self.platform_data = None
    
    
    def execute(self) -> Tuple[bool, str, str]:
        """
        Выполняет публикацию
        
        Returns:
            (success, error_message, post_url)
        """
        try:
            # 1. Загрузка данных
            self._load_data()
            
            # 2. Генерация контента через unified_generator
            content = self._generate_content()
            
            # 3. Публикация в Telegram
            post_url = self._publish_to_telegram(
                text=content['text'],
                image_bytes=content['image_bytes']
            )
            
            logger.info(f"✅ Telegram: Опубликовано {post_url}")
            
            return True, None, post_url
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Telegram: {error_msg}")
            return False, error_msg, None
    
    
    def _load_data(self):
        """Загружает категорию и данные платформы"""
        from database.database import db
        
        # Загрузка категории
        self.category = db.get_category(self.category_id)
        if not self.category:
            raise ValueError(f"Категория {self.category_id} не найдена")
        
        # Загрузка данных канала
        if self.user_id:
            user = db.get_user(self.user_id)
            if not user:
                raise ValueError(f"Пользователь {self.user_id} не найден")
            
            connections = user.get('platform_connections', {})
            if isinstance(connections, str):
                import json
                connections = json.loads(connections)
            
            telegrams = connections.get('telegrams', [])
            
            # Поиск канала
            for tg in telegrams:
                if isinstance(tg, dict):
                    if tg.get('channel_id') == self.platform_id or tg.get('username') == self.platform_id:
                        self.platform_data = tg
                        break
            
            if not self.platform_data:
                raise ValueError(f"Telegram канал {self.platform_id} не найден")
            
            if self.platform_data.get('status') != 'active':
                raise ValueError(f"Канал {self.platform_id} не активен")
        
        logger.info(f"📊 Загружены данные: категория '{self.category.get('name')}', канал '{self.platform_id}'")
    
    
    def _generate_content(self) -> Dict:
        """
        Генерирует контент через unified_generator
        
        Returns:
            {'text': str, 'image_bytes': bytes, 'image_format': str}
        """
        from ai.unified_generator import generate_for_platform
        import random
        
        # Получаем данные категории
        category_name = self.category.get('name', 'Контент')
        description = self.category.get('description', '')
        
        # Выбираем ЕДИНУЮ фразу из описания
        selected_phrase = ''
        if description:
            phrases = [s.strip() for s in description.split(',') if s.strip()]
            if phrases:
                selected_phrase = random.choice(phrases)
                logger.info(f"📝 Выбрана единая фраза: '{selected_phrase[:50]}...'")
        
        # Получаем стиль из настроек
        settings = self.category.get('settings', {})
        if isinstance(settings, str):
            import json
            settings = json.loads(settings)
        
        text_styles = settings.get('telegram_text_styles', ['engaging'])
        style = random.choice(text_styles) if text_styles else 'engaging'
        
        logger.info(f"🎨 Генерация контента для Telegram (стиль: {style})")
        
        # ГЕНЕРАЦИЯ через unified_generator
        result = generate_for_platform(
            platform='telegram',
            category_name=category_name,
            selected_phrase=selected_phrase,
            style=style
        )
        
        if not result['success']:
            raise Exception(f"Ошибка генерации: {result.get('error')}")
        
        logger.info(f"✅ Контент сгенерирован: {len(result['text'].split())} слов, {len(result['image_bytes'])} байт")
        
        return result
    
    
    def _publish_to_telegram(self, text: str, image_bytes: bytes) -> str:
        """
        Публикует контент в Telegram
        
        Args:
            text: Готовый текст поста
            image_bytes: Готовое изображение
        
        Returns:
            URL опубликованного поста
        """
        import telebot
        import os
        
        # Получаем токен бота
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN не установлен")
        
        bot = telebot.TeleBot(bot_token)
        
        # Получаем channel_id
        channel_id = self.platform_data.get('channel_id') if self.platform_data else self.platform_id
        
        # Конвертируем текст в HTML (Telegram поддерживает HTML)
        formatted_text = self._format_html(text)
        
        # Сохраняем изображение во временный файл
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
            tmp_file.write(image_bytes)
            tmp_path = tmp_file.name
        
        try:
            # Telegram ограничивает caption до 1024 символов
            MAX_CAPTION_LENGTH = 1024
            
            if len(formatted_text) <= MAX_CAPTION_LENGTH:
                # Текст короткий - отправляем в caption
                with open(tmp_path, 'rb') as photo:
                    message = bot.send_photo(
                        chat_id=channel_id,
                        photo=photo,
                        caption=formatted_text,
                        parse_mode='HTML'
                    )
            else:
                # Текст длинный - отправляем фото без caption, текст отдельно
                with open(tmp_path, 'rb') as photo:
                    photo_message = bot.send_photo(
                        chat_id=channel_id,
                        photo=photo
                    )
                
                # Отправляем текст отдельным сообщением
                message = bot.send_message(
                    chat_id=channel_id,
                    text=formatted_text,
                    parse_mode='HTML',
                    reply_to_message_id=photo_message.message_id
                )
            
            # Формируем URL поста
            username = self.platform_data.get('username', '').replace('@', '') if self.platform_data else channel_id.replace('@', '')
            post_url = f"https://t.me/{username}/{message.message_id}"
            
            return post_url
            
        finally:
            # Удаляем временный файл
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    
    
    def _format_html(self, text: str) -> str:
        """
        Форматирует текст для Telegram HTML
        
        Telegram поддерживает: <b>, <i>, <u>, <code>, <pre>, <a>
        """
        # Простое форматирование
        # Первая строка - жирная (заголовок)
        lines = text.split('\n')
        if lines:
            lines[0] = f"<b>{lines[0]}</b>"
        
        return '\n'.join(lines)


# ════════════════════════════════════════════════════════════════
# ПРИМЕР ИСПОЛЬЗОВАНИЯ
# ════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    # Пример публикации
    publisher = TelegramPublisher(
        category_id=1,
        platform_id='@my_channel',
        user_id=12345
    )
    
    success, error, post_url = publisher.execute()
    
    if success:
        print(f"✅ Опубликовано: {post_url}")
    else:
        print(f"❌ Ошибка: {error}")
