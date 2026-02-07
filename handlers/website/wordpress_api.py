# -*- coding: utf-8 -*-
"""
Модуль публикации статей на WordPress через REST API
"""
import base64
import requests
import re
import logging

logger = logging.getLogger(__name__)


def get_wp_headers(wp_login, wp_password):
    """
    Создаёт заголовки для Basic Auth WordPress API
    
    Args:
        wp_login: Логин WordPress
        wp_password: Пароль приложения (Application Password)
        
    Returns:
        dict: HTTP заголовки с авторизацией
    """
    token = base64.b64encode(f"{wp_login}:{wp_password}".encode()).decode()
    return {
        'Authorization': f'Basic {token}',
        'Content-Type': 'application/json'
    }


def test_wp_connection(wp_url, wp_login, wp_password):
    """
    Проверяет подключение к WordPress API
    
    Args:
        wp_url: URL сайта (например, https://site.com)
        wp_login: Логин
        wp_password: Пароль приложения
        
    Returns:
        dict: {'success': bool, 'message': str}
    """
    try:
        headers = get_wp_headers(wp_login, wp_password)
        
        # Пробуем получить информацию о пользователе
        response = requests.get(
            f"{wp_url}/wp-json/wp/v2/users/me",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            user_data = response.json()
            return {
                'success': True,
                'message': f"✅ Подключено как {user_data.get('name', 'пользователь')}",
                'user': user_data
            }
        else:
            return {
                'success': False,
                'message': f"❌ Ошибка подключения: {response.status_code}"
            }
            
    except Exception as e:
        return {
            'success': False,
            'message': f"❌ Ошибка: {str(e)[:100]}"
        }


def upload_image_to_wp(wp_url, wp_login, wp_password, image_path, filename_slug, alt_text=""):
    """
    Загружает изображение на WordPress
    
    Args:
        wp_url: URL сайта
        wp_login: Логин
        wp_password: Пароль приложения
        image_path: Путь к файлу изображения
        filename_slug: Slug для имени файла
        alt_text: ALT-текст для изображения (для SEO)
        
    Returns:
        dict: {'id': int, 'url': str} или None
    """
    try:
        media_url = f"{wp_url}/wp-json/wp/v2/media"
        token = base64.b64encode(f"{wp_login}:{wp_password}".encode()).decode()
        
        # Читаем файл
        with open(image_path, 'rb') as f:
            img_data = f.read()
        
        # Формируем имя файла
        img_filename = f"{filename_slug}-image.jpg"
        
        # Заголовки для загрузки медиа
        media_headers = {
            'Authorization': f'Basic {token}',
            'Content-Disposition': f'attachment; filename="{img_filename}"',
            'Content-Type': 'image/jpeg'
        }
        
        # Загружаем
        response = requests.post(
            media_url,
            headers=media_headers,
            data=img_data,
            timeout=60
        )
        
        if response.status_code in [200, 201]:
            media_data = response.json()
            media_id = media_data.get('id')
            
            # Если есть ALT-текст, обновляем метаданные изображения
            if alt_text and media_id:
                try:
                    update_url = f"{wp_url}/wp-json/wp/v2/media/{media_id}"
                    update_headers = {
                        'Authorization': f'Basic {token}',
                        'Content-Type': 'application/json'
                    }
                    update_data = {
                        'alt_text': alt_text,
                        'caption': alt_text  # Также устанавливаем как подпись
                    }
                    requests.post(update_url, headers=update_headers, json=update_data, timeout=30)
                    logger.info(f"✅ ALT-текст установлен: {alt_text[:50]}...")
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось установить ALT-текст: {e}")
            
            result = {
                'id': media_id,
                'url': media_data.get('source_url', '')
            }
            logger.info(f"✅ Изображение загружено: ID {result['id']}")
            return result
        else:
            logger.error(f"⚠️ Ошибка загрузки: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Ошибка upload_image_to_wp: {e}")
        return None


def insert_images_in_content(html_content, image_urls):
    """
    Вставляет изображения в HTML контент статьи
    
    Вставляет после каждого второго H2 заголовка
    
    Args:
        html_content: HTML текст статьи
        image_urls: list URL изображений
        
    Returns:
        str: HTML с вставленными изображениями
    """
    if not image_urls:
        return html_content
    
    # Находим все H2 заголовки
    h2_pattern = re.compile(r'(<h2[^>]*>.*?</h2>)', re.DOTALL | re.IGNORECASE)
    h2_positions = []
    
    for match in h2_pattern.finditer(html_content):
        h2_positions.append(match.end())
    
    # Вставляем изображения после каждого второго H2
    if h2_positions:
        image_index = 0
        offset = 0
        
        for i, pos in enumerate(h2_positions):
            # Вставляем после каждого 2-го H2 (индексы 1, 3, 5...)
            if (i + 1) % 2 == 0 and image_index < len(image_urls):
                img_html = f'\n\n<figure class="wp-block-image"><img src="{image_urls[image_index]}" alt="Изображение" /></figure>\n\n'
                html_content = html_content[:pos + offset] + img_html + html_content[pos + offset:]
                offset += len(img_html)
                image_index += 1
    
    return html_content


def create_wordpress_post(wp_url, wp_login, wp_password, article_data):
    """
    Создаёт пост на WordPress
    
    Args:
        wp_url: URL сайта
        wp_login: Логин
        wp_password: Пароль приложения
        article_data: dict с данными статьи:
            - title: Заголовок (SEO_TITLE)
            - content: HTML контент
            - excerpt: Краткое описание (META_DESC)
            - featured_media_id: ID изображения (опционально)
            - status: 'publish' или 'draft' (по умолчанию draft)
            
    Returns:
        dict: {'success': bool, 'post_id': int, 'url': str, 'error': str}
    """
    try:
        headers = get_wp_headers(wp_login, wp_password)
        posts_url = f"{wp_url}/wp-json/wp/v2/posts"
        
        # Формируем данные поста
        post_data = {
            'title': article_data.get('title', 'Без заголовка'),
            'content': article_data.get('content', ''),
            'excerpt': article_data.get('excerpt', ''),
            'status': article_data.get('status', 'draft'),
            'comment_status': 'open',
            'ping_status': 'open'
        }
        
        # Добавляем автора если указан (ID пользователя WordPress)
        if article_data.get('author_id'):
            post_data['author'] = article_data['author_id']
            logger.info(f"✍️ Добавлен автор: ID {article_data['author_id']}")
        
        # Добавляем slug (ЧПУ) если есть
        if article_data.get('slug'):
            post_data['slug'] = article_data['slug']
            logger.info(f"📝 Добавлен slug в post_data: {article_data['slug']}")
        else:
            logger.warning("⚠️ Slug не передан в article_data!")
        
        # Добавляем featured изображение если есть
        if article_data.get('featured_media_id'):
            post_data['featured_media'] = article_data['featured_media_id']
        
        # Добавляем categories если есть
        if article_data.get('categories'):
            post_data['categories'] = article_data['categories']
        
        # Добавляем tags если есть
        if article_data.get('tags'):
            post_data['tags'] = article_data['tags']
        
        # Добавляем мета-данные для Yoast SEO
        yoast_meta = {}
        if article_data.get('meta_description'):
            yoast_meta['_yoast_wpseo_metadesc'] = article_data['meta_description']
        if article_data.get('seo_title'):
            yoast_meta['_yoast_wpseo_title'] = article_data['seo_title']
        if article_data.get('focus_keyword'):
            yoast_meta['_yoast_wpseo_focuskw'] = article_data['focus_keyword']
        
        # Добавляем дополнительные SEO настройки
        if article_data.get('canonical_url'):
            yoast_meta['_yoast_wpseo_canonical'] = article_data['canonical_url']
        
        if article_data.get('robots_meta'):
            # Разбираем "index, follow" на отдельные параметры
            robots = article_data['robots_meta'].replace(' ', '').split(',')
            if 'noindex' in robots:
                yoast_meta['_yoast_wpseo_meta-robots-noindex'] = '1'
            if 'nofollow' in robots:
                yoast_meta['_yoast_wpseo_meta-robots-nofollow'] = '1'
        
        if article_data.get('schema_type'):
            yoast_meta['_yoast_wpseo_schema_article_type'] = article_data['schema_type']
        
        if yoast_meta:
            post_data['meta'] = yoast_meta
        
        # Создаём пост
        response = requests.post(
            posts_url,
            headers=headers,
            json=post_data,
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            post = response.json()
            actual_slug = post.get('slug', 'неизвестно')
            logger.info(f"✅ WordPress вернул slug: {actual_slug}")
            logger.info(f"✅ Итоговый URL: {post.get('link', '')}")
            return {
                'success': True,
                'post_id': post.get('id'),
                'url': post.get('link', ''),
                'slug': actual_slug,
                'status': post.get('status', 'draft'),
                'message': f"✅ Статья создана (ID: {post.get('id')}, slug: {actual_slug})"
            }
        else:
            error_msg = f"Ошибка {response.status_code}"
            try:
                error_data = response.json()
                error_msg = error_data.get('message', error_msg)
            except Exception:
                pass
            
            return {
                'success': False,
                'error': error_msg,
                'message': f"❌ {error_msg}"
            }
            
    except Exception as e:
        return {
            'success': False,
            'error': str(e)[:200],
            'message': f"❌ Ошибка: {str(e)[:100]}"
        }


def get_wordpress_categories(wp_url, wp_login, wp_password):
    """
    Получает список категорий WordPress
    
    Args:
        wp_url: URL сайта
        wp_login: Логин
        wp_password: Пароль
        
    Returns:
        list: [{'id': int, 'name': str, 'slug': str}] или []
    """
    try:
        headers = get_wp_headers(wp_login, wp_password)
        response = requests.get(
            f"{wp_url}/wp-json/wp/v2/categories?per_page=100",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            categories = response.json()
            return [
                {
                    'id': cat.get('id'),
                    'name': cat.get('name'),
                    'slug': cat.get('slug')
                }
                for cat in categories
            ]
        else:
            return []
            
    except Exception as e:
        logger.error(f"❌ Ошибка получения категорий: {e}")
        return []


def create_wordpress_category(wp_url, wp_login, wp_password, category_name):
    """
    Создает новую категорию WordPress
    
    Args:
        wp_url: URL сайта
        wp_login: Логин
        wp_password: Пароль
        category_name: Название категории
        
    Returns:
        dict: {'id': int, 'name': str, 'slug': str} или None
    """
    try:
        headers = get_wp_headers(wp_login, wp_password)
        response = requests.post(
            f"{wp_url}/wp-json/wp/v2/categories",
            headers=headers,
            json={'name': category_name},
            timeout=10
        )
        
        if response.status_code in [200, 201]:
            cat = response.json()
            return {
                'id': cat.get('id'),
                'name': cat.get('name'),
                'slug': cat.get('slug')
            }
        else:
            return None
            
    except Exception as e:
        logger.error(f"❌ Ошибка создания категории: {e}")
        return None


def get_wordpress_tags(wp_url, wp_login, wp_password):
    """
    Получает список меток (tags) WordPress
    
    Args:
        wp_url: URL сайта
        wp_login: Логин
        wp_password: Пароль
        
    Returns:
        list: [{'id': int, 'name': str, 'slug': str}] или []
    """
    try:
        headers = get_wp_headers(wp_login, wp_password)
        response = requests.get(
            f"{wp_url}/wp-json/wp/v2/tags?per_page=100",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            tags = response.json()
            return [
                {
                    'id': tag.get('id'),
                    'name': tag.get('name'),
                    'slug': tag.get('slug')
                }
                for tag in tags
            ]
        else:
            return []
            
    except Exception as e:
        logger.error(f"❌ Ошибка получения меток: {e}")
        return []


def get_wordpress_users(wp_url, wp_login, wp_password):
    """
    Получает список пользователей WordPress
    
    Args:
        wp_url: URL сайта
        wp_login: Логин
        wp_password: Пароль
        
    Returns:
        list: [{'id': int, 'name': str, 'slug': str, 'avatar_url': str}] или []
    """
    try:
        headers = get_wp_headers(wp_login, wp_password)
        response = requests.get(
            f"{wp_url}/wp-json/wp/v2/users?per_page=100",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            users = response.json()
            return [
                {
                    'id': user.get('id'),
                    'name': user.get('name'),
                    'slug': user.get('slug'),
                    'description': user.get('description', ''),
                    'avatar_url': user.get('avatar_urls', {}).get('96', '')
                }
                for user in users
            ]
        else:
            return []
            
    except Exception as e:
        logger.error(f"❌ Ошибка получения пользователей: {e}")
        return []


def create_wordpress_tag(wp_url, wp_login, wp_password, tag_name):
    """
    Создает новую метку (tag) WordPress
    
    Args:
        wp_url: URL сайта
        wp_login: Логин
        wp_password: Пароль
        tag_name: Название метки
        
    Returns:
        dict: {'id': int, 'name': str, 'slug': str} или None
    """
    try:
        headers = get_wp_headers(wp_login, wp_password)
        response = requests.post(
            f"{wp_url}/wp-json/wp/v2/tags",
            headers=headers,
            json={'name': tag_name},
            timeout=10
        )
        
        if response.status_code in [200, 201]:
            tag = response.json()
            return {
                'id': tag.get('id'),
                'name': tag.get('name'),
                'slug': tag.get('slug')
            }
        else:
            return None
            
    except Exception as e:
        logger.error(f"❌ Ошибка создания метки: {e}")
        return None


def publish_article_to_wordpress(wp_credentials, article_html, seo_title, meta_description, 
                                  images_paths=None, status='draft', focus_keyword=None, 
                                  categories=None, tags=None, canonical_url='', 
                                  robots_meta='index, follow', schema_type='Article', slug=None, author_id=None):
    """
    Полный цикл публикации статьи на WordPress
    
    Args:
        wp_credentials: dict с данными WP {'url': '...', 'username': '...', 'password': '...'}
        article_html: HTML статьи
        seo_title: SEO заголовок
        meta_description: Мета-описание
        images_paths: list путей к изображениям (опционально)
        status: 'draft' или 'publish'
        focus_keyword: Фокусное ключевое слово для Yoast SEO
        categories: list ID категорий WordPress
        tags: list названий меток (tags)
        canonical_url: Canonical URL для Yoast SEO
        slug: ЧПУ URL (например: 'wpc-paneli-dlya-kabineta')
        robots_meta: Robots meta (например, 'index, follow')
        schema_type: Schema.org тип (например, 'Article', 'Product')
        author_id: ID автора в WordPress (опционально)
        
    Returns:
        dict: {'success': bool, 'post_url': str, 'message': str}
    """
    print(f"\n{'='*60}")
    print(f"📝 publish_article_to_wordpress() ВЫЗВАНА")
    print(f"{'='*60}")
    
    wp_url = wp_credentials.get('url', '').rstrip('/')
    wp_login = wp_credentials.get('username', '')  # Было 'login', но передается 'username'!
    wp_password = wp_credentials.get('password', '')
    
    print(f"1️⃣ Проверка credentials...")
    print(f"   URL: {wp_url}")
    print(f"   Login: {wp_login}")
    print(f"   Password: {'*' * len(wp_password)} (длина: {len(wp_password)})")
    
    if not all([wp_url, wp_login, wp_password]):
        print(f"❌ ОШИБКА: Неполные credentials!")
        return {
            'success': False,
            'message': '❌ Не указаны данные WordPress'
        }
    
    print(f"✅ Credentials в порядке")
    
    try:
        # 1. Загружаем изображения
        print(f"\n2️⃣ Загрузка изображений...")
        uploaded_images = []
        featured_media_id = None
        
        if images_paths:
            print(f"   Найдено изображений: {len(images_paths)}")
            
            # Извлекаем ключевое слово для ALT-текстов из focus_keyword или seo_title
            primary_keyword = focus_keyword if focus_keyword else seo_title.split()[0]
            
            for i, img_path in enumerate(images_paths):
                print(f"   Загружаю изображение {i+1}/{len(images_paths)}: {img_path}")
                import os
                # Генерируем slug для ИЗОБРАЖЕНИЯ из заголовка (не путать с slug статьи!)
                image_slug = re.sub(r'[^a-z0-9]+', '-', seo_title.lower())[:100]
                
                # Генерируем описательный ALT-текст для SEO
                if i == 0:
                    # Первое изображение (обложка)
                    alt_text = f"{primary_keyword} - профессиональное качество и современный дизайн"
                elif i == 1:
                    alt_text = f"Примеры {primary_keyword} в интерьере - фото работ"
                elif i == 2:
                    alt_text = f"Установка и монтаж {primary_keyword} - этапы работы"
                else:
                    alt_text = f"{primary_keyword} - вариант {i}"
                
                try:
                    result = upload_image_to_wp(wp_url, wp_login, wp_password, img_path, f"{image_slug}-{i}", alt_text)
                    if result:
                        uploaded_images.append(result['url'])
                        if i == 0:  # Первое изображение = featured
                            featured_media_id = result['id']
                        print(f"   ✅ Изображение {i+1} загружено, ID: {result.get('id')}")
                    else:
                        print(f"   ⚠️ Изображение {i+1} не загружено")
                except Exception as e:
                    print(f"   ❌ Ошибка загрузки изображения {i+1}: {e}")
        else:
            print(f"   ℹ️ Изображения не предоставлены")
        
        print(f"✅ Загружено изображений: {len(uploaded_images)}")
        if featured_media_id:
            print(f"✅ Featured image ID: {featured_media_id}")
        
        # 2. Вставляем изображения в контент (КРОМЕ ПЕРВОГО - это обложка)
        print(f"\n3️⃣ Вставка изображений в контент...")
        # Убираем первое изображение из списка для вставки (оно уже featured)
        images_for_content = uploaded_images[1:] if len(uploaded_images) > 1 else []
        
        if images_for_content:
            print(f"   Вставляю {len(images_for_content)} изображений (без обложки)...")
            article_html = insert_images_in_content(article_html, images_for_content)
            print(f"✅ Изображения вставлены в контент")
        else:
            print(f"   ℹ️ Нет дополнительных изображений для вставки в контент")
            print(f"   ℹ️ Обложка установлена как featured image")
        
        # 3. Оборачиваем статью в светлый контейнер для корректного отображения на тёмных темах
        article_html = (
            '<div style="background: #ffffff; color: #333333; padding: 30px; '
            'border-radius: 12px; max-width: 100%; margin: 0 auto; '
            'font-family: inherit; line-height: 1.7;">'
            + article_html +
            '</div>'
        )
        
        # 4. Создаём пост
        print(f"\n4️⃣ Создание поста в WordPress...")
        article_data = {
            'title': seo_title,
            'content': article_html,
            'excerpt': meta_description,
            'featured_media_id': featured_media_id,
            'status': status,
            'seo_title': seo_title,
            'meta_description': meta_description,
            'focus_keyword': focus_keyword,
            'categories': categories if categories else [],
            'tags': tags if tags else [],
            'canonical_url': canonical_url,
            'robots_meta': robots_meta,
            'schema_type': schema_type,
            'slug': slug,  # ЧПУ URL
            'author_id': author_id  # ID автора
        }
        print(f"   Заголовок: {seo_title}")
        print(f"   Статус: {status}")
        print(f"   Контент: {len(article_html)} символов")
        print(f"   Featured media: {featured_media_id}")
        print(f"   Focus keyword: {focus_keyword}")
        print(f"   Categories: {categories}")
        print(f"   Tags: {tags}")
        print(f"   Canonical URL: {canonical_url}")
        print(f"   Robots: {robots_meta}")
        print(f"   Schema type: {schema_type}")
        print(f"   Slug (ЧПУ): {slug}")
        print(f"   Author ID: {author_id}")
        
        print(f"   🚀 Вызываю create_wordpress_post()...")
        result = create_wordpress_post(wp_url, wp_login, wp_password, article_data)
        print(f"   Результат: {result}")
        
        if result.get('success'):
            print(f"\n{'='*60}")
            print(f"✅ СТАТЬЯ УСПЕШНО ОПУБЛИКОВАНА!")
            print(f"🔗 URL: {result.get('url', '')}")
            print(f"🆔 ID: {result.get('post_id')}")
            print(f"{'='*60}\n")
            return {
                'success': True,
                'post_url': result.get('url', ''),
                'post_id': result.get('post_id'),
                'message': f"✅ Статья опубликована!\n🔗 {result.get('url', '')}"
            }
        else:
            print(f"\n{'='*60}")
            print(f"❌ ОШИБКА СОЗДАНИЯ ПОСТА")
            print(f"Причина: {result.get('message', 'Неизвестная ошибка')}")
            print(f"{'='*60}\n")
            return {
                'success': False,
                'message': result.get('message', '❌ Ошибка публикации')
            }
            
    except Exception as e:
        print(f"\n{'='*60}")
        print(f"❌ КРИТИЧЕСКОЕ ИСКЛЮЧЕНИЕ В publish_article_to_wordpress()")
        print(f"Тип ошибки: {type(e).__name__}")
        print(f"Сообщение: {str(e)}")
        print(f"{'='*60}")
        import traceback
        traceback.print_exc()
        print(f"{'='*60}\n")
        return {
            'success': False,
            'message': f"❌ Исключение: {str(e)[:100]}"
        }


print("✅ handlers/website/wordpress_api.py загружен")
