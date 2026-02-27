"""Tests for services/tokens.py — token economy service.

Covers: cost estimation, charge/refund/credit, GOD_MODE, history, profile stats.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from services.tokens import (
    COST_AUDIT,
    COST_COMPETITOR,
    COST_DESCRIPTION,
    COST_PER_100_WORDS,
    COST_PER_IMAGE,
    COST_REVIEW_EACH,
    TokenService,
    _avg_cost_by_platform,
    estimate_article_cost,
    estimate_keywords_cost,
    estimate_social_post_cost,
    estimate_text_cost,
)

# ---------------------------------------------------------------------------
# Pure estimation functions
# ---------------------------------------------------------------------------


class TestEstimateTextCost:
    def test_zero_words(self) -> None:
        assert estimate_text_cost(0) == 0

    def test_negative_words(self) -> None:
        assert estimate_text_cost(-50) == 0

    def test_exact_100(self) -> None:
        assert estimate_text_cost(100) == 10

    def test_101_rounds_up(self) -> None:
        # ceil(101/100) = 2 → 2*10 = 20
        assert estimate_text_cost(101) == 20

    def test_2000_words(self) -> None:
        # ceil(2000/100) = 20 → 20*10 = 200
        assert estimate_text_cost(2000) == 200

    def test_50_words(self) -> None:
        # ceil(50/100) = 1 → 1*10 = 10
        assert estimate_text_cost(50) == 10


class TestEstimateArticleCost:
    def test_default_article(self) -> None:
        # 2000 words + 4 images = 200 + 120 = 320
        assert estimate_article_cost() == 320

    def test_custom_article(self) -> None:
        # 1500 words + 2 images = 150 + 60 = 210
        assert estimate_article_cost(word_count=1500, images_count=2) == 210

    def test_no_images(self) -> None:
        assert estimate_article_cost(word_count=1000, images_count=0) == 100


class TestEstimateSocialPostCost:
    def test_default_post(self) -> None:
        # 100 words + 1 image = 10 + 30 = 40
        assert estimate_social_post_cost() == 40

    def test_longer_post(self) -> None:
        # 300 words + 1 image = 30 + 30 = 60
        assert estimate_social_post_cost(word_count=300, images_count=1) == 60


class TestEstimateKeywordsCost:
    def test_50_keywords(self) -> None:
        assert estimate_keywords_cost(50) == 50

    def test_200_keywords(self) -> None:
        assert estimate_keywords_cost(200) == 200

    def test_zero_keywords(self) -> None:
        assert estimate_keywords_cost(0) == 0

    def test_negative_returns_zero(self) -> None:
        assert estimate_keywords_cost(-10) == 0


class TestCostConstants:
    def test_per_100_words(self) -> None:
        assert COST_PER_100_WORDS == 10

    def test_per_image(self) -> None:
        assert COST_PER_IMAGE == 30

    def test_audit(self) -> None:
        assert COST_AUDIT == 50

    def test_competitor(self) -> None:
        assert COST_COMPETITOR == 50

    def test_description(self) -> None:
        assert COST_DESCRIPTION == 20

    def test_review_each(self) -> None:
        assert COST_REVIEW_EACH == 10


# ---------------------------------------------------------------------------
# TokenService fixtures
# ---------------------------------------------------------------------------


def _make_user_row(user_id: int = 123, balance: int = 1500) -> dict[str, Any]:
    return {
        "id": user_id,
        "username": "test",
        "first_name": "Test",
        "last_name": None,
        "balance": balance,
        "language": "ru",
        "role": "user",
        "referrer_id": None,
        "notify_publications": True,
        "notify_balance": True,
        "notify_news": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_activity": "2026-02-01T00:00:00+00:00",
    }


def _make_expense_row(
    amount: int = -100,
    operation_type: str = "text_generation",
    user_id: int = 123,
) -> dict[str, Any]:
    return {
        "id": 1,
        "user_id": user_id,
        "amount": amount,
        "operation_type": operation_type,
        "description": None,
        "ai_model": None,
        "input_tokens": None,
        "output_tokens": None,
        "cost_usd": None,
        "created_at": "2026-02-01T14:30:00+00:00",
    }


@pytest.fixture
def mock_users_repo() -> AsyncMock:
    repo = AsyncMock()
    return repo


@pytest.fixture
def mock_payments_repo() -> AsyncMock:
    repo = AsyncMock()
    return repo


@pytest.fixture
def mock_db() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(mock_db: AsyncMock, mock_users_repo: AsyncMock, mock_payments_repo: AsyncMock) -> TokenService:
    svc = TokenService.__new__(TokenService)
    svc._db = mock_db
    svc._users = mock_users_repo
    svc._payments = mock_payments_repo
    svc._admin_ids = [999]
    return svc


# ---------------------------------------------------------------------------
# TokenService.check_balance
# ---------------------------------------------------------------------------


class TestCheckBalance:
    async def test_sufficient_balance(self, service: TokenService, mock_users_repo: AsyncMock) -> None:
        from db.models import User

        mock_users_repo.get_by_id.return_value = User(**_make_user_row(balance=500))
        assert await service.check_balance(123, 100) is True

    async def test_insufficient_balance(self, service: TokenService, mock_users_repo: AsyncMock) -> None:
        from db.models import User

        mock_users_repo.get_by_id.return_value = User(**_make_user_row(balance=50))
        assert await service.check_balance(123, 100) is False

    async def test_user_not_found(self, service: TokenService, mock_users_repo: AsyncMock) -> None:
        mock_users_repo.get_by_id.return_value = None
        assert await service.check_balance(123, 100) is False

    async def test_exact_balance(self, service: TokenService, mock_users_repo: AsyncMock) -> None:
        from db.models import User

        mock_users_repo.get_by_id.return_value = User(**_make_user_row(balance=100))
        assert await service.check_balance(123, 100) is True


# ---------------------------------------------------------------------------
# TokenService.get_balance
# ---------------------------------------------------------------------------


class TestGetBalance:
    async def test_returns_balance(self, service: TokenService, mock_users_repo: AsyncMock) -> None:
        from db.models import User

        mock_users_repo.get_by_id.return_value = User(**_make_user_row(balance=1500))
        assert await service.get_balance(123) == 1500

    async def test_user_not_found_returns_zero(self, service: TokenService, mock_users_repo: AsyncMock) -> None:
        mock_users_repo.get_by_id.return_value = None
        assert await service.get_balance(123) == 0


# ---------------------------------------------------------------------------
# TokenService.charge
# ---------------------------------------------------------------------------


class TestCharge:
    async def test_charge_deducts_and_records(
        self,
        service: TokenService,
        mock_users_repo: AsyncMock,
        mock_payments_repo: AsyncMock,
    ) -> None:
        mock_users_repo.charge_balance.return_value = 1300
        result = await service.charge(123, 200, "text_generation", description="Article gen")
        assert result == 1300
        mock_users_repo.charge_balance.assert_awaited_once_with(123, 200)
        mock_payments_repo.create_expense.assert_awaited_once()
        expense_arg = mock_payments_repo.create_expense.call_args[0][0]
        assert expense_arg.amount == -200
        assert expense_arg.operation_type == "text_generation"

    async def test_charge_zero_amount_skips(
        self,
        service: TokenService,
        mock_users_repo: AsyncMock,
        mock_payments_repo: AsyncMock,
    ) -> None:
        from db.models import User

        mock_users_repo.get_by_id.return_value = User(**_make_user_row(balance=1500))
        result = await service.charge(123, 0, "text_generation")
        assert result == 1500
        mock_users_repo.charge_balance.assert_not_awaited()
        mock_payments_repo.create_expense.assert_not_awaited()

    async def test_god_mode_skips_charge(
        self,
        service: TokenService,
        mock_users_repo: AsyncMock,
        mock_payments_repo: AsyncMock,
    ) -> None:
        """GOD_MODE (admin_ids=[999]) records expense but doesn't deduct."""
        from db.models import User

        mock_users_repo.get_by_id.return_value = User(**_make_user_row(user_id=999, balance=99999))
        result = await service.charge(999, 320, "text_generation")
        assert result == 99999
        mock_users_repo.charge_balance.assert_not_awaited()
        mock_payments_repo.create_expense.assert_awaited_once()

    async def test_charge_with_cost_usd(
        self,
        service: TokenService,
        mock_users_repo: AsyncMock,
        mock_payments_repo: AsyncMock,
    ) -> None:
        mock_users_repo.charge_balance.return_value = 1000
        await service.charge(
            123,
            200,
            "text_generation",
            ai_model="anthropic/claude-sonnet-4.5",
            cost_usd=Decimal("0.05"),
        )
        expense_arg = mock_payments_repo.create_expense.call_args[0][0]
        assert expense_arg.ai_model == "anthropic/claude-sonnet-4.5"
        assert expense_arg.cost_usd == Decimal("0.05")


