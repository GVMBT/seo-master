"""Tests for api/middleware.py — security headers middleware (H11).

Covers: all security headers are set on every response.
"""

from __future__ import annotations

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer


async def _dummy_handler(request: web.Request) -> web.Response:
    """Simple handler for testing middleware."""
    return web.json_response({"ok": True})


class TestSecurityHeadersMiddleware(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        from api.middleware import security_headers_middleware

        app = web.Application(middlewares=[security_headers_middleware])
        app.router.add_get("/test", _dummy_handler)
        return app

    async def test_x_content_type_options(self) -> None:
        resp = await self.client.get("/test")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"

    async def test_x_frame_options(self) -> None:
        resp = await self.client.get("/test")
        assert resp.headers["X-Frame-Options"] == "DENY"

    async def test_x_xss_protection(self) -> None:
        resp = await self.client.get("/test")
        assert resp.headers["X-XSS-Protection"] == "0"

    async def test_referrer_policy(self) -> None:
        resp = await self.client.get("/test")
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    async def test_csp(self) -> None:
        resp = await self.client.get("/test")
        assert resp.headers["Content-Security-Policy"] == "default-src 'none'"

    async def test_response_body_not_affected(self) -> None:
        resp = await self.client.get("/test")
        data = await resp.json()
        assert data == {"ok": True}
