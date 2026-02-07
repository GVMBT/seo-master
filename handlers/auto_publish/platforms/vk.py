"""
VK Publisher (Refactored)
==========================
Publisher ТОЛЬКО публикует контент.
"""

import logging
from typing import Tuple, Dict

logger = logging.getLogger(__name__)


class VKPublisher:
    """Publisher для VK"""
    
    def __init__(self, category_id: str, platform_id: str, user_id: int = None):
        self.category_id = category_id
        self.platform_id = platform_id
        self.user_id = user_id
    
    def pre_validate(self):
        """
        КРИТИЧНО: Проверка VK токена ДО генерации контента
        """
        from database.database import db
        import requests
        
        print(f"🔍 Проверка VK токена перед генерацией...")
        print(f"   Platform ID (VK group/user ID): {self.platform_id}")
        
        # Получаем VK подключение
        user = db.get_user(self.user_id)
        platform_conns = user.get('platform_connections', {})
        
        if isinstance(platform_conns, str):
            import json
            platform_conns = json.loads(platform_conns)
        
        vks = platform_conns.get('vks', [])
        
        print(f"   Всего VK подключений: {len(vks)}")
        
        # Ищем подключение по VK ID (owner_id или group_id)
        # platform_id это ID группы VK или user_id VK
        vk_connection = None
        for vk in vks:
            vk_id = str(vk.get('id', ''))  # ID записи в БД
            vk_owner_id = str(vk.get('owner_id', ''))  # ID группы/пользователя VK
            
            print(f"   Проверяем VK: id={vk_id}, owner_id={vk_owner_id}, name={vk.get('name', 'N/A')}")
            
            # Ищем совпадение по owner_id
            if vk_owner_id == str(self.platform_id):
                vk_connection = vk
                print(f"   ✅ Найдено подключение по owner_id: {vk_owner_id}")
                break
        
        if not vk_connection:
            print(f"   ❌ VK подключение с owner_id={self.platform_id} не найдено")
            print(f"   Доступные owner_id: {[str(vk.get('owner_id', 'N/A')) for vk in vks]}")
            raise ValueError(f"VK подключение {self.platform_id} не найдено")
        
        access_token = vk_connection.get('access_token')
        if not access_token:
            raise ValueError("Токен доступа VK не найден")
        
        # КРИТИЧНО: Проверяем токен
        vk_type = vk_connection.get('type', 'user')
        
        if vk_type == 'group':
            # Для группы - проверяем через groups.getById
            group_id = abs(int(self.platform_id))
            response = requests.get(
                "https://api.vk.com/method/groups.getById",
                params={
                    "group_id": group_id,
                    "access_token": access_token,
                    "v": "5.199"
                },
                timeout=10
            )
        else:
            # Для личной страницы - проверяем через users.get
            response = requests.get(
                "https://api.vk.com/method/users.get",
                params={
                    "access_token": access_token,
                    "v": "5.199"
                },
                timeout=10
            )
        
        result = response.json()
        
        if 'error' in result:
            error_msg = result['error'].get('error_msg', 'Unknown error')
            error_code = result['error'].get('error_code', 0)
            raise ValueError(f"Ошибка VK API ({error_code}): {error_msg}")
        
        if 'response' not in result or not result['response']:
            raise ValueError("Невалидный ответ от VK API")
        
        print(f"✅ VK токен валиден")
    
    
    def execute(self) -> Tuple[bool, str, str]:
        """Выполняет публикацию"""
        try:
            # КРИТИЧНО: Проверка ДО генерации контента
            self.pre_validate()
            
            from ai.unified_generator import generate_for_platform
            from database.database import db
            import random
            
            # Загрузка категории
            category = db.get_category(self.category_id)
            if not category:
                raise ValueError(f"Категория {self.category_id} не найдена")
            
            # Единая фраза
            description = category.get('description', '')
            selected_phrase = ''
            if description:
                phrases = [s.strip() for s in description.split(',') if s.strip()]
                if phrases:
                    selected_phrase = random.choice(phrases)
            
            # Генерация
            result = generate_for_platform(
                platform='vk',
                category_name=category.get('name', 'Контент'),
                selected_phrase=selected_phrase,
                style='engaging'
            )
            
            if not result['success']:
                raise Exception(f"Ошибка генерации: {result.get('error')}")
            
            # Получаем сгенерированный контент
            text = result.get('text', '')
            image_bytes = result.get('image')
            
            if not text:
                raise Exception("Текст не сгенерирован")
            
            # Публикация в VK
            post_url = self._publish_to_vk(text, image_bytes)
            
            logger.info(f"✅ VK: Опубликовано {post_url}")
            return True, None, post_url
            
        except Exception as e:
            logger.error(f"❌ VK: {e}")
            return False, str(e), None
    
    def _publish_to_vk(self, text: str, image_bytes: bytes = None) -> str:
        """
        Публикует пост в VK (на стену группы или личной страницы)
        
        Args:
            text: Текст поста
            image_bytes: Изображение (опционально)
            
        Returns:
            URL опубликованного поста
        """
        import requests
        from database.database import db
        
        # Получаем VK подключение
        user = db.get_user(self.user_id)
        platform_conns = user.get('platform_connections', {})
        
        if isinstance(platform_conns, str):
            import json
            platform_conns = json.loads(platform_conns)
        
        vks = platform_conns.get('vks', [])
        
        # Ищем подключение
        vk_connection = None
        for vk in vks:
            if str(vk.get('id')) == str(self.platform_id):
                vk_connection = vk
                break
        
        if not vk_connection:
            raise ValueError(f"VK подключение {self.platform_id} не найдено")
        
        access_token = vk_connection.get('access_token')
        vk_type = vk_connection.get('type', 'user')
        
        # Определяем owner_id
        if vk_type == 'group':
            # Для группы используем отрицательный ID
            owner_id = int(self.platform_id)  # Уже отрицательный
        else:
            # Для личной страницы используем положительный ID
            owner_id = int(self.platform_id)
        
        print(f"📤 Публикация в VK: owner_id={owner_id}, type={vk_type}")
        
        # Шаг 1: Загрузка изображения (если есть)
        attachments = []
        if image_bytes:
            try:
                photo_id = self._upload_photo(access_token, owner_id, image_bytes)
                attachments.append(photo_id)
                print(f"✅ Изображение загружено: {photo_id}")
            except Exception as e:
                print(f"⚠️ Не удалось загрузить изображение: {e}")
                # Продолжаем без изображения
        
        # Шаг 2: Публикация поста
        # КРИТИЧНО: Для токена группы НЕ используем from_group
        # Токен группы уже авторизован от имени группы
        params = {
            'owner_id': owner_id,
            'message': text,
            'access_token': access_token,
            'v': '5.199'
        }
        
        # from_group используется ТОЛЬКО для личных токенов
        # Для токена группы он не нужен и вызывает ошибку
        if vk_type == 'user':
            params['from_group'] = 0
        
        if attachments:
            params['attachments'] = ','.join(attachments)
        
        response = requests.post(
            'https://api.vk.com/method/wall.post',
            data=params,
            timeout=30
        )
        
        result = response.json()
        
        if 'error' in result:
            error_msg = result['error'].get('error_msg', 'Unknown error')
            error_code = result['error'].get('error_code', 0)
            
            # Специальная обработка ошибки авторизации для личного токена
            if error_code == 5 and vk_type == 'user':
                raise Exception(
                    f"VK API error: {error_msg}\n\n"
                    "⚠️ Личный токен не работает для публикаций.\n"
                    "Используйте ТОКЕН ГРУППЫ вместо личного токена.\n\n"
                    "Как получить:\n"
                    "1. Удалите это VK подключение\n"
                    "2. Добавьте VK заново\n"
                    "3. Выберите 'Токен группы' вместо 'Личный токен'"
                )
            
            raise Exception(f"VK API error ({error_code}): {error_msg}")
        
        if 'response' not in result or 'post_id' not in result['response']:
            raise Exception("Невалидный ответ от VK API")
        
        post_id = result['response']['post_id']
        
        # Формируем URL поста
        if owner_id < 0:
            # Группа
            post_url = f"https://vk.com/wall{owner_id}_{post_id}"
        else:
            # Личная страница
            post_url = f"https://vk.com/wall{owner_id}_{post_id}"
        
        return post_url
    
    def _upload_photo(self, access_token: str, owner_id: int, image_bytes: bytes) -> str:
        """
        Загружает фото на сервер VK и возвращает attachment ID
        
        Args:
            access_token: Токен доступа
            owner_id: ID владельца (положительный для user, отрицательный для group)
            image_bytes: Байты изображения
            
        Returns:
            Attachment ID в формате photo{owner_id}_{photo_id}
        """
        import requests
        
        # Шаг 1: Получаем upload URL
        params = {
            'access_token': access_token,
            'v': '5.199'
        }
        
        if owner_id < 0:
            # Для группы
            params['group_id'] = abs(owner_id)
        
        response = requests.get(
            'https://api.vk.com/method/photos.getWallUploadServer',
            params=params,
            timeout=10
        )
        
        result = response.json()
        
        if 'error' in result:
            raise Exception(f"Ошибка получения upload URL: {result['error'].get('error_msg')}")
        
        upload_url = result['response']['upload_url']
        
        # Шаг 2: Загружаем фото на сервер
        files = {'photo': ('image.jpg', image_bytes, 'image/jpeg')}
        upload_response = requests.post(upload_url, files=files, timeout=30)
        upload_result = upload_response.json()
        
        if 'photo' not in upload_result:
            raise Exception("Ошибка загрузки фото на сервер VK")
        
        # Шаг 3: Сохраняем фото
        save_params = {
            'photo': upload_result['photo'],
            'server': upload_result['server'],
            'hash': upload_result['hash'],
            'access_token': access_token,
            'v': '5.199'
        }
        
        if owner_id < 0:
            save_params['group_id'] = abs(owner_id)
        
        save_response = requests.post(
            'https://api.vk.com/method/photos.saveWallPhoto',
            data=save_params,
            timeout=10
        )
        
        save_result = save_response.json()
        
        if 'error' in save_result:
            raise Exception(f"Ошибка сохранения фото: {save_result['error'].get('error_msg')}")
        
        if 'response' not in save_result or len(save_result['response']) == 0:
            raise Exception("Пустой ответ при сохранении фото")
        
        photo = save_result['response'][0]
        photo_id = f"photo{photo['owner_id']}_{photo['id']}"
        
        return photo_id
