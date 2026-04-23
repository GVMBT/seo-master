"""Pydantic response models for Bamboodom API v1.1."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KeyTestResponse(BaseModel):
    """Response shape of `blog_key_test` endpoint (v1.1).

    Fields documented in API_V1_1_CHANGELOG.md. All fields beyond `ok` are
    optional to stay forward-compatible if the server adds/removes keys.
    """

    model_config = ConfigDict(extra="allow")

    ok: bool
    version: str | None = None
    endpoints: list[str] = []
    writable: bool | None = None
    image_dir_writable: bool | None = None


class MaterialEntry(BaseModel):
    """One entry in `blog_context.materials`."""

    model_config = ConfigDict(extra="allow")

    slug: str
    name: str
    description: str | None = None
    applications: list[str] = []
    url: str | None = None
    series_count: int | None = None
    articles_count: int | None = None


class CompanyInfo(BaseModel):
    """`blog_context.company` block."""

    model_config = ConfigDict(extra="allow")

    name: str | None = None
    tagline: str | None = None
    domain: str | None = None
    location: str | None = None
    about: str | None = None


class ContextResponse(BaseModel):
    """Response shape of `blog_context` endpoint (v1.1)."""

    model_config = ConfigDict(extra="allow")

    ok: bool
    version: str | None = None
    cache_key: str | None = None
    company: CompanyInfo = Field(default_factory=CompanyInfo)
    materials: list[MaterialEntry] = []
    typical_contexts: list[str] = []
    cta_links: dict[str, Any] = Field(default_factory=dict)
    forbidden_claims: list[str] = []
    updated_at: str | None = None


class ArticleCodesResponse(BaseModel):
    """Response shape of `blog_article_codes` endpoint (v1.1).

    Contains per-category lists plus total count. Uses `extra="allow"` so new
    material groups appear automatically without a client update.
    """

    model_config = ConfigDict(extra="allow")

    ok: bool
    version: str | None = None
    cache_key: str | None = None
    total: int | None = None
    updated_at: str | None = None
    wpc: list[str] = []
    flex: list[str] = []
    reiki: list[str] = []
    profiles: list[str] = []

    def categories(self) -> dict[str, int]:
        """Return {category_name: count} for all list fields present in response.

        Scans `extra` fields for new categories added by the server post-release.
        """
        known = {"wpc": len(self.wpc), "flex": len(self.flex), "reiki": len(self.reiki), "profiles": len(self.profiles)}
        extras = getattr(self, "__pydantic_extra__", None) or {}
        for k, v in extras.items():
            if isinstance(v, list) and all(isinstance(x, str) for x in v):
                known[k] = len(v)
        return known


class BlockDropped(BaseModel):
    """Entry in `blog_publish.blocks_dropped` — explains why a block was filtered out.

    Server-side validation rejects:
    - product blocks with unknown article code → reason='article_not_found'
    - blocks with invalid type (not in the 15-type allowlist) → reason='invalid_type'
    """

    model_config = ConfigDict(extra="allow")

    index: int | None = None
    type: str | None = None
    reason: str | None = None
    article: str | None = None
    raw_type: str | None = None


class PublishResponse(BaseModel):
    """Response shape of `blog_publish` endpoint (v1.1)."""

    model_config = ConfigDict(extra="allow")

    ok: bool
    slug: str | None = None
    url: str | None = None
    action_type: str | None = None  # "created" or "updated"
    blocks_parsed: int | None = None
    blocks_dropped: list[BlockDropped] = []
