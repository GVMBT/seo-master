# -*- coding: utf-8 -*-
"""
Модуль генерации SEO-статей для сайтов
Модульная архитектура для удобства поддержки
"""

from .generator import generate_website_article
from .colors import get_adaptive_colors
from .parser import parse_article_response, count_words

__all__ = [
    'generate_website_article',
    'get_adaptive_colors',
    'parse_article_response',
    'count_words'
]
