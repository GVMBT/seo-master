"""LoggingMiddleware — structured JSON logging with correlation_id."""

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

log = structlog.get_logger()


class LoggingMiddleware(BaseMiddleware):
    """Inner middleware (#5): adds correlation_id, logs handler latency.

    Sets data["correlation_id"] (UUID4) for downstream use.
    Logs: user_id, update_type, latency_ms.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        correlation_id = str(uuid.uuid4())
        data["correlation_id"] = correlation_id

        user = data.get("event_from_user")
        user_id = user.id if user else None
        update_type = type(event).__name__

        start = time.monotonic()
        try:
            result = await handler(event, data)
            latency_ms = round((time.monotonic() - start) * 1000, 2)
            log.info(
                "request_handled",
                correlation_id=correlation_id,
                user_id=user_id,
                update_type=update_type,
                latency_ms=latency_ms,
            )
            return result
        except Exception:
            latency_ms = round((time.monotonic() - start) * 1000, 2)
            log.error(
                "request_failed",
                correlation_id=correlation_id,
                user_id=user_id,
                update_type=update_type,
                latency_ms=latency_ms,
                exc_info=True,
            )
            raise
