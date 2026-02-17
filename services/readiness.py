"""ReadinessService — pipeline readiness check (UX_PIPELINE.md §10.2).

Checks what data is available for article/social generation
and reports missing items. Zero Telegram/Aiogram dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from db.client import SupabaseClient
from db.repositories.categories import CategoriesRepository
from db.repositories.publications import PublicationsRepository
from services.tokens import estimate_article_cost

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# ReadinessReport (UX_PIPELINE.md §10.2)
# ---------------------------------------------------------------------------


@dataclass
class ReadinessReport:
    """Readiness check result for pipeline step 4."""

    has_keywords: bool
    keyword_count: int
    cluster_count: int
    has_description: bool
    has_prices: bool
    image_count: int  # current AI image count (default 4)
    estimated_cost: int  # total tokens
    user_balance: int
    is_sufficient_balance: bool
    publication_count: int  # user's total publications (for progressive readiness)
    missing_items: list[str] = field(default_factory=list)

    @property
    def all_filled(self) -> bool:
        """If all required items filled -- readiness check screen is skipped.

        Required: keywords + description.
        Prices and images are optional (never block).
        """
        return self.has_keywords and self.has_description

    @property
    def has_blockers(self) -> bool:
        """Keywords are the only hard blocker for generation."""
        return not self.has_keywords


# ---------------------------------------------------------------------------
# ReadinessService
# ---------------------------------------------------------------------------


class ReadinessService:
    """Checks category readiness for article generation.

    Progressive readiness (UX_PIPELINE.md §4.4):
    - 0 publications:  show keywords (required) + description
    - 2-5 publications: + prices, images
    - >5 publications:  show all items

    Prices and images are NEVER blocking — only informational.
    """

    def __init__(self, db: SupabaseClient) -> None:
        self._db = db
        self._categories = CategoriesRepository(db)
        self._publications = PublicationsRepository(db)

    async def check(
        self,
        user_id: int,
        category_id: int,
        user_balance: int,
        image_count: int = 4,
    ) -> ReadinessReport:
        """Build readiness report for a category.

        Args:
            user_id: Telegram user ID.
            category_id: Target category.
            user_balance: Current user balance (tokens).
            image_count: Number of AI images (default 4).

        Returns:
            ReadinessReport with all checks filled.
        """
        category = await self._categories.get_by_id(category_id)
        if category is None:
            msg = f"Category {category_id} not found"
            raise ValueError(msg)

        # Keywords: check clusters or flat format
        keywords = category.keywords or []
        has_keywords = len(keywords) > 0
        keyword_count = _count_phrases(keywords)
        cluster_count = len(keywords) if keywords and isinstance(keywords[0], dict) else 0

        # Description
        has_description = bool(category.description and category.description.strip())

        # Prices
        has_prices = bool(category.prices and category.prices.strip())

        # Publications count (for progressive readiness)
        user_pubs = await self._publications.get_by_user(user_id)
        publication_count = len(user_pubs)

        # Cost estimation
        estimated_cost = estimate_article_cost(images_count=image_count)

        # Missing items (progressive)
        missing = _build_missing_items(
            has_keywords=has_keywords,
            has_description=has_description,
            has_prices=has_prices,
            image_count=image_count,
            publication_count=publication_count,
        )

        is_sufficient = user_balance >= estimated_cost

        return ReadinessReport(
            has_keywords=has_keywords,
            keyword_count=keyword_count,
            cluster_count=cluster_count,
            has_description=has_description,
            has_prices=has_prices,
            image_count=image_count,
            estimated_cost=estimated_cost,
            user_balance=user_balance,
            is_sufficient_balance=is_sufficient,
            publication_count=publication_count,
            missing_items=missing,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_phrases(keywords: list) -> int:  # type: ignore[type-arg]
    """Count total phrases across clusters or flat list."""
    if not keywords:
        return 0
    if isinstance(keywords[0], dict):
        # Cluster format: [{cluster_name, phrases: [...]}]
        total = 0
        for cluster in keywords:
            phrases = cluster.get("phrases", [])
            total += len(phrases)
        return total
    # Flat format (legacy)
    return len(keywords)


def _build_missing_items(
    *,
    has_keywords: bool,
    has_description: bool,
    has_prices: bool,
    image_count: int,
    publication_count: int,
) -> list[str]:
    """Build list of missing items based on progressive readiness.

    UX_PIPELINE.md §4.4:
    - 0 pubs: keywords + description
    - 2-5 pubs: + prices, images
    - >5 pubs: all items shown
    """
    missing: list[str] = []

    # Keywords: always shown, only blocker
    if not has_keywords:
        missing.append("keywords")

    # Description: always shown for beginners, informational for experienced
    if not has_description:
        missing.append("description")

    # Prices: shown after 2+ publications
    if publication_count >= 2 and not has_prices:
        missing.append("prices")

    # Images: always available but shown as configurable after 2+ pubs
    if publication_count >= 2 and image_count == 0:
        missing.append("images")

    return missing
