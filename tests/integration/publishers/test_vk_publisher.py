"""Integration tests for VKPublisher (VK API v5.199).

Uses `respx` to mock httpx calls to the VK API.
The VK publisher uses a 3-step photo upload flow:
  1. photos.getWallUploadServer -> upload_url
  2. Upload file to upload_url
  3. photos.saveWallPhoto -> photo attachment
  4. wall.post with attachments
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from db.models import PlatformConnection
from services.publishers.base import PublishRequest, PublishResult
from services.publishers.vk import VKPublisher

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_VK_API = "https://api.vk.com/method"
_VK_TOKEN = "vk1.a.fake_access_token_for_testing"
_GROUP_ID = "12345"

_VK_CREDS = {
    "access_token": _VK_TOKEN,
    "group_id": _GROUP_ID,
}


def _make_connection(creds: dict[str, str] | None = None) -> PlatformConnection:
    """Build a PlatformConnection with VK credentials."""
    return PlatformConnection(
        id=300,
        project_id=1,
        platform_type="vk",
        status="active",
        credentials=creds or _VK_CREDS,
        metadata={},
        identifier=_GROUP_ID,
    )


def _make_request(
    content: str = "Test VK post content",
    images: list[bytes] | None = None,
    connection: PlatformConnection | None = None,
) -> PublishRequest:
    return PublishRequest(
        connection=connection or _make_connection(),
        content=content,
        content_type="plain_text",
        images=images or [],
    )


# ---------------------------------------------------------------------------
# 1. Wall post (text only)
# ---------------------------------------------------------------------------


@respx.mock
async def test_vk_publish_wall_post() -> None:
    """Post text to VK wall via wall.post."""
    wall_route = respx.post(f"{_VK_API}/wall.post").mock(
        return_value=httpx.Response(
            200,
            json={"response": {"post_id": 777}},
        ),
    )

    async with httpx.AsyncClient() as client:
        publisher = VKPublisher(client)
        result = await publisher.publish(_make_request(content="Hello from SEO Master Bot"))

    assert result.success is True
    assert result.platform_post_id == "777"
    assert result.post_url == f"https://vk.com/wall-{_GROUP_ID}_777"

    # Verify wall.post was called with correct data
    assert wall_route.call_count == 1
    # Request body is form-encoded
    request_body = wall_route.calls[0].request.content.decode()
    assert f"owner_id=-{_GROUP_ID}" in request_body
    assert "Hello+from+SEO+Master+Bot" in request_body or "Hello" in request_body


# ---------------------------------------------------------------------------
# 2. Wall post with image (3-step upload)
# ---------------------------------------------------------------------------


@respx.mock
async def test_vk_publish_with_image() -> None:
    """Upload photo (3-step) then post with attachment.

    Steps:
    1. photos.getWallUploadServer -> upload_url
    2. POST to upload_url -> photo, server, hash
    3. photos.saveWallPhoto -> photo attachment
    4. wall.post with attachments=photo{owner_id}_{id}
    """
    upload_url = "https://upload.vk.com/photos?upload_server=12345"

    # Step 1: get upload server
    respx.post(f"{_VK_API}/photos.getWallUploadServer").mock(
        return_value=httpx.Response(
            200,
            json={"response": {"upload_url": upload_url}},
        ),
    )

    # Step 2: upload file to VK upload server
    respx.post(upload_url).mock(
        return_value=httpx.Response(
            200,
            json={"photo": "uploaded_photo_data", "server": 12345, "hash": "abc123"},
        ),
    )

    # Step 3: save photo
    respx.post(f"{_VK_API}/photos.saveWallPhoto").mock(
        return_value=httpx.Response(
            200,
            json={"response": [{"id": 456789, "owner_id": -int(_GROUP_ID)}]},
        ),
    )

    # Step 4: wall.post
    wall_route = respx.post(f"{_VK_API}/wall.post").mock(
        return_value=httpx.Response(
            200,
            json={"response": {"post_id": 888}},
        ),
    )

    image_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    async with httpx.AsyncClient() as client:
        publisher = VKPublisher(client)
        result = await publisher.publish(_make_request(images=[image_data]))

    assert result.success is True
    assert result.platform_post_id == "888"

    # Verify wall.post included the photo attachment
    request_body = wall_route.calls[0].request.content.decode()
    assert f"photo-{_GROUP_ID}_456789" in request_body


# ---------------------------------------------------------------------------
# 3. Token expired / invalid token
# ---------------------------------------------------------------------------


@respx.mock
async def test_vk_publish_token_expired() -> None:
    """VK returns error 5 (auth failed) -> PublishResult with success=False."""
    respx.post(f"{_VK_API}/wall.post").mock(
        return_value=httpx.Response(
            200,
            json={
                "error": {
                    "error_code": 5,
                    "error_msg": "User authorization failed: invalid access_token.",
                },
            },
        ),
    )

    async with httpx.AsyncClient() as client:
        publisher = VKPublisher(client)
        result = await publisher.publish(_make_request())

    assert result.success is False
    assert result.error is not None
    assert "authorization" in result.error.lower() or "error 5" in result.error.lower()


# ---------------------------------------------------------------------------
# 4. Rate limited (VK error 6: Too many requests per second)
# ---------------------------------------------------------------------------


@respx.mock
async def test_vk_publish_rate_limited() -> None:
    """VK returns error 6 (rate limit) -> PublishResult with success=False."""
    respx.post(f"{_VK_API}/wall.post").mock(
        return_value=httpx.Response(
            200,
            json={
                "error": {
                    "error_code": 6,
                    "error_msg": "Too many requests per second.",
                },
            },
        ),
    )

    async with httpx.AsyncClient() as client:
        publisher = VKPublisher(client)
        result = await publisher.publish(_make_request())

    assert result.success is False
    assert result.error is not None
    assert "too many" in result.error.lower() or "error 6" in result.error.lower()
