"""Integration tests for GET /api/health endpoint.

Tests public vs detailed health checks with Bearer token authentication.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.integration


async def test_health_public_no_token(api_client):
    """GET /api/health without Bearer token returns minimal public response."""
    resp = await api_client.get("/api/health")
    assert resp.status == 200
    body = await resp.json()
    assert body == {"status": "ok"}
    # Public response must NOT include version or checks
    assert "version" not in body
    assert "checks" not in body


async def test_health_public_invalid_token(api_client):
    """GET /api/health with wrong Bearer token returns public response (no details)."""
    resp = await api_client.get("/api/health", headers={"Authorization": "Bearer wrong_token"})
    assert resp.status == 200
    body = await resp.json()
    assert body == {"status": "ok"}
    assert "checks" not in body


async def test_health_detailed_valid_token(api_client, app_services):
    """GET /api/health with correct Bearer token returns detailed checks."""
    # Configure mocks for a successful health check
    app_services["db"].set_response("users", MagicMock(data=[{"id": 1}]))
    app_services["redis"].clear()  # redis ping returns True by default

    # Mock httpx get for OpenRouter check
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    app_services["http_client"].get = AsyncMock(return_value=mock_resp)

    with patch("api.health.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.return_value = None  # QStash check passes

        resp = await api_client.get(
            "/api/health",
            headers={"Authorization": "Bearer health_token_secret"},
        )

    assert resp.status == 200
    body = await resp.json()
    assert "checks" in body
    assert "version" in body
    assert body["status"] == "ok"


async def test_health_detailed_db_down(api_client, app_services):
    """When DB is unreachable, detailed health returns status 'down'."""
    # Override the mock_db.table to raise
    original_table = app_services["db"].table

    def _broken_table(name):
        builder = original_table(name)
        # Override execute to raise
        async def _raise():
            raise ConnectionError("DB connection refused")
        builder.execute = _raise
        return builder

    app_services["db"].table = _broken_table

    # Mock httpx and QStash to pass
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    app_services["http_client"].get = AsyncMock(return_value=mock_resp)

    with patch("api.health.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.return_value = None

        resp = await api_client.get(
            "/api/health",
            headers={"Authorization": "Bearer health_token_secret"},
        )

    body = await resp.json()
    assert body["status"] == "down"
    assert body["checks"]["database"]["status"] == "error"


async def test_health_detailed_redis_down(api_client, app_services):
    """When Redis ping fails, detailed health returns status 'down'."""
    # Override redis.ping to raise
    original_ping = app_services["redis"].ping
    app_services["redis"].ping = AsyncMock(side_effect=ConnectionError("Redis down"))

    # DB passes
    app_services["db"].set_response("users", MagicMock(data=[{"id": 1}]))

    # Mock httpx and QStash
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    app_services["http_client"].get = AsyncMock(return_value=mock_resp)

    with patch("api.health.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.return_value = None

        resp = await api_client.get(
            "/api/health",
            headers={"Authorization": "Bearer health_token_secret"},
        )

    body = await resp.json()
    assert body["status"] == "down"
    assert body["checks"]["redis"]["status"] == "error"

    # Restore
    app_services["redis"].ping = original_ping


async def test_health_detailed_openrouter_down(api_client, app_services):
    """When OpenRouter is unreachable, detailed health returns status 'degraded'."""
    # DB and Redis pass
    app_services["db"].set_response("users", MagicMock(data=[{"id": 1}]))

    # OpenRouter fails
    app_services["http_client"].get = AsyncMock(side_effect=ConnectionError("OpenRouter down"))

    with patch("api.health.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.return_value = None

        resp = await api_client.get(
            "/api/health",
            headers={"Authorization": "Bearer health_token_secret"},
        )

    body = await resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["openrouter"]["status"] == "error"
    # DB and Redis should still be ok
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["redis"]["status"] == "ok"


async def test_health_detailed_all_ok(api_client, app_services):
    """When all services are up, health returns status 'ok' with all checks."""
    app_services["db"].set_response("users", MagicMock(data=[{"id": 1}]))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    app_services["http_client"].get = AsyncMock(return_value=mock_resp)

    with patch("api.health.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.return_value = None

        resp = await api_client.get(
            "/api/health",
            headers={"Authorization": "Bearer health_token_secret"},
        )

    body = await resp.json()
    assert body["status"] == "ok"
    assert set(body["checks"].keys()) == {"database", "redis", "openrouter", "qstash"}
    for name, check in body["checks"].items():
        assert check["status"] == "ok", f"{name} should be ok"


async def test_health_includes_version_and_uptime(api_client, app_services):
    """Detailed health response includes version string and uptime_seconds."""
    app_services["db"].set_response("users", MagicMock(data=[{"id": 1}]))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    app_services["http_client"].get = AsyncMock(return_value=mock_resp)

    with patch("api.health.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.return_value = None

        resp = await api_client.get(
            "/api/health",
            headers={"Authorization": "Bearer health_token_secret"},
        )

    body = await resp.json()
    assert "version" in body
    assert isinstance(body["version"], str)
    assert body["version"] == "2.0.0"
    assert "uptime_seconds" in body
    assert isinstance(body["uptime_seconds"], int)
    assert body["uptime_seconds"] >= 0
