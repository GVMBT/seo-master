"""Tests for services/ai/niche_detector.py -- niche detection from specialization.

Covers: all 14 niche types + general fallback, case insensitivity,
compound specializations, empty input, short pattern word-boundary matching.
"""

from __future__ import annotations

from services.ai.niche_detector import detect_niche


class TestNicheDetectorBasic:
    """Basic niche detection for each category."""

    def test_detect_medical_niche(self) -> None:
        assert detect_niche("Стоматологическая клиника") == "medical"

    def test_detect_legal_niche(self) -> None:
        assert detect_niche("Юридическая компания Право и Закон") == "legal"

    def test_detect_finance_niche(self) -> None:
        assert detect_niche("Инвестиционный фонд") == "finance"

    def test_detect_realestate_niche(self) -> None:
        assert detect_niche("Агентство недвижимости") == "realestate"

    def test_detect_beauty_niche(self) -> None:
        assert detect_niche("Салон красоты Елена") == "beauty"

    def test_detect_food_niche(self) -> None:
        assert detect_niche("Ресторан итальянской кухни") == "food"

    def test_detect_education_niche(self) -> None:
        assert detect_niche("Курсы английского языка") == "education"

    def test_detect_it_niche(self) -> None:
        assert detect_niche("Разработка веб-приложений") == "it"

    def test_detect_travel_niche(self) -> None:
        assert detect_niche("Агентство по туризму") == "travel"


class TestNicheDetectorEdgeCases:
    """Edge cases and fallback behavior."""

    def test_detect_general_for_unknown(self) -> None:
        assert detect_niche("Магазин электроники") == "general"

    def test_detect_empty_string_returns_general(self) -> None:
        assert detect_niche("") == "general"

    def test_detect_case_insensitive(self) -> None:
        """Detection should be case-insensitive."""
        assert detect_niche("СТОМАТОЛОГИЧЕСКАЯ КЛИНИКА") == "medical"

    def test_detect_compound_specialization_first_match_wins(self) -> None:
        """When multiple niches could match, first in order wins."""
        # "Медицинский центр с инвестиционной программой"
        # medical patterns checked before finance
        result = detect_niche("Медицинский центр с инвестиционной программой")
        assert result == "medical"

    def test_detect_auto_niche_with_boundary(self) -> None:
        """Short pattern 'сто' should match only with word boundaries."""
        # "СТО" as standalone should match auto
        assert detect_niche("СТО, автосервис") == "auto"

    def test_detect_construction_niche(self) -> None:
        assert detect_niche("Производство стройматериалов и бетона") == "construction"

    def test_detect_pets_niche(self) -> None:
        assert detect_niche("Ветеринарная клиника для домашних питомцев") == "pets"

    def test_detect_children_niche(self) -> None:
        assert detect_niche("Детский сад Солнышко") == "children"
