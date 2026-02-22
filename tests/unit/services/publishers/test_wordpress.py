"""Tests for services/publishers/wordpress.py — WordPress REST API v2 publisher.

Covers: validate_connection, publish (with/without images), delete_post,
_base_url, _auth helpers, E02 (WP unavailable).
"""

from __future__ import annotations

import base64
import json

import httpx

from db.models import PlatformConnection
from services.publishers.base import PublishRequest
from services.publishers.wordpress import WordPressPublisher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_connection(**overrides: object) -> PlatformConnection:
    defaults: dict = {
        "id": 1,
        "project_id": 1,
        "platform_type": "wordpress",
        "identifier": "example.com",
        "credentials": {
            "url": "https://example.com",
            "login": "admin",
            "app_password": "xxxx xxxx xxxx xxxx xxxx xxxx",
        },
    }
    defaults.update(overrides)
    return PlatformConnection(**defaults)


def _make_publisher(handler: object) -> WordPressPublisher:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    client = httpx.AsyncClient(transport=transport)
    return WordPressPublisher(http_client=client)


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------


class TestBaseUrl:
    def test_strips_trailing_slash(self) -> None:
        creds = {"url": "https://example.com/", "login": "a", "app_password": "b"}
        assert WordPressPublisher._base_url(creds) == "https://example.com/wp-json/wp/v2"

    def test_no_trailing_slash(self) -> None:
        creds = {"url": "https://example.com", "login": "a", "app_password": "b"}
        assert WordPressPublisher._base_url(creds) == "https://example.com/wp-json/wp/v2"

    def test_preserves_path(self) -> None:
        creds = {"url": "https://example.com/blog", "login": "a", "app_password": "b"}
        assert WordPressPublisher._base_url(creds) == "https://example.com/blog/wp-json/wp/v2"


class TestAuth:
    def test_returns_basic_auth(self) -> None:
        creds = {"url": "https://example.com", "login": "admin", "app_password": "secret"}
        auth = WordPressPublisher._auth(creds)
        assert isinstance(auth, httpx.BasicAuth)
        # Verify the auth header encodes login:password correctly
        expected = "Basic " + base64.b64encode(b"admin:secret").decode("ascii")
        assert auth._auth_header == expected


# ---------------------------------------------------------------------------
# validate_connection
# ---------------------------------------------------------------------------


class TestValidateConnection:
    async def test_success_returns_true(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert "/users/me" in str(request.url)
            return httpx.Response(200, json={"id": 1, "name": "admin"})

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.validate_connection(conn)
        assert result is True

    async def test_401_returns_false(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"code": "rest_not_logged_in"})

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.validate_connection(conn)
        assert result is False

    async def test_403_returns_false(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"code": "rest_forbidden"})

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.validate_connection(conn)
        assert result is False

    async def test_network_error_returns_false(self) -> None:
        """E02: WP unavailable."""

        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.validate_connection(conn)
        assert result is False


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------


class TestPublish:
    async def test_publish_text_only_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "/posts" in str(request.url):
                body = json.loads(request.content)
                assert body["title"] == "Test Article"
                assert body["status"] == "publish"
                assert body["featured_media"] == 0
                return httpx.Response(201, json={"id": 42, "link": "https://example.com/test-article"})
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="<h1>Hello</h1><p>World</p>",
            content_type="html",
            title="Test Article",
        )
        result = await pub.publish(req)
        assert result.success is True
        assert result.post_url == "https://example.com/test-article"
        assert result.platform_post_id == "42"

    async def test_publish_with_image_upload(self) -> None:
        call_order: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/media" in url:
                call_order.append("media")
                assert request.headers["Content-Type"] == "image/png"
                return httpx.Response(201, json={"id": 100})
            if "/posts" in url:
                call_order.append("posts")
                body = json.loads(request.content)
                assert body["featured_media"] == 100
                return httpx.Response(201, json={"id": 42, "link": "https://example.com/post"})
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="Article body",
            content_type="html",
            title="Test",
            images=[b"PNG_DATA"],
        )
        result = await pub.publish(req)
        assert result.success is True
        assert call_order == ["media", "posts"]

    async def test_publish_with_wp_category_id(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "/posts" in str(request.url):
                body = json.loads(request.content)
                assert body["categories"] == [5]
                return httpx.Response(201, json={"id": 1, "link": "https://example.com/p"})
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="Content",
            content_type="html",
            metadata={"wp_category_id": 5},
        )
        result = await pub.publish(req)
        assert result.success is True

    async def test_publish_with_seo_metadata(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "/posts" in str(request.url):
                body = json.loads(request.content)
                assert body["meta"]["_yoast_wpseo_title"] == "My SEO Title"
                assert body["meta"]["_yoast_wpseo_metadesc"] == "My Desc"
                assert body["meta"]["_yoast_wpseo_focuskw"] == "keyword"
                return httpx.Response(201, json={"id": 1, "link": "https://example.com/p"})
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="Content",
            content_type="html",
            title="Title",
            metadata={
                "seo_title": "My SEO Title",
                "meta_description": "My Desc",
                "focus_keyword": "keyword",
            },
        )
        result = await pub.publish(req)
        assert result.success is True

    async def test_publish_http_status_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(connection=conn, content="x", content_type="html")
        result = await pub.publish(req)
        assert result.success is False
        assert result.error is not None

    async def test_publish_network_error(self) -> None:
        """E02: WP unavailable during publish."""

        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(connection=conn, content="x", content_type="html")
        result = await pub.publish(req)
        assert result.success is False
        assert result.error is not None

    async def test_publish_media_upload_failure_returns_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "/media" in str(request.url):
                return httpx.Response(413, text="File too large")
            return httpx.Response(201, json={"id": 1, "link": "https://example.com/p"})

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="x",
            content_type="html",
            images=[b"LARGE_IMAGE"],
        )
        result = await pub.publish(req)
        assert result.success is False

    async def test_publish_no_title_defaults_empty(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "/posts" in str(request.url):
                body = json.loads(request.content)
                assert body["title"] == ""
                return httpx.Response(201, json={"id": 1, "link": "https://example.com/p"})
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(connection=conn, content="x", content_type="html")
        result = await pub.publish(req)
        assert result.success is True


# ---------------------------------------------------------------------------
# delete_post
# ---------------------------------------------------------------------------


class TestDeletePost:
    async def test_delete_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert "/posts/42" in str(request.url)
            assert request.url.params.get("force") == "true"
            return httpx.Response(200, json={"deleted": True})

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.delete_post(conn, "42")
        assert result is True

    async def test_delete_not_found(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"code": "rest_post_invalid_id"})

        pub = _make_publisher(handler)
        conn = _make_connection()
        # 404 is_success returns False
        result = await pub.delete_post(conn, "9999")
        assert result is False

    async def test_delete_network_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.delete_post(conn, "42")
        assert result is False
