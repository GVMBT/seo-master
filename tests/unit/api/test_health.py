"""Tests for api/health.py — health check endpoint."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from api.health import health_handler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(auth_header: str = "", health_token: str = "secret123") -> MagicMock:  # noqa: S107
    settings_mock = MagicMock()
    settings_mock.health_check_token.get_secret_value.return_value = health_token
    settings_mock.qstash_token.get_secret_value.return_value = "qstash_token"

    db_mock = MagicMock()
    db_mock.table.return_value.select.return_value.limit.return_value.execute = AsyncMock()

    redis_mock = MagicMock()
    redis_mock.ping = AsyncMock(return_value=True)

    http_mock = MagicMock()
    http_mock.get = AsyncMock(return_value=MagicMock(status_code=200))

    app = MagicMock()
    app.__getitem__ = MagicMock(side_effect=lambda key: {
        "settings": settings_mock,
        "db": db_mock,
        "redis": redis_mock,
        "http_client": http_mock,
    }[key])

    request = MagicMock()
    request.app = app
    request.headers = MagicMock()
    request.headers.get = MagicMock(side_effect=lambda k, d="": auth_header if k == "Authorization" else d)

    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_health_public_no_token() -> None:
    """No auth header returns simple status."""
    request = _make_request(auth_header="")
    resp = await health_handler(request)

    data = json.loads(resp.body)
    assert data["status"] == "ok"
    assert "version" not in data  # E29: no version in public response
    assert "checks" not in data


async def test_health_public_wrong_token() -> None:
    """Wrong token returns simple status (no detailed checks)."""
    request = _make_request(auth_header="Bearer wrong_token")
    resp = await health_handler(request)

    data = json.loads(resp.body)
    assert "checks" not in data


@patch("qstash.QStash")
async def test_health_detailed_all_ok(mock_qstash_cls: MagicMock) -> None:
    """Valid token returns detailed checks with all services ok."""
    mock_q = MagicMock()
    mock_q.schedule.list.return_value = []
    mock_qstash_cls.return_value = mock_q

    request = _make_request(auth_header="Bearer secret123")
    resp = await health_handler(request)

    data = json.loads(resp.body)
    assert data["status"] == "ok"
    assert data["checks"]["database"] == "ok"
    assert data["checks"]["redis"] == "ok"
    assert data["checks"]["openrouter"] == "ok"
    assert data["checks"]["qstash"] == "ok"


@patch("qstash.QStash")
async def test_health_db_down(mock_qstash_cls: MagicMock) -> None:
    """Database failure results in 'down' status."""
    mock_q = MagicMock()
    mock_q.schedule.list.return_value = []
    mock_qstash_cls.return_value = mock_q

    request = _make_request(auth_header="Bearer secret123")
    # Make DB fail
    request.app["db"].table.return_value.select.return_value.limit.return_value.execute = AsyncMock(
        side_effect=Exception("DB down")
    )

    resp = await health_handler(request)

    data = json.loads(resp.body)
    assert data["status"] == "down"
    assert data["checks"]["database"] == "error"


@patch("qstash.QStash")
async def test_health_degraded_openrouter(mock_qstash_cls: MagicMock) -> None:
    """OpenRouter failure results in 'degraded' status."""
    mock_q = MagicMock()
    mock_q.schedule.list.return_value = []
    mock_qstash_cls.return_value = mock_q

    request = _make_request(auth_header="Bearer secret123")
    request.app["http_client"].get = AsyncMock(return_value=MagicMock(status_code=500))

    resp = await health_handler(request)

    data = json.loads(resp.body)
    assert data["status"] == "degraded"
    assert data["checks"]["openrouter"] == "error"


@patch("qstash.QStash")
async def test_health_degraded_qstash(mock_qstash_cls: MagicMock) -> None:
    """QStash failure results in 'degraded' status."""
    mock_q = MagicMock()
    mock_q.schedule.list.side_effect = Exception("QStash down")
    mock_qstash_cls.return_value = mock_q

    request = _make_request(auth_header="Bearer secret123")
    resp = await health_handler(request)

    data = json.loads(resp.body)
    assert data["status"] == "degraded"
    assert data["checks"]["qstash"] == "error"


async def test_health_empty_token_config() -> None:
    """Empty health token means detailed check is never accessible."""
    request = _make_request(auth_header="Bearer anything", health_token="")
    resp = await health_handler(request)

    data = json.loads(resp.body)
    assert "checks" not in data
