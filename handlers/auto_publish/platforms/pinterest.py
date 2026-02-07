"""
Pinterest Publisher (Refactored)
=================================
Publisher ТОЛЬКО публикует контент.
Генерацию делает unified_generator.
"""

import logging
import tempfile
import os
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)


class PinterestPublisher:
    """
    Publisher для Pinterest
    
    Использует:
    - config/pinterest/text_rules.py для правил текста
    - config/pinterest/image_rules.py для правил изображений
    - ai/unified_generator.py для генерации контента
    """
    
    def __init__(self, category_id: str, platform_id: str, user_id: int = None, progress_callback=None):
        self.category_id = category_id
        self.platform_id = platform_id
        self.user_id = user_id
        self.progress_callback = progress_callback  # Коллбэк для обновления прогресса
        
        self.category = None
        self.platform_data = None
    
    
    def execute(self) -> Tuple[bool, str, str]:
        """Выполняет публикацию с детальным прогрессом (10 шагов)"""
        try:
            # ШАГ 1/10: Инициализация
            if self.progress_callback:
                self.progress_callback(1, "🔧 Инициализация...", "Подготовка системы")
            
            # ШАГ 2/10: Загрузка данных категории
            if self.progress_callback:
                self.progress_callback(2, "📂 Загружаю категорию...", "Получение настроек")
            self._load_data()
            
            # ШАГ 3/10: Подготовка к генерации
            if self.progress_callback:
                self.progress_callback(3, "⚙️ Настройка генератора...", "Конфигурация AI")
            
            # ШАГ 4/10: Генерация текста
            if self.progress_callback:
                self.progress_callback(4, "✍️ Генерирую описание...", "Claude создаёт текст")
            
            # ШАГ 5/10: Проверка текста
            if self.progress_callback:
                self.progress_callback(5, "📝 Проверяю описание...", "Валидация текста")
            
            # ШАГ 6/10: Генерация изображения
            if self.progress_callback:
                self.progress_callback(6, "🎨 Генерирую изображение...", "Nano Banana Pro создаёт пин")
            content = self._generate_content()
            
            # ШАГ 7/10: Обработка изображения
            if self.progress_callback:
                self.progress_callback(7, "🖼️ Обрабатываю изображение...", "Подготовка к загрузке")
            
            # ШАГ 8/10: Подключение к Pinterest
            if self.progress_callback:
                self.progress_callback(8, "🔗 Подключаюсь к Pinterest...", "Авторизация")
            
            # ШАГ 9/10: Загрузка пина
            if self.progress_callback:
                self.progress_callback(9, "📤 Загружаю пин...", "Отправка на доску")
            post_url = self._publish_to_pinterest(
                title=content.get('title', self.category.get('name', 'Pin')),
                description=content['text'],
                image_bytes=content['image_bytes']
            )
            
            # ШАГ 10/10: Завершение
            if self.progress_callback:
                self.progress_callback(10, "✅ Готово!", "Пин опубликован")
            
            logger.info(f"✅ Pinterest: Опубликовано {post_url}")
            
            return True, None, post_url
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Pinterest: {error_msg}")
            return False, error_msg, None
    
    
    def _load_data(self):
        """Загружает категорию и данные платформы"""
        from database.database import db
        
        print(f"🔍 _load_data: Загрузка категории {self.category_id}")
        print(f"   Тип category_id: {type(self.category_id)}")
        
        # Пробуем получить категорию
        try:
            self.category = db.get_category(self.category_id)
            print(f"   Результат db.get_category: {type(self.category)}")
            
            if self.category:
                print(f"   ✅ Категория найдена: {self.category.get('name', 'N/A')}")
            else:
                print(f"   ❌ db.get_category вернул None")
                
        except Exception as e:
            print(f"   ❌ Исключение при get_category: {e}")
            import traceback
            traceback.print_exc()
            self.category = None
        
        if not self.category:
            print(f"❌ Категория {self.category_id} НЕ НАЙДЕНА в БД!")
            print(f"   Проверьте что категория существует")
            raise ValueError(f"Категория {self.category_id} не найдена")
        
        # ВАЖНО: Берём Pinterest из platform_connections ПОЛЬЗОВАТЕЛЯ, а не из bots!
        if not self.user_id:
            raise ValueError("user_id обязателен для публикации в Pinterest")
        
        user = db.get_user(self.user_id)
        if not user:
            raise ValueError(f"Пользователь {self.user_id} не найден")
        
        # Ищем в platform_connections пользователя (там токены!)
        connections = user.get('platform_connections', {})
        if isinstance(connections, str):
            import json
            connections = json.loads(connections)
        
        pinterests = connections.get('pinterests', [])
        
        # ОТЛАДКА: Что есть в pinterests
        print(f"📊 ОТЛАДКА Pinterest:")
        print(f"   user_id: {self.user_id}")
        print(f"   platform_id: {self.platform_id} (type: {type(self.platform_id)})")
        print(f"   pinterests count: {len(pinterests)}")
        for idx, pin in enumerate(pinterests):
            print(f"   Pinterest {idx}:")
            if isinstance(pin, dict):
                print(f"      type: dict")
                print(f"      keys: {list(pin.keys())}")
                print(f"      id: {pin.get('id')} (type: {type(pin.get('id'))})")
                print(f"      board_name: {pin.get('board_name')}")
                print(f"      board_id: {pin.get('board_id')}")
            else:
                print(f"      type: {type(pin)}")
                print(f"      value: {pin}")
        
        # Поиск аккаунта Pinterest (по полю 'board', а не 'id'!)
        for pin in pinterests:
            if isinstance(pin, dict):
                # Pinterest может быть сохранён с board, board_name или id
                pin_identifier = pin.get('board') or pin.get('board_name') or pin.get('id')
                if pin_identifier and str(pin_identifier) == str(self.platform_id):
                    self.platform_data = pin
                    break
        
        if not self.platform_data:
            # ОТЛАДКА: Покажем что есть в pinterests
            print(f"❌ Pinterest {self.platform_id} не найден!")
            print(f"   Доступные Pinterest accounts:")
            for idx, pin in enumerate(pinterests):
                if isinstance(pin, dict):
                    board = pin.get('board') or pin.get('board_name') or pin.get('id')
                    print(f"   {idx}: board={board}, keys={list(pin.keys())}")
            raise ValueError(f"Pinterest аккаунт {self.platform_id} не найден")
        
        logger.info(f"📊 Загружены данные: категория '{self.category.get('name')}'")
    
    
    def _generate_content(self) -> Dict:
        """Генерирует контент через unified_generator"""
        from ai.unified_generator import generate_for_platform
        import random
        
        category_name = self.category.get('name', 'Контент')
        description = self.category.get('description', '')
        
        # Выбираем ЕДИНУЮ фразу
        selected_phrase = ''
        if description:
            phrases = [s.strip() for s in description.split(',') if s.strip()]
            if phrases:
                selected_phrase = random.choice(phrases)
                logger.info(f"📝 Выбрана единая фраза: '{selected_phrase[:50]}...'")
        
        # Стиль
        settings = self.category.get('settings', {})
        if isinstance(settings, str):
            import json
            settings = json.loads(settings)
        
        text_styles = settings.get('pinterest_text_styles', ['informative'])
        style = random.choice(text_styles) if text_styles else 'informative'
        
        logger.info(f"🎨 Генерация контента для Pinterest (стиль: {style})")
        
        # ГЕНЕРАЦИЯ
        result = generate_for_platform(
            platform='pinterest',
            category_name=category_name,
            selected_phrase=selected_phrase,
            style=style
        )
        
        if not result['success']:
            raise Exception(f"Ошибка генерации: {result.get('error')}")
        
        # Добавляем title
        result['title'] = category_name
        
        logger.info(f"✅ Контент сгенерирован: {len(result['text'])} символов")
        
        return result
    
    
    def _publish_to_pinterest(self, title: str, description: str, image_bytes: bytes) -> str:
        """Публикует в Pinterest"""
        import requests
        import base64
        import json
        
        # Токен доступа
        access_token = self.platform_data.get('access_token') if self.platform_data else None
        
        # ОТЛАДКА
        if not access_token:
            print(f"❌ access_token не найден!")
            print(f"   platform_data keys: {list(self.platform_data.keys()) if self.platform_data else 'None'}")
            print(f"   platform_data: {self.platform_data}")
            raise ValueError("Pinterest access_token не найден")
        
        print(f"✅ Pinterest token найден: {access_token[:20]}...")
        
        # ОТЛАДКА: Показываем все данные
        print(f"📊 platform_data содержимое:")
        for key, value in self.platform_data.items():
            if key == 'access_token':
                print(f"   {key}: {value[:20]}...")
            else:
                print(f"   {key}: {value}")
        
        # Board ID - сначала проверяем настройки категории
        board_id = self.platform_data.get('board_id')
        board_username = self.platform_data.get('board') or self.platform_data.get('username')
        
        # Проверяем выбранную доску в настройках категории
        import json
        settings = self.category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        # ПРОВЕРЯЕМ ОБА КЛЮЧА (старый и новый)
        selected_boards = settings.get('pinterest_selected_boards', []) or settings.get('pinterest_boards', [])
        
        print(f"📊 ОТЛАДКА выбора досок в publisher:")
        print(f"   category_id: {self.category_id}")
        print(f"   pinterest_selected_boards: {settings.get('pinterest_selected_boards', [])}")
        print(f"   pinterest_boards (старый ключ): {settings.get('pinterest_boards', [])}")
        print(f"   selected_boards (итого): {selected_boards}")
        
        if selected_boards:
            # Используем первую выбранную доску
            board_id = selected_boards[0]
            print(f"✅ Используем выбранную доску из категории: {board_id}")
        
        # Если нет board_id, получаем его через API
        if not board_id:
            print(f"⚠️ board_id отсутствует, получаем через Pinterest API...")
            print(f"   board_username: {board_username}")
            
            try:
                # Получаем список досок пользователя
                boards_url = "https://api.pinterest.com/v5/boards"
                headers = {"Authorization": f"Bearer {access_token}"}
                
                boards_response = requests.get(boards_url, headers=headers)
                boards_response.raise_for_status()
                boards_data = boards_response.json()
                
                print(f"📋 Получено досок: {len(boards_data.get('items', []))}")
                
                # Ищем доску по username
                for board in boards_data.get('items', []):
                    board_name = board.get('name', '').lower()
                    if board_username and board_username.lower() in board_name:
                        board_id = board.get('id')
                        print(f"✅ Найден board_id: {board_id} для доски '{board.get('name')}'")
                        
                        # Сохраняем board_id в platform_data для следующих публикаций
                        self.platform_data['board_id'] = board_id
                        
                        # Обновляем в БД
                        try:
                            from database.database import db
                            user = db.get_user(self.user_id)
                            connections = user.get('platform_connections', {})
                            if isinstance(connections, str):
                                import json
                                connections = json.loads(connections)
                            
                            pinterests = connections.get('pinterests', [])
                            for pin in pinterests:
                                if isinstance(pin, dict):
                                    pin_id = pin.get('board') or pin.get('username')
                                    if pin_id == board_username:
                                        pin['board_id'] = board_id
                                        print(f"💾 Сохраняем board_id в БД")
                                        break
                            
                            connections['pinterests'] = pinterests
                            db.cursor.execute("""
                                UPDATE users
                                SET platform_connections = %s::jsonb
                                WHERE id = %s
                            """, (json.dumps(connections), self.user_id))
                            db.conn.commit()
                        except Exception as e:
                            print(f"⚠️ Не удалось сохранить board_id в БД: {e}")
                        
                        break
                
                # Если не нашли по имени, берём первую доску
                if not board_id and boards_data.get('items'):
                    board_id = boards_data['items'][0].get('id')
                    print(f"⚠️ Используем первую доску: {board_id}")
                    
            except Exception as e:
                print(f"❌ Ошибка получения досок: {e}")
                raise ValueError(f"Не удалось получить board_id: {e}")
        
        if not board_id:
            print(f"❌ Board ID не найден!")
            raise ValueError("Board ID не найден после всех попыток")
        
        # Ссылка на сайт
        link = self.category.get('website_url', 'https://ecosteni.ru/')
        
        # Кодируем изображение в base64
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        
        # Создание пина через Pinterest API
        url = "https://api.pinterest.com/v5/pins"
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "board_id": board_id,
            "title": title,
            "description": description,
            "link": link,
            "media_source": {
                "source_type": "image_base64",
                "content_type": "image/jpeg",
                "data": image_base64
            }
        }
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code not in [200, 201]:
            raise Exception(f"Pinterest API error: {response.status_code} {response.text}")
        
        pin_data = response.json()
        pin_id = pin_data.get('id')
        
        return f"https://pinterest.com/pin/{pin_id}"
