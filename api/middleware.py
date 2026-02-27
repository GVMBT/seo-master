"""aiohttp middleware for API endpoints.

Security headers middleware (H11): adds standard security headers
to all API responses (QStash webhooks, health, OAuth, etc.).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiohttp import web


@web.middleware
async def security_headers_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Add security headers to every HTTP response (H11)."""
    response = await handler(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    # X-XSS-Protection: 0 disables legacy XSS auditor (modern CSP is preferred)
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'none'"
    return response
