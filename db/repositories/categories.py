"""Repository for categories table."""

from typing import Any

from db.models import (
    Category,
    CategoryCreate,
    CategoryUpdate,
)
from db.repositories.base import BaseRepository

_TABLE = "categories"


class CategoriesRepository(BaseRepository):
    """CRUD operations for categories table."""

    # --- categories ---

    async def get_by_id(self, category_id: int) -> Category | None:
        """Get category by ID."""
        resp = await self._table(_TABLE).select("*").eq("id", category_id).maybe_single().execute()
        row = self._single(resp)
        return Category(**row) if row else None

    async def get_by_project(self, project_id: int) -> list[Category]:
        """Get all categories for a project, ordered by name."""
        resp = await self._table(_TABLE).select("*").eq("project_id", project_id).order("name").execute()
        return [Category(**row) for row in self._rows(resp)]

    async def get_by_projects(self, project_ids: list[int]) -> list[Category]:
        """Get all categories for multiple projects in a single query (C20: batch).

        Returns categories ordered by project_id, then name.
        """
        if not project_ids:
            return []
        resp = (
            await self._table(_TABLE)
            .select("*")
            .in_("project_id", project_ids)
            .order("project_id")
            .order("name")
            .execute()
        )
        return [Category(**row) for row in self._rows(resp)]

    async def get_count_by_project(self, project_id: int) -> int:
        """Count categories in a project."""
        resp = (
            await self._table(_TABLE)
            .select("id", count="exact")  # type: ignore[arg-type]
            .eq("project_id", project_id)
            .execute()
        )
        return self._count(resp)

    async def create(self, data: CategoryCreate) -> Category:
        """Create a new category."""
        resp = await self._table(_TABLE).insert(data.model_dump()).execute()
        row = self._require_first(resp)
        return Category(**row)

    async def update(self, category_id: int, data: CategoryUpdate) -> Category | None:
        """Partial update. Returns None if not found."""
        payload = data.model_dump(exclude_none=True, mode="json")
        if not payload:
            return await self.get_by_id(category_id)
        resp = await self._table(_TABLE).update(payload).eq("id", category_id).execute()
        row = self._first(resp)
        return Category(**row) if row else None

    async def delete(self, category_id: int) -> bool:
        """Delete category. Service must cancel QStash schedules BEFORE calling this (E24)."""
        resp = await self._table(_TABLE).delete().eq("id", category_id).execute()
        return len(self._rows(resp)) > 0

    async def clear_prices(self, category_id: int) -> Category | None:
        """Set prices to NULL. Separate from update() which uses exclude_none."""
        resp = await self._table(_TABLE).update({"prices": None}).eq("id", category_id).execute()
        row = self._first(resp)
        return Category(**row) if row else None

    async def clear_description(self, category_id: int) -> Category | None:
        """Set description to NULL. Separate from update() which uses exclude_none."""
        resp = await self._table(_TABLE).update({"description": None}).eq("id", category_id).execute()
        row = self._first(resp)
        return Category(**row) if row else None

    async def update_keywords(self, category_id: int, keywords: list[dict[str, Any]]) -> Category | None:
        """Replace keywords JSONB array."""
        resp = await self._table(_TABLE).update({"keywords": keywords}).eq("id", category_id).execute()
        row = self._first(resp)
        return Category(**row) if row else None

    async def update_media(self, category_id: int, media: list[dict[str, Any]]) -> Category | None:
        """Replace media JSONB array."""
        resp = await self._table(_TABLE).update({"media": media}).eq("id", category_id).execute()
        row = self._first(resp)
        return Category(**row) if row else None

    async def update_reviews(self, category_id: int, reviews: list[dict[str, Any]]) -> Category | None:
        """Replace reviews JSONB array."""
        resp = await self._table(_TABLE).update({"reviews": reviews}).eq("id", category_id).execute()
        row = self._first(resp)
        return Category(**row) if row else None

