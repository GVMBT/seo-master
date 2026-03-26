"""Tests for services/payments/packages.py — package catalogue (PRD §5.4, 5 tariffs)."""

from __future__ import annotations

from services.payments.packages import (
    PACKAGES,
    REFERRAL_BONUS_PERCENT,
    Package,
    get_package,
)


class TestPackageCatalogue:
    def test_five_packages_defined(self) -> None:
        assert len(PACKAGES) == 5

    def test_package_names(self) -> None:
        assert set(PACKAGES.keys()) == {"mini", "start", "profi", "business", "maximum"}

    def test_mini_package(self) -> None:
        p = PACKAGES["mini"]
        assert p.tokens == 1000
        assert p.bonus == 0
        assert p.total_tokens == 1000
        assert p.price_rub == 1000
        assert p.stars == 260
        assert p.discount == ""
        assert p.label == "Мини"

    def test_start_package(self) -> None:
        p = PACKAGES["start"]
        assert p.tokens == 3000
        assert p.bonus == 500
        assert p.total_tokens == 3500
        assert p.price_rub == 3000
        assert p.stars == 780
        assert p.discount == "+500 бонус"
        assert p.label == "Старт"

    def test_profi_package(self) -> None:
        p = PACKAGES["profi"]
        assert p.tokens == 6000
        assert p.bonus == 1200
        assert p.total_tokens == 7200
        assert p.price_rub == 6000
        assert p.stars == 1560
        assert p.discount == "+1 200 бонус"
        assert p.label == "Профи"

    def test_business_package(self) -> None:
        p = PACKAGES["business"]
        assert p.tokens == 15000
        assert p.bonus == 3000
        assert p.total_tokens == 18000
        assert p.price_rub == 15000
        assert p.stars == 3900
        assert p.label == "Бизнес"

    def test_maximum_package(self) -> None:
        p = PACKAGES["maximum"]
        assert p.tokens == 40000
        assert p.bonus == 10000
        assert p.total_tokens == 50000
        assert p.price_rub == 40000
        assert p.stars == 10400
        assert p.label == "Максимум"

    def test_packages_are_frozen(self) -> None:
        """Packages should be immutable dataclasses."""
        p = PACKAGES["mini"]
        assert isinstance(p, Package)

    def test_all_tokens_positive(self) -> None:
        for name, pkg in PACKAGES.items():
            assert pkg.tokens > 0, f"Package {name} has non-positive tokens"

    def test_total_tokens_includes_bonus(self) -> None:
        """total_tokens = tokens + bonus for all packages."""
        for name, pkg in PACKAGES.items():
            assert pkg.total_tokens == pkg.tokens + pkg.bonus, f"Package {name} total mismatch"

    def test_price_per_total_token_decreases(self) -> None:
        """Bigger packages should have better or equal price per total token."""
        mini = PACKAGES["mini"].price_rub / PACKAGES["mini"].total_tokens
        start = PACKAGES["start"].price_rub / PACKAGES["start"].total_tokens
        profi = PACKAGES["profi"].price_rub / PACKAGES["profi"].total_tokens
        business = PACKAGES["business"].price_rub / PACKAGES["business"].total_tokens
        maximum = PACKAGES["maximum"].price_rub / PACKAGES["maximum"].total_tokens
        assert maximum <= business <= profi <= start <= mini
        # Mini (no bonus) is strictly worse than packages with bonuses
        assert start < mini


class TestGetPackage:
    def test_direct_name(self) -> None:
        pkg = get_package("mini")
        assert pkg is not None
        assert pkg.name == "mini"

    def test_legacy_standard_maps_to_start(self) -> None:
        pkg = get_package("standard")
        assert pkg is not None
        assert pkg.name == "start"

    def test_legacy_pro_maps_to_profi(self) -> None:
        pkg = get_package("pro")
        assert pkg is not None
        assert pkg.name == "profi"

    def test_unknown_returns_none(self) -> None:
        assert get_package("nonexistent") is None


class TestReferralBonus:
    def test_bonus_percent(self) -> None:
        assert REFERRAL_BONUS_PERCENT == 10
