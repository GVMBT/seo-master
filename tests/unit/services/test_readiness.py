"""Tests for services/readiness.py — ReadinessService.

Covers: checklist generation, all-ready detection, missing items,
cost estimation, category not found error.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from bot.exceptions import AppError
from db.models import Category
from services.readiness import ReadinessItem, ReadinessResult, ReadinessService
from services.tokens import COST_DESCRIPTION, estimate_keywords_cost

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_category(
    *,
    category_id: int = 1,
    project_id: int = 10,
    keywords: list[dict[str, Any]] | None = None,
    description: str | None = None,
    prices: str | None = None,
    media: list[dict[str, Any]] | None = None,
) -> Category:
    """Build a minimal Category for tests."""
    return Category(
        id=category_id,
        project_id=project_id,
        name="Test Category",
        keywords=keywords or [],
        description=description,
        prices=prices,
        media=media or [],
    )


# ---------------------------------------------------------------------------
# ReadinessItem / ReadinessResult dataclass tests
# ---------------------------------------------------------------------------


class TestReadinessResult:
    def test_all_ready_true_when_all_items_ready(self) -> None:
        items = [
            ReadinessItem(key="a", label="A", hint="h", ready=True, cost=0),
            ReadinessItem(key="b", label="B", hint="h", ready=True, cost=0),
        ]
        result = ReadinessResult(items=items)
        assert result.all_ready is True

    def test_all_ready_false_when_one_missing(self) -> None:
        items = [
            ReadinessItem(key="a", label="A", hint="h", ready=True, cost=0),
            ReadinessItem(key="b", label="B", hint="h", ready=False, cost=10),
        ]
        result = ReadinessResult(items=items)
        assert result.all_ready is False

    def test_all_ready_true_when_empty_items(self) -> None:
        result = ReadinessResult(items=[])
        assert result.all_ready is True

    def test_required_missing_always_empty(self) -> None:
        """All items are optional per spec -- required_missing is always empty."""
        items = [
            ReadinessItem(key="x", label="X", hint="h", ready=False, cost=5),
        ]
        result = ReadinessResult(items=items)
        assert result.required_missing == []

    def test_optional_missing_lists_unready_keys(self) -> None:
        items = [
            ReadinessItem(key="a", label="A", hint="h", ready=True, cost=0),
            ReadinessItem(key="b", label="B", hint="h", ready=False, cost=10),
            ReadinessItem(key="c", label="C", hint="h", ready=False, cost=5),
        ]
        result = ReadinessResult(items=items)
        assert result.optional_missing == ["b", "c"]

    def test_optional_missing_empty_when_all_ready(self) -> None:
        items = [
            ReadinessItem(key="a", label="A", hint="h", ready=True, cost=0),
        ]
        result = ReadinessResult(items=items)
        assert result.optional_missing == []


# ---------------------------------------------------------------------------
# ReadinessService.check() tests
# ---------------------------------------------------------------------------


class TestReadinessServiceCheck:
    """Test ReadinessService.check() with mocked repository."""

    @pytest.fixture()
    def mock_db(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture()
    def service(self, mock_db: AsyncMock) -> ReadinessService:
        return ReadinessService(db=mock_db)

    async def test_category_not_found_raises(self, service: ReadinessService) -> None:
        with (
            patch.object(service._categories, "get_by_id", new_callable=AsyncMock, return_value=None),
            pytest.raises(AppError, match="Category 999 not found"),
        ):
            await service.check(category_id=999, project_id=10)

    async def test_all_empty_returns_three_unready_items(self, service: ReadinessService) -> None:
        category = _make_category()
        with patch.object(service._categories, "get_by_id", new_callable=AsyncMock, return_value=category):
            result = await service.check(category_id=1, project_id=10)

        assert len(result.items) == 3
        assert result.all_ready is False

        keys = [item.key for item in result.items]
        assert keys == ["keywords", "description", "prices"]

        for item in result.items:
            assert item.ready is False

    async def test_all_filled_returns_all_ready(self, service: ReadinessService) -> None:
        category = _make_category(
            keywords=[{"phrase": "test", "volume": 100}],
            description="Company description",
            prices="Product: 1000 RUB",
        )
        with patch.object(service._categories, "get_by_id", new_callable=AsyncMock, return_value=category):
            result = await service.check(category_id=1, project_id=10)

        assert result.all_ready is True
        assert result.optional_missing == []
        assert result.required_missing == []

        # All costs should be 0 when items are already filled
        for item in result.items:
            assert item.ready is True
            assert item.cost == 0

    async def test_keywords_cost_when_missing(self, service: ReadinessService) -> None:
        category = _make_category()
        with patch.object(service._categories, "get_by_id", new_callable=AsyncMock, return_value=category):
            result = await service.check(category_id=1, project_id=10)

        kw_item = next(i for i in result.items if i.key == "keywords")
        assert kw_item.ready is False
        assert kw_item.cost == estimate_keywords_cost(100)  # default 100 keywords

    async def test_description_cost_when_missing(self, service: ReadinessService) -> None:
        category = _make_category()
        with patch.object(service._categories, "get_by_id", new_callable=AsyncMock, return_value=category):
            result = await service.check(category_id=1, project_id=10)

        desc_item = next(i for i in result.items if i.key == "description")
        assert desc_item.ready is False
        assert desc_item.cost == COST_DESCRIPTION

    async def test_prices_cost_always_zero(self, service: ReadinessService) -> None:
        """Prices are free manual input, cost is always 0."""
        category = _make_category()
        with patch.object(service._categories, "get_by_id", new_callable=AsyncMock, return_value=category):
            result = await service.check(category_id=1, project_id=10)

        prices_item = next(i for i in result.items if i.key == "prices")
        assert prices_item.cost == 0

    async def test_partial_fill_keywords_only(self, service: ReadinessService) -> None:
        category = _make_category(keywords=[{"phrase": "seo"}])
        with patch.object(service._categories, "get_by_id", new_callable=AsyncMock, return_value=category):
            result = await service.check(category_id=1, project_id=10)

        assert result.all_ready is False
        assert "keywords" not in result.optional_missing
        assert "description" in result.optional_missing
        assert "prices" in result.optional_missing

    async def test_partial_fill_description_and_prices(self, service: ReadinessService) -> None:
        category = _make_category(description="desc", prices="100 RUB")
        with patch.object(service._categories, "get_by_id", new_callable=AsyncMock, return_value=category):
            result = await service.check(category_id=1, project_id=10)

        assert result.all_ready is False
        assert result.optional_missing == ["keywords"]

    async def test_labels_are_russian(self, service: ReadinessService) -> None:
        category = _make_category()
        with patch.object(service._categories, "get_by_id", new_callable=AsyncMock, return_value=category):
            result = await service.check(category_id=1, project_id=10)

        labels = {item.key: item.label for item in result.items}
        assert labels["keywords"] == "Ключевые фразы"
        assert labels["description"] == "Описание компании"
        assert labels["prices"] == "Цены"

    async def test_hints_match_spec(self, service: ReadinessService) -> None:
        category = _make_category()
        with patch.object(service._categories, "get_by_id", new_callable=AsyncMock, return_value=category):
            result = await service.check(category_id=1, project_id=10)

        hints = {item.key: item.hint for item in result.items}
        assert hints["keywords"] == "SEO-оптимизация"
        assert hints["description"] == "точность контекста"
        assert hints["prices"] == "реальные цены в статье"

    async def test_frozen_dataclass_immutable(self, service: ReadinessService) -> None:
        """ReadinessItem is frozen -- cannot be mutated after creation."""
        item = ReadinessItem(key="x", label="X", hint="h", ready=False, cost=5)
        with pytest.raises(AttributeError):
            item.ready = True  # type: ignore[misc]
