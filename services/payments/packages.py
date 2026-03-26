"""Token package definitions.

Source of truth: PRD.md §5.4 — Stars маппинг и тарифы.
No subscriptions in v2 — users buy packages when needed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Package:
    """One-time token package."""

    name: str
    label: str  # Russian display name
    tokens: int  # base tokens (before bonus)
    bonus: int  # bonus tokens on top of base
    price_rub: int
    discount: str  # display discount, e.g. "+500 бонус" or ""
    stars: int  # Stars amount for Telegram invoice

    @property
    def total_tokens(self) -> int:
        """Total tokens credited (base + bonus)."""
        return self.tokens + self.bonus


# ---------------------------------------------------------------------------
# Package catalogue (5 tariffs)
# Stars: 1 Star ≈ 1.10 RUB developer revenue ($0.013/Star, ToS §6.2)
# Target: ~77-86% margin on Stars, ~35% of RUB price for user
# ---------------------------------------------------------------------------

PACKAGES: dict[str, Package] = {
    "mini": Package(
        name="mini",
        label="Мини",
        tokens=1000,
        bonus=0,
        price_rub=1000,
        discount="",
        stars=260,
    ),
    "start": Package(
        name="start",
        label="Старт",
        tokens=3000,
        bonus=500,
        price_rub=3000,
        discount="+500 бонус",
        stars=780,
    ),
    "profi": Package(
        name="profi",
        label="Профи",
        tokens=6000,
        bonus=1200,
        price_rub=6000,
        discount="+1 200 бонус",
        stars=1560,
    ),
    "business": Package(
        name="business",
        label="Бизнес",
        tokens=15000,
        bonus=3000,
        price_rub=15000,
        discount="+3 000 бонус",
        stars=3900,
    ),
    "maximum": Package(
        name="maximum",
        label="Максимум",
        tokens=40000,
        bonus=10000,
        price_rub=40000,
        discount="+10 000 бонус",
        stars=10400,
    ),
}

# Legacy name mapping for backward compatibility (old payloads in flight)
_LEGACY_PACKAGES: dict[str, str] = {
    "standard": "start",
    "pro": "profi",
}


def get_package(name: str) -> Package | None:
    """Resolve package by name with legacy fallback.

    Old "standard"/"pro" names are transparently mapped to new names
    so that in-flight pre_checkout payloads and YooKassa webhooks
    with legacy package names still resolve correctly.
    """
    resolved = _LEGACY_PACKAGES.get(name, name)
    return PACKAGES.get(resolved)


# Referral bonus percentage (PRD §5.4, F19)
REFERRAL_BONUS_PERCENT = 10
