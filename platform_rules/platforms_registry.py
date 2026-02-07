# -*- coding: utf-8 -*-
"""
Реестр платформ и их правил
Определяет требования к контенту для каждой платформы
"""


class PlatformRules:
    """Правила для платформы"""
    
    def __init__(self, name, text_rules=None, image_rules=None):
        self.name = name
        self.text_rules = text_rules or {}
        self.image_rules = image_rules or {}


# Правила для разных платформ
PLATFORMS = {
    'telegram': PlatformRules(
        name='Telegram',
        text_rules={
            'max_length': 4096,
            'format': 'markdown',
            'style': 'engaging'
        },
        image_rules={
            'aspect_ratio': '1:1',
            'max_width': 1280,
            'max_height': 1280,
            'format': 'jpeg'
        }
    ),
    'instagram': PlatformRules(
        name='Instagram',
        text_rules={
            'max_length': 2200,
            'hashtags': True,
            'style': 'engaging'
        },
        image_rules={
            'aspect_ratio': '1:1',
            'max_width': 1080,
            'max_height': 1080,
            'format': 'jpeg'
        }
    ),
    'pinterest': PlatformRules(
        name='Pinterest',
        text_rules={
            'max_length': 500,
            'title_max': 100,
            'style': 'inspiring'
        },
        image_rules={
            'aspect_ratio': '2:3',
            'max_width': 1000,
            'max_height': 1500,
            'format': 'jpeg'
        }
    ),
    'vk': PlatformRules(
        name='VK',
        text_rules={
            'max_length': 16384,
            'format': 'html',
            'style': 'engaging'
        },
        image_rules={
            'aspect_ratio': '1:1',
            'max_width': 1280,
            'max_height': 1280,
            'format': 'jpeg'
        }
    ),
    'website': PlatformRules(
        name='Website',
        text_rules={
            'max_length': 10000,
            'format': 'html',
            'style': 'professional'
        },
        image_rules={
            'aspect_ratio': '16:9',
            'max_width': 1920,
            'max_height': 1080,
            'format': 'jpeg'
        }
    )
}


def get_platform_rules(platform: str):
    """
    Получает правила для платформы
    
    Args:
        platform: Название платформы (telegram, instagram, pinterest, vk, website)
        
    Returns:
        tuple: (text_rules_object, image_rules_object)
        
    Raises:
        ValueError: Если платформа не найдена
    """
    platform = platform.lower()
    
    if platform not in PLATFORMS:
        raise ValueError(f"Платформа '{platform}' не найдена. Доступные: {list(PLATFORMS.keys())}")
    
    rules = PLATFORMS[platform]
    
    # Создаем объекты-обертки для совместимости со старым кодом
    class TextRules:
        def __init__(self, name, rules_dict):
            self.PLATFORM_NAME = name
            for key, value in rules_dict.items():
                setattr(self, key, value)
        
        def validate_text(self, text):
            """Валидация текста по правилам платформы"""
            if not text or not text.strip():
                return False, "Текст пустой"
            
            max_chars = getattr(self, 'max_length', None) or getattr(self, 'max_chars', 5000)
            if len(text) > max_chars:
                return False, f"Текст слишком длинный: {len(text)}/{max_chars} символов"
            
            return True, None
        
        def auto_fix_text(self, text, topic=None):
            """Автоисправление текста"""
            max_chars = getattr(self, 'max_length', None) or getattr(self, 'max_chars', 5000)
            if len(text) > max_chars:
                text = text[:max_chars].rsplit(' ', 1)[0]
            return text.strip()
    
    class ImageRules:
        def __init__(self, rules_dict):
            for key, value in rules_dict.items():
                setattr(self, key, value)
        
        def build_image_prompt(self, category_name, selected_phrase, image_settings=None):
            """
            Строит промпт для генерации изображения
            
            Args:
                category_name: Название категории
                selected_phrase: Фраза для генерации
                image_settings: Настройки изображения (опционально)
                
            Returns:
                tuple: (prompt, format)
            """
            # Формируем базовый промпт
            base_prompt = f"{category_name}: {selected_phrase}"
            
            # Если переданы настройки - используем их
            if image_settings:
                from handlers.platform_settings.utils import build_image_prompt as build_prompt_util
                
                # Создаем platform_settings из image_settings
                platform_settings = {
                    'formats': image_settings.get('formats', [self.aspect_ratio]),
                    'styles': image_settings.get('styles', []),
                    'tones': image_settings.get('tones', []),
                    'cameras': image_settings.get('cameras', []),
                    'angles': image_settings.get('angles', []),
                    'quality': image_settings.get('quality', image_settings.get('qualities', []))  # Поддержка обоих вариантов
                }
                
                # Используем утилиту для построения промпта
                return build_prompt_util(base_prompt, platform_settings, use_first_format=True)
            
            # Если настроек нет - возвращаем простой промпт
            return base_prompt, self.aspect_ratio
    
    text_rules = TextRules(rules.name, rules.text_rules)
    image_rules = ImageRules(rules.image_rules)
    
    return text_rules, image_rules


def platform_exists(platform: str) -> bool:
    """
    Проверяет существование платформы
    
    Args:
        platform: Название платформы
        
    Returns:
        bool: True если платформа существует
    """
    return platform.lower() in PLATFORMS


def get_all_platforms():
    """
    Возвращает список всех платформ
    
    Returns:
        list: Список названий платформ
    """
    return list(PLATFORMS.keys())
