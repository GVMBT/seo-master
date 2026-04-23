"""Pydantic response models for Bamboodom API v1.1."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


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
