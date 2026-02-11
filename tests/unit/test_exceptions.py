"""Tests for bot/exceptions.py — exception hierarchy."""

from bot.exceptions import (
    AIGenerationError,
    AppError,
    ConnectionValidationError,
    InsufficientBalanceError,
    PublishError,
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

    def test_all_catchable_as_app_error(self) -> None:
        for exc_cls in (InsufficientBalanceError, ConnectionValidationError, AIGenerationError, PublishError):
            try:
                raise exc_cls()
            except AppError:
                pass  # expected
