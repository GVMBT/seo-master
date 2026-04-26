"""Yandex.Metrika API exceptions."""

from __future__ import annotations


class YandexMetrikaError(Exception):
    """Базовая ошибка."""


class YandexMetrikaAuthError(YandexMetrikaError):
    """401/403 — токен не валиден / нет доступа к счётчику."""


class YandexMetrikaRateLimitError(YandexMetrikaError):
    """429 — превышены лимиты запросов."""

    def __init__(self, retry_after: int = 60) -> None:
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded, retry after {retry_after}s")
