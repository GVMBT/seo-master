# -*- coding: utf-8 -*-
"""
Auto Publish Platforms
Публикаторы для различных платформ
"""

from .website import WebsitePublisher
from .telegram import TelegramPublisher
from .pinterest import PinterestPublisher
from .vk import VKPublisher

__all__ = [
    'WebsitePublisher',
    'TelegramPublisher',
    'PinterestPublisher',
    'VKPublisher'
]