# ---------------------------------------------------------------------------
# TokenService.refund
# ---------------------------------------------------------------------------


class TestRefund:
    async def test_refund_credits_and_records(
        self,
        service: TokenService,
        mock_users_repo: AsyncMock,
        mock_payments_repo: AsyncMock,
    ) -> None:
        mock_users_repo.refund_balance.return_value = 1700
        result = await service.refund(123, 200, reason="refund", description="Generation failed")
        assert result == 1700
        mock_users_repo.refund_balance.assert_awaited_once_with(123, 200)
        expense_arg = mock_payments_repo.create_expense.call_args[0][0]
        assert expense_arg.amount == 200  # positive
        assert expense_arg.operation_type == "refund"

    async def test_refund_zero_skips(
        self,
        service: TokenService,
        mock_users_repo: AsyncMock,
        mock_payments_repo: AsyncMock,
    ) -> None:
        from db.models import User

        mock_users_repo.get_by_id.return_value = User(**_make_user_row(balance=1500))
        result = await service.refund(123, 0)
        assert result == 1500
        mock_users_repo.refund_balance.assert_not_awaited()


# ---------------------------------------------------------------------------
# TokenService.credit
# ---------------------------------------------------------------------------


class TestCredit:
    async def test_credit_adds_and_records(
        self,
        service: TokenService,
        mock_users_repo: AsyncMock,
        mock_payments_repo: AsyncMock,
    ) -> None:
        mock_users_repo.credit_balance.return_value = 5000
        result = await service.credit(123, 3500, operation_type="purchase", description="Starter pack")
        assert result == 5000
        mock_users_repo.credit_balance.assert_awaited_once_with(123, 3500)
        expense_arg = mock_payments_repo.create_expense.call_args[0][0]
        assert expense_arg.amount == 3500
        assert expense_arg.operation_type == "purchase"

    async def test_credit_zero_skips(
        self,
        service: TokenService,
        mock_users_repo: AsyncMock,
        mock_payments_repo: AsyncMock,
    ) -> None:
        from db.models import User

        mock_users_repo.get_by_id.return_value = User(**_make_user_row(balance=1500))
        result = await service.credit(123, 0)
        assert result == 1500
        mock_users_repo.credit_balance.assert_not_awaited()


