"""Cleanup service — expired preview refund, old log deletion.

Triggered by QStash daily cron. Zero Telegram deps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from db.client import SupabaseClient
from db.repositories.previews import PreviewsRepository
from db.repositories.publications import PublicationsRepository
from db.repositories.users import UsersRepository
from services.external.telegraph import TelegraphClient
from services.storage import ImageStorage
from services.tokens import TokenService

log = structlog.get_logger()

_LOG_RETENTION_DAYS = 90


@dataclass
class CleanupResult:
    """Result of cleanup execution."""

    expired_count: int = 0
    refunded: list[dict[str, Any]] = field(default_factory=list)
    logs_deleted: int = 0
    images_deleted: int = 0


class CleanupService:
    """Daily cleanup: expire drafts, refund tokens, delete old logs."""

    def __init__(
        self,
        db: SupabaseClient,
        http_client: httpx.AsyncClient,
        image_storage: ImageStorage,
        admin_ids: list[int],
    ) -> None:
        self._db = db
        self._http_client = http_client
        self._previews = PreviewsRepository(db)
        self._image_storage = image_storage
        self._tokens = TokenService(db, admin_ids)

    async def execute(self) -> CleanupResult:
        """Run full cleanup pipeline."""
        result = CleanupResult()

        # 1. Expire draft previews and refund tokens
        await self._expire_previews(result)

        # 2. Delete old publication logs (>90 days)
        await self._delete_old_logs(result)

        log.info(
            "cleanup_complete",
            expired=result.expired_count,
            refunds=len(result.refunded),
            logs_deleted=result.logs_deleted,
        )
        return result

    async def _expire_previews(self, result: CleanupResult) -> None:
        """Find expired draft previews, refund tokens, clean images."""
        expired_drafts = await self._previews.get_expired_drafts()

        for preview in expired_drafts:
            try:
                # Atomic mark as expired (prevents double-processing)
                marked = await self._previews.atomic_mark_expired(preview.id)
                if not marked:
                    continue  # Already processed by concurrent worker

                result.expired_count += 1

                # Refund tokens if charged
                tokens = preview.tokens_charged or 0
                if tokens > 0:
                    await self._tokens.refund(
                        preview.user_id,
                        tokens,
                        reason="preview_expired",
                        description=f"Expired preview: {preview.keyword or 'unknown'}",
                    )
                    # Load user to check notify preference (refund = balance notification)
                    user = await UsersRepository(self._db).get_by_id(preview.user_id)
                    result.refunded.append(
                        {
                            "user_id": preview.user_id,
                            "keyword": preview.keyword or "",
                            "tokens_refunded": tokens,
                            "notify_balance": user.notify_balance if user else True,
                        }
                    )

                # Clean up storage images
                if preview.images:
                    paths = [img.get("storage_path", "") for img in preview.images if img.get("storage_path")]
                    if paths:
                        deleted = await self._image_storage.cleanup_by_paths(paths)
                        result.images_deleted += deleted

                # Delete Telegraph page
                if preview.telegraph_path:
                    try:
                        telegraph = TelegraphClient(self._http_client)
                        await telegraph.delete_page(preview.telegraph_path)
                    except Exception:
                        log.warning("telegraph_delete_failed", path=preview.telegraph_path)

            except Exception:
                log.exception("cleanup_preview_error", preview_id=preview.id)

    async def _delete_old_logs(self, result: CleanupResult) -> None:
        """Delete publication_logs older than 90 days."""
        cutoff = (datetime.now(tz=UTC) - timedelta(days=_LOG_RETENTION_DAYS)).isoformat()
        try:
            result.logs_deleted = await PublicationsRepository(self._db).delete_old_logs(cutoff)
        except Exception:
            log.exception("cleanup_old_logs_failed")
