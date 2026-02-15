"""Integration tests for WordPressPublisher (WP REST API v2).

Uses `respx` to mock httpx calls to the WordPress REST API.
All tests exercise the real WordPressPublisher class with mocked HTTP transport.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from db.models import PlatformConnection
from services.publishers.base import PublishRequest
from services.publishers.wordpress import WordPressPublisher

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_WP_CREDS = {
    "url": "https://blog.example.com",
    "login": "admin",
    "app_password": "xxxx-xxxx-xxxx",
}

_WP_BASE = "https://blog.example.com/wp-json/wp/v2"


def _make_connection(creds: dict[str, str] | None = None) -> PlatformConnection:
    """Build a PlatformConnection with WP credentials."""
    return PlatformConnection(
        id=100,
        project_id=1,
        platform_type="wordpress",
        status="active",
        credentials=creds or _WP_CREDS,
        metadata={},
        identifier="https://blog.example.com",
    )


def _make_request(
    connection: PlatformConnection | None = None,
    content: str = "<h1>Test Article</h1><p>Test content.</p>",
    title: str = "Test Article",
    images: list[bytes] | None = None,
    images_meta: list[dict[str, str]] | None = None,
    metadata: dict[str, object] | None = None,
) -> PublishRequest:
    return PublishRequest(
        connection=connection or _make_connection(),
        content=content,
        content_type="html",
        images=images or [],
        images_meta=images_meta or [],
        title=title,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# 1. Successful article publish
# ---------------------------------------------------------------------------


@respx.mock
async def test_wp_publish_article_success() -> None:
    """POST /wp-json/wp/v2/posts -> 201 -> returns post URL."""
    respx.post(f"{_WP_BASE}/posts").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 42,
                "link": "https://blog.example.com/test-article/",
                "status": "publish",
            },
        )
    )

    async with httpx.AsyncClient() as client:
        publisher = WordPressPublisher(client)
        result = await publisher.publish(_make_request())

    assert result.success is True
    assert result.post_url == "https://blog.example.com/test-article/"
    assert result.platform_post_id == "42"


# ---------------------------------------------------------------------------
# 2. Publish with images (upload media + set featured_media)
# ---------------------------------------------------------------------------


@respx.mock
async def test_wp_publish_with_images() -> None:
    """Upload images via /wp-json/wp/v2/media, then create post with featured_media."""
    # RIFF header = WebP magic bytes
    webp_bytes = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100

    # Mock media upload (image)
    media_route = respx.post(f"{_WP_BASE}/media").mock(
        return_value=httpx.Response(201, json={"id": 99}),
    )
    # Mock media metadata update (alt_text, caption)
    respx.post(f"{_WP_BASE}/media/99").mock(
        return_value=httpx.Response(200, json={"id": 99}),
    )
    # Mock post creation
    post_route = respx.post(f"{_WP_BASE}/posts").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 55,
                "link": "https://blog.example.com/article-with-image/",
            },
        ),
    )

    meta = [{"filename": "hero-image", "alt": "Test hero image", "figcaption": "Hero caption"}]
    req = _make_request(images=[webp_bytes], images_meta=meta)

    async with httpx.AsyncClient() as client:
        publisher = WordPressPublisher(client)
        result = await publisher.publish(req)

    assert result.success is True
    assert result.post_url == "https://blog.example.com/article-with-image/"

    # Verify media was uploaded
    assert media_route.call_count == 1

    # Verify post was created with featured_media = 99
    post_call = post_route.calls[0]
    body = json.loads(post_call.request.content)
    assert body["featured_media"] == 99


# ---------------------------------------------------------------------------
# 3. Auth failure (401)
# ---------------------------------------------------------------------------


@respx.mock
async def test_wp_publish_auth_failure() -> None:
    """WP returns 401 -> PublishResult with success=False."""
    respx.post(f"{_WP_BASE}/posts").mock(
        return_value=httpx.Response(
            401,
            json={"code": "rest_cannot_create", "message": "Unauthorized"},
        ),
    )

    async with httpx.AsyncClient() as client:
        publisher = WordPressPublisher(client)
        result = await publisher.publish(_make_request())

    assert result.success is False
    assert result.error is not None
    assert "401" in result.error


# ---------------------------------------------------------------------------
# 4. Connection timeout
# ---------------------------------------------------------------------------


@respx.mock
async def test_wp_publish_connection_timeout() -> None:
    """httpx.ConnectTimeout -> PublishResult with success=False."""
    respx.post(f"{_WP_BASE}/posts").mock(
        side_effect=httpx.ConnectTimeout("Connection timed out"),
    )

    async with httpx.AsyncClient() as client:
        publisher = WordPressPublisher(client)
        result = await publisher.publish(_make_request())

    assert result.success is False
    assert result.error is not None
    assert "timed out" in result.error.lower() or "timeout" in result.error.lower()


# ---------------------------------------------------------------------------
# 5. Server error (500)
# ---------------------------------------------------------------------------


@respx.mock
async def test_wp_publish_server_error() -> None:
    """WP returns 500 -> PublishResult with success=False."""
    respx.post(f"{_WP_BASE}/posts").mock(
        return_value=httpx.Response(
            500,
            json={"code": "internal_server_error", "message": "DB connection lost"},
        ),
    )

    async with httpx.AsyncClient() as client:
        publisher = WordPressPublisher(client)
        result = await publisher.publish(_make_request())

    assert result.success is False
    assert result.error is not None
    assert "500" in result.error


# ---------------------------------------------------------------------------
# 6. Image WebP detection
# ---------------------------------------------------------------------------


@respx.mock
async def test_wp_upload_image_webp() -> None:
    """WebP image bytes (RIFF header) -> Content-Type: image/webp in upload."""
    webp_bytes = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 50

    media_route = respx.post(f"{_WP_BASE}/media").mock(
        return_value=httpx.Response(201, json={"id": 101}),
    )
    # Alt text update on the uploaded media
    respx.post(f"{_WP_BASE}/media/101").mock(
        return_value=httpx.Response(200, json={"id": 101}),
    )
    respx.post(f"{_WP_BASE}/posts").mock(
        return_value=httpx.Response(201, json={"id": 60, "link": "https://blog.example.com/p/"}),
    )

    req = _make_request(images=[webp_bytes], images_meta=[{"filename": "test-img", "alt": "test"}])

    async with httpx.AsyncClient() as client:
        publisher = WordPressPublisher(client)
        result = await publisher.publish(req)

    assert result.success is True
    # Verify Content-Type header on media upload
    upload_request = media_route.calls[0].request
    assert upload_request.headers["Content-Type"] == "image/webp"


# ---------------------------------------------------------------------------
# 7. Alt text in image upload
# ---------------------------------------------------------------------------


@respx.mock
async def test_wp_sets_alt_text() -> None:
    """Image upload includes alt_text from images_meta via separate POST to /media/{id}."""
    png_bytes = b"\x89PNG" + b"\x00" * 50  # not WebP (no RIFF header)

    respx.post(f"{_WP_BASE}/media").mock(
        return_value=httpx.Response(201, json={"id": 200}),
    )
    alt_update_route = respx.post(f"{_WP_BASE}/media/200").mock(
        return_value=httpx.Response(200, json={"id": 200}),
    )
    respx.post(f"{_WP_BASE}/posts").mock(
        return_value=httpx.Response(201, json={"id": 70, "link": "https://blog.example.com/p/"}),
    )

    meta = [{"filename": "product-photo", "alt": "Premium SEO tool screenshot", "figcaption": "Our tool in action"}]
    req = _make_request(images=[png_bytes], images_meta=meta)

    async with httpx.AsyncClient() as client:
        publisher = WordPressPublisher(client)
        result = await publisher.publish(req)

    assert result.success is True

    # Verify alt_text update was called with correct data
    assert alt_update_route.call_count == 1
    alt_body = json.loads(alt_update_route.calls[0].request.content)
    assert alt_body["alt_text"] == "Premium SEO tool screenshot"
    assert alt_body["caption"] == "Our tool in action"


# ---------------------------------------------------------------------------
# 8. Validate connection (auth check)
# ---------------------------------------------------------------------------


@respx.mock
async def test_wp_validate_connection_success() -> None:
    """GET /wp-json/wp/v2/users/me returns 200 -> validate returns True."""
    respx.get(f"{_WP_BASE}/users/me").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "admin"}),
    )

    connection = _make_connection()
    async with httpx.AsyncClient() as client:
        publisher = WordPressPublisher(client)
        valid = await publisher.validate_connection(connection)

    assert valid is True


@respx.mock
async def test_wp_validate_connection_failure() -> None:
    """GET /wp-json/wp/v2/users/me returns 401 -> validate returns False."""
    respx.get(f"{_WP_BASE}/users/me").mock(
        return_value=httpx.Response(401, json={"code": "rest_not_logged_in"}),
    )

    connection = _make_connection()
    async with httpx.AsyncClient() as client:
        publisher = WordPressPublisher(client)
        valid = await publisher.validate_connection(connection)

    assert valid is False
