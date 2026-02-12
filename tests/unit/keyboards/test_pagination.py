"""Tests for keyboards/pagination.py."""

from keyboards.pagination import PAGE_SIZE, paginate


class TestPaginate:
    def test_default_page_size_is_8(self) -> None:
        assert PAGE_SIZE == 8

    def test_returns_all_items_when_less_than_page_size(self) -> None:
        items = [1, 2, 3]
        builder, has_more, _nav = paginate(
            items=items,
            page=0,
            item_text_fn=str,
            item_callback_fn=lambda x: f"item:{x}",
            page_callback_fn=lambda p: f"page:{p}",
        )
        markup = builder.as_markup()
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        assert len(buttons) == 3
        assert has_more is False

    def test_paginates_when_more_than_page_size(self) -> None:
        items = list(range(10))
        builder, has_more, _nav = paginate(
            items=items,
            page=0,
            item_text_fn=str,
            item_callback_fn=lambda x: f"item:{x}",
            page_callback_fn=lambda p: f"page:{p}",
        )
        markup = builder.as_markup()
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        assert has_more is True
        # 8 items + 1 "more" button
        assert len(buttons) == 9
        assert buttons[-1].text == "Ещё ▼"
        assert buttons[-1].callback_data == "page:1"

    def test_second_page_shows_remaining_with_back(self) -> None:
        items = list(range(10))
        builder, has_more, _nav = paginate(
            items=items,
            page=1,
            item_text_fn=str,
            item_callback_fn=lambda x: f"item:{x}",
            page_callback_fn=lambda p: f"page:{p}",
        )
        markup = builder.as_markup()
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        assert has_more is False
        assert len(buttons) == 3  # items 8, 9 + back button
        assert buttons[0].text == "8"
        assert buttons[1].text == "9"
        assert buttons[2].text == "◀ Назад"
        assert buttons[2].callback_data == "page:0"

    def test_empty_items_returns_no_buttons(self) -> None:
        builder, has_more, _nav = paginate(
            items=[],
            page=0,
            item_text_fn=str,
            item_callback_fn=lambda x: f"item:{x}",
            page_callback_fn=lambda p: f"page:{p}",
        )
        markup = builder.as_markup()
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        assert len(buttons) == 0
        assert has_more is False

    def test_custom_page_size(self) -> None:
        items = list(range(5))
        builder, has_more, _nav = paginate(
            items=items,
            page=0,
            item_text_fn=str,
            item_callback_fn=lambda x: f"item:{x}",
            page_callback_fn=lambda p: f"page:{p}",
            page_size=3,
        )
        markup = builder.as_markup()
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        assert has_more is True
        assert len(buttons) == 4  # 3 items + "more"

    def test_exact_page_size_has_no_more(self) -> None:
        items = list(range(8))
        builder, has_more, _nav = paginate(
            items=items,
            page=0,
            item_text_fn=str,
            item_callback_fn=lambda x: f"item:{x}",
            page_callback_fn=lambda p: f"page:{p}",
        )
        assert has_more is False
        markup = builder.as_markup()
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        assert len(buttons) == 8

    def test_callback_data_uses_item_callback_fn(self) -> None:
        items = [42]
        builder, _, _nav = paginate(
            items=items,
            page=0,
            item_text_fn=str,
            item_callback_fn=lambda x: f"project:{x}:card",
            page_callback_fn=lambda p: f"page:{p}",
        )
        markup = builder.as_markup()
        assert markup.inline_keyboard[0][0].callback_data == "project:42:card"

    def test_middle_page_has_back_and_more(self) -> None:
        items = list(range(20))
        builder, has_more, _nav = paginate(
            items=items,
            page=1,
            item_text_fn=str,
            item_callback_fn=lambda x: f"item:{x}",
            page_callback_fn=lambda p: f"page:{p}",
        )
        markup = builder.as_markup()
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        assert has_more is True
        assert len(buttons) == 10  # 8 items + back + more
        assert buttons[-2].text == "◀ Назад"
        assert buttons[-2].callback_data == "page:0"
        assert buttons[-1].text == "Ещё ▼"
        assert buttons[-1].callback_data == "page:2"
        # Nav buttons should be on the same row
        last_row = markup.inline_keyboard[-1]
        assert len(last_row) == 2

    def test_first_page_no_back_button(self) -> None:
        items = list(range(10))
        builder, _, _nav = paginate(
            items=items,
            page=0,
            item_text_fn=str,
            item_callback_fn=lambda x: f"item:{x}",
            page_callback_fn=lambda p: f"page:{p}",
        )
        markup = builder.as_markup()
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        # No "◀ Назад" on first page
        assert not any(btn.text == "◀ Назад" for btn in buttons)

    def test_buttons_are_one_per_row(self) -> None:
        items = list(range(3))
        builder, _, _nav = paginate(
            items=items,
            page=0,
            item_text_fn=str,
            item_callback_fn=lambda x: f"item:{x}",
            page_callback_fn=lambda p: f"page:{p}",
        )
        markup = builder.as_markup()
        for row in markup.inline_keyboard:
            assert len(row) == 1

    def test_nav_count_zero_when_no_nav(self) -> None:
        items = [1, 2]
        _, _, nav_count = paginate(
            items=items,
            page=0,
            item_text_fn=str,
            item_callback_fn=lambda x: f"item:{x}",
            page_callback_fn=lambda p: f"page:{p}",
        )
        assert nav_count == 0

    def test_nav_count_one_for_more_only(self) -> None:
        items = list(range(10))
        _, _, nav_count = paginate(
            items=items,
            page=0,
            item_text_fn=str,
            item_callback_fn=lambda x: f"item:{x}",
            page_callback_fn=lambda p: f"page:{p}",
        )
        assert nav_count == 1

    def test_nav_count_two_for_back_and_more(self) -> None:
        items = list(range(20))
        _, _, nav_count = paginate(
            items=items,
            page=1,
            item_text_fn=str,
            item_callback_fn=lambda x: f"item:{x}",
            page_callback_fn=lambda p: f"page:{p}",
        )
        assert nav_count == 2
