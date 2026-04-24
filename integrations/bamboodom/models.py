"""Pydantic response models for Bamboodom API v1.1."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KeyTestResponse(BaseModel):
    """Response shape of `blog_key_test` endpoint (v1.1 + v1.2).

    Fields documented in API_V1_1_CHANGELOG.md + BLOG_API_V1.2_NOTES.md.
    All fields beyond `ok` are optional to stay forward-compatible.
    v1.2 adds `limits` and `defensive_layer` blocks — useful for smoke-check
    after deploy to confirm the expected server version is live.
    """

    model_config = ConfigDict(extra="allow")

    ok: bool
    version: str | None = None
    endpoints: list[str] = []
    writable: bool | None = None
    image_dir_writable: bool | None = None

    # v1.2 — added 2026-04-24. Inspect via extras if more fields appear.
    limits: dict[str, Any] | None = None
    defensive_layer: dict[str, Any] | None = None


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


class PublishWarning(BaseModel):
    """Entry in `blog_publish.warnings` (v1.2 defensive layer).

    Signals that the server accepted the article but detected a soft issue:
    unknown articles in text, denylist phrase matches, SEO meta issues, or
    draft forcing. Shown to the operator in UI — NOT a hard block.
    """

    model_config = ConfigDict(extra="allow")

    code: str
    hint: str | None = None
    category: str | None = None  # for denylist_matches
    items: list[dict[str, Any]] = []


class PublishResponse(BaseModel):
    """Response shape of `blog_publish` endpoint (v1.1 + v1.2 defensive layer).

    v1.2 fields (all optional for backward compat — servers <v1.2 omit them):
    - draft: final draft state (may differ from requested value)
    - draft_forced: True if bot-key was silently downgraded to draft
    - warnings: soft issues the operator should review
    - size_kb: article JSON size after processing
    - sandbox: whether the request hit the sandbox store
    """

    model_config = ConfigDict(extra="allow")

    ok: bool
    slug: str | None = None
    url: str | None = None
    action_type: str | None = None  # "created" or "updated"
    blocks_parsed: int | None = None
    blocks_dropped: list[BlockDropped] = []

    # v1.2 defensive layer — added 2026-04-24 per BLOG_API_V1.2_NOTES.md
    draft: bool | None = None
    draft_forced: bool | None = None
    warnings: list[PublishWarning] = []
    size_kb: int | None = None
    sandbox: bool | None = None
