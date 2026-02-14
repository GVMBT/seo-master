"""Anti-hallucination checks for AI-generated content.

Checks for fabricated prices, contacts, and statistics in generated HTML.
Source of truth: API_CONTRACTS.md section 3.7 (check_fabricated_data).

E48: price mismatch is warning, not error — does NOT block publish.
"""

from __future__ import annotations

import re

# Pattern for Russian currency amounts: digits (with optional spaces) followed by currency marker
_PRICE_RE = re.compile(r"(\d[\d\s]*)\s*(?:руб|₽|рублей)", re.IGNORECASE)

# Pattern for Russian phone numbers: +7 or 8, then 10 digits with optional separators
_PHONE_RE = re.compile(r"\+?[78]\s*[\(-]?\d{3}[\)-]?\s*\d{3}[\s-]?\d{2}[\s-]?\d{2}")

# Patterns indicating potentially fabricated statistics
_FAKE_STATS_RE = re.compile(
    r"(?:по данным|согласно|исследовани[ея]|опрос|статистик)",
    re.IGNORECASE,
)


def extract_prices(text: str) -> list[int]:
    """Extract numeric prices from text containing Russian currency markers.

    Handles formats like: "10 000 rub", "5000 RUB", "1500 rublej".
    Whitespace within digit groups is stripped before conversion.
    """
    matches = _PRICE_RE.findall(text)
    prices: list[int] = []
    for raw in matches:
        cleaned = raw.replace(" ", "").replace("\u00a0", "")
        if cleaned.isdigit():
            prices.append(int(cleaned))
    return prices


def check_fabricated_data(
    html: str,
    prices_excerpt: str,
    advantages: str,
) -> list[str]:
    """Check for hallucinated prices, contacts, and statistics in AI-generated content.

    Returns a list of warning strings (not errors -- does NOT block publish).
    E48: price mismatch is a warning, not an error.

    Checks:
    1. Prices in text match prices_excerpt (within 20% tolerance)
    2. Phone numbers not in advantages should not appear in text
    3. Fake statistics phrases ("by research data", "according to survey")
    """
    issues: list[str] = []

    # 1. Price validation: compare text prices against known prices
    text_prices = extract_prices(html)
    known_prices = extract_prices(prices_excerpt)

    for price in text_prices:
        if known_prices:
            # Check if the price is within 20% of any known price
            match_found = any(
                abs(price - known) / max(known, 1) < 0.2 for known in known_prices
            )
            if not match_found:
                issues.append(
                    f"Возможно выдуманная цена: {price} руб. (нет в прайсе)"
                )
        # If no known prices at all, we cannot validate -- skip

    # 2. Phone number check: phones in text but not in company data
    if _PHONE_RE.search(html) and not _PHONE_RE.search(advantages):
        issues.append("Найден телефон, не указанный в данных компании")

    # 3. Fake statistics detection
    if _FAKE_STATS_RE.search(html):
        issues.append("Возможна фабрикованная статистика — проверить источник")

    return issues
