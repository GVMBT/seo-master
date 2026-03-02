"""Tests for api/vk_auth.py — VK ID OAuth 2.1 aiohttp handlers.

Covers: redirect (302 + correct params), callback happy path,
error param (user denial), invalid state (403), missing device_id fallback.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from api.vk_auth import vk_auth_callback, vk_auth_redirect
from api.vk_oauth import VKOAuthError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_redirect_request(
    user_id: str = "",
    nonce: str = "",
) -> web.Request:
    """Create a mock request for /api/auth/vk."""
    query_parts = []
    if user_id:
        query_parts.append(f"user_id={user_id}")
    if nonce:
        query_parts.append(f"nonce={nonce}")
    query_string = "&".join(query_parts)

    app = MagicMock()
    app.__getitem__ = MagicMock(
        side_effect=lambda key: {
            "http_client": AsyncMock(),
            "redis": AsyncMock(),
        }[key]
    )
    return make_mocked_request("GET", f"/api/auth/vk?{query_string}", app=app)


def _make_callback_request(
    code: str = "",
    state: str = "",
    device_id: str = "",
    error: str = "",
    error_description: str = "",
    bot_username: str = "seo_master_bot",
) -> web.Request:
    """Create a mock request for /api/auth/vk/callback."""
    query_parts = []
    if code:
        query_parts.append(f"code={code}")
    if state:
        query_parts.append(f"state={state}")
    if device_id:
        query_parts.append(f"device_id={device_id}")
    if error:
        query_parts.append(f"error={error}")
    if error_description:
        query_parts.append(f"error_description={error_description}")
    query_string = "&".join(query_parts)

    app = MagicMock()
    app.__getitem__ = MagicMock(
        side_effect=lambda key: {
            "http_client": AsyncMock(),
            "redis": AsyncMock(),
            "bot_username": bot_username,
        }[key]
    )
    return make_mocked_request("GET", f"/api/auth/vk/callback?{query_string}", app=app)


def _mock_settings() -> MagicMock:
    settings = MagicMock()
    settings.railway_public_url = "https://example.com"
    settings.encryption_key = MagicMock()
    settings.encryption_key.get_secret_value.return_value = "x" * 32
    settings.vk_app_id = 123456
    return settings


# ---------------------------------------------------------------------------
# vk_auth_redirect
# ---------------------------------------------------------------------------


class TestVKAuthRedirect:
    async def test_missing_user_id_returns_400(self) -> None:
        request = _make_redirect_request(user_id="", nonce="abc")
        with patch("api.vk_auth.get_settings", return_value=_mock_settings()):
            response = await vk_auth_redirect(request)
        assert response.status == 400
        assert "user_id" in response.text

    async def test_missing_nonce_returns_400(self) -> None:
        request = _make_redirect_request(user_id="42", nonce="")
        with patch("api.vk_auth.get_settings", return_value=_mock_settings()):
            response = await vk_auth_redirect(request)
        assert response.status == 400
        assert "nonce" in response.text

    async def test_invalid_user_id_returns_400(self) -> None:
        request = _make_redirect_request(user_id="not_a_number", nonce="abc")
        with patch("api.vk_auth.get_settings", return_value=_mock_settings()):
            response = await vk_auth_redirect(request)
        assert response.status == 400
        assert "Invalid" in response.text

    async def test_success_redirects_to_vk(self) -> None:
        request = _make_redirect_request(user_id="42", nonce="test_nonce")

        mock_service = MagicMock()
        mock_service.build_authorize_url.return_value = (
            "https://id.vk.com/authorize?client_id=123",
            "verifier_abc",
            "state_xyz",
        )
        mock_service.store_pkce = AsyncMock()

        with (
            patch("api.vk_auth.get_settings", return_value=_mock_settings()),
            patch("api.vk_auth._build_vk_oauth_service", return_value=mock_service),
            pytest.raises(web.HTTPFound) as exc_info,
        ):
            await vk_auth_redirect(request)

        location = exc_info.value.location
        assert "id.vk.com/authorize" in location
        mock_service.store_pkce.assert_awaited_once_with("test_nonce", "verifier_abc", 42)

    async def test_redirect_calls_store_pkce(self) -> None:
        request = _make_redirect_request(user_id="99", nonce="n1")

        mock_service = MagicMock()
        mock_service.build_authorize_url.return_value = (
            "https://id.vk.com/authorize?foo=bar",
            "my_verifier",
            "my_state",
        )
        mock_service.store_pkce = AsyncMock()

        with (
            patch("api.vk_auth.get_settings", return_value=_mock_settings()),
            patch("api.vk_auth._build_vk_oauth_service", return_value=mock_service),
            pytest.raises(web.HTTPFound),
        ):
            await vk_auth_redirect(request)

        mock_service.store_pkce.assert_awaited_once_with("n1", "my_verifier", 99)


# ---------------------------------------------------------------------------
# vk_auth_callback
# ---------------------------------------------------------------------------


class TestVKAuthCallback:
    async def test_user_denial_returns_200_html(self) -> None:
        request = _make_callback_request(
            error="access_denied",
            error_description="User denied access",
        )
        with patch("api.vk_auth.get_settings", return_value=_mock_settings()):
            response = await vk_auth_callback(request)
        assert response.status == 200
        assert "text/html" in response.content_type
        assert "отменена" in response.text.lower()

    async def test_missing_code_returns_400(self) -> None:
        request = _make_callback_request(code="", state="some_state")
        with patch("api.vk_auth.get_settings", return_value=_mock_settings()):
            response = await vk_auth_callback(request)
        assert response.status == 400
        assert "Missing" in response.text

    async def test_missing_state_returns_400(self) -> None:
        request = _make_callback_request(code="some_code", state="")
        with patch("api.vk_auth.get_settings", return_value=_mock_settings()):
            response = await vk_auth_callback(request)
        assert response.status == 400
        assert "Missing" in response.text

    async def test_oauth_error_returns_403(self) -> None:
        request = _make_callback_request(
            code="bad_code",
            state="bad_state",
            device_id="dev123",
        )

        mock_service = AsyncMock()
        mock_service.handle_callback = AsyncMock(side_effect=VKOAuthError("HMAC failed"))

        with (
            patch("api.vk_auth.get_settings", return_value=_mock_settings()),
            patch("api.vk_auth._build_vk_oauth_service", return_value=mock_service),
        ):
            response = await vk_auth_callback(request)
        assert response.status == 403
        assert "failed" in response.text.lower()

    async def test_success_redirects_to_deep_link(self) -> None:
        request = _make_callback_request(
            code="good_code",
            state="valid_state",
            device_id="dev_abc",
            bot_username="testbot",
        )

        mock_service = AsyncMock()
        mock_service.handle_callback = AsyncMock(return_value=(42, "nonce_abc"))

        with (
            patch("api.vk_auth.get_settings", return_value=_mock_settings()),
            patch("api.vk_auth._build_vk_oauth_service", return_value=mock_service),
            pytest.raises(web.HTTPFound) as exc_info,
        ):
            await vk_auth_callback(request)

        location = exc_info.value.location
        assert "tg://resolve" in location
        assert "testbot" in location
        assert "vk_auth_nonce_abc" in location

    async def test_missing_device_id_generates_fallback(self) -> None:
        """device_id is required for token exchange — fallback if missing."""
        request = _make_callback_request(
            code="code",
            state="state",
            device_id="",  # missing
            bot_username="mybot",
        )

        mock_service = AsyncMock()
        mock_service.handle_callback = AsyncMock(return_value=(1, "n1"))

        with (
            patch("api.vk_auth.get_settings", return_value=_mock_settings()),
            patch("api.vk_auth._build_vk_oauth_service", return_value=mock_service),
            pytest.raises(web.HTTPFound),
        ):
            await vk_auth_callback(request)

        # Verify handle_callback was called with a non-empty device_id
        call_args = mock_service.handle_callback.call_args
        actual_device_id = call_args.kwargs.get("device_id") or call_args[1].get("device_id", call_args[0][2])
        assert len(actual_device_id) > 0

    async def test_deep_link_contains_nonce(self) -> None:
        request = _make_callback_request(
            code="code",
            state="state",
            device_id="dev",
            bot_username="mybot",
        )

        mock_service = AsyncMock()
        mock_service.handle_callback = AsyncMock(return_value=(999, "unique_nonce"))

        with (
            patch("api.vk_auth.get_settings", return_value=_mock_settings()),
            patch("api.vk_auth._build_vk_oauth_service", return_value=mock_service),
            pytest.raises(web.HTTPFound) as exc_info,
        ):
            await vk_auth_callback(request)

        assert "unique_nonce" in exc_info.value.location
