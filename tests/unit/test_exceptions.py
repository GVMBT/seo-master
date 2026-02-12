"""Tests for bot/exceptions.py — exception hierarchy."""

from bot.exceptions import (
    AIGenerationError,
    AppError,
    ConnectionValidationError,
    ContentValidationError,
    ExternalServiceError,
    InsufficientBalanceError,
    PublishError,
    RateLimitError,
    ScheduleError,
)


class TestAppError:
    def test_stores_message_and_user_message(self) -> None:
        err = AppError("internal detail", "Пользовательское сообщение")
        assert str(err) == "internal detail"
        assert err.user_message == "Пользовательское сообщение"

    def test_default_user_message(self) -> None:
        err = AppError("something broke")
        assert "ошибка" in err.user_message.lower()

    def test_is_exception(self) -> None:
        assert issubclass(AppError, Exception)


class TestSubclasses:
    def test_insufficient_balance_inherits_app_error(self) -> None:
        err = InsufficientBalanceError()
        assert isinstance(err, AppError)
        assert "токен" in err.user_message.lower()

    def test_connection_validation_inherits_app_error(self) -> None:
        err = ConnectionValidationError()
        assert isinstance(err, AppError)

    def test_ai_generation_inherits_app_error(self) -> None:
        err = AIGenerationError()
        assert isinstance(err, AppError)
        assert "генерац" in err.user_message.lower()

    def test_publish_error_inherits_app_error(self) -> None:
        err = PublishError()
        assert isinstance(err, AppError)
        assert "публикац" in err.user_message.lower()

    def test_rate_limit_inherits_app_error(self) -> None:
        err = RateLimitError()
        assert isinstance(err, AppError)
        assert "лимит" in err.user_message.lower()

    def test_schedule_error_inherits_app_error(self) -> None:
        err = ScheduleError()
        assert isinstance(err, AppError)
        assert "расписани" in err.user_message.lower()

    def test_external_service_inherits_app_error(self) -> None:
        err = ExternalServiceError()
        assert isinstance(err, AppError)
        assert "сервис" in err.user_message.lower()

    def test_content_validation_inherits_app_error(self) -> None:
        err = ContentValidationError()
        assert isinstance(err, AppError)
        assert "валидаци" in err.user_message.lower()

    def test_all_catchable_as_app_error(self) -> None:
        for exc_cls in (
            InsufficientBalanceError,
            ConnectionValidationError,
            AIGenerationError,
            PublishError,
            RateLimitError,
            ScheduleError,
            ExternalServiceError,
            ContentValidationError,
        ):
            try:
                raise exc_cls()
            except AppError:
                pass  # expected
