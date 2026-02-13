"""Tests for services/publishers/vk.py — VK API v5.199 publisher.

Covers: validate_connection, publish (3-step photo upload + wall.post),
delete_post, _check_vk_response, E08 (VK token revoked).
All VK API calls use POST with form data (not GET with URL params).
"""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest

from db.models import PlatformConnection
from services.publishers.base import PublishRequest
from services.publishers.vk import _VK_TEXT_LIMIT, _VK_VERSION, VKPublisher

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
            "group_id": "12345",
        },
    }
    defaults.update(overrides)
    return PlatformConnection(**defaults)


def _make_publisher(handler: object) -> VKPublisher:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    client = httpx.AsyncClient(transport=transport)
    return VKPublisher(http_client=client)


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
# validate_connection
# ---------------------------------------------------------------------------


class TestValidateConnection:
    async def test_success_returns_true(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert "groups.getById" in str(request.url)
            assert request.method == "POST"
            form = _parse_form_data(request)
            assert form["v"] == _VK_VERSION
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
            captured_form.update(_parse_form_data(request))
            # Verify token is NOT in URL params
            assert "access_token" not in str(request.url.params)
            return httpx.Response(200, json={"response": [{"id": 12345}]})

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
                # Upload step already uses POST — this is fine
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
