"""Smoke tests: deployment health and version verification.

Uses httpx to verify the Railway deployment is running and responsive.
All tests are skipped if RAILWAY_PUBLIC_URL is not set.
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


async def test_no_crash_loops_in_response() -> None:
    """GET /api/health returns 200 within 5 seconds (not hung or crashed).

    A healthy deployment should respond to the health endpoint quickly.
    If the service is in a crash loop or hung, the request will timeout.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            response = await client.get(f"{_BASE_URL}/api/health")
        except httpx.TimeoutException:
            pytest.fail(
                f"Health endpoint at {_BASE_URL}/api/health did not respond within 5 seconds "
                "(possible crash loop or service hang)"
            )
        except httpx.ConnectError as exc:
            pytest.fail(f"Cannot connect to {_BASE_URL}/api/health: {exc} (service may be down or URL is incorrect)")

    assert response.status_code == 200, f"Health endpoint returned {response.status_code}: {response.text}"

    data = response.json()
    assert "status" in data, f"Health response missing 'status' key: {data}"


@pytest.mark.skipif(not _HEALTH_TOKEN, reason="HEALTH_CHECK_TOKEN not set for version check")
async def test_version_matches_expected() -> None:
    """Detailed health check includes version '2.0.0'.

    Verifies that the deployed version matches the expected release version.
    Requires HEALTH_CHECK_TOKEN for the detailed health response.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{_BASE_URL}/api/health",
            headers={"Authorization": f"Bearer {_HEALTH_TOKEN}"},
        )

    assert response.status_code == 200, f"Health check returned {response.status_code}"

    data = response.json()
    assert "version" in data, f"Detailed health missing 'version': {data}"
    assert data["version"] == "2.0.0", f"Deployed version {data['version']!r} does not match expected '2.0.0'"
