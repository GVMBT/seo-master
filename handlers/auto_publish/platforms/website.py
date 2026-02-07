# -*- coding: utf-8 -*-
"""
Website Publisher
Публикация SEO-статей в WordPress
"""
import logging
import tempfile
import os
from typing import Dict, Any, List

from ..base import BasePlatformPublisher
from ..utils.error_handler import (
    PlatformNotFoundError,
    ValidationError,
    ContentGenerationError,
    APIError
)

logger = logging.getLogger(__name__)


class WebsitePublisher(BasePlatformPublisher):
    """
    Публикатор для Website (WordPress)
    
    Генерирует SEO-статью с изображениями и публикует в WordPress
    """
    
    def get_platform_name(self) -> str:
        return 'website'
    
    def get_cost(self) -> int:
        """
        Стоимость зависит от параметров статьи
        
        По умолчанию:
        - 1500 слов = 150 токенов (10 токенов за 100 слов)
        - 4 изображения = 120 токенов (30 токенов за изображение)
        ИТОГО: ~270 токенов
        """
        # Получаем сохраненные параметры или используем дефолтные
        params = self._get_article_params()
        
        words = params.get('words', 1500)
        images = params.get('images', 4)  # 1 обложка + 3 в статье
        
        # Расчет стоимости
        text_cost = (words // 100) * 10
        image_cost = images * 30
        
        total = text_cost + image_cost
        logger.info(f"💰 Стоимость статьи: {total} токенов ({words} слов + {images} изображений)")
        
        return total
    
    def get_platform_data(self) -> Dict[str, Any]:
        """
        Получает данные подключенного WordPress сайта
        """
        from database.database import db
        
        user = db.get_user(self.user_id)
        if not user:
            raise ValueError(f"Пользователь {self.user_id} не найден")
        
        if not isinstance(user, dict):
            user = dict(user)
        
        # Получаем connections
        connections = user.get('platform_connections', {})
        if isinstance(connections, str):
            import json
            connections = json.loads(connections)
        
        websites = connections.get('websites', [])
        
        # Ищем сайт по URL (platform_id)
        website = None
        for site in websites:
            if isinstance(site, dict):
                if site.get('url') == self.platform_id:
                    website = site
                    break
        
        if not website:
            raise PlatformNotFoundError('website', self.platform_id)
        
        if website.get('status') != 'active':
            raise PlatformNotFoundError('website', f"{self.platform_id} (не активен)")
        
        return website
    
    def get_settings(self) -> Dict[str, Any]:
        """
        Получает настройки Website из категории
        """
        from handlers.platform_settings.utils import get_platform_settings
        
        settings = get_platform_settings(self.category, 'website')
        
        logger.info(
            f"📋 Настройки Website: "
            f"html_style={settings.get('html_style')}, "
            f"format={settings.get('format')}"
        )
        
        return settings
    
    def pre_validate(self):
        """
        КРИТИЧНО: Проверка подключения к WordPress ДО генерации контента
        
        Raises:
            PublishError: Если подключение не работает
        """
        from handlers.website.wordpress_api import test_wp_connection
        
        print(f"🔍 Проверка подключения к WordPress...")
        
        # Проверяем наличие данных
        if not self.platform_data:
            raise ValidationError(
                "Сайт не найден или не настроен",
                field='platform_data',
                platform='website'
            )
        
        url = self.platform_data.get('url', '').rstrip('/')
        username = self.platform_data.get('username', '')
        password = self.platform_data.get('password', '')
        
        # Проверяем что все данные есть
        if not url:
            raise ValidationError("Не указан URL сайта WordPress", field='url', platform='website')
        
        if not username:
            raise ValidationError("Не указан логин WordPress", field='username', platform='website')
        
        if not password:
            raise ValidationError("Не указан пароль приложения WordPress", field='password', platform='website')
        
        # КРИТИЧНО: Тестируем подключение
        result = test_wp_connection(url, username, password)
        
        if not result.get('success'):
            error_msg = result.get('message', 'Неизвестная ошибка')
            print(f"❌ Подключение к WordPress не удалось: {error_msg}")
            raise ValidationError(
                f"Не удалось подключиться к WordPress: {error_msg}\n\n"
                f"Проверьте:\n"
                f"• Логин и пароль приложения\n"
                f"• Доступность сайта {url}\n"
                f"• Права доступа к REST API",
                field='connection',
                platform='website'
            )
        
        print(f"✅ Подключение к WordPress успешно")
        logger.info(f"✅ pre_validate Website: подключение к {url} работает")
    
    def validate(self):
        """
        Валидирует данные WordPress
        """
        # Проверяем URL
        if not self.platform_data.get('url'):
            raise ValidationError(
                "Не указан URL сайта",
                field='url',
                platform='website'
            )
        
        # Проверяем username
        if not self.platform_data.get('username'):
            raise ValidationError(
                "Не указан username WordPress",
                field='username',
                platform='website'
            )
        
        # Проверяем password (app password)
        if not self.platform_data.get('password'):
            raise ValidationError(
                "Не указан пароль приложения WordPress",
                field='password',
                platform='website'
            )
        
        logger.info(f"✅ Валидация Website пройдена")
    
    def publish(self) -> str:
        """
        Публикует SEO-статью в WordPress
        
        Returns:
            str: URL статьи
        """
        # 1. Генерируем статью
        article_data = self._generate_article()
        
        # 2. Генерируем изображения
        images = self._generate_images(article_data)
        
        # 3. Публикуем в WordPress
        try:
            post_url = self._publish_to_wordpress(article_data, images)
            return post_url
        finally:
            # Удаляем временные файлы
            for img_path in images:
                try:
                    os.unlink(img_path)
                except Exception:
                    pass
    
    def _get_article_params(self) -> Dict[str, Any]:
        """
        Получает сохраненные параметры статьи или возвращает дефолтные
        """
        # Проверяем есть ли сохраненные параметры в категории
        settings = self.category.get('settings', {})
        if isinstance(settings, str):
            import json
            settings = json.loads(settings)
        
        website_settings = settings.get('website', {})
        
        return {
            'words': website_settings.get('words', 1500),
            'images': website_settings.get('images', 4),
            'style': website_settings.get('html_style', 'news')
        }
    
    def _generate_article(self) -> Dict[str, Any]:
        """
        Генерирует SEO-статью через AI
        
        Returns:
            dict: {
                'title': str,
                'content': str (HTML),
                'meta_description': str,
                'keywords': List[str]
            }
        """
        from ai.website_article_generator import generate_website_article
        import random
        
        params = self._get_article_params()
        
        category_name = self.category.get('name', '')
        description = self.category.get('description', '')
        keywords_list = self.category.get('keywords', [])
        
        # Выбираем ключевую фразу из description
        keyword = category_name  # По умолчанию
        if description:
            phrases = [s.strip() for s in description.split(',') if s.strip()]
            if phrases:
                keyword = random.choice(phrases)
        
        logger.info(
            f"📝 Генерация статьи: {params['words']} слов, "
            f"стиль={params['style']}, ключ='{keyword}'"
        )
        
        # Получаем данные компании из БД
        from database.database import db
        user = db.get_user(self.user_id)
        company_data = {
            'company_name': 'ООО «Дизайн-Сервис»',
            'company_city': user.get('company_city', '') if user else '',
            'company_address': user.get('company_address', '') if user else '',
            'company_phone': user.get('company_phone', '') if user else '',
            'company_email': user.get('company_email', '') if user else '',
            'telegram': user.get('telegram', '') if user else '',
            'experience': '16 лет'
        }
        
        result = generate_website_article(
            keyword=keyword,
            category_name=category_name,
            category_description=description,
            company_data=company_data,
            prices=None,  # TODO: добавить получение цен из категории
            reviews=None,  # TODO: добавить получение отзывов
            external_links=None,
            internal_links=None,
            text_style=params.get('style', 'professional'),
            html_style=params.get('style', 'creative'),
            site_colors=None,
            min_words=params.get('words', 1500),
            max_words=params.get('words', 2500)
        )
        
        if not result.get('success'):
            error = result.get('error', 'Неизвестная ошибка')
            raise ContentGenerationError('text', error, platform='website')
        
        article_html = result.get('html', '')
        if not article_html:
            raise ContentGenerationError('text', 'Пустая статья', platform='website')
        
        title = result.get('seo_title', category_name)
        meta_description = result.get('meta_description', description[:160])
        
        logger.info(f"✅ Статья сгенерирована: '{title}' ({len(article_html)} символов)")
        
        return {
            'title': title,
            'content': article_html,
            'meta_description': meta_description,
            'keywords': keywords_list
        }
    
    def _generate_images(self, article_data: Dict[str, Any]) -> List[str]:
        """
        Генерирует изображения для статьи
        
        Args:
            article_data: Данные статьи
            
        Returns:
            List[str]: Список путей к временным файлам с изображениями
        """
        # ВАЖНО: Используем generate_image_only с НАСТРОЙКАМИ, как в ручной публикации!
        from ai.unified_generator import generate_image_only
        
        params = self._get_article_params()
        num_images = params['images']
        
        category_name = self.category.get('name', '')
        title = article_data.get('title', category_name)
        description = self.category.get('description', '')
        
        # Получаем КЛЮЧЕВОЕ СЛОВО статьи (как в ручной публикации!)
        keywords = self.category.get('keywords', [])
        if isinstance(keywords, str):
            import json
            try:
                keywords = json.loads(keywords)
            except Exception:
                keywords = []
        
        # Выбираем случайное ключевое слово
        import random
        article_keyword = random.choice(keywords) if keywords else category_name
        
        logger.info(f"🔑 Ключевое слово для изображений: {article_keyword}")
        
        # ПОЛУЧАЕМ НАСТРОЙКИ ИЗОБРАЖЕНИЙ ИЗ БД (как в ручной публикации!)
        platform_image_settings = {}
        category_settings = self.category.get('settings', {})
        if isinstance(category_settings, str):
            import json
            try:
                category_settings = json.loads(category_settings)
            except Exception:
                category_settings = {}
        
        # Извлекаем настройки изображений для website
        platform_image_settings = {
            'styles': category_settings.get('website_image_styles', []),
            'cameras': category_settings.get('website_image_cameras', []),
            'angles': category_settings.get('website_image_angles', []),
            'quality': category_settings.get('website_image_quality', []),
            'tones': category_settings.get('website_image_tones', []),
            'formats': category_settings.get('website_image_formats', ['16:9'])
        }
        
        logger.info(f"📸 Настройки изображений из БД:")
        logger.info(f"   Стили: {platform_image_settings['styles']}")
        logger.info(f"   Камеры: {platform_image_settings['cameras']}")
        logger.info(f"   Ракурсы: {platform_image_settings['angles']}")
        logger.info(f"   Качество: {platform_image_settings['quality']}")
        logger.info(f"   Тональность: {platform_image_settings['tones']}")
        logger.info(f"   Форматы: {platform_image_settings['formats']}")
        
        images = []
        
        # Выбираем фразы из описания для вариативности
        phrases = []
        if description:
            phrases = [s.strip() for s in description.split(',') if s.strip()]
        
        for i in range(num_images):
            try:
                # Варьируем контекст для каждого изображения (как в ручной публикации!)
                if i == 0:
                    context = "detailed view, professional photography"
                elif i == 1:
                    context = "installation process, professional setting"
                else:
                    context = "finished result, high quality"
                
                # ОБЯЗАТЕЛЬНО добавляем ключевое слово + контекст + фразу (как в ручной публикации!)
                if phrases:
                    random_phrase = random.choice(phrases)
                    selected_phrase = f"{article_keyword}, {context}, {random_phrase}"
                else:
                    selected_phrase = f"{article_keyword}, {context}"
                
                logger.info(f"🎨 Генерация изображения {i+1}/{num_images}")
                logger.info(f"   Keyword (ОБЯЗАТЕЛЬНО): {article_keyword}")
                logger.info(f"   Full phrase: {selected_phrase[:100]}...")
                
                # Подготавливаем настройки для изображения (как в ручной публикации!)
                image_settings = {
                    'styles': platform_image_settings.get('styles', []),
                    'cameras': platform_image_settings.get('cameras', []),
                    'angles': platform_image_settings.get('angles', []),
                    'quality': platform_image_settings.get('quality', []),
                    'tones': platform_image_settings.get('tones', []),
                    'format': platform_image_settings.get('formats', ['16:9'])[0] if platform_image_settings.get('formats') else '16:9',
                    'formats': platform_image_settings.get('formats', ['16:9'])
                }
                
                logger.info(f"📸 Применяемые настройки изображения {i+1}:")
                logger.info(f"   Стили: {image_settings['styles']}")
                logger.info(f"   Камеры: {image_settings['cameras']}")
                logger.info(f"   Ракурсы: {image_settings['angles']}")
                logger.info(f"   Качество: {image_settings['quality']}")
                logger.info(f"   Тональность: {image_settings['tones']}")
                logger.info(f"   Формат: {image_settings['format']}")
                
                # ИСПОЛЬЗУЕМ generate_image_only С НАСТРОЙКАМИ (как в ручной публикации!)
                result = generate_image_only(
                    platform='website',
                    category_name=category_name,
                    selected_phrase=selected_phrase,
                    image_settings=image_settings
                )
                
                if not result.get('success'):
                    logger.warning(f"⚠️ Не удалось сгенерировать изображение {i+1}, пропускаем")
                    continue
                
                image_bytes = result.get('image_bytes')
                if not image_bytes:
                    logger.warning(f"⚠️ Изображение {i+1} не содержит данных, пропускаем")
                    continue
                
                # Сохраняем во временный файл
                fd, image_path = tempfile.mkstemp(suffix='.jpg', prefix=f'website_{i}_')
                with os.fdopen(fd, 'wb') as f:
                    f.write(image_bytes)
                
                images.append(image_path)
                logger.info(f"✅ Изображение {i+1} сгенерировано")
                
            except Exception as e:
                logger.warning(f"⚠️ Ошибка генерации изображения {i+1}: {e}, продолжаем")
                continue
        
        if not images:
            raise ContentGenerationError('image', 'Не удалось сгенерировать ни одного изображения', platform='website')
        
        logger.info(f"✅ Сгенерировано {len(images)} изображений")
        return images
    
    def _publish_to_wordpress(self, article_data: Dict[str, Any], images: List[str]) -> str:
        """
        Публикует статью с изображениями в WordPress
        
        Args:
            article_data: Данные статьи
            images: Список путей к изображениям
            
        Returns:
            str: URL статьи
        """
        from handlers.website.wordpress_api import WordPressManager
        
        wp_url = self.platform_data.get('url')
        wp_username = self.platform_data.get('username')
        wp_password = self.platform_data.get('password')
        
        try:
            # Создаем менеджер WordPress
            wp = WordPressManager(wp_url, wp_username, wp_password)
            
            # 1. Загружаем изображения в WordPress
            logger.info(f"📤 Загрузка {len(images)} изображений в WordPress...")
            
            uploaded_images = []
            for i, img_path in enumerate(images):
                try:
                    img_id = wp.upload_image(img_path, f"Article image {i+1}")
                    if img_id:
                        img_url = wp.get_image_url(img_id)
                        uploaded_images.append({
                            'id': img_id,
                            'url': img_url
                        })
                        logger.info(f"✅ Изображение {i+1} загружено: ID={img_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось загрузить изображение {i+1}: {e}")
                    continue
            
            if not uploaded_images:
                raise APIError("Не удалось загрузить ни одного изображения в WordPress", platform='website')
            
            # 2. Вставляем изображения в статью
            content = article_data['content']
            
            # Первое изображение будет featured image
            featured_image_id = uploaded_images[0]['id']
            
            # Остальные вставляем в текст статьи через равные промежутки
            if len(uploaded_images) > 1:
                # Разбиваем контент на параграфы
                paragraphs = content.split('</p>')
                insert_positions = [len(paragraphs) // (len(uploaded_images)- 1) * i 
                                   for i in range(1, len(uploaded_images))]
                
                # Вставляем изображения
                for idx, pos in enumerate(insert_positions, 1):
                    if idx < len(uploaded_images) and pos < len(paragraphs):
                        img_html = f'<img src="{uploaded_images[idx]["url"]}" alt="{article_data["title"]}" class="wp-image-{uploaded_images[idx]["id"]}"/>'
                        paragraphs[pos] += img_html
                
                content = '</p>'.join(paragraphs)
            
            # 3. Создаем пост
            logger.info(f"📝 Публикация статьи в WordPress...")
            
            post_data = {
                'title': article_data['title'],
                'content': content,
                'status': 'publish',
                'featured_media': featured_image_id,
                'meta': {
                    'description': article_data['meta_description']
                }
            }
            
            post_id = wp.create_post(**post_data)
            
            if not post_id:
                raise APIError("WordPress не вернул ID поста", platform='website')
            
            post_url = f"{wp_url}/?p={post_id}"
            
            logger.info(f"✅ Статья опубликована в WordPress: {post_url}")
            return post_url
            
        except Exception as e:
            if "WordPress" in str(e) or "API" in str(e):
                raise APIError(str(e), platform='website')
            else:
                raise


# Экспортируем класс
__all__ = ['WebsitePublisher']
