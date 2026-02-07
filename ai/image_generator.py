"""
ЗАГЛУШКА ДЛЯ ОБРАТНОЙ СОВМЕСТИМОСТИ
====================================
Этот модуль существует только для поддержки старого кода.
Все вызовы перенаправляются на unified_generator.

Новый код должен использовать:
    from ai.unified_generator import generate_for_platform
"""

def generate_image(prompt: str, aspect_ratio: str = "1:1") -> dict:
    """
    Заглушка для старого API
    Перенаправляет на unified_generator
    """
    print("⚠️ ПРЕДУПРЕЖДЕНИЕ: Используется старый API image_generator")
    print("   Рекомендуется мигрировать на unified_generator")
    
    from ai.unified_generator import ContentGenerator
    
    generator = ContentGenerator()
    
    # Определяем платформу по формату
    platform_map = {
        "1:1": "instagram",
        "9:16": "instagram",
        "16:9": "youtube",
        "4:5": "pinterest",
        "3:4": "pinterest"
    }
    
    platform = platform_map.get(aspect_ratio, "instagram")
    
    # Генерируем через unified_generator
    # НО unified_generator генерирует И текст И изображение
    # Здесь нам нужно только изображение
    
    result = generator._generate_image(
        image_rules=__get_image_rules(platform),
        category_name="Контент",
        selected_phrase=prompt
    )
    
    return result


def __get_image_rules(platform: str):
    """Получает правила изображений для платформы"""
    from platform_rules.platforms_registry import get_platform_rules
    text_rules, image_rules = get_platform_rules(platform)
    return image_rules