# ---------------------------------------------------------------------------
# TokenService.get_history
# ---------------------------------------------------------------------------


class TestGetHistory:
    async def test_returns_expenses(self, service: TokenService, mock_payments_repo: AsyncMock) -> None:
        from db.models import TokenExpense

        mock_payments_repo.get_expenses_by_user.return_value = [
            TokenExpense(**_make_expense_row(amount=-200, operation_type="text_generation")),
            TokenExpense(**_make_expense_row(amount=3500, operation_type="purchase")),
        ]
        history = await service.get_history(123, limit=20)
        assert len(history) == 2
        assert history[0].amount == -200
        assert history[1].amount == 3500

    async def test_empty_history(self, service: TokenService, mock_payments_repo: AsyncMock) -> None:
        mock_payments_repo.get_expenses_by_user.return_value = []
        history = await service.get_history(123)
        assert history == []


# ---------------------------------------------------------------------------
# TokenService.get_referral_bonus_total
# ---------------------------------------------------------------------------


class TestGetReferralBonusTotal:
    async def test_sums_referral_bonuses(self, service: TokenService, mock_payments_repo: AsyncMock) -> None:
        from db.models import TokenExpense

        mock_payments_repo.get_expenses_by_user.return_value = [
            TokenExpense(**_make_expense_row(amount=300, operation_type="referral_bonus")),
            TokenExpense(**_make_expense_row(amount=-200, operation_type="text_generation")),
            TokenExpense(**_make_expense_row(amount=150, operation_type="referral_bonus")),
        ]
        total = await service.get_referral_bonus_total(123)
        assert total == 450

    async def test_no_bonuses_returns_zero(self, service: TokenService, mock_payments_repo: AsyncMock) -> None:
        mock_payments_repo.get_expenses_by_user.return_value = []
        total = await service.get_referral_bonus_total(123)
        assert total == 0


