"""Tests for api/vk_auth.py — VK OAuth aiohttp handlers.

Covers: redirect (step 1 VK ID + step 2 classic), callback happy path,
device_id passthrough, error param (user denial), invalid state (403).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from api.vk_auth import vk_auth_callback, vk_auth_redirect
from services.oauth.vk import VKOAuthError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_redirect_request(
    user_id: str = "",
    nonce: str = "",
    group_ids: str = "",
) -> web.Request:
    """Create a mock request for /api/auth/vk."""
    query_parts = []
    if user_id:
        query_parts.append(f"user_id={user_id}")
    if nonce:
        query_parts.append(f"nonce={nonce}")
    if group_ids:
        query_parts.append(f"group_ids={group_ids}")
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
    error: str = "",
    error_description: str = "",
    device_id: str = "",
    bot_username: str = "seo_master_bot",
) -> web.Request:
    """Create a mock request for /api/auth/vk/callback."""
    query_parts = []
    if code:
        query_parts.append(f"code={code}")
    if state:
        query_parts.append(f"state={state}")
    if error:
        query_parts.append(f"error={error}")
    if error_description:
        query_parts.append(f"error_description={error_description}")
    if device_id:
        query_parts.append(f"device_id={device_id}")
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
    settings.vk_secure_key = MagicMock()
    settings.vk_secure_key.get_secret_value.return_value = "test_secret"
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

    async def test_step1_redirects_to_vkid(self) -> None:
        """Step 1 (no group_ids): redirects to VK ID OAuth 2.1 (id.vk.ru)."""
        request = _make_redirect_request(user_id="42", nonce="test_nonce")

        mock_service = MagicMock()
        mock_service.build_authorize_url.return_value = (
            "https://id.vk.ru/authorize?client_id=123",
            "state_xyz",
        )
        mock_service.get_last_code_verifier.return_value = "test_code_verifier"
        mock_service.store_auth = AsyncMock()

        with (
            patch("api.vk_auth.get_settings", return_value=_mock_settings()),
            patch("api.vk_auth._build_vk_oauth_service", return_value=mock_service),
            pytest.raises(web.HTTPFound) as exc_info,
        ):
            await vk_auth_redirect(request)

        location = exc_info.value.location
        assert "id.vk.ru/authorize" in location
        mock_service.store_auth.assert_awaited_once_with(
            "test_nonce", 42, step="groups", code_verifier="test_code_verifier",
        )

    async def test_step2_redirects_to_classic_vk(self) -> None:
        """Step 2 (with group_ids): redirects to classic VK OAuth (oauth.vk.com)."""
        request = _make_redirect_request(user_id="42", nonce="test_nonce", group_ids="999")

        mock_service = MagicMock()
        mock_service.build_authorize_url.return_value = (
            "https://oauth.vk.com/authorize?group_ids=999",
            "state_xyz",
        )
        mock_service.store_auth = AsyncMock()

        with (
            patch("api.vk_auth.get_settings", return_value=_mock_settings()),
            patch("api.vk_auth._build_vk_oauth_service", return_value=mock_service),
            pytest.raises(web.HTTPFound),
        ):
            await vk_auth_redirect(request)

        # Step 2: store_auth NOT called (already stored by group select handler)
        mock_service.store_auth.assert_not_awaited()
        mock_service.build_authorize_url.assert_called_once_with(42, "test_nonce", group_ids=999)

    async def test_invalid_group_ids_returns_400(self) -> None:
        request = _make_redirect_request(user_id="42", nonce="abc", group_ids="not_a_number")
        with patch("api.vk_auth.get_settings", return_value=_mock_settings()):
            response = await vk_auth_redirect(request)
        assert response.status == 400
        assert "group_ids" in response.text


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
        request = _make_callback_request(code="bad_code", state="bad_state")

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

    async def test_device_id_passed_to_handle_callback(self) -> None:
        """VK ID OAuth 2.1 (step 1) returns device_id which must be forwarded."""
        request = _make_callback_request(
            code="code",
            state="state",
            device_id="test_device_123",
            bot_username="mybot",
        )

        mock_service = AsyncMock()
        mock_service.handle_callback = AsyncMock(return_value=(999, "unique_nonce"))

        with (
            patch("api.vk_auth.get_settings", return_value=_mock_settings()),
            patch("api.vk_auth._build_vk_oauth_service", return_value=mock_service),
            pytest.raises(web.HTTPFound),
        ):
            await vk_auth_callback(request)

        mock_service.handle_callback.assert_awaited_once_with(
            "code", "state", device_id="test_device_123",
        )

    async def test_deep_link_contains_nonce(self) -> None:
        request = _make_callback_request(
            code="code",
            state="state",
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
