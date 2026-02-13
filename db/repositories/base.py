"""Base repository with shared DB access and typed response helpers."""

from typing import Any

from postgrest import AsyncRequestBuilder

from bot.exceptions import AppError
from db.client import SupabaseClient


class BaseRepository:
    """Base class for all repositories. Provides table access via SupabaseClient.

    Includes typed helpers to safely extract data from PostgREST responses,
    centralizing type: ignore comments for postgrest's loose union types.
    """

    def __init__(self, db: SupabaseClient) -> None:
        self._db = db

    def _table(self, name: str) -> AsyncRequestBuilder:
        """Return a PostgREST request builder for the given table."""
        return self._db.table(name)

    @staticmethod
    def _single(resp: Any) -> dict[str, Any] | None:
        """Extract single row dict from maybe_single() response."""
        if resp is None:
            return None
        return resp.data if resp.data else None  # type: ignore[no-any-return]

    @staticmethod
    def _rows(resp: Any) -> list[dict[str, Any]]:
        """Extract list of row dicts from response."""
        return resp.data if resp.data is not None else []  # type: ignore[no-any-return]

    @staticmethod
    def _first(resp: Any) -> dict[str, Any] | None:
        """Extract first row from insert/update/upsert/delete response."""
        if resp.data:
            return resp.data[0]  # type: ignore[no-any-return]
        return None

    @staticmethod
    def _require_first(resp: Any) -> dict[str, Any]:
        """Extract first row from insert response. Raises AppError if empty."""
        if resp.data:
            return resp.data[0]  # type: ignore[no-any-return]
        raise AppError("Database insert returned no data")

    @staticmethod
    def _count(resp: Any) -> int:
        """Extract count from count query response."""
        return resp.count or 0  # type: ignore[no-any-return]