# ---------------------------------------------------------------------------
# TokenService.get_profile_stats
# ---------------------------------------------------------------------------


class TestAvgCostByPlatform:
    """Tests for _avg_cost_by_platform helper (C17)."""

    def test_wordpress_cost(self) -> None:
        assert _avg_cost_by_platform("wordpress") == 320

    def test_telegram_cost(self) -> None:
        assert _avg_cost_by_platform("telegram") == 40

    def test_vk_cost(self) -> None:
        assert _avg_cost_by_platform("vk") == 40

    def test_pinterest_cost(self) -> None:
        assert _avg_cost_by_platform("pinterest") == 40

    def test_unknown_platform_default(self) -> None:
        assert _avg_cost_by_platform("some_future_platform") == 40


class TestGetProfileStats:
    async def test_wordpress_schedule_uses_320_cost(
        self, service: TokenService, mock_users_repo: AsyncMock
    ) -> None:
        """C17: WP schedules must use ~320 tokens/post, not 40."""
        from db.models import Category, PlatformSchedule, Project, User

        user = User(**_make_user_row(balance=2000))

        with (
            patch("services.tokens.ProjectsRepository") as mock_proj_cls,
            patch("services.tokens.SchedulesRepository") as mock_sched_cls,
            patch("services.tokens.CategoriesRepository") as mock_cat_cls,
        ):
            proj_repo = AsyncMock()
            proj_repo.get_by_user.return_value = [
                Project(id=1, user_id=123, name="P1", company_name="C", specialization="S"),
            ]
            mock_proj_cls.return_value = proj_repo

            cat_repo = AsyncMock()
            cat_repo.get_by_project.return_value = [
                Category(id=1, project_id=1, name="Cat1"),
            ]
            mock_cat_cls.return_value = cat_repo

            sched_repo = AsyncMock()
            sched_repo.get_by_project.return_value = [
                PlatformSchedule(
                    id=1,
                    category_id=1,
                    platform_type="wordpress",
                    connection_id=1,
                    enabled=True,
                    schedule_days=["mon", "wed", "fri"],
                    posts_per_day=1,
                ),
            ]
            mock_sched_cls.return_value = sched_repo

            mock_users_repo.get_referral_count.return_value = 0

            stats = await service.get_profile_stats(user)

        # 1 post/day * 3 days = 3 posts/week
        assert stats["posts_per_week"] == 3
        # WP cost: 3 * 320 = 960 (NOT 3 * 40 = 120)
        assert stats["tokens_per_week"] == 3 * 320  # 960
        assert stats["tokens_per_month"] == 3 * 320 * 4  # 3840

    async def test_mixed_platforms_differentiated_cost(
        self, service: TokenService, mock_users_repo: AsyncMock
    ) -> None:
        """C17: Mixed WP + social schedules use different costs."""
        from db.models import Category, PlatformSchedule, Project, User

        user = User(**_make_user_row(balance=5000))

        with (
            patch("services.tokens.ProjectsRepository") as mock_proj_cls,
            patch("services.tokens.SchedulesRepository") as mock_sched_cls,
            patch("services.tokens.CategoriesRepository") as mock_cat_cls,
        ):
            proj_repo = AsyncMock()
            proj_repo.get_by_user.return_value = [
                Project(id=1, user_id=123, name="P1", company_name="C", specialization="S"),
            ]
            mock_proj_cls.return_value = proj_repo

            cat_repo = AsyncMock()
            cat_repo.get_by_project.return_value = [
                Category(id=1, project_id=1, name="Cat1"),
                Category(id=2, project_id=1, name="Cat2"),
            ]
            mock_cat_cls.return_value = cat_repo

            sched_repo = AsyncMock()
            sched_repo.get_by_project.return_value = [
                PlatformSchedule(
                    id=1,
                    category_id=1,
                    platform_type="wordpress",
                    connection_id=1,
                    enabled=True,
                    schedule_days=["mon", "wed", "fri"],
                    posts_per_day=2,
                ),
                PlatformSchedule(
                    id=2,
                    category_id=1,
                    platform_type="telegram",
                    connection_id=2,
                    enabled=True,
                    schedule_days=["mon", "tue", "wed", "thu", "fri"],
                    posts_per_day=1,
                ),
            ]
            mock_sched_cls.return_value = sched_repo

            mock_users_repo.get_referral_count.return_value = 3

            stats = await service.get_profile_stats(user)

        assert stats["project_count"] == 1
        assert stats["category_count"] == 2
        assert stats["schedule_count"] == 2
        assert stats["referral_count"] == 3
        # WP: 2 posts/day * 3 days = 6 posts/week
        # TG: 1 post/day * 5 days = 5 posts/week
        assert stats["posts_per_week"] == 11
        # WP: 6 * 320 = 1920
        # TG: 5 * 40 = 200
        # Total: 2120
        assert stats["tokens_per_week"] == 2120
        assert stats["tokens_per_month"] == 2120 * 4

    async def test_social_only_schedule(
        self, service: TokenService, mock_users_repo: AsyncMock
    ) -> None:
        """Social-only schedule uses 40 tokens/post."""
        from db.models import Category, PlatformSchedule, Project, User

        user = User(**_make_user_row(balance=2000))

        with (
            patch("services.tokens.ProjectsRepository") as mock_proj_cls,
            patch("services.tokens.SchedulesRepository") as mock_sched_cls,
            patch("services.tokens.CategoriesRepository") as mock_cat_cls,
        ):
            proj_repo = AsyncMock()
            proj_repo.get_by_user.return_value = [
                Project(id=1, user_id=123, name="P1", company_name="C", specialization="S"),
            ]
            mock_proj_cls.return_value = proj_repo

            cat_repo = AsyncMock()
            cat_repo.get_by_project.return_value = [
                Category(id=1, project_id=1, name="Cat1"),
            ]
            mock_cat_cls.return_value = cat_repo

            sched_repo = AsyncMock()
            sched_repo.get_by_project.return_value = [
                PlatformSchedule(
                    id=1,
                    category_id=1,
                    platform_type="vk",
                    connection_id=1,
                    enabled=True,
                    schedule_days=["mon", "wed", "fri"],
                    posts_per_day=2,
                ),
            ]
            mock_sched_cls.return_value = sched_repo

            mock_users_repo.get_referral_count.return_value = 0

            stats = await service.get_profile_stats(user)

        # 2 posts/day * 3 days = 6 posts/week * 40 = 240
        assert stats["posts_per_week"] == 6
        assert stats["tokens_per_week"] == 240
        assert stats["tokens_per_month"] == 960

    async def test_no_projects(self, service: TokenService, mock_users_repo: AsyncMock) -> None:
        from db.models import User

        user = User(**_make_user_row())

        with (
            patch("services.tokens.ProjectsRepository") as mock_proj_cls,
            patch("services.tokens.SchedulesRepository"),
            patch("services.tokens.CategoriesRepository"),
        ):
            proj_repo = AsyncMock()
            proj_repo.get_by_user.return_value = []
            mock_proj_cls.return_value = proj_repo
            mock_users_repo.get_referral_count.return_value = 0

            stats = await service.get_profile_stats(user)

        assert stats["project_count"] == 0
        assert stats["category_count"] == 0
        assert stats["schedule_count"] == 0
        assert stats["posts_per_week"] == 0
        assert stats["tokens_per_week"] == 0


