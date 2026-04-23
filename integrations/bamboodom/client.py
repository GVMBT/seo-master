"""Async HTTP client for bamboodom.ru blog API (v1.1).

Session 1 surface: only `key_test()` — smoke-test endpoint used by the
admin panel. Other endpoints (blog_context, blog_article_codes, blog_publish,
blog_upload_image) arrive in subsequent sessions.

Design notes:
- Stateless HTTP calls via shared/one-off httpx.AsyncClient.
- No caching here (deferred to Session 2 when it actually matters).
- Exceptions map to user-facing screen messages; logs are structured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from bot.config import get_settings
from integrations.bamboodom.exceptions import (
    BamboodomAPIError,
    BamboodomAuthError,
    BamboodomRateLimitError,
)
from integrations.bamboodom.models import KeyTestResponse

log = structlog.get_logger()

_DEFAULT_TIMEOUT = 10.0
_MAX_ERROR_BODY = 500


@dataclass
class BamboodomClient:
    """Thin async wrapper over bamboodom.ru blog API.

    Parameters are optional — defaults fall back to `Settings` singleton.
    Pass explicit values in tests.
    """

    api_base: str = ""
    api_key: str = ""
    http_client: httpx.AsyncClient | None = None
    timeout: float = _DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        if not self.api_base or not self.api_key:
            settings = get_settings()
            self.api_base = self.api_base or settings.bamboodom_api_base
            self.api_key = self.api_key or settings.bamboodom_blog_key.get_secret_value()

    # ---- internals ----------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise BamboodomAuthError("BAMBOODOM_BLOG_KEY not configured")
        return {
            "X-Blog-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        action: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        headers = self._headers()  # raises BamboodomAuthError if key missing
        query: dict[str, Any] = {"action": action, **(params or {})}
        effective_timeout = timeout if timeout is not None else self.timeout

        async def _send(client: httpx.AsyncClient) -> httpx.Response:
            return await client.request(
                method,
                self.api_base,
                params=query,
                headers=headers,
                json=json_body,
                timeout=effective_timeout,
            )

        try:
            if self.http_client is not None:
                resp = await _send(self.http_client)
            else:
                async with httpx.AsyncClient(timeout=effective_timeout) as client:
                    resp = await _send(client)
        except httpx.TimeoutException as exc:
            raise BamboodomAPIError(f"Timeout on {action}: {exc}") from exc
        except httpx.RequestError as exc:
            raise BamboodomAPIError(f"Network error on {action}: {exc}") from exc

        return self._handle_response(action, resp)

    @staticmethod
    def _handle_response(action: str, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 401:
            raise BamboodomAuthError("Invalid X-Blog-Key (HTTP 401)")
        if resp.status_code == 429:
            retry_after_raw = resp.headers.get("Retry-After", "60")
            try:
                retry_after = int(retry_after_raw)
            except ValueError:
                retry_after = 60
            raise BamboodomRateLimitError(retry_after)
        if resp.status_code >= 500:
            raise BamboodomAPIError(f"Server error {resp.status_code} on {action}: {resp.text[:_MAX_ERROR_BODY]}")
        if resp.status_code >= 400:
            raise BamboodomAPIError(f"Client error {resp.status_code} on {action}: {resp.text[:_MAX_ERROR_BODY]}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise BamboodomAPIError(f"Non-JSON response on {action}: {resp.text[:_MAX_ERROR_BODY]}") from exc

        if not isinstance(data, dict):
            raise BamboodomAPIError(f"Unexpected JSON shape on {action}: {type(data).__name__}")

        if not data.get("ok"):
            raise BamboodomAPIError(f"API returned ok=false on {action}: {str(data)[:_MAX_ERROR_BODY]}")
        return data

    # ---- public API ---------------------------------------------------

    async def key_test(self) -> KeyTestResponse:
        """GET blog_key_test — smoke-test endpoint (no rate limit, no sandbox needed)."""
        data = await self._request("GET", "blog_key_test", timeout=_DEFAULT_TIMEOUT)
        return KeyTestResponse.model_validate(data)
