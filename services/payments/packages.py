"""Token package and subscription definitions.

Source of truth: PRD.md §5.4 — Stars маппинг и тарифы.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Package:
    """One-time token package."""

    name: str
    tokens: int  # total tokens credited (base + bonus)
    bonus: int
    price_rub: int
    stars: int  # Stars amount for Telegram invoice


@dataclass(frozen=True, slots=True)
class Subscription:
    """Monthly auto-renewing subscription."""

    name: str
    tokens_per_month: int
    price_rub: int
    stars: int
    period_seconds: int = 2_592_000  # 30 days


# ---------------------------------------------------------------------------
# Package catalogue (PRD §5.4)
# ---------------------------------------------------------------------------

PACKAGES: dict[str, Package] = {
    "mini": Package(name="mini", tokens=1000, bonus=0, price_rub=1000, stars=65),
    "starter": Package(name="starter", tokens=3500, bonus=500, price_rub=3000, stars=195),
    "pro": Package(name="pro", tokens=7200, bonus=1200, price_rub=6000, stars=390),
    "business": Package(name="business", tokens=18000, bonus=3000, price_rub=15000, stars=975),
    "enterprise": Package(name="enterprise", tokens=50000, bonus=10000, price_rub=40000, stars=2600),
}

# ---------------------------------------------------------------------------
# Subscription catalogue (PRD §5.4)
# ---------------------------------------------------------------------------

SUBSCRIPTIONS: dict[str, Subscription] = {
    "pro": Subscription(name="pro", tokens_per_month=7200, price_rub=6000, stars=390),
    "business": Subscription(name="business", tokens_per_month=18000, price_rub=15000, stars=975),
    "enterprise": Subscription(name="enterprise", tokens_per_month=50000, price_rub=40000, stars=2600),
}

# Referral bonus percentage (PRD §5.4, F19)
REFERRAL_BONUS_PERCENT = 10
