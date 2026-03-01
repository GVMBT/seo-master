"""Shared HTTP retry helper with exponential backoff and Retry-After support.

Used by all publishers, external clients, and AIOrchestrator.
DRY: one retry implementation for the entire codebase.

Rules:
  - 429: respect Retry-After header (cap 60s), then retry
  - 5xx: exponential backoff (base_delay * 2^attempt), then retry
  - 401/403: never retry (auth failure)
  - Other 4xx: never retry (client error)
  - Network errors (timeout, connect): retry with backoff
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx
import structlog

log = structlog.get_logger()

# Status codes that should never be retried (auth / client errors)
_NO_RETRY_STATUSES = frozenset({401, 403})

# Maximum time to wait on a Retry-After header (seconds)
_MAX_RETRY_AFTER = 60.0

# HTTP status codes considered retryable (server errors + rate limit)
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

# Network-level exceptions that are retryable
_RETRYABLE_NETWORK_ERRORS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
)


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Extract Retry-After header value as seconds.

    Returns None if header is missing or unparseable.
    Caps at _MAX_RETRY_AFTER seconds.
    """
    raw = response.headers.get("Retry-After") or response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw)
        return min(seconds, _MAX_RETRY_AFTER)
    except (ValueError, TypeError):
        return None


def _get_status_code(exc: BaseException) -> int | None:
    """Extract HTTP status code from an exception, if available."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    return None


def _is_retryable(exc: BaseException) -> bool:
    """Determine if an exception is retryable.

    Retryable: 429, 5xx, network errors.
    Not retryable: 401, 403, other 4xx.
    """
    # Network-level errors are always retryable
    if isinstance(exc, _RETRYABLE_NETWORK_ERRORS):
        return True

    status = _get_status_code(exc)
    if status is None:
        return False

    if status in _NO_RETRY_STATUSES:
        return False

    return status in _RETRYABLE_STATUSES


def _get_retry_delay(exc: BaseException, attempt: int, base_delay: float) -> float:
    """Calculate delay before next retry attempt.

    For 429: use Retry-After header if present.
    For 5xx/network: exponential backoff.
    """
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        retry_after = _parse_retry_after(exc.response)
        if retry_after is not None:
            return retry_after

    # Exponential backoff: base_delay * 2^attempt (0-indexed)
    backoff: float = base_delay * (2**attempt)
    return min(backoff, _MAX_RETRY_AFTER)


async def retry_with_backoff[T](
    func: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 2,
    base_delay: float = 1.0,
    operation: str = "http_request",
) -> T:
    """Execute an async function with retry on transient failures.

    Args:
        func: Zero-argument async callable to execute.
        max_retries: Maximum number of retry attempts (0 = no retry).
        base_delay: Base delay in seconds for exponential backoff.
        operation: Human-readable name for logging.

    Returns:
        The result of func() on success.

    Raises:
        The last exception if all attempts fail, or immediately on non-retryable errors.
    """
    last_exc: BaseException | None = None

    for attempt in range(max_retries + 1):
        try:
            return await func()
        except Exception as exc:
            last_exc = exc

            if not _is_retryable(exc):
                raise

            if attempt >= max_retries:
                raise

            delay = _get_retry_delay(exc, attempt, base_delay)
            status = _get_status_code(exc)

            log.warning(
                "http_retry",
                operation=operation,
                attempt=attempt + 1,
                max_retries=max_retries,
                status=status,
                delay_s=round(delay, 2),
                error=str(exc)[:200],
            )

            await asyncio.sleep(delay)

    # Should not reach here, but satisfy type checker
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retry_with_backoff: unexpected state")  # pragma: no cover
