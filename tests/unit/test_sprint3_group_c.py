"""Tests for Sprint 3 Group C: Rate Limits + Anti-Fraud + Idempotency.

H14: Referral limits (daily + lifetime cap)
H15: Per-user pipeline generation rate limit (3/10min)
H16: YooKassa webhook idempotency (Redis NX lock)
H17: Project/category creation limits
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from api.yookassa import _YOOKASSA_IDEMPOTENCY_TTL, yookassa_webhook
from cache.keys import CacheKeys
from db.repositories.categories import CategoriesRepository
from db.repositories.payments import PaymentsRepository
from db.repositories.projects import ProjectsRepository
from routers.categories.manage import MAX_CATEGORIES_PER_PROJECT
from routers.projects.create import MAX_PROJECTS_PER_USER
from services.ai.rate_limiter import RATE_LIMITS
from services.payments.stars import (
    MAX_REFERRAL_DAILY,
    MAX_REFERRAL_LIFETIME_TOKENS,
    credit_referral_bonus,
)
from tests.unit.routers.conftest import make_user

_STARS_MODULE = "services.payments.stars"


# ===========================================================================
# H14: Referral limits + anti-fraud
# ===========================================================================


class TestReferralDailyCap:
    """H14: daily cap of 10 referral bonuses per referrer."""

    async def test_allows_bonus_within_daily_limit(self) -> None:
        """Bonus credited when daily count is below MAX_REFERRAL_DAILY."""
        users = MagicMock()
        payments = MagicMock()
        redis = MagicMock()

        buyer = MagicMock(referrer_id=100)
        referrer = MagicMock(id=100)
        users.get_by_id = AsyncMock(side_effect=lambda uid: buyer if uid == 42 else referrer)
        users.credit_balance = AsyncMock(return_value=5000)
        payments.create_expense = AsyncMock()
        payments.update = AsyncMock()
        payments.sum_referral_bonuses = AsyncMock(return_value=0)

        redis.incr = AsyncMock(return_value=1)
        redis.expire = AsyncMock()
        redis.decr = AsyncMock()

        await credit_referral_bonus(users, payments, user_id=42, price_rub=1000, payment_id=1, redis=redis)

        users.credit_balance.assert_called_once_with(100, 100)
        payments.create_expense.assert_called_once()

    async def test_blocks_bonus_when_daily_limit_exceeded(self) -> None:
        """Bonus NOT credited when daily count exceeds MAX_REFERRAL_DAILY."""
        users = MagicMock()
        payments = MagicMock()
        redis = MagicMock()

        buyer = MagicMock(referrer_id=100)
        referrer = MagicMock(id=100)
        users.get_by_id = AsyncMock(side_effect=lambda uid: buyer if uid == 42 else referrer)
        users.credit_balance = AsyncMock()
        payments.create_expense = AsyncMock()

        redis.incr = AsyncMock(return_value=MAX_REFERRAL_DAILY + 1)
        redis.expire = AsyncMock()
        redis.decr = AsyncMock()

        await credit_referral_bonus(users, payments, user_id=42, price_rub=1000, payment_id=1, redis=redis)

        users.credit_balance.assert_not_called()
        payments.create_expense.assert_not_called()
        # Counter should be decremented back
        redis.decr.assert_called_once()

    async def test_sets_ttl_on_first_daily_increment(self) -> None:
        """Redis key TTL set on first increment (counter=1)."""
        users = MagicMock()
        payments = MagicMock()
        redis = MagicMock()

        buyer = MagicMock(referrer_id=100)
        referrer = MagicMock(id=100)
        users.get_by_id = AsyncMock(side_effect=lambda uid: buyer if uid == 42 else referrer)
        users.credit_balance = AsyncMock(return_value=5000)
        payments.create_expense = AsyncMock()
        payments.update = AsyncMock()
        payments.sum_referral_bonuses = AsyncMock(return_value=0)

        redis.incr = AsyncMock(return_value=1)
        redis.expire = AsyncMock()
        redis.decr = AsyncMock()

        await credit_referral_bonus(users, payments, user_id=42, price_rub=500, payment_id=1, redis=redis)

        redis.expire.assert_called_once()


class TestReferralLifetimeCap:
    """H14: lifetime cap of MAX_REFERRAL_LIFETIME_TOKENS tokens from referrals."""

    async def test_blocks_when_lifetime_cap_exceeded(self) -> None:
        """Bonus NOT credited when lifetime total + bonus > cap."""
        users = MagicMock()
        payments = MagicMock()
        redis = MagicMock()

        buyer = MagicMock(referrer_id=100)
        referrer = MagicMock(id=100)
        users.get_by_id = AsyncMock(side_effect=lambda uid: buyer if uid == 42 else referrer)
        users.credit_balance = AsyncMock()
        payments.create_expense = AsyncMock()

        redis.incr = AsyncMock(return_value=1)
        redis.expire = AsyncMock()
        redis.decr = AsyncMock()

        # Lifetime total already at cap - 50, bonus is 100 -> exceeds
        payments.sum_referral_bonuses = AsyncMock(return_value=MAX_REFERRAL_LIFETIME_TOKENS - 50)

        await credit_referral_bonus(users, payments, user_id=42, price_rub=1000, payment_id=1, redis=redis)

        users.credit_balance.assert_not_called()
        payments.create_expense.assert_not_called()
        # Daily counter should be decremented back
        redis.decr.assert_called_once()

    async def test_allows_when_within_lifetime_cap(self) -> None:
        """Bonus credited when lifetime total + bonus <= cap."""
        users = MagicMock()
        payments = MagicMock()
        redis = MagicMock()

        buyer = MagicMock(referrer_id=100)
        referrer = MagicMock(id=100)
        users.get_by_id = AsyncMock(side_effect=lambda uid: buyer if uid == 42 else referrer)
        users.credit_balance = AsyncMock(return_value=5000)
        payments.create_expense = AsyncMock()
        payments.update = AsyncMock()

        redis.incr = AsyncMock(return_value=1)
        redis.expire = AsyncMock()
        redis.decr = AsyncMock()

        payments.sum_referral_bonuses = AsyncMock(return_value=1000)

        await credit_referral_bonus(users, payments, user_id=42, price_rub=500, payment_id=1, redis=redis)

        # 10% of 500 = 50, lifetime 1000 + 50 = 1050 < 5000 cap
        users.credit_balance.assert_called_once_with(100, 50)

    async def test_backward_compat_without_redis(self) -> None:
        """When redis=None (backward compat), daily check is skipped but lifetime still checked."""
        users = MagicMock()
        payments = MagicMock()

        buyer = MagicMock(referrer_id=100)
        referrer = MagicMock(id=100)
        users.get_by_id = AsyncMock(side_effect=lambda uid: buyer if uid == 42 else referrer)
        users.credit_balance = AsyncMock(return_value=5000)
        payments.create_expense = AsyncMock()
        payments.update = AsyncMock()
        payments.sum_referral_bonuses = AsyncMock(return_value=0)

        await credit_referral_bonus(users, payments, user_id=42, price_rub=1000, payment_id=1)

        users.credit_balance.assert_called_once_with(100, 100)

    async def test_payment_not_blocked_when_bonus_skipped(self) -> None:
        """Payment processing is NOT affected by referral limit -- only bonus is skipped."""
        users = MagicMock()
        payments = MagicMock()
        redis = MagicMock()

        buyer = MagicMock(referrer_id=100)
        referrer = MagicMock(id=100)
        users.get_by_id = AsyncMock(side_effect=lambda uid: buyer if uid == 42 else referrer)

        redis.incr = AsyncMock(return_value=MAX_REFERRAL_DAILY + 1)
        redis.expire = AsyncMock()
        redis.decr = AsyncMock()

        # This should complete without error (just skip bonus)
        await credit_referral_bonus(users, payments, user_id=42, price_rub=1000, payment_id=1, redis=redis)
        # No exception raised = payment flow continues normally


# ===========================================================================
# H15: Per-user pipeline generation rate limit
# ===========================================================================


class TestPipelineGenerationRateLimit:
    """H15: pipeline_generation rate limit (3 per 10 min)."""

    def test_rate_limit_configured(self) -> None:
        """RATE_LIMITS contains pipeline_generation entry."""
        assert "pipeline_generation" in RATE_LIMITS
        max_req, window = RATE_LIMITS["pipeline_generation"]
        assert max_req == 3
        assert window == 600  # 10 minutes

    async def test_confirm_generate_checks_pipeline_rate_limit(self) -> None:
        """confirm_generate should check pipeline_generation rate limit before text_generation."""
        from bot.exceptions import RateLimitError
        from routers.publishing.pipeline.generation import confirm_generate

        callback = MagicMock()
        callback.message = MagicMock()
        callback.answer = AsyncMock()
        callback.data = "pipeline:article:confirm"

        state = MagicMock()
        state.get_data = AsyncMock(return_value={
            "category_id": 10,
            "project_id": 1,
            "image_count": 4,
        })
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()

        user = make_user(id=42, balance=5000)
        db = MagicMock()
        redis = MagicMock()
        redis.set = AsyncMock(return_value="OK")
        redis.delete = AsyncMock()

        # Mock the rate limiter to raise on pipeline_generation
        with patch("routers.publishing.pipeline.generation.RateLimiter") as mock_rl_cls:
            mock_rl = MagicMock()
            mock_rl_cls.return_value = mock_rl

            # First call (pipeline_generation) raises
            mock_rl.check = AsyncMock(
                side_effect=RateLimitError(
                    message="Rate limit exceeded",
                    user_message="Too fast",
                    retry_after_seconds=300,
                )
            )

            with patch("routers.publishing.pipeline.generation._fresh_image_count", new_callable=AsyncMock, return_value=4):
                with patch("routers.publishing.pipeline.generation.get_settings") as mock_settings:
                    mock_settings.return_value = MagicMock(admin_ids=[])
                    await confirm_generate(
                        callback=callback,
                        state=state,
                        user=user,
                        db=db,
                        redis=redis,
                        http_client=MagicMock(),
                        ai_orchestrator=MagicMock(),
                        image_storage=MagicMock(),
                    )

            # Should show rate limit alert
            callback.answer.assert_called()
            call_args = callback.answer.call_args
            assert call_args[1].get("show_alert") is True
            assert "мин" in call_args[0][0]


# ===========================================================================
# H16: YooKassa webhook idempotency
# ===========================================================================


def _make_yookassa_request(
    body: dict | None = None,
    client_ip: str = "185.71.76.1",
    x_forwarded_for: str = "",
    webhook_result: dict | None = None,
    redis_set_return: str | None = "OK",
) -> web.Request:
    """Create a mock aiohttp request for YooKassa webhook with Redis."""
    mock_service = MagicMock()
    mock_service.process_webhook = AsyncMock(return_value=webhook_result)

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=redis_set_return)

    app = MagicMock()
    app.__getitem__ = MagicMock(
        side_effect=lambda key: {
            "db": MagicMock(),
            "http_client": MagicMock(),
            "yookassa_service": mock_service,
            "bot": mock_bot,
            "redis": mock_redis,
        }[key]
    )

    request = MagicMock()
    request.remote = client_ip
    request.app = app
    request.headers = MagicMock()
    request.headers.get = MagicMock(
        side_effect=lambda k, d="": x_forwarded_for if k == "X-Forwarded-For" else d,
    )

    if body is not None:
        request.json = AsyncMock(return_value=body)
    else:
        request.json = AsyncMock(side_effect=json.JSONDecodeError("err", "doc", 0))

    return request


class TestYooKassaIdempotency:
    """H16: Redis NX lock prevents duplicate payment.succeeded processing."""

    async def test_first_webhook_processes_normally(self) -> None:
        """First webhook with payment_id acquires lock and processes."""
        body = {
            "event": "payment.succeeded",
            "object": {"id": "yk_123", "metadata": {}},
        }
        request = _make_yookassa_request(body=body, x_forwarded_for="185.71.76.1")

        resp = await yookassa_webhook(request)

        assert resp.status == 200
        service = request.app["yookassa_service"]
        service.process_webhook.assert_called_once()

    async def test_duplicate_webhook_returns_200_without_processing(self) -> None:
        """Duplicate webhook (NX lock fails) returns 200 but does NOT process."""
        body = {
            "event": "payment.succeeded",
            "object": {"id": "yk_123", "metadata": {}},
        }
        request = _make_yookassa_request(
            body=body,
            x_forwarded_for="185.71.76.1",
            redis_set_return=None,  # NX lock failed = duplicate
        )

        resp = await yookassa_webhook(request)

        assert resp.status == 200
        service = request.app["yookassa_service"]
        service.process_webhook.assert_not_called()

    async def test_non_succeeded_events_skip_idempotency(self) -> None:
        """payment.canceled events should NOT use idempotency lock."""
        body = {
            "event": "payment.canceled",
            "object": {"id": "yk_456", "metadata": {}},
        }
        request = _make_yookassa_request(body=body, x_forwarded_for="185.71.76.1")

        resp = await yookassa_webhook(request)

        assert resp.status == 200
        service = request.app["yookassa_service"]
        service.process_webhook.assert_called_once()
        # Redis.set should NOT be called for non-succeeded events
        redis = request.app["redis"]
        redis.set.assert_not_called()

    async def test_idempotency_key_uses_payment_id(self) -> None:
        """The Redis key should include payment_id."""
        body = {
            "event": "payment.succeeded",
            "object": {"id": "yk_789", "metadata": {}},
        }
        request = _make_yookassa_request(body=body, x_forwarded_for="185.71.76.1")

        await yookassa_webhook(request)

        redis = request.app["redis"]
        redis.set.assert_called_once()
        call_args = redis.set.call_args
        assert "yk_789" in call_args[0][0]
        assert call_args[1]["nx"] is True
        assert call_args[1]["ex"] == _YOOKASSA_IDEMPOTENCY_TTL


# ===========================================================================
# H17: Project/category creation limits
# ===========================================================================


class TestProjectLimit:
    """H17: max 20 projects per user."""

    def test_max_projects_constant(self) -> None:
        assert MAX_PROJECTS_PER_USER == 20

    async def test_blocks_creation_at_limit(self) -> None:
        """start_create should reject when user already has MAX_PROJECTS_PER_USER."""
        from routers.projects.create import start_create

        callback = MagicMock()
        callback.message = MagicMock()
        callback.answer = AsyncMock()
        callback.data = "project:create"

        state = MagicMock()
        state.set_state = AsyncMock()
        state.update_data = AsyncMock()

        user = make_user(id=42)
        db = MagicMock()

        with patch("routers.projects.create.ProjectsRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_count_by_user = AsyncMock(return_value=MAX_PROJECTS_PER_USER)

            await start_create(callback=callback, state=state, user=user, db=db)

        callback.answer.assert_called_once()
        call_args = callback.answer.call_args
        assert call_args[1].get("show_alert") is True
        assert str(MAX_PROJECTS_PER_USER) in call_args[0][0]
        state.set_state.assert_not_called()

    async def test_allows_creation_under_limit(self) -> None:
        """start_create should proceed when user has less than MAX_PROJECTS_PER_USER."""
        from routers.projects.create import start_create

        callback = MagicMock()
        callback.message = MagicMock()
        callback.message.answer = AsyncMock()
        callback.answer = AsyncMock()
        callback.data = "project:create"

        state = MagicMock()
        state.set_state = AsyncMock()
        state.update_data = AsyncMock()
        state.get_state = AsyncMock(return_value=None)

        user = make_user(id=42)
        db = MagicMock()

        with patch("routers.projects.create.ProjectsRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_count_by_user = AsyncMock(return_value=5)

            with patch("routers.projects.create.ensure_no_active_fsm", new_callable=AsyncMock, return_value=None):
                await start_create(callback=callback, state=state, user=user, db=db)

        state.set_state.assert_called_once()


class TestCategoryLimit:
    """H17: max 50 categories per project."""

    def test_max_categories_constant(self) -> None:
        assert MAX_CATEGORIES_PER_PROJECT == 50

    async def test_blocks_creation_at_limit(self) -> None:
        """start_category_create should reject when project has MAX_CATEGORIES_PER_PROJECT."""
        from routers.categories.manage import start_category_create

        callback = MagicMock()
        callback.message = MagicMock()
        callback.message.answer = AsyncMock()
        callback.answer = AsyncMock()
        callback.data = "category:1:create"

        state = MagicMock()
        state.set_state = AsyncMock()
        state.update_data = AsyncMock()

        user = make_user(id=42)
        db = MagicMock()

        project = MagicMock(id=1, user_id=42)

        with (
            patch("routers.categories.manage.ProjectsRepository") as mock_proj_cls,
            patch("routers.categories.manage.CategoriesRepository") as mock_cat_cls,
        ):
            mock_proj = MagicMock()
            mock_proj_cls.return_value = mock_proj
            mock_proj.get_by_id = AsyncMock(return_value=project)

            mock_cat = MagicMock()
            mock_cat_cls.return_value = mock_cat
            mock_cat.get_count_by_project = AsyncMock(return_value=MAX_CATEGORIES_PER_PROJECT)

            await start_category_create(callback=callback, state=state, user=user, db=db)

        callback.answer.assert_called()
        call_args = callback.answer.call_args
        assert call_args[1].get("show_alert") is True
        assert str(MAX_CATEGORIES_PER_PROJECT) in call_args[0][0]
        state.set_state.assert_not_called()

    async def test_allows_creation_under_limit(self) -> None:
        """start_category_create should proceed when project has room."""
        from routers.categories.manage import start_category_create

        callback = MagicMock()
        callback.message = MagicMock()
        callback.message.answer = AsyncMock()
        callback.answer = AsyncMock()
        callback.data = "category:1:create"

        state = MagicMock()
        state.set_state = AsyncMock()
        state.update_data = AsyncMock()
        state.get_state = AsyncMock(return_value=None)

        user = make_user(id=42)
        db = MagicMock()

        project = MagicMock(id=1, user_id=42)

        with (
            patch("routers.categories.manage.ProjectsRepository") as mock_proj_cls,
            patch("routers.categories.manage.CategoriesRepository") as mock_cat_cls,
            patch("routers.categories.manage.ensure_no_active_fsm", new_callable=AsyncMock, return_value=None),
        ):
            mock_proj = MagicMock()
            mock_proj_cls.return_value = mock_proj
            mock_proj.get_by_id = AsyncMock(return_value=project)

            mock_cat = MagicMock()
            mock_cat_cls.return_value = mock_cat
            mock_cat.get_count_by_project = AsyncMock(return_value=10)

            await start_category_create(callback=callback, state=state, user=user, db=db)

        state.set_state.assert_called_once()


# ===========================================================================
# Repository methods
# ===========================================================================


class TestPaymentsRepoSumReferralBonuses:
    """Test sum_referral_bonuses repository method."""

    async def test_sum_referral_bonuses_returns_total(self) -> None:
        """sum_referral_bonuses should sum all positive referral expenses."""
        from tests.unit.db.repositories.conftest import MockResponse, MockSupabaseClient

        db = MockSupabaseClient()
        db.set_response("token_expenses", MockResponse(data=[
            {"amount": 100},
            {"amount": 50},
            {"amount": 200},
        ]))

        repo = PaymentsRepository(db)  # type: ignore[arg-type]
        total = await repo.sum_referral_bonuses(42)

        assert total == 350

    async def test_sum_referral_bonuses_returns_zero_on_empty(self) -> None:
        """sum_referral_bonuses returns 0 when no referral expenses exist."""
        from tests.unit.db.repositories.conftest import MockResponse, MockSupabaseClient

        db = MockSupabaseClient()
        db.set_response("token_expenses", MockResponse(data=[]))

        repo = PaymentsRepository(db)  # type: ignore[arg-type]
        total = await repo.sum_referral_bonuses(42)

        assert total == 0


class TestCategoriesRepoGetCountByProject:
    """Test get_count_by_project repository method."""

    async def test_returns_count(self) -> None:
        """get_count_by_project returns the count from PostgREST."""
        from tests.unit.db.repositories.conftest import MockResponse, MockSupabaseClient

        db = MockSupabaseClient()
        db.set_response("categories", MockResponse(data=[], count=15))

        repo = CategoriesRepository(db)  # type: ignore[arg-type]
        count = await repo.get_count_by_project(1)

        assert count == 15

    async def test_returns_zero_when_empty(self) -> None:
        """get_count_by_project returns 0 when no categories exist."""
        from tests.unit.db.repositories.conftest import MockResponse, MockSupabaseClient

        db = MockSupabaseClient()
        db.set_response("categories", MockResponse(data=[], count=0))

        repo = CategoriesRepository(db)  # type: ignore[arg-type]
        count = await repo.get_count_by_project(1)

        assert count == 0


# ===========================================================================
# CacheKeys
# ===========================================================================


class TestCacheKeysNewMethods:
    """Test new CacheKeys methods."""

    def test_referral_daily_key(self) -> None:
        key = CacheKeys.referral_daily(42, "2026-02-27")
        assert key == "referral_daily:42:2026-02-27"

    def test_yookassa_idempotency_key(self) -> None:
        key = CacheKeys.yookassa_idempotency("yk_abc123")
        assert key == "yookassa_payment:yk_abc123"
