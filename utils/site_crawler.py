# -*- coding: utf-8 -*-
"""
Краулер для автоматического сбора внутренних ссылок сайта
"""
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import logging

logger = logging.getLogger(__name__)


def crawl_website(base_url, max_pages=50, timeout=30):
    """
    Краулит сайт и собирает важные внутренние ссылки
    
    Args:
        base_url: Базовый URL сайта (например, https://ecosteni.ru)
        max_pages: Максимум страниц для обхода
        timeout: Максимальное время выполнения (секунды)
        
    Returns:
        dict: {
            'success': bool,
            'links': list of dict [{'url': str, 'title': str, 'priority': int}],
            'error': str
        }
    """
    try:
        start_time = time.time()
        base_domain = urlparse(base_url).netloc
        
        visited = set()
        to_visit = [base_url]
        important_links = []
        
        # Приоритетные пути (важные разделы)
        priority_keywords = [
            'услуг', 'товар', 'продукт', 'категор', 'о-компани', 'about',
            'контакт', 'contact', 'цен', 'price', 'портфол', 'portfolio',
            'проект', 'work', 'отзыв', 'review'
        ]
        
        # Игнорируемые пути
        ignore_patterns = [
            'wp-admin', 'wp-login', 'wp-content', 'wp-includes',
            'admin', 'login', 'register', 'cart', 'checkout',
            'search', 'feed', 'rss', 'sitemap.xml', 'robots.txt',
            '.jpg', '.png', '.gif', '.pdf', '.zip', '.css', '.js'
        ]
        
        print(f"🕷 Начинаю краулинг: {base_url}")
        print(f"📊 Макс. страниц: {max_pages}, таймаут: {timeout}с")
        
        while to_visit and len(visited) < max_pages:
            # Проверка таймаута
            if time.time() - start_time > timeout:
                print(f"⏱ Достигнут таймаут {timeout}с")
                break
            
            current_url = to_visit.pop(0)
            
            # Пропускаем уже посещенные
            if current_url in visited:
                continue
            
            # Пропускаем игнорируемые пути
            if any(pattern in current_url.lower() for pattern in ignore_patterns):
                continue
            
            visited.add(current_url)
            
            try:
                # Запрос страницы
                response = requests.get(
                    current_url,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    },
                    timeout=10,
                    allow_redirects=True
                )
                
                # Проверка статуса
                if response.status_code != 200:
                    print(f"⚠️ Пропуск {current_url}: статус {response.status_code}")
                    continue
                
                # Парсинг HTML
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Получаем title страницы
                title_tag = soup.find('title')
                page_title = title_tag.get_text().strip() if title_tag else current_url
                
                # Определяем приоритет
                priority = 1  # Обычная страница
                url_lower = current_url.lower()
                
                # Повышенный приоритет для важных разделов
                for keyword in priority_keywords:
                    if keyword in url_lower or keyword in page_title.lower():
                        priority = 2
                        break
                
                # Главная страница - максимальный приоритет
                if current_url == base_url or current_url == base_url + '/':
                    priority = 3
                
                # Добавляем ссылку
                if current_url != base_url:  # Не добавляем главную
                    important_links.append({
                        'url': current_url,
                        'title': page_title[:100],  # Обрезаем длинные заголовки
                        'priority': priority
                    })
                
                print(f"✅ [{len(visited)}/{max_pages}] {current_url[:60]}... (приоритет: {priority})")
                
                # Ищем новые ссылки на странице
                for link in soup.find_all('a', href=True):
                    href = link.get('href')
                    
                    # Преобразуем относительные ссылки в абсолютные
                    absolute_url = urljoin(current_url, href)
                    
                    # Проверяем что ссылка на тот же домен
                    if urlparse(absolute_url).netloc == base_domain:
                        # Убираем якоря и параметры
                        clean_url = absolute_url.split('#')[0].split('?')[0]
                        
                        if clean_url not in visited and clean_url not in to_visit:
                            to_visit.append(clean_url)
                
                # Небольшая задержка между запросами
                time.sleep(0.5)
                
            except requests.exceptions.RequestException as e:
                print(f"⚠️ Ошибка запроса {current_url}: {e}")
                continue
            except Exception as e:
                print(f"⚠️ Ошибка парсинга {current_url}: {e}")
                continue
        
        # Сортируем по приоритету
        important_links.sort(key=lambda x: x['priority'], reverse=True)
        
        # Ограничиваем до топ-30
        important_links = important_links[:30]
        
        print(f"\n✅ Краулинг завершен!")
        print(f"📊 Посещено страниц: {len(visited)}")
        print(f"🔗 Собрано важных ссылок: {len(important_links)}")
        
        return {
            'success': True,
            'links': important_links,
            'total_visited': len(visited)
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка краулинга: {e}")
        return {
            'success': False,
            'error': str(e),
            'links': []
        }


print("✅ utils/site_crawler.py загружен")
