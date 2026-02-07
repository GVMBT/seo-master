# -*- coding: utf-8 -*-
"""
Работа с цветами для статей
Адаптивные цвета с гарантией контраста
"""


def get_adaptive_colors(site_colors=None):
    """
    Получает адаптивные цвета для блоков статьи с гарантией контраста
    
    Args:
        site_colors: dict с цветами сайта (если известны)
        
    Returns:
        dict: Набор цветов для использования в статье
    """
    if not site_colors:
        # Цвета по умолчанию с высоким контрастом
        return {
            'bg': '#ffffff',
            'text': '#1a1a1a',          # Тёмнее для лучшего контраста
            'accent': '#0066cc',
            'block_bg': '#f8f9fa',
            'block_text': '#1a1a1a',    # Всегда тёмный текст на светлом блоке
            'block_border': '#0066cc',
            'heading_color': '#0066cc',  # Для заголовков
            'is_dark_theme': False
        }
    
    # Определяем тёмная ли тема
    bg = site_colors.get('background', '#ffffff').lower()
    is_dark = False
    
    # Проверка на тёмный фон
    if bg.startswith('#'):
        # Конвертируем hex в RGB и вычисляем яркость
        hex_color = bg.lstrip('#')
        if len(hex_color) == 6:
            r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
            brightness = (r * 299 + g * 587 + b * 114) / 1000
            is_dark = brightness < 128
    
    # Для тёмной темы
    if is_dark:
        return {
            'bg': bg,
            'text': '#e8e8e8',           # Светлый текст на тёмном фоне
            'accent': '#4dabf7',         # Голубой акцент для тёмной темы
            'block_bg': '#2b2b2b',       # Чуть светлее основного фона
            'block_text': '#ffffff',     # Белый текст на тёмном блоке
            'block_border': '#4dabf7',
            'heading_color': '#4dabf7',  # Голубой для заголовков
            'is_dark_theme': True
        }
    
    # Для светлой темы - ГАРАНТИРУЕМ КОНТРАСТ!
    accent_color = site_colors.get('accent', '#0066cc')
    
    return {
        'bg': bg,
        'text': '#1a1a1a',              # ВСЕГДА тёмный текст на светлом
        'accent': accent_color,          # Акцентный цвет сайта
        'block_bg': '#f8f9fa',          # Светло-серый блок
        'block_text': '#1a1a1a',        # ВСЕГДА тёмный текст на светлом блоке
        'block_border': accent_color,    # Акцентная рамка
        'heading_color': accent_color,   # Акцентный для заголовков
        'is_dark_theme': False
    }
