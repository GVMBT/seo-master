"""Exception hierarchy for Yandex Webmaster API errors."""

from __future__ import annotations


class YandexWebmasterError(Exception):
    """Base for all Yandex Webmaster API errors."""


class YandexWebmasterAuthError(YandexWebmasterError):
    """401/403 — токен невалиден или отозван.

    Expected condition; do NOT capture to Sentry.
    """


class YandexWebmasterRateLimitError(YandexWebmasterError):
    """429 — превышен лимит запросов / суточная квота переобхода.

    Expected condition. Контейнер для retry_after в секундах.
    """

    def __init__(self, retry_after: int = 60, message: str = "") -> None:
        self.retry_after = retry_after
        super().__init__(message or f"Rate limit exceeded, retry after {retry_after}s")


class YandexWebmasterQuotaExceededError(YandexWebmasterError):
    """Дневная квота переобхода исчерпана (HTTP 4xx с конкретным error_code)."""


class YandexWebmasterHostNotFoundError(YandexWebmasterError):
    """Сайт не найден в кабинете пользователя."""
