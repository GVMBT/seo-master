"""Tests for keyboards/category.py — category feature keyboard builders."""

from keyboards.category import (
    description_confirm_kb,
    description_existing_kb,
    description_result_kb,
    media_menu_kb,
    price_existing_kb,
    price_method_kb,
    price_result_kb,
    review_confirm_kb,
    review_existing_kb,
    review_quantity_kb,
    review_result_kb,
)


def _get_buttons(builder):  # type: ignore[no-untyped-def]
    """Extract flat list of (text, callback_data) from builder."""
    markup = builder.as_markup()
    return [(btn.text, btn.callback_data) for row in markup.inline_keyboard for btn in row]


# ---------------------------------------------------------------------------
# Description keyboards
# ---------------------------------------------------------------------------


class TestDescriptionConfirmKb:
    def test_buttons(self) -> None:
        btns = _get_buttons(description_confirm_kb(10, 20))
        assert len(btns) == 2
        assert btns[0] == ("Да, сгенерировать (20 ток.)", "desc:confirm")
        assert btns[1] == ("Отмена", "category:10:card")

    def test_cost_in_label(self) -> None:
        btns = _get_buttons(description_confirm_kb(5, 50))
        assert "50 ток." in btns[0][0]


class TestDescriptionResultKb:
    def test_free_regen(self) -> None:
        btns = _get_buttons(description_result_kb(10, 0))
        assert btns[1] == ("Перегенерировать", "desc:regen")

    def test_paid_regen(self) -> None:
        btns = _get_buttons(description_result_kb(10, 3))
        assert btns[1] == ("Перегенерировать (платно)", "desc:regen")

    def test_three_buttons(self) -> None:
        btns = _get_buttons(description_result_kb(10, 0))
        assert len(btns) == 3
        assert btns[0][1] == "desc:save"
        assert btns[2][1] == "category:10:card"


class TestDescriptionExistingKb:
    def test_buttons(self) -> None:
        btns = _get_buttons(description_existing_kb(7))
        assert len(btns) == 2
        assert btns[0][1] == "category:7:description:regen"
        assert btns[1][1] == "category:7:card"


# ---------------------------------------------------------------------------
# Review keyboards
# ---------------------------------------------------------------------------


class TestReviewQuantityKb:
    def test_buttons(self) -> None:
        btns = _get_buttons(review_quantity_kb(10))
        assert len(btns) == 4  # 3 qty + cancel
        assert btns[0] == ("3", "review:qty:10:3")
        assert btns[1] == ("5", "review:qty:10:5")
        assert btns[2] == ("10", "review:qty:10:10")
        assert btns[3][1] == "category:10:card"


class TestReviewConfirmKb:
    def test_cost_in_label(self) -> None:
        btns = _get_buttons(review_confirm_kb(5, 30))
        assert btns[0] == ("Да, сгенерировать (30 ток.)", "review:confirm")


class TestReviewResultKb:
    def test_free_regen(self) -> None:
        btns = _get_buttons(review_result_kb(5, 1))
        assert btns[1][0] == "Перегенерировать"

    def test_paid_regen(self) -> None:
        btns = _get_buttons(review_result_kb(5, 2))
        assert btns[1][0] == "Перегенерировать (платно)"


class TestReviewExistingKb:
    def test_buttons(self) -> None:
        btns = _get_buttons(review_existing_kb(8, 5))
        assert len(btns) == 2
        assert "5 шт." in btns[0][0]
        assert btns[0][1] == "category:8:reviews:regen"


# ---------------------------------------------------------------------------
# Price keyboards
# ---------------------------------------------------------------------------


class TestPriceMethodKb:
    def test_buttons(self) -> None:
        btns = _get_buttons(price_method_kb(3))
        assert len(btns) == 3
        assert btns[0][1] == "price:cat:3:text"
        assert btns[1][1] == "price:cat:3:excel"
        assert btns[2][1] == "category:3:card"


class TestPriceResultKb:
    def test_buttons(self) -> None:
        btns = _get_buttons(price_result_kb(3))
        assert len(btns) == 2
        assert btns[0][1] == "price:save"


class TestPriceExistingKb:
    def test_buttons(self) -> None:
        btns = _get_buttons(price_existing_kb(3))
        assert len(btns) == 3
        assert btns[1][1] == "price:cat:3:clear"


# ---------------------------------------------------------------------------
# Media keyboards
# ---------------------------------------------------------------------------


class TestMediaMenuKb:
    def test_with_media(self) -> None:
        btns = _get_buttons(media_menu_kb(4, has_media=True))
        assert len(btns) == 3
        texts = [b[0] for b in btns]
        assert "Очистить" in texts

    def test_without_media(self) -> None:
        btns = _get_buttons(media_menu_kb(4, has_media=False))
        assert len(btns) == 2  # no "Очистить"
        texts = [b[0] for b in btns]
        assert "Очистить" not in texts
