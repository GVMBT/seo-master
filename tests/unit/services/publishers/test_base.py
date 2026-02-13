"""Tests for services/publishers/base.py — PublishRequest, PublishResult dataclasses."""

from __future__ import annotations

from db.models import Category, PlatformConnection
from services.publishers.base import BasePublisher, PublishRequest, PublishResult

# ---------------------------------------------------------------------------
# PublishRequest
# ---------------------------------------------------------------------------


class TestPublishRequest:
    def _make_connection(self) -> PlatformConnection:
        return PlatformConnection(
            id=1,
            project_id=1,
            platform_type="wordpress",
            identifier="example.com",
            credentials={"url": "https://example.com", "login": "admin", "app_password": "xxxx"},
        )

    def test_create_minimal(self) -> None:
        conn = self._make_connection()
        req = PublishRequest(connection=conn, content="Hello", content_type="html")
        assert req.connection is conn
        assert req.content == "Hello"
        assert req.content_type == "html"
        assert req.images == []
        assert req.title is None
        assert req.category is None
        assert req.metadata == {}

    def test_create_with_all_fields(self) -> None:
        conn = self._make_connection()
        cat = Category(id=10, project_id=1, name="Test")
        img_data = b"PNG_DATA"
        req = PublishRequest(
            connection=conn,
            content="<h1>Article</h1>",
            content_type="html",
            images=[img_data],
            title="My Article",
            category=cat,
            metadata={"seo_title": "SEO Title"},
        )
        assert req.title == "My Article"
        assert req.category is cat
        assert req.images == [img_data]
        assert req.metadata["seo_title"] == "SEO Title"

    def test_frozen_immutable(self) -> None:
        conn = self._make_connection()
        req = PublishRequest(connection=conn, content="Hello", content_type="html")
        try:
            req.content = "Changed"  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")
        except AttributeError:
            pass

    def test_content_type_variants(self) -> None:
        conn = self._make_connection()
        for ct in ("html", "telegram_html", "plain_text", "pin_text"):
            req = PublishRequest(connection=conn, content="x", content_type=ct)
            assert req.content_type == ct

    def test_default_images_list_independence(self) -> None:
        """Each instance gets its own default list."""
        conn = self._make_connection()
        req1 = PublishRequest(connection=conn, content="a", content_type="html")
        req2 = PublishRequest(connection=conn, content="b", content_type="html")
        assert req1.images is not req2.images


# ---------------------------------------------------------------------------
# PublishResult
# ---------------------------------------------------------------------------


class TestPublishResult:
    def test_success_result(self) -> None:
        result = PublishResult(
            success=True,
            post_url="https://example.com/post/1",
            platform_post_id="1",
        )
        assert result.success is True
        assert result.post_url == "https://example.com/post/1"
        assert result.platform_post_id == "1"
        assert result.error is None

    def test_failure_result(self) -> None:
        result = PublishResult(success=False, error="Connection refused")
        assert result.success is False
        assert result.post_url is None
        assert result.platform_post_id is None
        assert result.error == "Connection refused"

    def test_defaults(self) -> None:
        result = PublishResult(success=True)
        assert result.post_url is None
        assert result.platform_post_id is None
        assert result.error is None

    def test_frozen_immutable(self) -> None:
        result = PublishResult(success=True)
        try:
            result.success = False  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")
        except AttributeError:
            pass


# ---------------------------------------------------------------------------
# BasePublisher is abstract
# ---------------------------------------------------------------------------


class TestBasePublisherAbstract:
    def test_cannot_instantiate_directly(self) -> None:
        try:
            BasePublisher()  # type: ignore[abstract]
            raise AssertionError("Should have raised TypeError")
        except TypeError:
            pass
