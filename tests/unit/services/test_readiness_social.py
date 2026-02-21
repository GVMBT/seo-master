"""Tests for ReadinessService with pipeline_type='social'.

Verifies:
- Social pipeline skips prices/images in missing items
- Cost estimation uses estimate_social_post_cost()
- image_count forced to 0 for social
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from db.models import Category
from services.readiness import ReadinessService, _build_missing_items


class TestBuildMissingItemsSocial:
    def test_social_no_prices_or_images(self) -> None:
        missing = _build_missing_items(
            has_keywords=True,
            has_description=True,
            has_prices=False,
            image_count=0,
            publication_count=10,
            pipeline_type="social",
        )
        assert "prices" not in missing
        assert "images" not in missing
        assert missing == []

    def test_social_missing_keywords_and_description(self) -> None:
        missing = _build_missing_items(
            has_keywords=False,
            has_description=False,
            has_prices=False,
            image_count=0,
            publication_count=0,
            pipeline_type="social",
        )
        assert "keywords" in missing
        assert "description" in missing
        assert "prices" not in missing
        assert "images" not in missing

    def test_article_still_shows_prices_after_2_pubs(self) -> None:
        missing = _build_missing_items(
            has_keywords=True,
            has_description=True,
            has_prices=False,
            image_count=0,
            publication_count=3,
            pipeline_type="article",
        )
        assert "prices" in missing
        assert "images" in missing


class TestReadinessServiceSocial:
    async def test_social_pipeline_cost_and_images(self) -> None:
        db = MagicMock()
        service = ReadinessService(db)

        cat = Category(
            id=10,
            project_id=1,
            name="Test Cat",
            keywords=[{"cluster_name": "c1", "phrases": ["kw1"]}],
            description="Some description",
        )
        service._categories = MagicMock()
        service._categories.get_by_id = AsyncMock(return_value=cat)
        service._publications = MagicMock()
        service._publications.get_by_user = AsyncMock(return_value=[])

        report = await service.check(
            user_id=123,
            category_id=10,
            user_balance=1500,
            image_count=4,
            pipeline_type="social",
        )

        assert report.image_count == 0
        assert report.has_keywords is True
        assert report.has_description is True
        assert "prices" not in report.missing_items
        assert "images" not in report.missing_items
        # Social cost should be less than article cost (no images)
        assert report.estimated_cost < 300
