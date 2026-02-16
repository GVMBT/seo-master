"""Tests for keyboards/publish.py."""

from keyboards.publish import (
    article_confirm_kb,
    article_preview_kb,
    audit_menu_kb,
    audit_results_kb,
    competitor_confirm_kb,
    competitor_results_kb,
    insufficient_balance_kb,
    keyword_confirm_kb,
    keyword_quantity_kb,
    keyword_results_kb,
    keywords_main_kb,
    publish_platform_choice_kb,
    social_confirm_kb,
    social_review_kb,
)

# Max callback_data is 64 bytes
MAX_CB = 64


def _all_callbacks(builder) -> list[str]:
    markup = builder.as_markup()
    return [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]


def _all_texts(builder) -> list[str]:
    markup = builder.as_markup()
    return [btn.text for row in markup.inline_keyboard for btn in row]


def _button_count(builder) -> int:
    markup = builder.as_markup()
    return sum(len(row) for row in markup.inline_keyboard)


# ---------------------------------------------------------------------------
# Article confirm
# ---------------------------------------------------------------------------


class TestArticleConfirmKb:
    def test_has_2_buttons(self) -> None:
        assert _button_count(article_confirm_kb(10, 5, 320)) == 2

    def test_shows_cost(self) -> None:
        texts = _all_texts(article_confirm_kb(10, 5, 320))
        assert any("320" in t for t in texts)

    def test_cancel_goes_to_category(self) -> None:
        cbs = _all_callbacks(article_confirm_kb(10, 5, 320))
        assert "category:10:card" in cbs

    def test_confirm_callback(self) -> None:
        cbs = _all_callbacks(article_confirm_kb(10, 5, 320))
        assert "pub:article:confirm" in cbs

    def test_callbacks_within_64_bytes(self) -> None:
        for cb in _all_callbacks(article_confirm_kb(999999, 999999, 99999)):
            assert len(cb.encode("utf-8")) <= MAX_CB


# ---------------------------------------------------------------------------
# Article preview
# ---------------------------------------------------------------------------


class TestArticlePreviewKb:
    def test_has_3_buttons(self) -> None:
        assert _button_count(article_preview_kb(1, 0)) == 3

    def test_regen_shows_remaining(self) -> None:
        texts = _all_texts(article_preview_kb(1, 0))
        assert any("2/2" in t for t in texts)

    def test_regen_shows_remaining_after_1(self) -> None:
        texts = _all_texts(article_preview_kb(1, 1))
        assert any("1/2" in t for t in texts)

    def test_regen_shows_0_after_2(self) -> None:
        texts = _all_texts(article_preview_kb(1, 2))
        assert any("0/2" in t for t in texts)

    def test_callbacks(self) -> None:
        cbs = _all_callbacks(article_preview_kb(1, 0))
        assert "pub:article:publish" in cbs
        assert "pub:article:regen" in cbs
        assert "pub:article:cancel" in cbs


# ---------------------------------------------------------------------------
# Social confirm
# ---------------------------------------------------------------------------


class TestSocialConfirmKb:
    def test_has_2_buttons(self) -> None:
        assert _button_count(social_confirm_kb(10, "telegram", 5, 40)) == 2

    def test_shows_cost(self) -> None:
        texts = _all_texts(social_confirm_kb(10, "telegram", 5, 40))
        assert any("40" in t for t in texts)

    def test_cancel_goes_to_category(self) -> None:
        cbs = _all_callbacks(social_confirm_kb(10, "tg", 5, 40))
        assert "category:10:card" in cbs


# ---------------------------------------------------------------------------
# Social review
# ---------------------------------------------------------------------------


class TestSocialReviewKb:
    def test_has_3_buttons(self) -> None:
        assert _button_count(social_review_kb(0)) == 3

    def test_callbacks(self) -> None:
        cbs = _all_callbacks(social_review_kb(0))
        assert "pub:social:publish" in cbs
        assert "pub:social:regen" in cbs
        assert "pub:social:cancel" in cbs


# ---------------------------------------------------------------------------
# Insufficient balance
# ---------------------------------------------------------------------------


class TestInsufficientBalanceKb:
    def test_has_2_buttons(self) -> None:
        assert _button_count(insufficient_balance_kb()) == 2

    def test_topup_callback(self) -> None:
        cbs = _all_callbacks(insufficient_balance_kb())
        assert "tariffs:topup" in cbs


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------


