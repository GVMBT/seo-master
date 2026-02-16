"""Base publisher interface and data models.

Source of truth: docs/API_CONTRACTS.md section 3.2.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from db.models import Category, PlatformConnection


@dataclass(frozen=True, slots=True)
class PublishRequest:
    """Input data for publishing content to a platform."""

    connection: PlatformConnection
    content: str
    content_type: Literal["html", "telegram_html", "plain_text", "pin_text"]
    images: list[bytes] = field(default_factory=list)
    images_meta: list[dict[str, str]] = field(default_factory=list)
    title: str | None = None
    category: Category | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PublishResult:
    """Result of a publish operation."""

    success: bool
    post_url: str | None = None
    platform_post_id: str | None = None
    error: str | None = None


class BasePublisher(ABC):
    """Abstract base for all platform publishers."""

    @abstractmethod
    async def validate_connection(self, connection: PlatformConnection) -> bool:
        """Check that the connection credentials are valid."""
        ...

    @abstractmethod
    async def publish(self, request: PublishRequest) -> PublishResult:
        """Publish content to the platform."""
        ...

    @abstractmethod
    async def delete_post(self, connection: PlatformConnection, post_id: str) -> bool:
        """Delete a previously published post. Returns True on success."""
        ...
