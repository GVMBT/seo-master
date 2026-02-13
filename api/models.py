"""Pydantic v2 models for QStash webhook payloads."""

from typing import Literal

from pydantic import BaseModel


class PublishPayload(BaseModel):
    """QStash auto-publish webhook payload."""

    schedule_id: int
    category_id: int
    connection_id: int
    platform_type: str
    user_id: int
    project_id: int
    idempotency_key: str = ""


class CleanupPayload(BaseModel):
    """QStash daily cleanup webhook payload."""

    action: Literal["cleanup"] = "cleanup"
    idempotency_key: str = ""


class NotifyPayload(BaseModel):
    """QStash notifications webhook payload."""

    action: Literal["notify"] = "notify"
    type: Literal["low_balance", "weekly_digest", "reactivation"]
    idempotency_key: str = ""
