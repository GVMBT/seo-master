"""
ЕДИНЫЙ ГЕНЕРАТОР КОНТЕНТА
========================
Этот модуль отвечает за генерацию текста и изображений для ВСЕХ платформ.
Использует правила из config/ для каждой платформы.

ПРИНЦИП РАБОТЫ:
1. Получает правила из config/platforms_registry
2. Генерирует контент согласно правилам платформы
3. Валидирует результат
4. Возвращает готовый контент

ИСПОЛЬЗОВАНИЕ:
    from ai.unified_generator import ContentGenerator
    
    generator = ContentGenerator()
    result = generator.generate_content(
        platform='telegram',
        category_name='WPC панели',
        selected_phrase='Глянцевые панели большого формата',
        style='engaging'
    )
    
    if result['success']:
        text = result['text']
        image_bytes = result['image_bytes']
        image_format = result['image_format']
"""

import os
import sys
from typing import Dict, Tuple, Optional

# Добавляем путь к config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from platform_rules.platforms_registry import get_platform_rules, platform_exists


class ContentGenerator:
    """
    Единый генератор контента для всех платформ
    """
    
    def __init__(self):
        """Инициализация генератора"""
        # ВАЖНО: Используем config.py который читает GEMINI_API_KEY для Nano Banana Pro
        from config import ANTHROPIC_API_KEY, GOOGLE_API_KEY
        
        self.anthropic_api_key = ANTHROPIC_API_KEY
        self.google_api_key = GOOGLE_API_KEY
        
        # Проверка API ключей
        if not self.anthropic_api_key:
            print("⚠️ ANTHROPIC_API_KEY не установлен")
        
        if not self.google_api_key:
            print("⚠️ GOOGLE_API_KEY не установлен")
        
        # Импорт библиотек
        try:
            from anthropic import Anthropic
            self.claude_client = Anthropic(api_key=self.anthropic_api_key)
        except ImportError:
            print("⚠️ Модуль anthropic не установлен")
            self.claude_client = None
        
        try:
            # НОВЫЙ пакет google.genai
            from google import genai
            if self.google_api_key:
                self.genai_client = genai.Client(api_key=self.google_api_key)
            else:
                self.genai_client = None
            self.genai = genai
        except ImportError:
            print("⚠️ Модуль google-genai не установлен")
            self.genai = None
            self.genai_client = None
    
    
    def generate_content(
        self,
        platform: str,
        category_name: str,
        selected_phrase: str,
        style: str = 'engaging'
    ) -> Dict:
        """
        Генерирует текст и изображение для платформы
        
        Args:
            platform: Название платформы ('telegram', 'pinterest', 'vk', 'website')
            category_name: Название категории (например "WPC панели")
            selected_phrase: ЕДИНАЯ фраза из описания категории
            style: Стиль текста (engaging, professional, funny, inspiring)
        
        Returns:
            {
                'success': bool,
                'text': str,
                'image_bytes': bytes,
                'image_format': str,
                'error': str (если success=False)
            }
        """
        # Проверка платформы
        if not platform_exists(platform):
            return {
                'success': False,
                'error': f"Платформа '{platform}' не найдена"
            }
        
        # Загрузка правил
        try:
            text_rules, image_rules = get_platform_rules(platform)
        except Exception as e:
            return {
                'success': False,
                'error': f"Ошибка загрузки правил: {e}"
            }
        
        print(f"📋 Генерация контента для {text_rules.PLATFORM_NAME}")
        print(f"   Категория: {category_name}")
        print(f"   Фраза: {selected_phrase[:50]}...")
        print(f"   Стиль: {style}")
        
        # Генерация текста
        text_result = self._generate_text(
            text_rules=text_rules,
            category_name=category_name,
            selected_phrase=selected_phrase,
            style=style
        )
        
        if not text_result['success']:
            return text_result
        
        # Генерация изображения
        image_result = self._generate_image(
            image_rules=image_rules,
            category_name=category_name,
            selected_phrase=selected_phrase
        )
        
        if not image_result['success']:
            return image_result
        
        # Возвращаем всё вместе
        return {
            'success': True,
            'text': text_result['text'],
            'image_bytes': image_result['image_bytes'],
            'image_format': image_result['format']
        }
    
    
    def _generate_text(
        self,
        text_rules,
        category_name: str,
        selected_phrase: str,
        style: str
    ) -> Dict:
        """
        Генерирует текст согласно правилам платформы
        
        Args:
            text_rules: Модуль с правилами текста
            category_name: Название категории
            selected_phrase: Единая фраза
            style: Стиль
        
        Returns:
            {'success': bool, 'text': str, 'error': str}
        """
        if not self.claude_client:
            return {
                'success': False,
                'error': 'Claude API не настроен'
            }
        
        # Формируем топик
        topic = f"{category_name}. {selected_phrase}"
        
        # Получаем настройки из правил
        max_length = getattr(text_rules, 'max_length', 500)
        text_format = getattr(text_rules, 'format', 'text')
        
        # Формируем системный промпт
        system_prompt = f"""Ты — профессиональный копирайтер, специализирующийся на создании {style} контента для {text_rules.PLATFORM_NAME}.

Создай короткое описание товара/услуги на основе темы.

ТРЕБОВАНИЯ:
- Максимум {max_length} символов
- Стиль: {style}
- Формат: {text_format}
- БЕЗ эмодзи, БЕЗ хештегов
- Только текст описания"""

        # Формируем пользовательский промпт
        user_prompt = f"""Тема: {topic}

Напиши короткое продающее описание (максимум {max_length} символов).
Сфокусируйся на преимуществах и применении."""
        
        print(f"🤖 Генерация текста...")
        print(f"   Максимум символов: {max_length}")
        print(f"   Стиль: {style}")
        
        try:
            # Вызов Claude API
            response = self.claude_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}]
            )
            
            if response and response.content:
                text = response.content[0].text.strip()
                
                # Удаляем запрещенные символы
                forbidden_chars = ['*', '"', '№', '$', '%', '&', '@', '_', '`', "'", '~', '^', '|', '<', '>', '[', ']', '{', '}']
                for char in forbidden_chars:
                    text = text.replace(char, '')
                
                # Нормализация пробелов НО СОХРАНЯЕМ ПЕРЕНОСЫ СТРОК
                import re
                # Заменяем множественные пробелы на один, но НЕ трогаем переносы строк
                text = re.sub(r'[^\S\n]+', ' ', text)  # Заменяем пробелы кроме \n
                # Убираем лишние пустые строки (более 2х подряд)
                text = re.sub(r'\n{3,}', '\n\n', text)  # Максимум 2 переноса подряд
                text = text.strip()
                
                print(f"✅ Текст сгенерирован: {len(text.split())} слов")
                
                # Валидация
                is_valid, error_message = text_rules.validate_text(text)
                
                if not is_valid:
                    print(f"⚠️ Валидация: {error_message}")
                    print(f"🔧 Автоисправление...")
                    text = text_rules.auto_fix_text(text, topic)
                    print(f"✅ Исправлено: {len(text.split())} слов")
                
                return {
                    'success': True,
                    'text': text
                }
            else:
                return {
                    'success': False,
                    'error': 'Claude вернул пустой ответ'
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'Ошибка генерации текста: {str(e)}'
            }
    
    
    def _generate_image(
        self,
        image_rules,
        category_name: str,
        selected_phrase: str,
        image_settings: Dict = None
    ) -> Dict:
        """
        Генерирует изображение согласно правилам платформы
        
        Args:
            image_rules: Модуль с правилами изображений
            category_name: Название категории
            selected_phrase: Единая фраза
            image_settings: Настройки изображения (styles, cameras, angles, quality, tones, format)
        
        Returns:
            {'success': bool, 'image_bytes': bytes, 'format': str, 'error': str}
        """
        if not self.genai:
            return {
                'success': False,
                'error': 'Google Generative AI не настроен'
            }
        
        # Строим промпт из правил С НАСТРОЙКАМИ
        image_prompt, image_format = image_rules.build_image_prompt(
            category_name=category_name,
            selected_phrase=selected_phrase,
            image_settings=image_settings  # Передаём настройки
        )
        
        try:
            # Генерация изображений через Nano Banana Pro (как в старом боте)
            if not self.genai_client:
                return {
                    'success': False,
                    'error': 'Google Genai client не инициализирован'
                }
            
            # Конфигурация генерации (из рабочего кода)
            from google.genai import types
            generation_config = types.GenerateContentConfig(
                temperature=1.0,
                top_p=0.95,
                top_k=40,
                candidate_count=1,
                max_output_tokens=8192,
                response_modalities=["IMAGE"],
            )
            
            # Улучшаем промпт с соотношением сторон
            enhanced_prompt = f"{image_prompt}, aspect ratio {image_format}, high quality, detailed"
            
            print(f"🍌 Nano Banana Pro генерация...")
            print(f"   Промпт: {enhanced_prompt[:100]}...")
            print(f"   Формат: {image_format}")
            
            # Генерация (ПРАВИЛЬНЫЙ метод!)
            response = self.genai_client.models.generate_content(
                model="models/nano-banana-pro-preview",
                contents=enhanced_prompt,
                config=generation_config
            )
            
            # Извлекаем изображение (как в старом боте)
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                
                if hasattr(candidate, 'content') and candidate.content:
                    if hasattr(candidate.content, 'parts') and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, 'inline_data') and part.inline_data:
                                image_data = part.inline_data.data
                                
                                # Декодируем base64 если нужно
                                import base64
                                if isinstance(image_data, str):
                                    image_bytes = base64.b64decode(image_data)
                                else:
                                    image_bytes = image_data
                                
                                print(f"✅ Изображение сгенерировано: {len(image_bytes)} байт")
                                
                                return {
                                    'success': True,
                                    'image_bytes': image_bytes,
                                    'format': image_format
                                }
            
            return {
                'success': False,
                'error': 'Изображение не найдено в ответе'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Ошибка генерации изображения: {str(e)}'
            }