# ---------------------------------------------------------------------------
# TokenService.format_insufficient_msg
# ---------------------------------------------------------------------------


class TestFormatInsufficientMsg:
    def test_message_format(self) -> None:
        svc = TokenService.__new__(TokenService)
        msg = svc.format_insufficient_msg(320, 100)
        assert "320" in msg
        assert "100" in msg
        assert "токенов" in msg


# ---------------------------------------------------------------------------
# TokenService.refund_active_previews (E42)
# ---------------------------------------------------------------------------


class TestRefundActivePreviews:
    async def test_refunds_all_previews_with_tokens(
        self,
        service: TokenService,
        mock_users_repo: AsyncMock,
        mock_payments_repo: AsyncMock,
    ) -> None:
        from db.models import ArticlePreview

        mock_users_repo.refund_balance.return_value = 1500
        previews = [
            ArticlePreview(id=1, user_id=123, project_id=1, category_id=1, tokens_charged=100),
            ArticlePreview(id=2, user_id=123, project_id=1, category_id=1, tokens_charged=200),
        ]
        count = await service.refund_active_previews(previews, 123, "удаление проекта #1")
        assert count == 2
        assert mock_users_repo.refund_balance.await_count == 2
        assert mock_payments_repo.create_expense.await_count == 2

    async def test_skips_previews_with_zero_tokens(
        self,
        service: TokenService,
        mock_users_repo: AsyncMock,
        mock_payments_repo: AsyncMock,
    ) -> None:
        from db.models import ArticlePreview

        previews = [
            ArticlePreview(id=1, user_id=123, project_id=1, category_id=1, tokens_charged=0),
            ArticlePreview(id=2, user_id=123, project_id=1, category_id=1, tokens_charged=None),
        ]
        count = await service.refund_active_previews(previews, 123, "удаление категории #5")
        assert count == 0
        mock_users_repo.refund_balance.assert_not_awaited()

    async def test_mixed_previews(
        self,
        service: TokenService,
        mock_users_repo: AsyncMock,
        mock_payments_repo: AsyncMock,
    ) -> None:
        from db.models import ArticlePreview

        mock_users_repo.refund_balance.return_value = 1500
        previews = [
            ArticlePreview(id=1, user_id=123, project_id=1, category_id=1, tokens_charged=100),
            ArticlePreview(id=2, user_id=123, project_id=1, category_id=1, tokens_charged=0),
            ArticlePreview(id=3, user_id=123, project_id=1, category_id=1, tokens_charged=300),
        ]
        count = await service.refund_active_previews(previews, 123, "удаление проекта #2")
        assert count == 2  # only previews with tokens_charged > 0

    async def test_empty_previews(
        self,
        service: TokenService,
        mock_users_repo: AsyncMock,
    ) -> None:
        count = await service.refund_active_previews([], 123, "empty test")
        assert count == 0
        mock_users_repo.refund_balance.assert_not_awaited()
