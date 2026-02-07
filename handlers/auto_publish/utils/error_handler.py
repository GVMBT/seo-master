# -*- coding: utf-8 -*-
"""
Error Handler для автопостинга
Классы исключений для обработки различных ошибок публикации
"""


class PublishError(Exception):
    """
    Базовый класс для всех ошибок публикации
    """
    def __init__(self, message: str, platform: str = None, category_id: int = None):
        self.message = message
        self.platform = platform
        self.category_id = category_id
        super().__init__(self.message)
    
    def __str__(self):
        parts = [self.message]
        if self.platform:
            parts.append(f"Platform: {self.platform}")
        if self.category_id:
            parts.append(f"Category: {self.category_id}")
        return " | ".join(parts)


class InsufficientTokensError(PublishError):
    """
    Ошибка: недостаточно токенов для публикации
    """
    def __init__(self, required: int, available: int, platform: str = None):
        self.required = required
        self.available = available
        message = f"Недостаточно токенов (нужно {required}, есть {available})"
        super().__init__(message, platform=platform)


class PlatformNotFoundError(PublishError):
    """
    Ошибка: платформа не найдена или не активна
    """
    def __init__(self, platform_type: str, platform_id: str):
        self.platform_type = platform_type
        self.platform_id = platform_id
        message = f"{platform_type} '{platform_id}' не найден или не активен"
        super().__init__(message, platform=platform_type)


class ValidationError(PublishError):
    """
    Ошибка: неверные данные для публикации
    """
    def __init__(self, message: str, field: str = None, platform: str = None):
        self.field = field
        if field:
            message = f"{message} (поле: {field})"
        super().__init__(message, platform=platform)


class APIError(PublishError):
    """
    Ошибка: ошибка API внешней платформы
    """
    def __init__(self, message: str, platform: str, status_code: int = None, response: str = None):
        self.status_code = status_code
        self.response = response
        
        error_parts = [message]
        if status_code:
            error_parts.append(f"Status: {status_code}")
        if response:
            # Обрезаем длинные ответы
            response_preview = response[:200] + "..." if len(response) > 200 else response
            error_parts.append(f"Response: {response_preview}")
        
        full_message = " | ".join(error_parts)
        super().__init__(full_message, platform=platform)


class ContentGenerationError(PublishError):
    """
    Ошибка: не удалось сгенерировать контент (текст или изображение)
    """
    def __init__(self, content_type: str, message: str, platform: str = None):
        self.content_type = content_type  # 'text' или 'image'
        full_message = f"Ошибка генерации {content_type}: {message}"
        super().__init__(full_message, platform=platform)


class CategoryNotFoundError(PublishError):
    """
    Ошибка: категория не найдена
    """
    def __init__(self, category_id: int):
        message = f"Категория {category_id} не найдена"
        super().__init__(message, category_id=category_id)


# Экспортируем все классы исключений
__all__ = [
    'PublishError',
    'InsufficientTokensError',
    'PlatformNotFoundError',
    'ValidationError',
    'APIError',
    'ContentGenerationError',
    'CategoryNotFoundError'
]
