"""Yandex Webmaster API v4 client (recrawl queue).

Public surface:
    YandexWebmasterClient        — async HTTP client
    add_urls_with_rate_limit     — helper для пакетной отправки с задержкой
    YWHost / YWUserInfo / ...    — модели ответов
    YandexWebmasterError         — base exception
    YandexWebmasterAuthError     — 401/403
    YandexWebmasterRateLimitError — 429
    YandexWebmasterQuotaExceededError — суточная квота
    YandexWebmasterHostNotFoundError  — хост не подтверждён
"""

from integrations.yandex_webmaster.client import (
    YandexWebmasterClient,
    add_urls_with_rate_limit,
)
from integrations.yandex_webmaster.exceptions import (
    YandexWebmasterAuthError,
    YandexWebmasterError,
    YandexWebmasterHostNotFoundError,
    YandexWebmasterQuotaExceededError,
    YandexWebmasterRateLimitError,
)
from integrations.yandex_webmaster.models import (
    YWHost,
    YWHostQuota,
    YWHostsList,
    YWRecrawlAddResponse,
    YWUserInfo,
)

__all__ = [
    "YWHost",
    "YWHostQuota",
    "YWHostsList",
    "YWRecrawlAddResponse",
    "YWUserInfo",
    "YandexWebmasterAuthError",
    "YandexWebmasterClient",
    "YandexWebmasterError",
    "YandexWebmasterHostNotFoundError",
    "YandexWebmasterQuotaExceededError",
    "YandexWebmasterRateLimitError",
    "add_urls_with_rate_limit",
]
