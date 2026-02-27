"""Tests for services/http_retry.py -- shared retry helper.

Covers: retry_with_backoff (success, 429 with Retry-After, 5xx backoff,
401/403 no retry, network errors, max retries exhausted),
helper functions (_parse_retry_after, _is_retryable, _get_retry_delay).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from services.http_retry import (
    _get_retry_delay,
    _is_retryable,
    _parse_retry_after,
    retry_with_backoff,
)


# ---------------------------------------------------------------------------
# _parse_retry_after
# ---------------------------------------------------------------------------


class TestParseRetryAfter:
    def test_returns_seconds_from_header(self) -> None:
        response = httpx.Response(429, headers={"Retry-After": "5"})
        assert _parse_retry_after(response) == 5.0

    def test_caps_at_60_seconds(self) -> None:
        response = httpx.Response(429, headers={"Retry-After": "120"})
        assert _parse_retry_after(response) == 60.0

    def test_returns_none_when_missing(self) -> None:
        response = httpx.Response(429)
        assert _parse_retry_after(response) is None

    def test_returns_none_for_invalid_value(self) -> None:
        response = httpx.Response(429, headers={"Retry-After": "not-a-number"})
        assert _parse_retry_after(response) is None

    def test_handles_float_value(self) -> None:
        response = httpx.Response(429, headers={"Retry-After": "2.5"})
        assert _parse_retry_after(response) == 2.5

    def test_lowercase_header_name(self) -> None:
        response = httpx.Response(429, headers={"retry-after": "3"})
        assert _parse_retry_after(response) == 3.0


# ---------------------------------------------------------------------------
# _is_retryable
# ---------------------------------------------------------------------------


class TestIsRetryable:
    def test_429_is_retryable(self) -> None:
        exc = httpx.HTTPStatusError(
            "rate limited",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(429),
        )
        assert _is_retryable(exc) is True

    def test_500_is_retryable(self) -> None:
        exc = httpx.HTTPStatusError(
            "server error",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(500),
        )
        assert _is_retryable(exc) is True

    def test_502_is_retryable(self) -> None:
        exc = httpx.HTTPStatusError(
            "bad gateway",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(502),
        )
        assert _is_retryable(exc) is True

    def test_503_is_retryable(self) -> None:
        exc = httpx.HTTPStatusError(
            "service unavailable",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(503),
        )
        assert _is_retryable(exc) is True

    def test_504_is_retryable(self) -> None:
        exc = httpx.HTTPStatusError(
            "gateway timeout",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(504),
        )
        assert _is_retryable(exc) is True

    def test_401_is_not_retryable(self) -> None:
        exc = httpx.HTTPStatusError(
            "unauthorized",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(401),
        )
        assert _is_retryable(exc) is False

    def test_403_is_not_retryable(self) -> None:
        exc = httpx.HTTPStatusError(
            "forbidden",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(403),
        )
        assert _is_retryable(exc) is False

    def test_404_is_not_retryable(self) -> None:
        exc = httpx.HTTPStatusError(
            "not found",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(404),
        )
        assert _is_retryable(exc) is False

    def test_timeout_is_retryable(self) -> None:
        exc = httpx.ReadTimeout("Timed out")
        assert _is_retryable(exc) is True

    def test_connect_error_is_retryable(self) -> None:
        exc = httpx.ConnectError("Connection refused")
        assert _is_retryable(exc) is True

    def test_generic_exception_is_not_retryable(self) -> None:
        exc = ValueError("bad value")
        assert _is_retryable(exc) is False


# ---------------------------------------------------------------------------
# _get_retry_delay
# ---------------------------------------------------------------------------


class TestGetRetryDelay:
    def test_429_with_retry_after(self) -> None:
        exc = httpx.HTTPStatusError(
            "rate limited",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(429, headers={"Retry-After": "10"}),
        )
        assert _get_retry_delay(exc, attempt=0, base_delay=1.0) == 10.0

    def test_429_without_retry_after_uses_backoff(self) -> None:
        exc = httpx.HTTPStatusError(
            "rate limited",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(429),
        )
        # attempt=0, base=1.0 -> 1.0 * 2^0 = 1.0
        assert _get_retry_delay(exc, attempt=0, base_delay=1.0) == 1.0

    def test_500_uses_exponential_backoff(self) -> None:
        exc = httpx.HTTPStatusError(
            "server error",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(500),
        )
        assert _get_retry_delay(exc, attempt=0, base_delay=1.0) == 1.0
        assert _get_retry_delay(exc, attempt=1, base_delay=1.0) == 2.0
        assert _get_retry_delay(exc, attempt=2, base_delay=1.0) == 4.0

    def test_backoff_capped_at_60(self) -> None:
        exc = httpx.HTTPStatusError(
            "server error",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(500),
        )
        assert _get_retry_delay(exc, attempt=10, base_delay=1.0) == 60.0

    def test_timeout_uses_backoff(self) -> None:
        exc = httpx.ReadTimeout("Timed out")
        assert _get_retry_delay(exc, attempt=1, base_delay=1.0) == 2.0


# ---------------------------------------------------------------------------
# retry_with_backoff — success
# ---------------------------------------------------------------------------


class TestRetrySuccess:
    async def test_returns_result_on_first_try(self) -> None:
        func = AsyncMock(return_value="success")
        result = await retry_with_backoff(func, max_retries=2, operation="test")
        assert result == "success"
        assert func.await_count == 1

    async def test_retries_on_500_then_succeeds(self) -> None:
        call_count = 0

        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.HTTPStatusError(
                    "server error",
                    request=httpx.Request("GET", "https://example.com"),
                    response=httpx.Response(500),
                )
            return "recovered"

        result = await retry_with_backoff(
            flaky,
            max_retries=2,
            base_delay=0.01,
            operation="test",
        )
        assert result == "recovered"
        assert call_count == 2

    async def test_retries_on_429_then_succeeds(self) -> None:
        call_count = 0

        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.HTTPStatusError(
                    "rate limited",
                    request=httpx.Request("GET", "https://example.com"),
                    response=httpx.Response(429, headers={"Retry-After": "0.01"}),
                )
            return "recovered"

        result = await retry_with_backoff(
            flaky,
            max_retries=2,
            base_delay=0.01,
            operation="test",
        )
        assert result == "recovered"
        assert call_count == 2

    async def test_retries_on_timeout_then_succeeds(self) -> None:
        call_count = 0

        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ReadTimeout("Timed out")
            return "recovered"

        result = await retry_with_backoff(
            flaky,
            max_retries=2,
            base_delay=0.01,
            operation="test",
        )
        assert result == "recovered"
        assert call_count == 2

    async def test_retries_on_connect_error_then_succeeds(self) -> None:
        call_count = 0

        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectError("Connection refused")
            return "ok"

        result = await retry_with_backoff(
            flaky,
            max_retries=1,
            base_delay=0.01,
            operation="test",
        )
        assert result == "ok"
        assert call_count == 2


# ---------------------------------------------------------------------------
# retry_with_backoff — no retry on auth errors
# ---------------------------------------------------------------------------


class TestRetryNoRetryOnAuth:
    async def test_401_raises_immediately(self) -> None:
        async def auth_fail() -> str:
            raise httpx.HTTPStatusError(
                "unauthorized",
                request=httpx.Request("GET", "https://example.com"),
                response=httpx.Response(401),
            )

        with pytest.raises(httpx.HTTPStatusError, match="unauthorized"):
            await retry_with_backoff(
                auth_fail,
                max_retries=3,
                base_delay=0.01,
                operation="test",
            )

    async def test_403_raises_immediately(self) -> None:
        async def auth_fail() -> str:
            raise httpx.HTTPStatusError(
                "forbidden",
                request=httpx.Request("GET", "https://example.com"),
                response=httpx.Response(403),
            )

        with pytest.raises(httpx.HTTPStatusError, match="forbidden"):
            await retry_with_backoff(
                auth_fail,
                max_retries=3,
                base_delay=0.01,
                operation="test",
            )

    async def test_404_raises_immediately(self) -> None:
        async def not_found() -> str:
            raise httpx.HTTPStatusError(
                "not found",
                request=httpx.Request("GET", "https://example.com"),
                response=httpx.Response(404),
            )

        with pytest.raises(httpx.HTTPStatusError, match="not found"):
            await retry_with_backoff(
                not_found,
                max_retries=3,
                base_delay=0.01,
                operation="test",
            )


# ---------------------------------------------------------------------------
# retry_with_backoff — max retries exhausted
# ---------------------------------------------------------------------------


class TestRetryExhausted:
    async def test_raises_after_max_retries(self) -> None:
        call_count = 0

        async def always_500() -> str:
            nonlocal call_count
            call_count += 1
            raise httpx.HTTPStatusError(
                "server error",
                request=httpx.Request("GET", "https://example.com"),
                response=httpx.Response(500),
            )

        with pytest.raises(httpx.HTTPStatusError, match="server error"):
            await retry_with_backoff(
                always_500,
                max_retries=2,
                base_delay=0.01,
                operation="test",
            )
        # 1 initial + 2 retries = 3 total
        assert call_count == 3

    async def test_raises_after_max_retries_timeout(self) -> None:
        call_count = 0

        async def always_timeout() -> str:
            nonlocal call_count
            call_count += 1
            raise httpx.ReadTimeout("Timed out")

        with pytest.raises(httpx.ReadTimeout):
            await retry_with_backoff(
                always_timeout,
                max_retries=1,
                base_delay=0.01,
                operation="test",
            )
        # 1 initial + 1 retry = 2 total
        assert call_count == 2

    async def test_zero_max_retries_no_retry(self) -> None:
        call_count = 0

        async def fail_once() -> str:
            nonlocal call_count
            call_count += 1
            raise httpx.HTTPStatusError(
                "server error",
                request=httpx.Request("GET", "https://example.com"),
                response=httpx.Response(500),
            )

        with pytest.raises(httpx.HTTPStatusError):
            await retry_with_backoff(
                fail_once,
                max_retries=0,
                base_delay=0.01,
                operation="test",
            )
        assert call_count == 1


# ---------------------------------------------------------------------------
# retry_with_backoff — non-retryable exceptions
# ---------------------------------------------------------------------------


class TestRetryNonRetryable:
    async def test_value_error_raises_immediately(self) -> None:
        async def bad_value() -> str:
            raise ValueError("invalid")

        with pytest.raises(ValueError, match="invalid"):
            await retry_with_backoff(
                bad_value,
                max_retries=3,
                base_delay=0.01,
                operation="test",
            )
