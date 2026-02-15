"""Fixtures for API integration tests using aiohttp TestClient."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests.integration.conftest import (
    MockRedisClient,
    MockSupabaseClient,
)


def _create_test_app(
    mock_db: MockSupabaseClient,
    mock_redis: MockRedisClient,
    mock_bot: MagicMock,
    mock_http_client: MagicMock,
    mock_settings: MagicMock,
) -> web.Application:
    """Create aiohttp app with real route handlers and mocked dependencies.

    Mirrors bot/main.py create_app() route registration but injects test mocks.
    """
    from api.cleanup import cleanup_handler
    from api.health import health_handler
    from api.notify import notify_handler
    from api.publish import publish_handler
    from api.yookassa import yookassa_webhook

    app = web.Application()

    # Register routes (same as bot/main.py)
    app.router.add_post("/api/publish", publish_handler)
    app.router.add_post("/api/cleanup", cleanup_handler)
    app.router.add_post("/api/notify", notify_handler)
    app.router.add_get("/api/health", health_handler)
    app.router.add_post("/api/yookassa/webhook", yookassa_webhook)

    # Inject mocked dependencies (same keys as bot/main.py)
    app["db"] = mock_db
    app["redis"] = mock_redis
    app["bot"] = mock_bot
    app["http_client"] = mock_http_client
    app["settings"] = mock_settings
    app["ai_orchestrator"] = MagicMock()
    app["image_storage"] = MagicMock()
    app["yookassa_service"] = MagicMock()
    app["scheduler_service"] = MagicMock()

    return app


@pytest.fixture
async def api_client(
    mock_db: MockSupabaseClient,
    mock_redis: MockRedisClient,
    mock_bot: MagicMock,
    mock_http_client: MagicMock,
    mock_settings: MagicMock,
) -> Any:
    """aiohttp TestClient with real handlers and mock dependencies.

    Usage:
        async def test_health(api_client):
            resp = await api_client.get("/api/health")
            assert resp.status == 200
    """
    app = _create_test_app(mock_db, mock_redis, mock_bot, mock_http_client, mock_settings)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await client.close()


@pytest.fixture
def app_services(api_client: TestClient) -> dict[str, Any]:
    """Access to app-level mock services for assertions.

    Usage:
        def test_something(api_client, app_services):
            app_services["yookassa_service"].process_webhook = AsyncMock(...)
    """
    app = api_client.app
    return {
        "db": app["db"],
        "redis": app["redis"],
        "bot": app["bot"],
        "http_client": app["http_client"],
        "settings": app["settings"],
        "ai_orchestrator": app["ai_orchestrator"],
        "image_storage": app["image_storage"],
        "yookassa_service": app["yookassa_service"],
        "scheduler_service": app["scheduler_service"],
    }
