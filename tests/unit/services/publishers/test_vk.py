"""Tests for services/publishers/vk.py — VK API v5.199 publisher.

Covers: validate_connection, publish (3-step photo upload + wall.post),
delete_post, _check_vk_response, E08 (VK token revoked),
_maybe_refresh_token, _refresh_token (OAuth 2.1 token refresh).
All VK API calls use POST with form data (not GET with URL params).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest

from db.models import PlatformConnection
from services.publishers.base import PublishRequest
from services.publishers.vk import _VK_TEXT_LIMIT, VK_API_VERSION, VKPublisher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_connection(**overrides: object) -> PlatformConnection:
    defaults: dict = {
        "id": 1,
        "project_id": 1,
        "platform_type": "vk",
        "identifier": "My Group",
        "credentials": {
            "access_token": "vk1.a.test_token_123",
            "refresh_token": "vk1.a.refresh_token_abc",
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "device_id": "device123",
            "group_id": "12345",
        },
    }
    defaults.update(overrides)
    return PlatformConnection(**defaults)


def _make_legacy_connection() -> PlatformConnection:
    """Connection without refresh_token (legacy Implicit Flow)."""
    return PlatformConnection(
        id=2,
        project_id=1,
        platform_type="vk",
        identifier="Legacy Group",
        credentials={
            "access_token": "legacy_token",
            "group_id": "12345",
        },
    )


def _make_publisher(handler: object, vk_app_id: int = 12345, on_token_refresh: object = None) -> VKPublisher:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    client = httpx.AsyncClient(transport=transport)
    return VKPublisher(
        http_client=client,
        vk_app_id=vk_app_id,
        on_token_refresh=on_token_refresh,  # type: ignore[arg-type]
    )


def _parse_form_data(request: httpx.Request) -> dict[str, str]:
    """Parse URL-encoded form body into a dict."""
    body = request.content.decode("utf-8")
    parsed = parse_qs(body)
    # parse_qs returns lists — flatten single values
    return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _check_vk_response
# ---------------------------------------------------------------------------


class TestCheckVkResponse:
    def test_no_error_passes(self) -> None:
        data = {"response": [{"id": 1}]}
        # Should not raise
        VKPublisher._check_vk_response(data, "test")

    def test_error_block_raises(self) -> None:
        data = {"error": {"error_code": 5, "error_msg": "User authorization failed"}}
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            VKPublisher._check_vk_response(data, "test_op")
        assert "error 5" in str(exc_info.value)
        assert "User authorization failed" in str(exc_info.value)

    def test_error_without_code_uses_fallback(self) -> None:
        data = {"error": {"error_msg": "Something"}}
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            VKPublisher._check_vk_response(data, "op")
        assert "?" in str(exc_info.value)  # error_code defaults to "?"


# ---------------------------------------------------------------------------
# _maybe_refresh_token / _refresh_token
# ---------------------------------------------------------------------------


class TestTokenRefresh:
    async def test_valid_token_returns_existing(self) -> None:
        """Token not expiring soon — return current access_token."""
        async def handler(request: httpx.Request) -> httpx.Response:
            pytest.fail("Should not make HTTP call for valid token")

        pub = _make_publisher(handler)
        conn = _make_connection()
        token = await pub._maybe_refresh_token(conn.credentials)
        assert token == "vk1.a.test_token_123"

    async def test_expired_token_triggers_refresh(self) -> None:
        """Token expired — should refresh."""
        refresh_called = False

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal refresh_called
            if "oauth2/auth" in str(request.url):
                refresh_called = True
                form = _parse_form_data(request)
                assert form["grant_type"] == "refresh_token"
                assert form["refresh_token"] == "vk1.a.refresh_token_abc"
                assert form["client_id"] == "12345"
                assert form["device_id"] == "device123"
                return httpx.Response(200, json={
                    "access_token": "new_token",
                    "refresh_token": "new_refresh",
                    "expires_in": 3600,
                })
            return httpx.Response(404)

        pub = _make_publisher(handler)
        creds = {
            "access_token": "old_token",
            "refresh_token": "vk1.a.refresh_token_abc",
            "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            "device_id": "device123",
            "group_id": "12345",
        }
        token = await pub._maybe_refresh_token(creds)
        assert token == "new_token"
        assert refresh_called

    async def test_token_expiring_soon_triggers_refresh(self) -> None:
        """Token expires in < 5 minutes — should refresh."""
        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth2/auth" in str(request.url):
                return httpx.Response(200, json={
                    "access_token": "refreshed_token",
                    "refresh_token": "new_refresh",
                    "expires_in": 3600,
                })
            return httpx.Response(404)

        pub = _make_publisher(handler)
        creds = {
            "access_token": "old_token",
            "refresh_token": "some_refresh",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
            "device_id": "dev123",
            "group_id": "12345",
        }
        token = await pub._maybe_refresh_token(creds)
        assert token == "refreshed_token"

    async def test_legacy_connection_without_refresh_token(self) -> None:
        """Legacy connection without refresh_token — return current token as-is."""
        async def handler(request: httpx.Request) -> httpx.Response:
            pytest.fail("Should not make HTTP call for legacy connection")

        pub = _make_publisher(handler)
        conn = _make_legacy_connection()
        token = await pub._maybe_refresh_token(conn.credentials)
        assert token == "legacy_token"

    async def test_on_token_refresh_callback_called(self) -> None:
        """on_token_refresh callback is called with old and new credentials."""
        callback_called = False
        old_creds_received: dict = {}
        new_creds_received: dict = {}

        async def token_callback(old_creds: dict, new_creds: dict) -> None:
            nonlocal callback_called, old_creds_received, new_creds_received
            callback_called = True
            old_creds_received = old_creds
            new_creds_received = new_creds

        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth2/auth" in str(request.url):
                return httpx.Response(200, json={
                    "access_token": "new_access",
                    "refresh_token": "new_refresh",
                    "expires_in": 3600,
                })
            return httpx.Response(404)

        pub = _make_publisher(handler, on_token_refresh=token_callback)
        creds = {
            "access_token": "old",
            "refresh_token": "old_refresh",
            "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            "device_id": "dev",
            "group_id": "123",
        }
        await pub._maybe_refresh_token(creds)
        assert callback_called
        assert old_creds_received["access_token"] == "old"
        assert new_creds_received["access_token"] == "new_access"
        assert new_creds_received["refresh_token"] == "new_refresh"
        assert "expires_at" in new_creds_received
        assert new_creds_received["device_id"] == "dev"
        assert new_creds_received["group_id"] == "123"

    async def test_no_expires_at_with_refresh_token_triggers_refresh(self) -> None:
        """No expires_at but has refresh_token — try refresh."""
        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth2/auth" in str(request.url):
                return httpx.Response(200, json={
                    "access_token": "refreshed",
                    "expires_in": 3600,
                })
            return httpx.Response(404)

        pub = _make_publisher(handler)
        creds = {
            "access_token": "old",
            "refresh_token": "rf",
            "device_id": "d",
            "group_id": "1",
        }
        token = await pub._maybe_refresh_token(creds)
        assert token == "refreshed"

    async def test_refresh_http_error_propagates(self) -> None:
        """HTTP error during refresh should raise."""
        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth2/auth" in str(request.url):
                return httpx.Response(401, json={"error": "invalid_grant"})
            return httpx.Response(404)

        pub = _make_publisher(handler)
        creds = {
            "access_token": "old",
            "refresh_token": "rf",
            "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            "device_id": "d",
            "group_id": "1",
        }
        with pytest.raises(httpx.HTTPStatusError):
            await pub._maybe_refresh_token(creds)


# ---------------------------------------------------------------------------
# validate_connection
# ---------------------------------------------------------------------------


class TestValidateConnection:
    async def test_success_returns_true(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth2/auth" in str(request.url):
                return httpx.Response(404)  # shouldn't be called — token is valid
            assert "groups.getById" in str(request.url)
            assert request.method == "POST"
            form = _parse_form_data(request)
            assert form["v"] == VK_API_VERSION
            return httpx.Response(200, json={"response": [{"id": 12345, "name": "Group"}]})

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.validate_connection(conn)
        assert result is True

    async def test_error_response_returns_false(self) -> None:
        """E08: VK token revoked."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"error": {"error_code": 5, "error_msg": "User authorization failed"}})

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.validate_connection(conn)
        assert result is False

    async def test_network_error_returns_false(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("VK API unreachable")

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.validate_connection(conn)
        assert result is False

    async def test_passes_correct_params_in_body(self) -> None:
        """Token must be in POST body, not URL params."""
        captured_form: dict = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            if "groups.getById" in str(request.url):
                captured_form.update(_parse_form_data(request))
                assert "access_token" not in str(request.url.params)
                return httpx.Response(200, json={"response": [{"id": 12345}]})
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        await pub.validate_connection(conn)
        assert captured_form["access_token"] == "vk1.a.test_token_123"
        assert captured_form["group_id"] == "12345"

    async def test_uses_post_not_get(self) -> None:
        """All VK API calls must use POST (C3 fix)."""
        captured_methods: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            captured_methods.append(request.method)
            return httpx.Response(200, json={"response": [{"id": 12345}]})

        pub = _make_publisher(handler)
        conn = _make_connection()
        await pub.validate_connection(conn)
        assert all(m == "POST" for m in captured_methods)


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------


class TestPublish:
    async def test_publish_text_only(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "wall.post" in url:
                assert request.method == "POST"
                form = _parse_form_data(request)
                assert form["owner_id"] == "-12345"
                assert form["message"] == "Hello VK"
                return httpx.Response(200, json={"response": {"post_id": 999}})
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="Hello VK",
            content_type="plain_text",
        )
        result = await pub.publish(req)
        assert result.success is True
        assert result.platform_post_id == "999"
        assert "vk.com/wall-12345_999" in result.post_url  # type: ignore[operator]

    async def test_publish_with_image_three_step(self) -> None:
        call_sequence: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "photos.getWallUploadServer" in url:
                call_sequence.append("get_server")
                assert request.method == "POST"
                return httpx.Response(
                    200,
                    json={"response": {"upload_url": "https://upload.vk.com/upload"}},
                )
            if "upload.vk.com/upload" in url:
                call_sequence.append("upload")
                return httpx.Response(
                    200,
                    json={"photo": "photo_data", "server": 1, "hash": "abc123"},
                )
            if "photos.saveWallPhoto" in url:
                call_sequence.append("save")
                assert request.method == "POST"
                return httpx.Response(
                    200,
                    json={"response": [{"id": 456, "owner_id": -12345}]},
                )
            if "wall.post" in url:
                call_sequence.append("post")
                assert request.method == "POST"
                form = _parse_form_data(request)
                assert "photo-12345_456" in form.get("attachments", "")
                return httpx.Response(200, json={"response": {"post_id": 777}})
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="Post with image",
            content_type="plain_text",
            images=[b"PNG_IMAGE_DATA"],
        )
        result = await pub.publish(req)
        assert result.success is True
        assert call_sequence == ["get_server", "upload", "save", "post"]

    async def test_publish_text_truncated_to_limit(self) -> None:
        long_text = "A" * 20000

        async def handler(request: httpx.Request) -> httpx.Response:
            if "wall.post" in str(request.url):
                form = _parse_form_data(request)
                assert len(form["message"]) <= _VK_TEXT_LIMIT
                return httpx.Response(200, json={"response": {"post_id": 1}})
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content=long_text,
            content_type="plain_text",
        )
        result = await pub.publish(req)
        assert result.success is True

    async def test_publish_vk_api_error_returns_failure(self) -> None:
        """E08: token revoked during publish."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"error": {"error_code": 5, "error_msg": "User authorization failed"}},
            )

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(connection=conn, content="x", content_type="plain_text")
        result = await pub.publish(req)
        assert result.success is False
        assert result.error is not None

    async def test_publish_network_error_returns_failure(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("VK down")

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(connection=conn, content="x", content_type="plain_text")
        result = await pub.publish(req)
        assert result.success is False

    async def test_publish_upload_error_returns_failure(self) -> None:
        """Failure during photo upload step."""

        async def handler(request: httpx.Request) -> httpx.Response:
            if "photos.getWallUploadServer" in str(request.url):
                return httpx.Response(
                    200,
                    json={"error": {"error_code": 100, "error_msg": "Missing parameter"}},
                )
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="text",
            content_type="plain_text",
            images=[b"DATA"],
        )
        result = await pub.publish(req)
        assert result.success is False

    async def test_all_api_calls_use_post(self) -> None:
        """Verify every VK API call uses POST method (C3 security fix)."""
        captured_methods: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            captured_methods.append(request.method)
            url = str(request.url)
            if "photos.getWallUploadServer" in url:
                return httpx.Response(
                    200,
                    json={"response": {"upload_url": "https://upload.vk.com/upload"}},
                )
            if "upload.vk.com/upload" in url:
                return httpx.Response(
                    200,
                    json={"photo": "photo_data", "server": 1, "hash": "abc123"},
                )
            if "photos.saveWallPhoto" in url:
                return httpx.Response(
                    200,
                    json={"response": [{"id": 456, "owner_id": -12345}]},
                )
            if "wall.post" in url:
                return httpx.Response(200, json={"response": {"post_id": 777}})
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="test",
            content_type="plain_text",
            images=[b"DATA"],
        )
        await pub.publish(req)
        # All calls should be POST
        assert all(m == "POST" for m in captured_methods)


# ---------------------------------------------------------------------------
# delete_post
# ---------------------------------------------------------------------------


class TestDeletePost:
    async def test_delete_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert "wall.delete" in str(request.url)
            assert request.method == "POST"
            form = _parse_form_data(request)
            assert form["post_id"] == "42"
            assert form["owner_id"] == "-12345"
            return httpx.Response(200, json={"response": 1})

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.delete_post(conn, "42")
        assert result is True

    async def test_delete_failure_response(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"response": 0})

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.delete_post(conn, "42")
        assert result is False

    async def test_delete_network_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("VK down")

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.delete_post(conn, "42")
        assert result is False

    async def test_delete_vk_error_response(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"error": {"error_code": 15, "error_msg": "Access denied"}})

        pub = _make_publisher(handler)
        conn = _make_connection()
        # VK returns error object, but no "response" key -> get("response") returns None
        result = await pub.delete_post(conn, "42")
        assert result is False
