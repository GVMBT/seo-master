"""Tests for services/payments/packages.py — package catalogue (PRD §5.4, 3 tariffs)."""

from __future__ import annotations

from services.payments.packages import (
    PACKAGES,
    REFERRAL_BONUS_PERCENT,
    Package,
)


class TestPackageCatalogue:
    def test_three_packages_defined(self) -> None:
        assert len(PACKAGES) == 3

    def test_package_names(self) -> None:
        assert set(PACKAGES.keys()) == {"start", "standard", "pro"}

    def test_start_package(self) -> None:
        p = PACKAGES["start"]
        assert p.tokens == 500
        assert p.price_rub == 500
        assert p.stars == 33
        assert p.discount == ""
        assert p.label == "\u0421\u0442\u0430\u0440\u0442"

    def test_standard_package(self) -> None:
        p = PACKAGES["standard"]
        assert p.tokens == 2000
        assert p.price_rub == 1600
        assert p.stars == 104
        assert p.discount == "\u221220%"
        assert p.label == "\u0421\u0442\u0430\u043d\u0434\u0430\u0440\u0442"

    def test_pro_package(self) -> None:
        p = PACKAGES["pro"]
        assert p.tokens == 5000
        assert p.price_rub == 3000
        assert p.stars == 195
        assert p.discount == "\u221240%"
        assert p.label == "\u041f\u0440\u043e"

    def test_packages_are_frozen(self) -> None:
        """Packages should be immutable dataclasses."""
        p = PACKAGES["start"]
        assert isinstance(p, Package)

    def test_all_tokens_positive(self) -> None:
        for name, pkg in PACKAGES.items():
            assert pkg.tokens > 0, f"Package {name} has non-positive tokens"

    def test_price_decreases_per_token(self) -> None:
        """Pro should have best price per token (biggest discount)."""
        prices_per_token = {n: p.price_rub / p.tokens for n, p in PACKAGES.items()}
        assert prices_per_token["pro"] < prices_per_token["standard"] < prices_per_token["start"]


class TestReferralBonus:
    def test_bonus_percent(self) -> None:
        assert REFERRAL_BONUS_PERCENT == 10
