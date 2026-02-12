"""Application exception hierarchy."""

# Default user-facing messages (Russian)
_DEFAULT_USER_MSG = "Произошла ошибка"
_INSUFFICIENT_BALANCE_MSG = "Недостаточно токенов"
_CONNECTION_VALIDATION_MSG = "Ошибка подключения к платформе"
_AI_GENERATION_MSG = "Ошибка генерации. Попробуйте ещё раз"
_PUBLISH_MSG = "Ошибка публикации"


class AppError(Exception):
    """Base exception for all application errors."""

    def __init__(
        self,
        message: str = "Internal error",
        user_message: str = _DEFAULT_USER_MSG,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.user_message = user_message


class InsufficientBalanceError(AppError):
    """Raised when user balance is too low for the requested operation."""

    def __init__(
        self,
        message: str = "Insufficient token balance",
        user_message: str = _INSUFFICIENT_BALANCE_MSG,
    ) -> None:
        super().__init__(message=message, user_message=user_message)


class ConnectionValidationError(AppError):
    """Raised when platform connection credentials are invalid."""

    def __init__(
        self,
        message: str = "Connection validation failed",
        user_message: str = _CONNECTION_VALIDATION_MSG,
    ) -> None:
        super().__init__(message=message, user_message=user_message)


class AIGenerationError(AppError):
    """Raised when AI content generation fails."""

    def __init__(
        self,
        message: str = "AI generation failed",
        user_message: str = _AI_GENERATION_MSG,
    ) -> None:
        super().__init__(message=message, user_message=user_message)


class PublishError(AppError):
    """Raised when publishing to a platform fails."""

    def __init__(
        self,
        message: str = "Publishing failed",
        user_message: str = _PUBLISH_MSG,
    ) -> None:
        super().__init__(message=message, user_message=user_message)


_RATE_LIMIT_MSG = "Превышен лимит запросов. Подождите немного"
_SCHEDULE_MSG = "Ошибка расписания"
_EXTERNAL_SERVICE_MSG = "Внешний сервис недоступен. Попробуйте позже"
_CONTENT_VALIDATION_MSG = "Контент не прошёл валидацию"


class RateLimitError(AppError):
    """Raised when rate limit is exceeded. Tokens are NOT deducted (E25)."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        user_message: str = _RATE_LIMIT_MSG,
    ) -> None:
        super().__init__(message=message, user_message=user_message)


class ScheduleError(AppError):
    """Raised when QStash schedule operation fails."""

    def __init__(
        self,
        message: str = "Schedule operation failed",
        user_message: str = _SCHEDULE_MSG,
    ) -> None:
        super().__init__(message=message, user_message=user_message)


class ExternalServiceError(AppError):
    """Raised when an external API (Firecrawl, DataForSEO, Serper) is unavailable."""

    def __init__(
        self,
        message: str = "External service unavailable",
        user_message: str = _EXTERNAL_SERVICE_MSG,
    ) -> None:
        super().__init__(message=message, user_message=user_message)


class ContentValidationError(AppError):
    """Raised when content fails validation before publishing."""

    def __init__(
        self,
        message: str = "Content validation failed",
        user_message: str = _CONTENT_VALIDATION_MSG,
    ) -> None:
        super().__init__(message=message, user_message=user_message)
