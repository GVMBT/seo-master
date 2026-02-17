"""Tests for services/readiness.py -- ReadinessService and helpers.

Covers:
- ReadinessReport properties (all_filled, has_blockers)
- _count_phrases with cluster and flat format
- _build_missing_items with progressive readiness
- ReadinessService.check() with various category states
- Cost estimation integration
- Category not found raises ValueError
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from services.readiness import ReadinessReport, ReadinessService, _build_missing_items, _count_phrases
from services.tokens import estimate_article_cost

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_report(**overrides: Any) -> ReadinessReport:
    """Build ReadinessReport with sensible defaults."""
    defaults: dict[str, Any] = {
        "has_keywords": True,
        "keyword_count": 50,
        "cluster_count": 3,
        "has_description": True,
        "has_prices": True,
        "image_count": 4,
        "estimated_cost": 320,
        "user_balance": 1500,
        "is_sufficient_balance": True,
        "publication_count": 0,
        "missing_items": [],
    }
    defaults.update(overrides)
    return ReadinessReport(**defaults)


def _make_category_dict(**overrides: Any) -> dict[str, Any]:
    """Category row as returned by CategoriesRepository."""
    defaults: dict[str, Any] = {
        "id": 10,
        "project_id": 1,
        "name": "Test Category",
        "description": "A test description",
        "keywords": [
            {
                "cluster_name": "main",
                "cluster_type": "article",
                "main_phrase": "seo test",
                "phrases": [
                    {"phrase": "seo test", "volume": 1000},
                    {"phrase": "seo testing", "volume": 500},
                ],
            },
        ],
        "prices": "100 rub per unit",
        "media": [],
        "reviews": [],
        "image_settings": {},
        "text_settings": {},
        "created_at": None,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# ReadinessReport properties
# ---------------------------------------------------------------------------


class TestReadinessReportAllFilled:
    """all_filled: True when has_keywords AND has_description."""

    def test_all_filled_both_present(self) -> None:
        report = _make_report(has_keywords=True, has_description=True)
        assert report.all_filled is True

    def test_all_filled_no_keywords(self) -> None:
        report = _make_report(has_keywords=False, has_description=True)
        assert report.all_filled is False

    def test_all_filled_no_description(self) -> None:
        report = _make_report(has_keywords=True, has_description=False)
        assert report.all_filled is False

    def test_all_filled_neither(self) -> None:
        report = _make_report(has_keywords=False, has_description=False)
        assert report.all_filled is False

    def test_all_filled_ignores_prices(self) -> None:
        """Prices are optional -- do not affect all_filled."""
        report = _make_report(has_keywords=True, has_description=True, has_prices=False)
        assert report.all_filled is True

    def test_all_filled_ignores_images(self) -> None:
        """Image count does not affect all_filled."""
        report = _make_report(has_keywords=True, has_description=True, image_count=0)
        assert report.all_filled is True


class TestReadinessReportHasBlockers:
    """has_blockers: True when no keywords (only hard blocker)."""

    def test_has_blockers_no_keywords(self) -> None:
        report = _make_report(has_keywords=False)
        assert report.has_blockers is True

    def test_no_blockers_with_keywords(self) -> None:
        report = _make_report(has_keywords=True)
        assert report.has_blockers is False

    def test_no_blockers_even_without_description(self) -> None:
        """Description missing is NOT a blocker."""
        report = _make_report(has_keywords=True, has_description=False)
        assert report.has_blockers is False


# ---------------------------------------------------------------------------
# _count_phrases
# ---------------------------------------------------------------------------


class TestCountPhrases:
    """_count_phrases with cluster and flat keyword formats."""

    def test_empty_list(self) -> None:
        assert _count_phrases([]) == 0

    def test_cluster_format_single_cluster(self) -> None:
        keywords = [
            {"cluster_name": "a", "phrases": [{"phrase": "p1"}, {"phrase": "p2"}]},
        ]
        assert _count_phrases(keywords) == 2

    def test_cluster_format_multiple_clusters(self) -> None:
        keywords = [
            {"cluster_name": "a", "phrases": [{"phrase": "p1"}, {"phrase": "p2"}]},
            {"cluster_name": "b", "phrases": [{"phrase": "p3"}]},
            {"cluster_name": "c", "phrases": [{"phrase": "p4"}, {"phrase": "p5"}, {"phrase": "p6"}]},
        ]
        assert _count_phrases(keywords) == 6

    def test_cluster_format_empty_phrases(self) -> None:
        keywords = [
            {"cluster_name": "a", "phrases": []},
        ]
        assert _count_phrases(keywords) == 0

    def test_cluster_format_missing_phrases_key(self) -> None:
        """Cluster dict without 'phrases' key defaults to empty."""
        keywords = [
            {"cluster_name": "a"},
        ]
        assert _count_phrases(keywords) == 0

    def test_flat_format_legacy(self) -> None:
        """Flat format: list of strings (legacy)."""
        keywords = ["keyword 1", "keyword 2", "keyword 3"]
        assert _count_phrases(keywords) == 3

    def test_flat_format_single(self) -> None:
        assert _count_phrases(["single"]) == 1


# ---------------------------------------------------------------------------
# _build_missing_items
# ---------------------------------------------------------------------------


class TestBuildMissingItems:
    """_build_missing_items with progressive readiness rules."""

    def test_all_present_zero_pubs(self) -> None:
        """Everything filled, 0 pubs -- no missing items."""
        result = _build_missing_items(
            has_keywords=True,
            has_description=True,
            has_prices=True,
            image_count=4,
            publication_count=0,
        )
        assert result == []

    def test_no_keywords_zero_pubs(self) -> None:
        """Missing keywords always shown."""
        result = _build_missing_items(
            has_keywords=False,
            has_description=True,
            has_prices=True,
            image_count=4,
            publication_count=0,
        )
        assert result == ["keywords"]

    def test_no_description_zero_pubs(self) -> None:
        """Missing description shown for beginners."""
        result = _build_missing_items(
            has_keywords=True,
            has_description=False,
            has_prices=True,
            image_count=4,
            publication_count=0,
        )
        assert result == ["description"]

    def test_no_keywords_no_description_zero_pubs(self) -> None:
        result = _build_missing_items(
            has_keywords=False,
            has_description=False,
            has_prices=False,
            image_count=4,
            publication_count=0,
        )
        # At 0 pubs: only keywords and description shown
        assert "keywords" in result
        assert "description" in result
        # Prices NOT shown at 0 pubs
        assert "prices" not in result

    def test_missing_prices_shown_at_2_pubs(self) -> None:
        """Prices shown after 2+ publications."""
        result = _build_missing_items(
            has_keywords=True,
            has_description=True,
            has_prices=False,
            image_count=4,
            publication_count=2,
        )
        assert result == ["prices"]

    def test_missing_prices_hidden_at_1_pub(self) -> None:
        """Prices NOT shown at 1 publication."""
        result = _build_missing_items(
            has_keywords=True,
            has_description=True,
            has_prices=False,
            image_count=4,
            publication_count=1,
        )
        assert "prices" not in result

    def test_missing_images_shown_at_2_pubs(self) -> None:
        """Image count 0 shown as missing after 2+ pubs."""
        result = _build_missing_items(
            has_keywords=True,
            has_description=True,
            has_prices=True,
            image_count=0,
            publication_count=2,
        )
        assert result == ["images"]

    def test_images_present_not_missing_at_2_pubs(self) -> None:
        """Non-zero images at 2+ pubs -- NOT listed as missing."""
        result = _build_missing_items(
            has_keywords=True,
            has_description=True,
            has_prices=True,
            image_count=4,
            publication_count=5,
        )
        assert "images" not in result

    def test_all_missing_at_5_pubs(self) -> None:
        """At 5+ pubs: all items shown."""
        result = _build_missing_items(
            has_keywords=False,
            has_description=False,
            has_prices=False,
            image_count=0,
            publication_count=5,
        )
        assert "keywords" in result
        assert "description" in result
        assert "prices" in result
        assert "images" in result


# ---------------------------------------------------------------------------
# ReadinessService.check()
# ---------------------------------------------------------------------------


class TestReadinessServiceCheck:
    """ReadinessService.check() integration with mocked repos."""

    async def test_check_with_keywords_and_description(self) -> None:
        """Category with keywords + description -> fully ready."""
        from db.models import Category

        cat = Category(**_make_category_dict())

        with (
            patch("services.readiness.CategoriesRepository") as CatRepoMock,
            patch("services.readiness.PublicationsRepository") as PubRepoMock,
        ):
            cat_repo = CatRepoMock.return_value
            cat_repo.get_by_id = AsyncMock(return_value=cat)

            pub_repo = PubRepoMock.return_value
            pub_repo.get_by_user = AsyncMock(return_value=[])

            service = ReadinessService(db=AsyncMock())
            report = await service.check(user_id=1, category_id=10, user_balance=1500)

        assert report.has_keywords is True
        assert report.has_description is True
        assert report.all_filled is True
        assert report.has_blockers is False
        assert report.is_sufficient_balance is True

    async def test_check_without_keywords(self) -> None:
        """Category without keywords -> has_blockers True."""
        from db.models import Category

        cat = Category(**_make_category_dict(keywords=[]))

        with (
            patch("services.readiness.CategoriesRepository") as CatRepoMock,
            patch("services.readiness.PublicationsRepository") as PubRepoMock,
        ):
            cat_repo = CatRepoMock.return_value
            cat_repo.get_by_id = AsyncMock(return_value=cat)

            pub_repo = PubRepoMock.return_value
            pub_repo.get_by_user = AsyncMock(return_value=[])

            service = ReadinessService(db=AsyncMock())
            report = await service.check(user_id=1, category_id=10, user_balance=1500)

        assert report.has_keywords is False
        assert report.keyword_count == 0
        assert report.has_blockers is True
        assert "keywords" in report.missing_items

    async def test_check_without_description(self) -> None:
        """Category without description -> not all_filled but no blockers."""
        from db.models import Category

        cat = Category(**_make_category_dict(description=None))

        with (
            patch("services.readiness.CategoriesRepository") as CatRepoMock,
            patch("services.readiness.PublicationsRepository") as PubRepoMock,
        ):
            cat_repo = CatRepoMock.return_value
            cat_repo.get_by_id = AsyncMock(return_value=cat)

            pub_repo = PubRepoMock.return_value
            pub_repo.get_by_user = AsyncMock(return_value=[])

            service = ReadinessService(db=AsyncMock())
            report = await service.check(user_id=1, category_id=10, user_balance=1500)

        assert report.has_description is False
        assert report.all_filled is False
        assert report.has_blockers is False
        assert "description" in report.missing_items

    async def test_check_whitespace_description_treated_as_empty(self) -> None:
        """Description with only whitespace -> has_description False."""
        from db.models import Category

        cat = Category(**_make_category_dict(description="   "))

        with (
            patch("services.readiness.CategoriesRepository") as CatRepoMock,
            patch("services.readiness.PublicationsRepository") as PubRepoMock,
        ):
            cat_repo = CatRepoMock.return_value
            cat_repo.get_by_id = AsyncMock(return_value=cat)

            pub_repo = PubRepoMock.return_value
            pub_repo.get_by_user = AsyncMock(return_value=[])

            service = ReadinessService(db=AsyncMock())
            report = await service.check(user_id=1, category_id=10, user_balance=1500)

        assert report.has_description is False

    async def test_check_without_prices(self) -> None:
        """Category without prices -> has_prices False."""
        from db.models import Category

        cat = Category(**_make_category_dict(prices=None))

        with (
            patch("services.readiness.CategoriesRepository") as CatRepoMock,
            patch("services.readiness.PublicationsRepository") as PubRepoMock,
        ):
            cat_repo = CatRepoMock.return_value
            cat_repo.get_by_id = AsyncMock(return_value=cat)

            pub_repo = PubRepoMock.return_value
            pub_repo.get_by_user = AsyncMock(return_value=[])

            service = ReadinessService(db=AsyncMock())
            report = await service.check(user_id=1, category_id=10, user_balance=1500)

        assert report.has_prices is False

    async def test_check_category_not_found_raises(self) -> None:
        """Category not found -> ValueError."""
        with (
            patch("services.readiness.CategoriesRepository") as CatRepoMock,
            patch("services.readiness.PublicationsRepository"),
        ):
            cat_repo = CatRepoMock.return_value
            cat_repo.get_by_id = AsyncMock(return_value=None)

            service = ReadinessService(db=AsyncMock())
            with pytest.raises(ValueError, match="Category 999 not found"):
                await service.check(user_id=1, category_id=999, user_balance=1500)

    async def test_check_cost_estimation_default_images(self) -> None:
        """Default 4 images -> estimated_cost = estimate_article_cost(images_count=4)."""
        from db.models import Category

        cat = Category(**_make_category_dict())

        with (
            patch("services.readiness.CategoriesRepository") as CatRepoMock,
            patch("services.readiness.PublicationsRepository") as PubRepoMock,
        ):
            cat_repo = CatRepoMock.return_value
            cat_repo.get_by_id = AsyncMock(return_value=cat)

            pub_repo = PubRepoMock.return_value
            pub_repo.get_by_user = AsyncMock(return_value=[])

            service = ReadinessService(db=AsyncMock())
            report = await service.check(user_id=1, category_id=10, user_balance=1500)

        expected_cost = estimate_article_cost(images_count=4)
        assert report.estimated_cost == expected_cost
        assert report.estimated_cost == 320  # 200 text + 120 images

    async def test_check_cost_estimation_custom_images(self) -> None:
        """Custom image_count=2 -> adjusted cost."""
        from db.models import Category

        cat = Category(**_make_category_dict())

        with (
            patch("services.readiness.CategoriesRepository") as CatRepoMock,
            patch("services.readiness.PublicationsRepository") as PubRepoMock,
        ):
            cat_repo = CatRepoMock.return_value
            cat_repo.get_by_id = AsyncMock(return_value=cat)

            pub_repo = PubRepoMock.return_value
            pub_repo.get_by_user = AsyncMock(return_value=[])

            service = ReadinessService(db=AsyncMock())
            report = await service.check(user_id=1, category_id=10, user_balance=1500, image_count=2)

        expected_cost = estimate_article_cost(images_count=2)
        assert report.estimated_cost == expected_cost
        assert report.estimated_cost == 260  # 200 text + 60 images

    async def test_check_insufficient_balance(self) -> None:
        """Balance < estimated_cost -> is_sufficient_balance False."""
        from db.models import Category

        cat = Category(**_make_category_dict())

        with (
            patch("services.readiness.CategoriesRepository") as CatRepoMock,
            patch("services.readiness.PublicationsRepository") as PubRepoMock,
        ):
            cat_repo = CatRepoMock.return_value
            cat_repo.get_by_id = AsyncMock(return_value=cat)

            pub_repo = PubRepoMock.return_value
            pub_repo.get_by_user = AsyncMock(return_value=[])

            service = ReadinessService(db=AsyncMock())
            report = await service.check(user_id=1, category_id=10, user_balance=100)

        assert report.is_sufficient_balance is False
        assert report.user_balance == 100
        assert report.estimated_cost == 320

    async def test_check_progressive_readiness_zero_pubs(self) -> None:
        """0 pubs: prices and images missing are NOT shown."""
        from db.models import Category

        cat = Category(**_make_category_dict(prices=None))

        with (
            patch("services.readiness.CategoriesRepository") as CatRepoMock,
            patch("services.readiness.PublicationsRepository") as PubRepoMock,
        ):
            cat_repo = CatRepoMock.return_value
            cat_repo.get_by_id = AsyncMock(return_value=cat)

            pub_repo = PubRepoMock.return_value
            pub_repo.get_by_user = AsyncMock(return_value=[])

            service = ReadinessService(db=AsyncMock())
            report = await service.check(user_id=1, category_id=10, user_balance=1500)

        # At 0 pubs: prices missing not listed
        assert "prices" not in report.missing_items
        assert report.publication_count == 0

    async def test_check_progressive_readiness_many_pubs(self) -> None:
        """3 pubs: prices shown as missing when absent."""
        from db.models import Category

        cat = Category(**_make_category_dict(prices=None))
        fake_pubs = [AsyncMock(), AsyncMock(), AsyncMock()]  # 3 items

        with (
            patch("services.readiness.CategoriesRepository") as CatRepoMock,
            patch("services.readiness.PublicationsRepository") as PubRepoMock,
        ):
            cat_repo = CatRepoMock.return_value
            cat_repo.get_by_id = AsyncMock(return_value=cat)

            pub_repo = PubRepoMock.return_value
            pub_repo.get_by_user = AsyncMock(return_value=fake_pubs)

            service = ReadinessService(db=AsyncMock())
            report = await service.check(user_id=1, category_id=10, user_balance=1500)

        assert report.publication_count == 3
        assert "prices" in report.missing_items

    async def test_check_cluster_count(self) -> None:
        """Cluster format keywords -> cluster_count > 0."""
        from db.models import Category

        keywords = [
            {"cluster_name": "a", "phrases": [{"phrase": "p1"}]},
            {"cluster_name": "b", "phrases": [{"phrase": "p2"}, {"phrase": "p3"}]},
        ]
        cat = Category(**_make_category_dict(keywords=keywords))

        with (
            patch("services.readiness.CategoriesRepository") as CatRepoMock,
            patch("services.readiness.PublicationsRepository") as PubRepoMock,
        ):
            cat_repo = CatRepoMock.return_value
            cat_repo.get_by_id = AsyncMock(return_value=cat)

            pub_repo = PubRepoMock.return_value
            pub_repo.get_by_user = AsyncMock(return_value=[])

            service = ReadinessService(db=AsyncMock())
            report = await service.check(user_id=1, category_id=10, user_balance=1500)

        assert report.cluster_count == 2
        assert report.keyword_count == 3
