"""Detect business niche from project specialization for YMYL disclaimers and tone adaptation.

Source of truth: API_CONTRACTS.md section 5, variable niche_type.
"""

from __future__ import annotations

import re

# Niche keyword patterns: niche_name -> list of keyword stems/substrings (case-insensitive)
# ORDER MATTERS: more specific niches (pets, beauty) before generic (medical) to avoid
# false positives like "ветеринарная клиника" matching "клиник" from medical first.
_NICHE_PATTERNS: list[tuple[str, list[str]]] = [
    ("pets", ["ветеринар", "животн", "питомец", "зоомагазин"]),
    ("beauty", ["красот", "маникюр", "парикмах", "салон красоты", "косметолог"]),
    ("children", ["детск", "ребёнок", "игруш", "детский сад"]),
    ("medical", ["медиц", "клиник", "врач", "здоров", "стомат", "лечен"]),
    ("legal", ["юрид", "адвокат", "право", "нотариус", "суд"]),
    ("finance", ["финанс", "банк", "инвест", "страхов", "кредит", "ипотек", "бухгалтер"]),
    ("realestate", ["недвижим", "квартир", "дом", "строительств", "ремонт"]),
    ("auto", ["авто", "машин", "шин", "гараж", "сто", "осаго"]),
    ("food", ["еда", "ресторан", "кафе", "доставка еды", "кулинар", "кондитер"]),
    ("education", ["образован", "курс", "обучен", "школ", "универс", "репетитор"]),
    ("it", ["программ", "разработ", "сайт", "приложен", "it", "веб"]),
    ("travel", ["туризм", "путешеств", "отель", "гостиниц", "тур", "экскурс"]),
    ("sport", ["спорт", "фитнес", "тренажер", "йога", "бассейн"]),
    ("construction", ["стройматериал", "бетон", "кирпич", "фундамент"]),
]


def detect_niche(specialization: str) -> str:
    """Detect business niche from project specialization string.

    Uses case-insensitive substring matching against known niche patterns.

    Returns one of: medical, legal, finance, realestate, auto, beauty, food,
    education, it, travel, sport, children, pets, construction, general.
    """
    if not specialization:
        return "general"

    lower = specialization.lower()

    for niche, patterns in _NICHE_PATTERNS:
        for pattern in patterns:
            # Use word-boundary-aware search for short patterns like "it"
            # to avoid false positives (e.g. "history" matching "it")
            if len(pattern) <= 3:
                # For very short patterns, require word boundary or start/end
                if re.search(rf"(?:^|\s|,|;){re.escape(pattern)}(?:\s|,|;|$)", lower):
                    return niche
            elif pattern in lower:
                return niche

    return "general"
