"""Exception hierarchy for Bamboodom API errors."""

from __future__ import annotations


class BamboodomAPIError(Exception):
    """Base for all bamboodom API errors."""


class BamboodomAuthError(BamboodomAPIError):
    """401 Unauthorized or X-Blog-Key missing/empty.

    User-facing: expected condition when the key is unset or wrong.
    Do NOT capture to Sentry.
    """


class BamboodomRateLimitError(BamboodomAPIError):
    """429 Too Many Requests. Respect Retry-After header.

    Expected condition under rate-limit pressure. Do NOT capture to Sentry.
    """

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded, retry after {retry_after}s")
