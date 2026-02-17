"""Tests for services/payments/packages.py — package/subscription catalogue."""

from __future__ import annotations

from services.payments.packages import (
    PACKAGES,
    REFERRAL_BONUS_PERCENT,
    SUBSCRIPTIONS,
    Package,
    Subscription,
)


class TestPackageCatalogue:
    def test_three_packages_defined(self) -> None:
        assert len(PACKAGES) == 3

    def test_package_names(self) -> None:
        assert set(PACKAGES.keys()) == {"start", "standard", "pro"}

    def test_start_package(self) -> None:
        p = PACKAGES["start"]
        assert p.tokens == 500
        assert p.bonus == 0
        assert p.price_rub == 500
        assert p.stars == 33

    def test_standard_package(self) -> None:
        p = PACKAGES["standard"]
        assert p.tokens == 2000
        assert p.bonus == 0
        assert p.price_rub == 1600
        assert p.stars == 104

    def test_pro_package(self) -> None:
        p = PACKAGES["pro"]
        assert p.tokens == 5000
        assert p.bonus == 0
        assert p.price_rub == 3000
        assert p.stars == 195

    def test_packages_are_frozen(self) -> None:
        """Packages should be immutable dataclasses."""
        p = PACKAGES["start"]
        assert isinstance(p, Package)

    def test_tokens_include_bonus(self) -> None:
        """tokens = base + bonus for all packages."""
        for name, pkg in PACKAGES.items():
            base = pkg.tokens - pkg.bonus
            assert base > 0, f"Package {name} has non-positive base tokens"


class TestSubscriptionCatalogue:
    def test_three_subscriptions_defined(self) -> None:
        assert len(SUBSCRIPTIONS) == 3

    def test_subscription_names(self) -> None:
        assert set(SUBSCRIPTIONS.keys()) == {"pro", "business", "enterprise"}

    def test_period_seconds_30_days(self) -> None:
        for sub in SUBSCRIPTIONS.values():
            assert sub.period_seconds == 2_592_000

    def test_pro_subscription(self) -> None:
        s = SUBSCRIPTIONS["pro"]
        assert s.tokens_per_month == 7200
        assert s.price_rub == 6000
        assert s.stars == 390

    def test_subscriptions_are_frozen(self) -> None:
        s = SUBSCRIPTIONS["pro"]
        assert isinstance(s, Subscription)


class TestReferralBonus:
    def test_bonus_percent(self) -> None:
        assert REFERRAL_BONUS_PERCENT == 10