# ════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ════════════════════════════════════════════════════════════════

def generate_for_platform(
    platform: str,
    category_name: str,
    selected_phrase: str,
    style: str = 'engaging'
) -> Dict:
    """
    Упрощенная функция для генерации контента
    
    Args:
        platform: Платформа ('telegram', 'pinterest', 'vk', 'website')
        category_name: Категория
        selected_phrase: ЕДИНАЯ фраза из описания
        style: Стиль текста
    
    Returns:
        Результат генерации
    
    Пример:
        result = generate_for_platform(
            platform='telegram',
            category_name='WPC панели',
            selected_phrase='Глянцевые панели большого формата',
            style='engaging'
        )
        
        if result['success']:
            print(result['text'])
            # Сохранить result['image_bytes']
    """
    generator = ContentGenerator()
    return generator.generate_content(
        platform=platform,
        category_name=category_name,
        selected_phrase=selected_phrase,
        style=style
    )


# ════════════════════════════════════════════════════════════════
# СПЕЦИАЛЬНЫЕ ФУНКЦИИ
# ════════════════════════════════════════════════════════════════

def generate_product_description(
    product_name: str,
    category: str = "",
    features: str = "",
    benefits: str = "",
    target_audience: str = "",
    tone: str = 'professional',
    length: str = 'medium'
) -> Dict:
    """
    Генерирует маркетинговое описание товара/услуги
    
    Args:
        product_name: Название товара
        category: Категория
        features: Характеристики/особенности
        benefits: Преимущества
        target_audience: Целевая аудитория
        tone: Стиль ('professional', 'friendly', 'expert', 'casual')
        length: Длина ('short'=100 слов, 'medium'=300, 'long'=500)
    
    Returns:
        {'success': bool, 'text': str, 'word_count': int, 'error': str}
    """
    import anthropic
    from config import ANTHROPIC_API_KEY
    
    if not ANTHROPIC_API_KEY:
        return {
            'success': False,
            'text': '',
            'word_count': 0,
            'error': 'Claude API не настроен'
        }
    
    # Определяем количество слов
    word_counts = {
        'short': 100,
        'medium': 300,
        'long': 500
    }
    target_words = word_counts.get(length, 300)
    
    # Определяем стиль
    tone_descriptions = {
        'professional': 'профессиональный, деловой стиль',
        'friendly': 'дружелюбный, разговорный стиль',
        'expert': 'экспертный, авторитетный стиль',
        'casual': 'неформальный, простой стиль'
    }
    tone_desc = tone_descriptions.get(tone, 'профессиональный стиль')
    
    # Формируем промпт
    system_prompt = f"""Ты — эксперт по созданию продающих описаний товаров и услуг.

ТРЕБОВАНИЯ:
1. Длина: примерно {target_words} слов
2. Стиль: {tone_desc}
3. Формат: связный текст без заголовков и списков
4. БЕЗ emoji и спецсимволов
5. Акцент на преимущества и ценность для клиента

ВАЖНО:
- Пиши убедительно и конкретно
- Избегай общих фраз
- Фокусируйся на пользе для покупателя
- Естественный, читаемый текст"""
    
    user_prompt = f"""Создай маркетинговое описание.

ТОВАР/УСЛУГА: {product_name}
КАТЕГОРИЯ: {category or 'Не указана'}

ХАРАКТЕРИСТИКИ:
{features or 'Не указаны'}

ПРЕИМУЩЕСТВА:
{benefits or 'Не указаны'}

ЦЕЛЕВАЯ АУДИТОРИЯ:
{target_audience or 'Широкая аудитория'}

Создай продающее описание примерно на {target_words} слов."""
    
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        
        if response and response.content:
            text = response.content[0].text.strip()
            
            # Убираем запрещенные символы
            forbidden_chars = ['*', '"', '№', '$', '%', '&', '@', '_', '`', "'", '~', '^', '|', '<', '>', '[', ']', '{', '}']
            for char in forbidden_chars:
                text = text.replace(char, '')
            
            # Нормализация пробелов
            import re
            text = re.sub(r'[^\S\n]+', ' ', text)
            text = text.strip()
            
            word_count = len(text.split())
            
            return {
                'success': True,
                'text': text,
                'word_count': word_count,
                'char_count': len(text)
            }
        else:
            return {
                'success': False,
                'text': '',
                'word_count': 0,
                'error': 'Claude вернул пустой ответ'
            }
            
    except Exception as e:
        return {
            'success': False,
            'text': '',
            'word_count': 0,
            'error': f'Ошибка: {str(e)[:200]}'
        }


