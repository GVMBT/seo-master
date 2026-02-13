"""Tests for services/ai/rate_limiter.py — Redis-backed per-action rate limiting.

Covers: under-limit pass-through, over-limit rejection (with DECR undo),
unknown actions, TTL lifecycle, user isolation, batch check.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from bot.exceptions import RateLimitError
from services.ai.rate_limiter import RATE_LIMITS, RateLimiter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Mock RedisClient with async methods: incr, decr, incrby, decrby, expire, ttl, get."""
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=1)
    redis.decr = AsyncMock(return_value=0)
    redis.incrby = AsyncMock(return_value=1)
    redis.decrby = AsyncMock(return_value=0)
    redis.expire = AsyncMock(return_value=True)
    redis.ttl = AsyncMock(return_value=3500)
    redis.get = AsyncMock(return_value=None)
    return redis


@pytest.fixture
def limiter(mock_redis: AsyncMock) -> RateLimiter:
    return RateLimiter(redis=mock_redis)


# ---------------------------------------------------------------------------
# RATE_LIMITS config sanity
# ---------------------------------------------------------------------------


class TestRateLimitsConfig:
    def test_text_generation_limit(self) -> None:
        assert RATE_LIMITS["text_generation"] == (10, 3600)

    def test_image_generation_limit(self) -> None:
        assert RATE_LIMITS["image_generation"] == (20, 3600)

    def test_keyword_generation_limit(self) -> None:
        assert RATE_LIMITS["keyword_generation"] == (5, 3600)

    def test_token_purchase_limit(self) -> None:
        assert RATE_LIMITS["token_purchase"] == (5, 600)

    def test_platform_connection_limit(self) -> None:
        assert RATE_LIMITS["platform_connection"] == (10, 3600)


# ---------------------------------------------------------------------------
# check() — under limit (no exception)
# ---------------------------------------------------------------------------


