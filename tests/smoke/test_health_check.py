"""Smoke tests: health check endpoint on deployed Railway instance.

Uses httpx to hit the public URL. All tests are skipped if RAILWAY_PUBLIC_URL is not set.
"""

from __future__ import annotations

import os

import httpx
import pytest

_BASE_URL = os.environ.get("RAILWAY_PUBLIC_URL", "").rstrip("/")
_HEALTH_TOKEN = os.environ.get("HEALTH_CHECK_TOKEN", "")

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(not _BASE_URL, reason="RAILWAY_PUBLIC_URL not set"),
]


async def test_health_public_ok() -> None:
    """GET /api/health without token -> 200 + {status: 'ok'}.

    Public health check returns minimal response without sensitive details (E29).
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{_BASE_URL}/api/health")

    assert response.status_code == 200, f"Health check returned {response.status_code}: {response.text}"

    data = response.json()
    assert data["status"] == "ok", f"Health status is not 'ok': {data}"
    # Public response must NOT contain version or detailed checks (E29)
    assert "version" not in data, "Public health check leaks version info (E29 violation)"
    assert "checks" not in data, "Public health check leaks detailed checks (E29 violation)"


@pytest.mark.skipif(not _HEALTH_TOKEN, reason="HEALTH_CHECK_TOKEN not set")
async def test_health_detailed_with_token() -> None:
    """GET /api/health with Bearer token -> detailed response with checks.

    Detailed health check returns version, uptime, and individual service checks.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{_BASE_URL}/api/health",
            headers={"Authorization": f"Bearer {_HEALTH_TOKEN}"},
        )

    assert response.status_code == 200, f"Detailed health check returned {response.status_code}"

    data = response.json()
    # Detailed response must include version and checks
    assert "version" in data, f"Detailed health missing version: {data}"
    assert "checks" in data, f"Detailed health missing checks: {data}"
    assert "uptime_seconds" in data, f"Detailed health missing uptime: {data}"

    # Status should be one of the valid values
    assert data["status"] in ("ok", "degraded", "down"), f"Invalid health status: {data['status']}"

    # Checks should include at least database and redis
    checks = data["checks"]
    assert "database" in checks, f"Health checks missing database: {checks}"
    assert "redis" in checks, f"Health checks missing redis: {checks}"


async def test_webhook_endpoint_rejects_unsigned() -> None:
    """POST /api/publish without QStash signature -> 401.

    Verifies that the publish webhook properly rejects unsigned requests.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{_BASE_URL}/api/publish",
            json={"user_id": 1, "category_id": 1, "platform_type": "wordpress"},
        )

    # Should reject with 401 (missing Upstash-Signature)
    assert response.status_code == 401, (
        f"Unsigned publish request returned {response.status_code} instead of 401: {response.text}"
    )
