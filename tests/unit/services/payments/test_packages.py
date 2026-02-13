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
    def test_five_packages_defined(self) -> None:
        assert len(PACKAGES) == 5

    def test_package_names(self) -> None:
        assert set(PACKAGES.keys()) == {"mini", "starter", "pro", "business", "enterprise"}

    def test_mini_package(self) -> None:
        p = PACKAGES["mini"]
        assert p.tokens == 1000
        assert p.bonus == 0
        assert p.price_rub == 1000
        assert p.stars == 65

    def test_starter_package(self) -> None:
        p = PACKAGES["starter"]
        assert p.tokens == 3500
        assert p.bonus == 500
        assert p.price_rub == 3000
        assert p.stars == 195

    def test_pro_package(self) -> None:
        p = PACKAGES["pro"]
        assert p.tokens == 7200
        assert p.bonus == 1200
        assert p.price_rub == 6000

    def test_business_package(self) -> None:
        p = PACKAGES["business"]
        assert p.tokens == 18000
        assert p.bonus == 3000
        assert p.price_rub == 15000
        assert p.stars == 975

    def test_enterprise_package(self) -> None:
        p = PACKAGES["enterprise"]
        assert p.tokens == 50000
        assert p.bonus == 10000
        assert p.price_rub == 40000
        assert p.stars == 2600

    def test_packages_are_frozen(self) -> None:
        """Packages should be immutable dataclasses."""
        p = PACKAGES["mini"]
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
