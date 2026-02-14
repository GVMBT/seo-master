"""Tests for services/ai/anti_hallucination.py -- fabricated data detection.

Covers: price extraction, price mismatch warnings, phone number detection,
fake statistics detection, E48 (warning not error), empty inputs.
"""

from __future__ import annotations

from services.ai.anti_hallucination import check_fabricated_data, extract_prices


class TestExtractPrices:
    """Tests for extract_prices helper."""

    def test_extract_single_price_rub(self) -> None:
        prices = extract_prices("Стоимость: 5000 руб")
        assert prices == [5000]

    def test_extract_price_with_ruble_sign(self) -> None:
        prices = extract_prices("Цена: 3500₽")
        assert prices == [3500]

    def test_extract_price_with_spaces_in_number(self) -> None:
        prices = extract_prices("от 10 000 рублей")
        assert prices == [10000]

    def test_extract_multiple_prices(self) -> None:
        text = "Услуга А: 5000 руб, услуга Б: 12 000₽"
        prices = extract_prices(text)
        assert 5000 in prices
        assert 12000 in prices

    def test_extract_no_prices_returns_empty(self) -> None:
        prices = extract_prices("Текст без цен и чисел")
        assert prices == []

    def test_extract_prices_empty_string(self) -> None:
        assert extract_prices("") == []


class TestCheckFabricatedData:
    """Tests for check_fabricated_data main function."""

    def test_matching_prices_no_warnings(self) -> None:
        html = "<p>Стоимость услуги: 5000 руб</p>"
        prices_excerpt = "Базовая услуга: 5000 руб"
        result = check_fabricated_data(html, prices_excerpt, "")
        # Price matches exactly -- no price warning
        price_warnings = [w for w in result if "цена" in w.lower()]
        assert len(price_warnings) == 0

    def test_price_within_tolerance_no_warning(self) -> None:
        """Prices within 20% tolerance should not trigger warning."""
        html = "<p>от 4500 руб</p>"
        prices_excerpt = "Услуга: 5000 руб"
        result = check_fabricated_data(html, prices_excerpt, "")
        price_warnings = [w for w in result if "цена" in w.lower()]
        assert len(price_warnings) == 0

    def test_mismatched_price_produces_warning_e48(self) -> None:
        """E48: price mismatch is warning, not error."""
        html = "<p>Стоимость: 99000 руб</p>"
        prices_excerpt = "Услуга: 5000 руб"
        result = check_fabricated_data(html, prices_excerpt, "")
        assert any("99000" in w for w in result)

    def test_phone_not_in_advantages_produces_warning(self) -> None:
        html = "<p>Звоните: +7 (495) 123-45-67</p>"
        result = check_fabricated_data(html, "", "Доставка по Москве")
        assert any("телефон" in w.lower() for w in result)

    def test_phone_in_advantages_no_warning(self) -> None:
        html = "<p>Звоните: +7 (495) 123-45-67</p>"
        advantages = "Телефон: +7 (495) 123-45-67"
        result = check_fabricated_data(html, "", advantages)
        assert not any("телефон" in w.lower() for w in result)

    def test_fake_statistics_detected(self) -> None:
        html = "<p>По данным исследований, 90% клиентов довольны</p>"
        result = check_fabricated_data(html, "", "")
        assert any("статистик" in w.lower() for w in result)

    def test_clean_content_no_warnings(self) -> None:
        html = "<p>Наша компания предлагает качественный сервис.</p>"
        result = check_fabricated_data(html, "", "")
        assert result == []

    def test_no_known_prices_no_price_warning(self) -> None:
        """If prices_excerpt is empty, text prices are not flagged."""
        html = "<p>Стоимость: 15000 руб</p>"
        result = check_fabricated_data(html, "", "")
        price_warnings = [w for w in result if "цена" in w.lower()]
        assert len(price_warnings) == 0
