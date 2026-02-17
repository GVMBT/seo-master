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
    tokens: int  # total tokens credited (base only, no bonus)
    price_rub: int
    discount: str  # display discount, e.g. "−20%" or ""
    stars: int  # Stars amount for Telegram invoice


# ---------------------------------------------------------------------------
# Package catalogue (PRD §5.4, 3 tariffs)
# Stars ≈ price_rub / 15.38 (approximate, hardcoded per PRD)
# ---------------------------------------------------------------------------

PACKAGES: dict[str, Package] = {
    "start": Package(
        name="start",
        label="\u0421\u0442\u0430\u0440\u0442",
        tokens=500,
        price_rub=500,
        discount="",
        stars=33,
    ),
    "standard": Package(
        name="standard",
        label="\u0421\u0442\u0430\u043d\u0434\u0430\u0440\u0442",
        tokens=2000,
        price_rub=1600,
        discount="\u221220%",
        stars=104,
    ),
    "pro": Package(
        name="pro",
        label="\u041f\u0440\u043e",
        tokens=5000,
        price_rub=3000,
        discount="\u221240%",
        stars=195,
    ),
}

# Referral bonus percentage (PRD §5.4, F19)
REFERRAL_BONUS_PERCENT = 10