# ════════════════════════════════════════════════════════════════
# ТЕСТИРОВАНИЕ
# ════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    # Тест генерации для Telegram
    print("="*60)
    print("ТЕСТ: Генерация для Telegram")
    print("="*60)
    
    result = generate_for_platform(
        platform='telegram',
        category_name='WPC панели',
        selected_phrase='Глянцевые панели большого формата матовые одноцветные',
        style='engaging'
    )
    
    if result['success']:
        print("\n✅ УСПЕШНО!")
        print(f"\nТекст ({len(result['text'].split())} слов):")
        print(result['text'])
        print(f"\nИзображение: {len(result['image_bytes'])} байт, формат: {result['image_format']}")
    else:
        print(f"\n❌ ОШИБКА: {result['error']}")


def generate_image_only(
    platform: str,
    category_name: str,
    selected_phrase: str,
    image_settings: Dict = None
) -> Dict:
    """
    Генерирует ТОЛЬКО изображение без текста (для website где текст уже есть)
    
    Args:
        platform: Платформа (website, pinterest, telegram, vk)
        category_name: Название категории
        selected_phrase: Фраза для генерации
        image_settings: Настройки изображения (styles, cameras, angles, quality, tones, format)
    
    Returns:
        dict: {
            'success': bool,
            'image_bytes': bytes,
            'image_format': str,
            'error': str (если success=False)
        }
    """
    # Создаём генератор БЕЗ параметров
    generator = ContentGenerator()
    
    # Загружаем правила для платформы
    try:
        _, image_rules = get_platform_rules(platform)
    except Exception as e:
        return {
            'success': False,
            'error': f"Ошибка загрузки правил: {e}"
        }
    
    # Логируем настройки перед генерацией
    if image_settings:
        print(f"\n🎨 Применяемые настройки изображения:")
        print(f"   Стили: {image_settings.get('styles', [])}")
        print(f"   Камеры: {image_settings.get('cameras', [])}")
        print(f"   Ракурсы: {image_settings.get('angles', [])}")
        print(f"   Качество: {image_settings.get('quality', [])}")
        print(f"   Тональность: {image_settings.get('tones', [])}")
        print(f"   Формат: {image_settings.get('format', '16:9')}")
    
    # Используем приватную функцию _generate_image напрямую
    result = generator._generate_image(
        image_rules=image_rules,
        category_name=category_name,
        selected_phrase=selected_phrase,
        image_settings=image_settings  # Передаём настройки
    )
    
    return result