class TestCheckUnderLimit:
    async def test_check_first_request_no_exception(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """First request (incr returns 1) should pass without raising."""
        mock_redis.incr.return_value = 1
        await limiter.check(123, "text_generation")
        # No exception raised

    async def test_check_at_exact_limit_no_exception(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """Request at exact max (e.g. 10th for text_generation) should pass."""
        mock_redis.incr.return_value = 10  # text_generation max = 10
        await limiter.check(123, "text_generation")

    async def test_check_midway_no_exception(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """Midway through the limit window (5/20 for image_generation) should pass."""
        mock_redis.incr.return_value = 5
        await limiter.check(123, "image_generation")
        # No exception raised — under limit

    async def test_check_incr_called_with_correct_key(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """Verifies the Redis key matches CacheKeys.rate_limit format."""
        mock_redis.incr.return_value = 1
        await limiter.check(42, "keyword_generation")
        mock_redis.incr.assert_awaited_once_with("rate:42:keyword_generation")


# ---------------------------------------------------------------------------
# check() — over limit (raises RateLimitError, with DECR undo)
# ---------------------------------------------------------------------------


class TestCheckOverLimit:
    async def test_check_over_limit_raises_rate_limit_error(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """11th text_generation request should raise RateLimitError."""
        mock_redis.incr.return_value = 11
        mock_redis.ttl.return_value = 2400
        with pytest.raises(RateLimitError):
            await limiter.check(123, "text_generation")

    async def test_check_over_limit_calls_decr(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """When over limit, counter must be decremented back (H13 fix)."""
        mock_redis.incr.return_value = 11
        mock_redis.ttl.return_value = 2400
        with pytest.raises(RateLimitError):
            await limiter.check(123, "text_generation")
        mock_redis.decr.assert_awaited_once_with("rate:123:text_generation")

    async def test_check_over_limit_error_message_contains_action(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """Error message should mention the action name."""
        mock_redis.incr.return_value = 6
        mock_redis.ttl.return_value = 300
        with pytest.raises(RateLimitError, match="keyword_generation"):
            await limiter.check(123, "keyword_generation")

    async def test_check_over_limit_error_message_contains_counts(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """Error message should include current count and max."""
        mock_redis.incr.return_value = 21
        mock_redis.ttl.return_value = 1800
        with pytest.raises(RateLimitError, match="21/20"):
            await limiter.check(123, "image_generation")

    async def test_check_over_limit_queries_ttl(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """When over limit, check() should query TTL for logging."""
        mock_redis.incr.return_value = 11
        mock_redis.ttl.return_value = 1234
        with pytest.raises(RateLimitError):
            await limiter.check(123, "text_generation")
        mock_redis.ttl.assert_awaited_once_with("rate:123:text_generation")

    async def test_check_over_limit_negative_ttl_clamped_to_zero(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """If TTL returns -1 (no expiry) or -2 (key gone), remaining_seconds should be 0."""
        mock_redis.incr.return_value = 11
        mock_redis.ttl.return_value = -1
        # Should still raise; the negative TTL is clamped via max(ttl, 0)
        with pytest.raises(RateLimitError):
            await limiter.check(123, "text_generation")

    async def test_check_token_purchase_over_limit(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """token_purchase has a 5/600s window; 6th request should raise."""
        mock_redis.incr.return_value = 6
        mock_redis.ttl.return_value = 400
        with pytest.raises(RateLimitError):
            await limiter.check(99, "token_purchase")


# ---------------------------------------------------------------------------
# check() — unknown action (no limit configured)
# ---------------------------------------------------------------------------


class TestCheckUnknownAction:
    async def test_check_unknown_action_no_exception(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """Unknown action should pass without touching Redis."""
        await limiter.check(123, "nonexistent_action")

    async def test_check_unknown_action_does_not_raise(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """Even calling multiple times with unknown action should never raise."""
        await limiter.check(123, "some_other_action")
        await limiter.check(123, "some_other_action")
        await limiter.check(123, "some_other_action")

    async def test_check_unknown_action_no_redis_calls(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """Redis should not be called at all for unconfigured actions."""
        await limiter.check(123, "unknown")
        mock_redis.incr.assert_not_awaited()
        mock_redis.expire.assert_not_awaited()
        mock_redis.ttl.assert_not_awaited()


# ---------------------------------------------------------------------------
# TTL lifecycle — set on first call, not reset on subsequent
# ---------------------------------------------------------------------------


class TestTTLLifecycle:
    async def test_check_sets_ttl_on_first_call(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """When incr returns 1 (first call), expire() must be called with the window."""
        mock_redis.incr.return_value = 1
        await limiter.check(123, "text_generation")
        mock_redis.expire.assert_awaited_once_with("rate:123:text_generation", 3600)

    async def test_check_sets_ttl_with_correct_window_token_purchase(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """token_purchase window is 600s, not 3600s."""
        mock_redis.incr.return_value = 1
        await limiter.check(77, "token_purchase")
        mock_redis.expire.assert_awaited_once_with("rate:77:token_purchase", 600)

    async def test_check_does_not_reset_ttl_on_second_call(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """When incr returns 2 (subsequent call), expire() must NOT be called."""
        mock_redis.incr.return_value = 2
        await limiter.check(123, "text_generation")
        mock_redis.expire.assert_not_awaited()

    async def test_check_does_not_reset_ttl_on_tenth_call(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """At the 10th call (still within limit), expire should not be called."""
        mock_redis.incr.return_value = 10
        await limiter.check(123, "text_generation")
        mock_redis.expire.assert_not_awaited()

    async def test_check_does_not_reset_ttl_on_over_limit(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """Even when over limit, expire() should NOT be called (only on incr==1)."""
        mock_redis.incr.return_value = 11
        mock_redis.ttl.return_value = 2000
        with pytest.raises(RateLimitError):
            await limiter.check(123, "text_generation")
        mock_redis.expire.assert_not_awaited()


# ---------------------------------------------------------------------------
# User isolation — different users have independent counters
# ---------------------------------------------------------------------------


class TestUserIsolation:
    async def test_different_users_independent_counters(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """Two different users should use different Redis keys."""
        mock_redis.incr.return_value = 1
        await limiter.check(100, "text_generation")
        await limiter.check(200, "text_generation")

        incr_calls = mock_redis.incr.call_args_list
        assert len(incr_calls) == 2
        assert incr_calls[0].args[0] == "rate:100:text_generation"
        assert incr_calls[1].args[0] == "rate:200:text_generation"

    async def test_user_over_limit_does_not_affect_other_user(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """User A exceeding limit should not block user B."""
        # User A: over limit
        mock_redis.incr.return_value = 11
        mock_redis.ttl.return_value = 3000
        with pytest.raises(RateLimitError):
            await limiter.check(100, "text_generation")

        # User B: first request, under limit
        mock_redis.incr.return_value = 1
        await limiter.check(200, "text_generation")
        # No exception for user B

    async def test_different_actions_independent_counters(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """Same user, different actions should use different Redis keys."""
        mock_redis.incr.return_value = 1
        await limiter.check(123, "text_generation")
        await limiter.check(123, "image_generation")

        incr_calls = mock_redis.incr.call_args_list
        assert len(incr_calls) == 2
        assert incr_calls[0].args[0] == "rate:123:text_generation"
        assert incr_calls[1].args[0] == "rate:123:image_generation"


# ---------------------------------------------------------------------------
# RateLimitError properties
# ---------------------------------------------------------------------------


class TestRateLimitErrorProperties:
    async def test_rate_limit_error_is_app_error(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """RateLimitError should be an AppError subclass."""
        from bot.exceptions import AppError

        mock_redis.incr.return_value = 11
        mock_redis.ttl.return_value = 1000
        with pytest.raises(AppError):
            await limiter.check(123, "text_generation")

    async def test_rate_limit_error_has_user_message(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """RateLimitError should have a Russian user_message."""
        mock_redis.incr.return_value = 6
        mock_redis.ttl.return_value = 500
        with pytest.raises(RateLimitError) as exc_info:
            await limiter.check(123, "keyword_generation")
        assert exc_info.value.user_message  # non-empty


# ---------------------------------------------------------------------------
# check_batch() — batch rate limit for parallel image generation (H14)
# ---------------------------------------------------------------------------


class TestCheckBatch:
    async def test_batch_under_limit_passes(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """Batch of 4 images when 0 used (max 20) should pass."""
        mock_redis.get.return_value = None  # key doesn't exist
        mock_redis.incrby.return_value = 4
        await limiter.check_batch(123, "image_generation", 4)
        mock_redis.incrby.assert_awaited_once_with("rate:123:image_generation", 4)

    async def test_batch_at_exact_limit_passes(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """Batch that exactly fills remaining slots should pass."""
        mock_redis.get.return_value = "16"
        mock_redis.incrby.return_value = 20  # 16 + 4 = 20 = max
        await limiter.check_batch(123, "image_generation", 4)
        # No exception

    async def test_batch_over_limit_raises_and_undoes(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """Batch that would exceed limit should raise and DECRBY."""
        mock_redis.get.return_value = "18"
        mock_redis.incrby.return_value = 22  # 18 + 4 = 22 > 20
        mock_redis.ttl.return_value = 2000
        with pytest.raises(RateLimitError):
            await limiter.check_batch(123, "image_generation", 4)
        mock_redis.decrby.assert_awaited_once_with("rate:123:image_generation", 4)

    async def test_batch_sets_ttl_on_new_key(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """TTL should be set when key was just created (first batch)."""
        mock_redis.get.return_value = None  # key doesn't exist
        mock_redis.incrby.return_value = 4
        await limiter.check_batch(123, "image_generation", 4)
        mock_redis.expire.assert_awaited_once_with("rate:123:image_generation", 3600)

    async def test_batch_does_not_reset_ttl_on_existing_key(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """TTL should NOT be reset when key already exists."""
        mock_redis.get.return_value = "5"
        mock_redis.incrby.return_value = 9
        await limiter.check_batch(123, "image_generation", 4)
        mock_redis.expire.assert_not_awaited()

    async def test_batch_unknown_action_no_effect(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """Unknown action should not touch Redis."""
        await limiter.check_batch(123, "nonexistent_action", 5)
        mock_redis.incrby.assert_not_awaited()

    async def test_batch_zero_count_no_effect(
        self, limiter: RateLimiter, mock_redis: AsyncMock
    ) -> None:
        """count=0 should not touch Redis."""
        await limiter.check_batch(123, "image_generation", 0)
        mock_redis.incrby.assert_not_awaited()
