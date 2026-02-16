"""Readiness check service for article/post generation pipeline.

Checks whether a category has all the data enrichers filled in
(keywords, description, prices, media) and returns a structured
checklist for the pipeline UI (PIPELINE_UX_PROPOSAL.md section 4.1, step 4).

Zero dependencies on Telegram/Aiogram (services/ pattern).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from bot.exceptions import AppError
from db.client import SupabaseClient
from db.repositories.categories import CategoriesRepository
from services.tokens import COST_DESCRIPTION, COST_PER_IMAGE, estimate_keywords_cost

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReadinessItem:
    """Single checklist item for the readiness screen."""

    key: str  # "keywords", "description", "prices", "media"
    label: str  # Human-readable label (Russian)
    hint: str  # Short hint why this matters
    ready: bool  # True if already filled
    cost: int  # Token cost to fill (0 if free or already filled)


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    """Aggregated readiness check result for a category."""

    items: list[ReadinessItem] = field(default_factory=list)

    @property
    def all_ready(self) -> bool:
        """True if every checklist item is filled."""
        return all(item.ready for item in self.items)

    @property
    def required_missing(self) -> list[str]:
        """Keys of missing REQUIRED items.

        Per spec, ALL items are optional (enrichers, not blockers).
        Always returns an empty list.
        """
        return []

    @property
    def optional_missing(self) -> list[str]:
        """Keys of optional items that are not yet filled."""
        return [item.key for item in self.items if not item.ready]


# ---------------------------------------------------------------------------
# Default keyword quantity for cost estimation
# ---------------------------------------------------------------------------

_DEFAULT_KEYWORD_QUANTITY = 100

# Default image count for WP articles (ARCHITECTURE.md §3.2, WP override = 4)
_DEFAULT_IMAGE_COUNT = 4

# User-friendly labels for image styles (ARCHITECTURE.md IMAGE_DEFAULTS)
IMAGE_STYLE_LABELS: dict[str, str] = {
    "Фотореализм": "Фотореализм",
    "medical": "Медицина",
    "legal": "Юриспруденция",
    "finance": "Финансы",
    "realestate": "Недвижимость",
    "food": "Еда",
    "beauty": "Красота",
    "construction": "Строительство",
    "auto": "Авто",
}

# Allowed image counts for pipeline UI
ALLOWED_IMAGE_COUNTS: list[int] = [0, 2, 4, 6]


def _format_images_hint(configured: bool, count: int, img_settings: dict[str, object]) -> str:
    """Build human-readable hint for the images checklist item."""
    if not configured:
        return "выберите кол-во и стиль"
    raw_styles = img_settings.get("styles", [])
    styles: list[str] = list(raw_styles) if isinstance(raw_styles, list) else []
    style_label = IMAGE_STYLE_LABELS.get(styles[0], styles[0]) if styles else "Фотореализм"
    if count == 0:
        return "без изображений"
    return f"{count} шт., {style_label}"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ReadinessService:
    """Check readiness for article generation (pipeline step 4).

    Inspects category data (keywords, description, prices, media)
    and returns a structured checklist with labels, hints, and costs.
    """

    def __init__(self, db: SupabaseClient) -> None:
        self._db = db
        self._categories = CategoriesRepository(db)

    async def check(self, category_id: int, project_id: int) -> ReadinessResult:
        """Check readiness for article generation.

        Args:
            category_id: Target category ID.
            project_id: Owning project ID (for logging/context).

        Returns:
            ReadinessResult with items list and convenience properties.

        Raises:
            AppError: If category is not found.
        """
        category = await self._categories.get_by_id(category_id)
        if category is None:
            raise AppError(
                message=f"Category {category_id} not found",
                user_message="Категория не найдена",
            )

        has_keywords = bool(category.keywords)
        has_description = bool(category.description)
        has_prices = bool(category.prices)

        # Image settings: configured = user explicitly set count+style
        img_settings = category.image_settings or {}
        has_images = bool(img_settings.get("count") is not None and img_settings.get("styles"))
        image_count = img_settings.get("count", _DEFAULT_IMAGE_COUNT)
        image_cost = image_count * COST_PER_IMAGE

        items: list[ReadinessItem] = [
            ReadinessItem(
                key="keywords",
                label="Ключевые фразы",
                hint="SEO-оптимизация",
                ready=has_keywords,
                cost=0 if has_keywords else estimate_keywords_cost(_DEFAULT_KEYWORD_QUANTITY),
            ),
            ReadinessItem(
                key="description",
                label="Описание компании",
                hint="точность контекста",
                ready=has_description,
                cost=0 if has_description else COST_DESCRIPTION,
            ),
            ReadinessItem(
                key="prices",
                label="Цены",
                hint="реальные цены в статье",
                ready=has_prices,
                cost=0,  # free manual input
            ),
            ReadinessItem(
                key="images",
                label="Фото",
                hint=_format_images_hint(has_images, image_count, img_settings),
                ready=has_images,
                cost=image_cost,
            ),
        ]

        result = ReadinessResult(items=items)

        log.info(
            "readiness_checked",
            category_id=category_id,
            project_id=project_id,
            all_ready=result.all_ready,
            optional_missing=result.optional_missing,
        )

        return result
