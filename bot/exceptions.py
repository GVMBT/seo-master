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
