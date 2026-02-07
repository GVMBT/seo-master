# -*- coding: utf-8 -*-
"""
Генератор статей через Claude API
Основная логика вызова API с retry
"""
import anthropic
from config import ANTHROPIC_API_KEY
from datetime import datetime
from .colors import get_adaptive_colors
from .parser import parse_article_response, count_words
from ..website_article_prompt_v4 import build_article_prompt  # ПРОМПТ v4 - новые правила


# Инициализация клиента
client = None
if ANTHROPIC_API_KEY:
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        print("✅ Claude API для генерации статей инициализирован")
    except Exception as e:
        print(f"⚠️ Ошибка инициализации Claude: {e}")


def generate_website_article(
    keyword,
    category_name,
    category_description="",
    company_data=None,
    prices=None,
    reviews=None,
    external_links=None,
    internal_links=None,
    text_style="professional",
    html_style="creative",
    site_colors=None,
    min_words=1500,
    max_words=2500,
    h2_list=None,
    author_data=None,
    images_count=None,
    image_formats=None,
    image_styles=None,
    image_cameras=None,
    image_angles=None,
    image_quality=None,
    image_tones=None,
    image_text_percent=0,
    image_collage_percent=0
):
    """
    Генерирует SEO-статью для сайта с полной оптимизацией
    
    Args:
        keyword: Основное ключевое слово
        category_name: Название категории
        category_description: Описание категории для контекста
        company_data: dict с данными компании
        prices: list с ценами
        reviews: list с отзывами клиентов (3 штуки)
        external_links: list внешних ссылок (соцсети)
        internal_links: list внутренних ссылок сайта
        text_style: стиль текста (professional, conversational, informative, motivational)
        html_style: стиль HTML (creative, news, minimalistic)
        site_colors: dict с цветами сайта {'background': '#fff', 'text': '#333', 'accent': '#0066cc'}
        min_words: Минимум слов
        max_words: Максимум слов
        h2_list: Список подзаголовков H2 (или None для автогенерации)
        author_data: dict с данными автора {'id': int, 'name': str, 'avatar_url': str, 'bio': str}
        
    Returns:
        dict: {
            'success': True/False,
            'html': 'HTML статьи',
            'seo_title': 'SEO заголовок',
            'meta_description': 'Мета описание',
            'word_count': 1234,
            'error': 'текст ошибки' (если success=False)
        }
    """
    
    if not client:
        return {
            'success': False,
            'error': 'Claude API не инициализирован'
        }
    
    # Получаем адаптивные цвета
    colors = get_adaptive_colors(site_colors)
    
    # Дефолтные данные компании
    if not company_data:
        company_data = {}
    
    # Используем промпт из website_article_prompt_v4.py
    user_prompt = build_article_prompt(
        keyword=keyword,
        category_name=category_name,
        category_description=category_description,
        company_data=company_data,
        prices=prices,
        reviews=reviews,
        external_links=external_links,
        internal_links=internal_links,
        text_style=text_style,
        html_style=html_style,
        colors=colors,
        min_words=min_words,
        max_words=max_words,
        author_data=author_data,
        images_count=images_count,
        image_formats=image_formats,
        image_styles=image_styles,
        image_cameras=image_cameras,
        image_angles=image_angles,
        image_quality=image_quality,
        image_tones=image_tones,
        image_text_percent=image_text_percent,
        image_collage_percent=image_collage_percent
    )
    
    # Retry логика
    max_retries = 3
    retry_delay = 10
    
    for attempt in range(max_retries):
        try:
            print(f"🔄 Попытка {attempt + 1}/{max_retries}...")
            
            # Логируем информацию о промпте
            if attempt == 0:
                print(f"\n📋 Параметры запроса к Claude:")
                print(f"   Модель: claude-sonnet-4-20250514")
                print(f"   Max tokens: 16384 (лимит API)")
                print(f"   Web Search: ✅ включён (до 5 запросов)")
                print(f"   Timeout: 600 секунд")
                print(f"   User prompt: {len(user_prompt)} символов")
                print(f"\n📝 Первые 500 символов user prompt:")
                print(f"   {user_prompt[:500]}...")
                print(f"\n📝 Последние 300 символов user prompt:")
                print(f"   ...{user_prompt[-300:]}")
            
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=16384,  # Максимум для Sonnet 4
                messages=[{"role": "user", "content": user_prompt}],
                tools=[
                    {
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": 3
                    }
                ],
                timeout=600.0  # Увеличен таймаут для web_search
            )
            
            if response and response.content:
                print("✅ Ответ получен успешно!")
                
                # Извлекаем usage для расчёта стоимости
                usage_data = {
                    'input_tokens': getattr(response.usage, 'input_tokens', 0),
                    'output_tokens': getattr(response.usage, 'output_tokens', 0)
                }
                print(f"📊 Использование токенов Claude API:")
                print(f"   • Input tokens: {usage_data['input_tokens']}")
                print(f"   • Output tokens: {usage_data['output_tokens']}")
                print(f"   • Total tokens: {usage_data['input_tokens'] + usage_data['output_tokens']}")
                
                # Проверяем причину остановки
                stop_reason = getattr(response, 'stop_reason', None)
                if stop_reason == 'max_tokens':
                    print("⚠️  ВНИМАНИЕ! Статья обрезана - достигнут лимит max_tokens")
                elif stop_reason == 'end_turn':
                    print("✅ Статья завершена корректно (end_turn)")
                elif stop_reason:
                    print(f"ℹ️  Причина остановки: {stop_reason}")
                
                # Собираем текст из всех блоков (web_search возвращает несколько блоков)
                search_count = 0
                text_parts = []
                for block in response.content:
                    block_type = getattr(block, 'type', '')
                    if block_type == 'text' and hasattr(block, 'text') and block.text:
                        text_parts.append(block.text)
                    elif block_type == 'web_search_tool_result':
                        search_count += 1
                
                if search_count > 0:
                    print(f"🔍 Выполнено web_search запросов: {search_count}")
                
                print(f"📝 Текстовых блоков в ответе: {len(text_parts)}")
                
                if text_parts:
                    # Берём самый длинный текстовый блок — это статья
                    article_html = max(text_parts, key=len).strip()
                else:
                    # Фоллбэк на старый способ
                    article_html = response.content[0].text.strip() if hasattr(response.content[0], 'text') else ""
                
                # Парсим ответ
                result = parse_article_response(
                    article_html=article_html,
                    keyword=keyword,
                    company_data=company_data,
                    min_words=min_words,
                    max_words=max_words
                )
                
                # Проверяем объём
                word_count = result['word_count']
                
                # Проверяем только если заданы ограничения
                if min_words is not None and word_count < min_words:
                    shortage = min_words - word_count
                    print(f"\n⚠️ НЕДОСТАТОЧНО СЛОВ: {word_count} < {min_words}")
                    print(f"   Не хватает: {shortage} слов")
                    print(f"   ⚠️ Возвращаем как есть - корректировка отключена")
                
                elif max_words is not None and word_count > max_words:
                    excess = word_count - max_words
                    print(f"\n⚠️ СЛИШКОМ МНОГО СЛОВ: {word_count} > {max_words}")
                    print(f"   Лишних: {excess} слов")
                    print(f"   ⚠️ Возвращаем как есть - корректировка отключена")
                
                print(f"\n✅ Генерация завершена:")
                print(f"   • Слов: {word_count}")
                print(f"   • SEO Title: {result['seo_title']}")
                print(f"   • Meta Desc: {result['meta_description'][:100]}...")
                
                return {
                    'success': True,
                    'html': result['html'],
                    'seo_title': result['seo_title'],
                    'meta_description': result['meta_description'],
                    'word_count': word_count,
                    'usage': usage_data  # 🆕 Добавлено для расчёта стоимости
                }
            
            else:
                error_msg = "Пустой ответ от Claude"
                print(f"❌ {error_msg}")
                
                if attempt < max_retries - 1:
                    print(f"   Повтор через {retry_delay} сек...")
                    import time
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                else:
                    return {
                        'success': False,
                        'html': '',
                        'seo_title': '',
                        'meta_description': '',
                        'error': error_msg
                    }
        
        except anthropic.APITimeoutError as e:
            error_msg = f"Timeout: {str(e)}"
            print(f"❌ {error_msg}")
            
            if attempt < max_retries - 1:
                print(f"   Повтор через {retry_delay} сек...")
                import time
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            else:
                return {
                    'success': False,
                    'html': '',
                    'seo_title': '',
                    'meta_description': '',
                    'error': 'Превышено время ожидания ответа от API'
                }
        
        except Exception as e:
            error_msg = str(e)[:200]
            print(f"❌ Ошибка: {error_msg}")
            
            if attempt < max_retries - 1:
                print(f"   Повтор через {retry_delay} сек...")
                import time
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            else:
                return {
                    'success': False,
                    'html': '',
                    'seo_title': '',
                    'meta_description': '',
                    'error': f'Ошибка Claude AI: {error_msg}'
                }
    
    # Если все попытки неудачны
    return {
        'success': False,
        'html': '',
        'seo_title': '',
        'meta_description': '',
        'error': 'Превышено количество попыток'
    }
