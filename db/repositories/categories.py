"""Repository for categories and platform_content_overrides tables."""

from typing import Any

from db.models import (
    Category,
    CategoryCreate,
    CategoryUpdate,
    PlatformContentOverride,
    PlatformContentOverrideCreate,
    PlatformContentOverrideUpdate,
)
from db.repositories.base import BaseRepository

_TABLE = "categories"
_OVERRIDES_TABLE = "platform_content_overrides"


class CategoriesRepository(BaseRepository):
    """CRUD operations for categories + content settings inheritance (F41)."""

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

    async def create(self, data: CategoryCreate) -> Category:
        """Create a new category."""
        resp = await self._table(_TABLE).insert(data.model_dump()).execute()
        row = self._require_first(resp)
        return Category(**row)

    async def update(self, category_id: int, data: CategoryUpdate) -> Category | None:
        """Partial update. Returns None if not found."""
        payload = data.model_dump(exclude_none=True)
        if not payload:
            return await self.get_by_id(category_id)
        resp = await self._table(_TABLE).update(payload).eq("id", category_id).execute()
        row = self._first(resp)
        return Category(**row) if row else None

    async def delete(self, category_id: int) -> bool:
        """Delete category. Service must cancel QStash schedules BEFORE calling this (E24)."""
        resp = await self._table(_TABLE).delete().eq("id", category_id).execute()
        return len(self._rows(resp)) > 0

    async def update_description(self, category_id: int, description: str) -> Category | None:
        """Update category description text."""
        resp = await self._table(_TABLE).update({"description": description}).eq("id", category_id).execute()
        row = self._first(resp)
        return Category(**row) if row else None

    async def update_prices(self, category_id: int, prices: str) -> Category | None:
        """Update category prices text."""
        resp = await self._table(_TABLE).update({"prices": prices}).eq("id", category_id).execute()
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

    # --- platform_content_overrides (F41 settings inheritance) ---

    async def get_override(self, category_id: int, platform_type: str) -> PlatformContentOverride | None:
        """Get platform-specific override for a category."""
        resp = (
            await self._table(_OVERRIDES_TABLE)
            .select("*")
            .eq("category_id", category_id)
            .eq("platform_type", platform_type)
            .maybe_single()
            .execute()
        )
        row = self._single(resp)
        return PlatformContentOverride(**row) if row else None

    async def upsert_override(self, data: PlatformContentOverrideCreate) -> PlatformContentOverride:
        """Create or update platform content override."""
        resp = (
            await self._table(_OVERRIDES_TABLE)
            .upsert(data.model_dump(), on_conflict="category_id,platform_type")
            .execute()
        )
        row = self._require_first(resp)
        return PlatformContentOverride(**row)

    async def update_override(
        self, override_id: int, data: PlatformContentOverrideUpdate
    ) -> PlatformContentOverride | None:
        """Update existing override."""
        payload = data.model_dump(exclude_none=True)
        if not payload:
            return None
        resp = await self._table(_OVERRIDES_TABLE).update(payload).eq("id", override_id).execute()
        row = self._first(resp)
        return PlatformContentOverride(**row) if row else None

    async def delete_override(self, override_id: int) -> bool:
        """Delete platform content override."""
        resp = await self._table(_OVERRIDES_TABLE).delete().eq("id", override_id).execute()
        return len(self._rows(resp)) > 0

    async def get_content_settings(self, category_id: int, platform_type: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Get merged content settings (image_settings, text_settings).

        Override field None -> inherit from category. Category field {} -> service applies defaults.
        """
        category = await self.get_by_id(category_id)
        if category is None:
            return {}, {}

        override = await self.get_override(category_id, platform_type)

        image_settings = category.image_settings
        text_settings = category.text_settings

        if override is not None:
            if override.image_settings is not None:
                image_settings = override.image_settings
            if override.text_settings is not None:
                text_settings = override.text_settings

        return image_settings, text_settings
