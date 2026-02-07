# -*- coding: utf-8 -*-
"""
Auto Publish Module
Модульная система автоматических публикаций

Архитектура:
- base.py - базовый класс для всех публикаторов
- scheduler.py - главный планировщик
- platforms/ - публикаторы для каждой платформы
- utils/ - вспомогательные утилиты

Использование:
    from handlers.auto_publish import auto_publish_scheduler
    
    # Запуск планировщика
    auto_publish_scheduler.start()
    
    # Остановка планировщика
    auto_publish_scheduler.stop()
"""

# Импортируем базовый класс
from .base import BasePlatformPublisher

# Импортируем планировщик
from .scheduler import AutoPublishScheduler, auto_publish_scheduler

# Импортируем все публикаторы
from .platforms import (
    WebsitePublisher,
    TelegramPublisher,
    PinterestPublisher,
    VKPublisher
)

# Импортируем утилиты
from .utils import (
    # Token Manager
    check_balance,
    charge_tokens,
    refund_tokens,
    get_user_balance,
    
    # Error Handler
    PublishError,
    InsufficientTokensError,
    PlatformNotFoundError,
    ValidationError,
    APIError,
    ContentGenerationError,
    CategoryNotFoundError,
    
    # Reporter
    send_success_report,
    send_error_report
)

# Экспортируем основное
__all__ = [
    # Главный планировщик (готовый экземпляр)
    'auto_publish_scheduler',
    
    # Классы
    'AutoPublishScheduler',
    'BasePlatformPublisher',
    
    # Публикаторы
    'WebsitePublisher',
    'TelegramPublisher',
    'PinterestPublisher',
    'VKPublisher',
    
    # Утилиты (если нужны для прямого использования)
    'check_balance',
    'charge_tokens',
    'refund_tokens',
    'get_user_balance',
    'PublishError',
    'InsufficientTokensError',
    'PlatformNotFoundError',
    'ValidationError',
    'APIError',
    'ContentGenerationError',
    'CategoryNotFoundError',
    'send_success_report',
    'send_error_report'
]

# Логирование загрузки модуля
import logging
logger = logging.getLogger(__name__)
logger.info("✅ Модуль auto_publish загружен (модульная архитектура)")
