"""Tests for services/publishers/pinterest.py — Pinterest API v5 publisher.

Covers: validate_connection, _maybe_refresh_token (token refresh), publish,
delete_post, on_token_refresh callback, E20 (OAuth timeout).
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx

from db.models import PlatformConnection
from services.publishers.base import PublishRequest
from services.publishers.pinterest import _DESCRIPTION_LIMIT, _TITLE_LIMIT, PinterestPublisher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Token that expires in 30 days (fresh)
_FRESH_EXPIRES = (datetime.now(UTC) + timedelta(days=15)).isoformat()
# Token that expires in less than 1 day (needs refresh)
_EXPIRING_SOON = (datetime.now(UTC) + timedelta(hours=12)).isoformat()
# Already expired token
_EXPIRED = (datetime.now(UTC) - timedelta(days=1)).isoformat()


def _make_connection(
    expires_at: str = _FRESH_EXPIRES,
    **overrides: object,
) -> PlatformConnection:
    defaults: dict = {
        "id": 1,
        "project_id": 1,
        "platform_type": "pinterest",
        "identifier": "My Board",
        "credentials": {
            "access_token": "pin_access_token_123",
            "refresh_token": "pin_refresh_token_456",
            "expires_at": expires_at,
            "board_id": "board_999",
        },
    }
    defaults.update(overrides)
    return PlatformConnection(**defaults)


def _make_publisher(
    handler: object,
    on_token_refresh: object | None = None,
) -> PinterestPublisher:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    client = httpx.AsyncClient(transport=transport)
    return PinterestPublisher(
        http_client=client,
        client_id="test_app_id",
        client_secret="test_app_secret",
        on_token_refresh=on_token_refresh,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# _maybe_refresh_token
# ---------------------------------------------------------------------------


class TestMaybeRefreshToken:
    async def test_fresh_token_not_refreshed(self) -> None:
        """Token with >1 day until expiry should not refresh."""

        async def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("Should not make any HTTP requests")

        pub = _make_publisher(handler)
        conn = _make_connection(expires_at=_FRESH_EXPIRES)
        token = await pub._maybe_refresh_token(conn.credentials)
        assert token == "pin_access_token_123"

    async def test_expiring_soon_triggers_refresh(self) -> None:
        """Token expiring within 1 day should trigger refresh."""

        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth/token" in str(request.url):
                return httpx.Response(200, json={
                    "access_token": "new_access_token",
                    "refresh_token": "new_refresh_token",
                    "expires_in": 2592000,
                })
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection(expires_at=_EXPIRING_SOON)
        token = await pub._maybe_refresh_token(conn.credentials)
        assert token == "new_access_token"

    async def test_expired_token_triggers_refresh(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth/token" in str(request.url):
                return httpx.Response(200, json={
                    "access_token": "refreshed_token",
                    "expires_in": 2592000,
                })
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection(expires_at=_EXPIRED)
        token = await pub._maybe_refresh_token(conn.credentials)
        assert token == "refreshed_token"

    async def test_no_expires_at_triggers_refresh(self) -> None:
        """No expires_at in creds -> always refresh."""

        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth/token" in str(request.url):
                return httpx.Response(200, json={
                    "access_token": "refreshed",
                    "expires_in": 2592000,
                })
            return httpx.Response(404)

        pub = _make_publisher(handler)
        creds = {
            "access_token": "old",
            "refresh_token": "refresh_tok",
        }
        token = await pub._maybe_refresh_token(creds)
        assert token == "refreshed"

    async def test_refresh_calls_on_token_refresh_callback(self) -> None:
        callback = AsyncMock()

        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth/token" in str(request.url):
                return httpx.Response(200, json={
                    "access_token": "new_at",
                    "refresh_token": "new_rt",
                    "expires_in": 2592000,
                })
            return httpx.Response(404)

        pub = _make_publisher(handler, on_token_refresh=callback)
        conn = _make_connection(expires_at=_EXPIRING_SOON)
        await pub._maybe_refresh_token(conn.credentials)

        callback.assert_awaited_once()
        _old_creds, new_creds = callback.call_args.args
        assert new_creds["access_token"] == "new_at"
        assert new_creds["refresh_token"] == "new_rt"
        assert "expires_at" in new_creds

    async def test_refresh_without_callback(self) -> None:
        """Publisher with no on_token_refresh callback should still work."""

        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth/token" in str(request.url):
                return httpx.Response(200, json={
                    "access_token": "new_token",
                    "expires_in": 2592000,
                })
            return httpx.Response(404)

        pub = _make_publisher(handler, on_token_refresh=None)
        conn = _make_connection(expires_at=_EXPIRING_SOON)
        token = await pub._maybe_refresh_token(conn.credentials)
        assert token == "new_token"

    async def test_refresh_preserves_old_refresh_token_if_not_returned(self) -> None:
        callback = AsyncMock()

        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth/token" in str(request.url):
                return httpx.Response(200, json={
                    "access_token": "new_at",
                    # No refresh_token in response -> should keep old one
                    "expires_in": 2592000,
                })
            return httpx.Response(404)

        pub = _make_publisher(handler, on_token_refresh=callback)
        conn = _make_connection(expires_at=_EXPIRING_SOON)
        await pub._maybe_refresh_token(conn.credentials)

        _, new_creds = callback.call_args.args
        assert new_creds["refresh_token"] == "pin_refresh_token_456"


# ---------------------------------------------------------------------------
# validate_connection
# ---------------------------------------------------------------------------


class TestValidateConnection:
    async def test_success_returns_true(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "user_account" in str(request.url):
                assert "Bearer pin_access_token_123" in request.headers.get("Authorization", "")
                return httpx.Response(200, json={"username": "testuser"})
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.validate_connection(conn)
        assert result is True

    async def test_401_returns_false(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"code": 0, "message": "Unauthorized"})

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.validate_connection(conn)
        assert result is False

    async def test_network_error_returns_false(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Pinterest down")

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.validate_connection(conn)
        assert result is False


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------


class TestPublish:
    async def test_publish_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "/pins" in str(request.url) and request.method == "POST":
                body = json.loads(request.content)
                assert body["board_id"] == "board_999"
                assert body["media_source"]["source_type"] == "image_base64"
                assert body["media_source"]["content_type"] == "image/png"
                return httpx.Response(201, json={"id": "pin_12345"})
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="Beautiful SEO content",
            content_type="pin_text",
            images=[b"PNG_DATA"],
            metadata={"board_id": "board_999", "pin_title": "My Pin"},
        )
        result = await pub.publish(req)
        assert result.success is True
        assert result.post_url == "https://pinterest.com/pin/pin_12345"
        assert result.platform_post_id == "pin_12345"

    async def test_publish_no_images_returns_error(self) -> None:
        """Pinterest requires at least one image."""

        async def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("Should not make HTTP requests")

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="No image",
            content_type="pin_text",
            metadata={"board_id": "board_999"},
        )
        result = await pub.publish(req)
        assert result.success is False
        assert "image" in result.error.lower()  # type: ignore[union-attr]

    async def test_publish_image_encoded_base64(self) -> None:
        img_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        expected_b64 = base64.b64encode(img_data).decode()

        async def handler(request: httpx.Request) -> httpx.Response:
            if "/pins" in str(request.url) and request.method == "POST":
                body = json.loads(request.content)
                assert body["media_source"]["data"] == expected_b64
                return httpx.Response(201, json={"id": "pin_1"})
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="Pin",
            content_type="pin_text",
            images=[img_data],
            metadata={"board_id": "b1"},
        )
        result = await pub.publish(req)
        assert result.success is True

    async def test_publish_with_link(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "/pins" in str(request.url) and request.method == "POST":
                body = json.loads(request.content)
                assert body["link"] == "https://example.com/article"
                return httpx.Response(201, json={"id": "pin_1"})
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="Pin desc",
            content_type="pin_text",
            images=[b"IMG"],
            metadata={"board_id": "b1", "link": "https://example.com/article"},
        )
        result = await pub.publish(req)
        assert result.success is True

    async def test_publish_description_truncated(self) -> None:
        long_desc = "A" * 1000

        async def handler(request: httpx.Request) -> httpx.Response:
            if "/pins" in str(request.url) and request.method == "POST":
                body = json.loads(request.content)
                assert len(body["description"]) <= _DESCRIPTION_LIMIT
                return httpx.Response(201, json={"id": "pin_1"})
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content=long_desc,
            content_type="pin_text",
            images=[b"IMG"],
            metadata={"board_id": "b1"},
        )
        result = await pub.publish(req)
        assert result.success is True

    async def test_publish_title_truncated(self) -> None:
        long_title = "T" * 200

        async def handler(request: httpx.Request) -> httpx.Response:
            if "/pins" in str(request.url) and request.method == "POST":
                body = json.loads(request.content)
                assert len(body["title"]) <= _TITLE_LIMIT
                return httpx.Response(201, json={"id": "pin_1"})
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="Desc",
            content_type="pin_text",
            images=[b"IMG"],
            metadata={"board_id": "b1", "pin_title": long_title},
        )
        result = await pub.publish(req)
        assert result.success is True

    async def test_publish_api_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"code": 0, "message": "Forbidden"})

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="x",
            content_type="pin_text",
            images=[b"IMG"],
            metadata={"board_id": "b1"},
        )
        result = await pub.publish(req)
        assert result.success is False

    async def test_publish_network_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Pinterest unreachable")

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="x",
            content_type="pin_text",
            images=[b"IMG"],
            metadata={"board_id": "b1"},
        )
        result = await pub.publish(req)
        assert result.success is False


# ---------------------------------------------------------------------------
# delete_post
# ---------------------------------------------------------------------------


class TestDeletePost:
    async def test_delete_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "/pins/pin_123" in str(request.url) and request.method == "DELETE":
                return httpx.Response(204)
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.delete_post(conn, "pin_123")
        assert result is True

    async def test_delete_not_found(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"code": 0, "message": "Not found"})

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.delete_post(conn, "pin_999")
        assert result is False

    async def test_delete_network_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Network error")

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.delete_post(conn, "pin_123")
        assert result is False
