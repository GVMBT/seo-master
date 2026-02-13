"""Tests for api/auth.py — Pinterest OAuth callback aiohttp handler.

Covers: valid request + redirect, missing code/state -> 400,
OAuth error -> 403, deep_link construction.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from api.auth import pinterest_callback
from api.auth_service import PinterestOAuthError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    code: str = "",
    state: str = "",
    bot_username: str = "seo_master_bot",
) -> web.Request:
    """Create a mock aiohttp request with query params."""
    query_parts = []
    if code:
        query_parts.append(f"code={code}")
    if state:
        query_parts.append(f"state={state}")
    query_string = "&".join(query_parts)

    app = MagicMock()
    app.__getitem__ = MagicMock(side_effect=lambda key: {
        "http_client": AsyncMock(),
        "redis": AsyncMock(),
        "bot_username": bot_username,
    }[key])

    request = make_mocked_request(
        "GET",
        f"/api/auth/pinterest/callback?{query_string}",
        app=app,
    )
    return request


def _mock_settings() -> MagicMock:
    settings = MagicMock()
    settings.railway_public_url = "https://example.com"
    settings.encryption_key = MagicMock()
    settings.encryption_key.get_secret_value.return_value = "x" * 32  # noqa: S106
    settings.pinterest_app_id = "test_app"
    settings.pinterest_app_secret = MagicMock()
    settings.pinterest_app_secret.get_secret_value.return_value = "test_secret"
    return settings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPinterestCallback:
    async def test_missing_code_returns_400(self) -> None:
        request = _make_request(code="", state="some_state")
        with patch("api.auth.get_settings", return_value=_mock_settings()):
            response = await pinterest_callback(request)
        assert response.status == 400
        assert "Missing code" in response.text

    async def test_missing_state_returns_400(self) -> None:
        request = _make_request(code="some_code", state="")
        with patch("api.auth.get_settings", return_value=_mock_settings()):
            response = await pinterest_callback(request)
        assert response.status == 400
        assert "Missing" in response.text

    async def test_missing_both_returns_400(self) -> None:
        request = _make_request(code="", state="")
        with patch("api.auth.get_settings", return_value=_mock_settings()):
            response = await pinterest_callback(request)
        assert response.status == 400

    async def test_oauth_error_returns_403(self) -> None:
        request = _make_request(code="bad_code", state="bad_state")

        mock_service = AsyncMock()
        mock_service.handle_callback = AsyncMock(side_effect=PinterestOAuthError("HMAC failed"))

        with (
            patch("api.auth.get_settings", return_value=_mock_settings()),
            patch("api.auth.PinterestOAuthService", return_value=mock_service),
        ):
            response = await pinterest_callback(request)
        assert response.status == 403
        assert "failed" in response.text.lower()

    async def test_success_redirects_to_deep_link(self) -> None:
        request = _make_request(code="good_code", state="valid_state", bot_username="testbot")

        mock_service = AsyncMock()
        mock_service.handle_callback = AsyncMock(return_value=(12345, "nonce_abc"))

        with (
            patch("api.auth.get_settings", return_value=_mock_settings()),
            patch("api.auth.PinterestOAuthService", return_value=mock_service),
            pytest.raises(web.HTTPFound) as exc_info,
        ):
            await pinterest_callback(request)

        location = exc_info.value.location
        assert "tg://resolve" in location
        assert "testbot" in location
        assert "pinterest_auth_nonce_abc" in location

    async def test_deep_link_contains_nonce(self) -> None:
        request = _make_request(code="code", state="state", bot_username="mybot")

        mock_service = AsyncMock()
        mock_service.handle_callback = AsyncMock(return_value=(999, "unique_nonce"))

        with (
            patch("api.auth.get_settings", return_value=_mock_settings()),
            patch("api.auth.PinterestOAuthService", return_value=mock_service),
            pytest.raises(web.HTTPFound) as exc_info,
        ):
            await pinterest_callback(request)

        assert "unique_nonce" in exc_info.value.location