class TestKeywordsMainKb:
    def test_has_3_buttons(self) -> None:
        assert _button_count(keywords_main_kb(10, has_keywords=True)) == 3

    def test_callbacks(self) -> None:
        cbs = _all_callbacks(keywords_main_kb(10, has_keywords=False))
        assert "category:10:kw:generate" in cbs
        assert "category:10:kw:upload" in cbs
        assert "category:10:card" in cbs


class TestKeywordQuantityKb:
    def test_has_4_options(self) -> None:
        assert _button_count(keyword_quantity_kb(10)) == 4

    def test_options_are_50_100_150_200(self) -> None:
        texts = _all_texts(keyword_quantity_kb(10))
        assert texts == ["50", "100", "150", "200"]

    def test_callback_format(self) -> None:
        cbs = _all_callbacks(keyword_quantity_kb(10))
        assert "kw:qty:10:50" in cbs
        assert "kw:qty:10:200" in cbs


class TestKeywordConfirmKb:
    def test_shows_cost(self) -> None:
        texts = _all_texts(keyword_confirm_kb(10, 100))
        assert any("100" in t for t in texts)


class TestKeywordResultsKb:
    def test_has_save_and_back(self) -> None:
        cbs = _all_callbacks(keyword_results_kb(10))
        assert "kw:save" in cbs
        assert "category:10:card" in cbs


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class TestAuditMenuKb:
    def test_has_3_buttons(self) -> None:
        assert _button_count(audit_menu_kb(1, has_audit=False)) == 3

    def test_rerun_label_when_has_audit(self) -> None:
        texts = _all_texts(audit_menu_kb(1, has_audit=True))
        assert "Перезапустить аудит" in texts

    def test_first_run_label(self) -> None:
        texts = _all_texts(audit_menu_kb(1, has_audit=False))
        assert "Тех. аудит" in texts

    def test_callbacks(self) -> None:
        cbs = _all_callbacks(audit_menu_kb(5, has_audit=False))
        assert "project:5:audit:run" in cbs
        assert "project:5:competitor" in cbs
        assert "project:5:card" in cbs


class TestAuditResultsKb:
    def test_has_3_buttons(self) -> None:
        assert _button_count(audit_results_kb(5)) == 3


# ---------------------------------------------------------------------------
# Competitor
# ---------------------------------------------------------------------------


class TestCompetitorConfirmKb:
    def test_shows_cost(self) -> None:
        texts = _all_texts(competitor_confirm_kb(1, 50))
        assert any("50" in t for t in texts)

    def test_cancel_goes_to_project(self) -> None:
        cbs = _all_callbacks(competitor_confirm_kb(5, 50))
        assert "project:5:card" in cbs


class TestCompetitorResultsKb:
    def test_has_back_button(self) -> None:
        cbs = _all_callbacks(competitor_results_kb(5))
        assert "project:5:card" in cbs


# ---------------------------------------------------------------------------
# publish_platform_choice_kb
# ---------------------------------------------------------------------------


class TestPublishPlatformChoiceKb:
    def test_shows_connections(self) -> None:
        from db.models import PlatformConnection

        conns = [
            PlatformConnection(id=1, project_id=1, platform_type="wordpress", identifier="site.com", credentials={}),
            PlatformConnection(id=2, project_id=1, platform_type="telegram", identifier="@channel", credentials={}),
        ]
        texts = _all_texts(publish_platform_choice_kb(5, conns))
        assert any("WordPress" in t for t in texts)
        assert any("Telegram" in t for t in texts)

    def test_has_back_button(self) -> None:
        from db.models import PlatformConnection

        conns = [PlatformConnection(id=1, project_id=1, platform_type="vk", identifier="g", credentials={})]
        cbs = _all_callbacks(publish_platform_choice_kb(5, conns))
        assert "category:5:card" in cbs

    def test_callback_within_64_bytes(self) -> None:
        from db.models import PlatformConnection

        conns = [PlatformConnection(id=999, project_id=1, platform_type="wordpress", identifier="x", credentials={})]
        for cb in _all_callbacks(publish_platform_choice_kb(999, conns)):
            assert len(cb.encode("utf-8")) <= MAX_CB
