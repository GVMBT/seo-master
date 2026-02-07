# -*- coding: utf-8 -*-
"""
Модуль для определения цветовой схемы сайта
Автоматически парсит CSS и определяет цвета фона, текста, акцентов
"""
import re
import requests
import logging

logger = logging.getLogger(__name__)


def is_valid_color(color_str):
    """
    Проверяет валидность CSS цвета
    
    Args:
        color_str: Строка цвета
        
    Returns:
        bool: True если валидный цвет
    """
    if not color_str or not isinstance(color_str, str):
        return False
    
    color_str = color_str.strip().lower()
    
    # Hex цвета
    if re.match(r'^#[0-9a-f]{3}([0-9a-f]{3})?$', color_str):
        return True
    
    # RGB/RGBA
    if re.match(r'^rgba?\([\d\s,./]+\)$', color_str):
        return True
    
    # Именованные цвета
    named_colors = ['white', 'black', 'red', 'blue', 'green', 'yellow', 
                    'gray', 'grey', 'transparent', 'inherit']
    if color_str in named_colors:
        return True
    
    return False


def hex_to_brightness(hex_color):
    """
    Вычисляет яркость hex цвета (0-255)
    
    Args:
        hex_color: Цвет в формате #RRGGBB
        
    Returns:
        int: Яркость 0-255
    """
    hex_color = hex_color.lstrip('#')
    
    if len(hex_color) == 3:
        hex_color = ''.join([c*2 for c in hex_color])
    
    if len(hex_color) != 6:
        return 128  # Средняя яркость по умолчанию
    
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        
        # Формула яркости
        brightness = (r * 299 + g * 587 + b * 114) / 1000
        return int(brightness)
    except Exception:
        return 128


def detect_site_colors(url):
    """
    Определяет цветовую схему сайта
    
    Args:
        url: URL сайта для анализа
        
    Returns:
        dict: {
            'background': str,      # Цвет фона
            'text': str,           # Цвет текста
            'accent': str,         # Акцентный цвет
            'is_dark_theme': bool  # Тёмная ли тема
        }
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        html = response.text
        
        colors = {
            'background': None,
            'text': None,
            'accent': None,
            'is_dark_theme': False
        }
        
        # Собираем CSS из <style> тегов
        style_blocks = re.findall(r'<style[^>]*>(.*?)</style>', html, re.DOTALL | re.IGNORECASE)
        css_content = '\n'.join(style_blocks)
        
        # Ищем фон (body, html, .site, main)
        bg_patterns = [
            r'body\s*\{[^}]*background(?:-color)?:\s*([^;}\s]+)',
            r'html\s*\{[^}]*background(?:-color)?:\s*([^;}\s]+)',
            r'\.site\s*\{[^}]*background(?:-color)?:\s*([^;}\s]+)',
            r'main\s*\{[^}]*background(?:-color)?:\s*([^;}\s]+)',
        ]
        
        for pattern in bg_patterns:
            match = re.search(pattern, css_content, re.IGNORECASE)
            if match:
                color = match.group(1).strip()
                if is_valid_color(color):
                    colors['background'] = color
                    break
        
        # Ищем цвет текста
        text_patterns = [
            r'body\s*\{[^}]*(?<!background-)color:\s*([^;}\s]+)',
            r'\.content\s*\{[^}]*(?<!background-)color:\s*([^;}\s]+)',
            r'p\s*\{[^}]*(?<!background-)color:\s*([^;}\s]+)',
        ]
        
        for pattern in text_patterns:
            match = re.search(pattern, css_content, re.IGNORECASE)
            if match:
                color = match.group(1).strip()
                if is_valid_color(color):
                    colors['text'] = color
                    break
        
        # Ищем акцентный цвет (кнопки, ссылки)
        accent_patterns = [
            r'\.btn\s*\{[^}]*background(?:-color)?:\s*([^;}\s]+)',
            r'a\s*\{[^}]*color:\s*([^;}\s]+)',
            r'\.button\s*\{[^}]*background(?:-color)?:\s*([^;}\s]+)',
        ]
        
        for pattern in accent_patterns:
            match = re.search(pattern, css_content, re.IGNORECASE)
            if match:
                color = match.group(1).strip()
                if is_valid_color(color) and color not in ['inherit', 'transparent']:
                    colors['accent'] = color
                    break
        
        # Определяем тёмная ли тема
        bg_color = colors.get('background', '#ffffff')
        if bg_color and bg_color.startswith('#'):
            brightness = hex_to_brightness(bg_color)
            colors['is_dark_theme'] = brightness < 128
        
        # Значения по умолчанию если не нашли
        if not colors['background']:
            colors['background'] = '#ffffff'
        if not colors['text']:
            colors['text'] = '#333333' if not colors['is_dark_theme'] else '#e0e0e0'
        if not colors['accent']:
            colors['accent'] = '#0066cc' if not colors['is_dark_theme'] else '#4dabf7'
        
        logger.info(f"✅ Цвета сайта определены: фон={colors['background']}, тема={'тёмная' if colors['is_dark_theme'] else 'светлая'}")
        return colors
        
    except Exception as e:
        logger.error(f"⚠️ Ошибка определения цветов: {e}")
        # Возвращаем цвета по умолчанию
        return {
            'background': '#ffffff',
            'text': '#333333',
            'accent': '#0066cc',
            'is_dark_theme': False
        }


print("✅ handlers/site_colors_detector.py загружен")
