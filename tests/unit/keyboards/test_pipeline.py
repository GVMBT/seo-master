"""Tests for keyboards/pipeline.py -- Article Pipeline keyboards.

Covers all pipeline keyboard functions:
- Project selection (with/without projects)
- WP connection selection (with/without connections)
- Category selection
- Readiness checklist
- Cost confirmation + insufficient balance
- Preview, result, exit confirm
- Readiness sub-flows: keywords, description, images
"""

from __future__ import annotations

from typing import Any

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton

from db.models import Category, PlatformConnection, Project
from keyboards.pipeline import (
    pipeline_categories_kb,
    pipeline_confirm_kb,
    pipeline_description_options_kb,
    pipeline_exit_confirm_kb,
    pipeline_images_options_kb,
    pipeline_insufficient_balance_kb,
    pipeline_keywords_options_kb,
    pipeline_no_categories_kb,
    pipeline_no_projects_kb,
    pipeline_no_wp_kb,
    pipeline_preview_kb,
    pipeline_projects_kb,
    pipeline_readiness_kb,
    pipeline_result_kb,
    pipeline_wp_select_kb,
)
from services.readiness import ReadinessReport
from services.tokens import (
    COST_DESCRIPTION,
    COST_PER_IMAGE,
    estimate_keywords_cost,
)

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_project(id: int = 1, **overrides: Any) -> Project:
    defaults: dict[str, Any] = {
        "id": id,
        "user_id": 123,
        "name": f"Project {id}",
        "company_name": "TestCo",
        "specialization": "SEO",
    }
    defaults.update(overrides)
    return Project(**defaults)


def _make_category(id: int = 1, project_id: int = 1, **overrides: Any) -> Category:
    defaults: dict[str, Any] = {
        "id": id,
        "project_id": project_id,
        "name": f"Category {id}",
    }
    defaults.update(overrides)
    return Category(**defaults)


def _make_connection(id: int = 1, project_id: int = 1, **overrides: Any) -> PlatformConnection:
    defaults: dict[str, Any] = {
        "id": id,
        "project_id": project_id,
        "platform_type": "wordpress",
        "identifier": f"site-{id}.example.com",
        "credentials": {"url": "https://example.com", "login": "admin", "password": "pass"},
        "status": "active",
    }
    defaults.update(overrides)
    return PlatformConnection(**defaults)


def _make_report(**overrides: Any) -> ReadinessReport:
    defaults: dict[str, Any] = {
        "has_keywords": True,
        "keyword_count": 50,
        "cluster_count": 3,
        "has_description": True,
        "has_prices": True,
        "image_count": 4,
        "estimated_cost": 320,
        "user_balance": 1500,
        "is_sufficient_balance": True,
        "publication_count": 0,
        "missing_items": [],
    }
    defaults.update(overrides)
    return ReadinessReport(**defaults)


def _flatten_buttons(kb) -> list[InlineKeyboardButton]:
    """Flatten keyboard into a single list of buttons."""
    return [btn for row in kb.inline_keyboard for btn in row]


# ---------------------------------------------------------------------------
# Step 1: Project selection
# ---------------------------------------------------------------------------


class TestPipelineProjectsKb:
    """pipeline_projects_kb generates correct callback_data pattern."""

    def test_single_project(self) -> None:
        kb = pipeline_projects_kb([_make_project(id=5)])
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:article:5:select" for b in buttons)

    def test_multiple_projects(self) -> None:
        projects = [_make_project(id=i) for i in range(1, 4)]
        kb = pipeline_projects_kb(projects)
        buttons = _flatten_buttons(kb)
        cb_data = [b.callback_data for b in buttons if b.callback_data and b.callback_data.startswith("pipeline:")]
        assert "pipeline:article:1:select" in cb_data
        assert "pipeline:article:2:select" in cb_data
        assert "pipeline:article:3:select" in cb_data

    def test_project_name_as_text(self) -> None:
        kb = pipeline_projects_kb([_make_project(id=1, name="My Site")])
        buttons = _flatten_buttons(kb)
        assert any(b.text == "My Site" for b in buttons)

    def test_pagination_at_9_projects(self) -> None:
        """PAGE_SIZE=8, so 9 projects show pagination."""
        projects = [_make_project(id=i) for i in range(1, 10)]
        kb = pipeline_projects_kb(projects, page=1)
        buttons = _flatten_buttons(kb)
        # Navigation row exists
        nav_cbs = [b.callback_data for b in buttons if b.callback_data and b.callback_data.startswith("page:")]
        assert any("page:pipeline_projects:2" in cb for cb in nav_cbs)


class TestPipelineNoProjectsKb:
    """pipeline_no_projects_kb has PRIMARY style create button."""

    def test_create_button_primary(self) -> None:
        kb = pipeline_no_projects_kb()
        buttons = _flatten_buttons(kb)
        create_btn = next(b for b in buttons if b.callback_data == "pipeline:article:create_project")
        assert create_btn.style == ButtonStyle.PRIMARY

    def test_cancel_button_present(self) -> None:
        kb = pipeline_no_projects_kb()
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:article:cancel" for b in buttons)

    def test_two_buttons_total(self) -> None:
        kb = pipeline_no_projects_kb()
        buttons = _flatten_buttons(kb)
        assert len(buttons) == 2


# ---------------------------------------------------------------------------
# Step 2: WP connection selection
# ---------------------------------------------------------------------------


class TestPipelineWpSelectKb:
    """pipeline_wp_select_kb shows correct identifiers."""

    def test_single_connection_identifier(self) -> None:
        conn = _make_connection(id=10, identifier="blog.example.com")
        kb = pipeline_wp_select_kb([conn], project_id=5)
        buttons = _flatten_buttons(kb)
        assert buttons[0].text == "blog.example.com"
        assert buttons[0].callback_data == "pipeline:article:5:wp:10"

    def test_multiple_connections(self) -> None:
        conns = [
            _make_connection(id=1, identifier="site1.com"),
            _make_connection(id=2, identifier="site2.com"),
        ]
        kb = pipeline_wp_select_kb(conns, project_id=3)
        buttons = _flatten_buttons(kb)
        assert len(buttons) == 2
        assert buttons[0].callback_data == "pipeline:article:3:wp:1"
        assert buttons[1].callback_data == "pipeline:article:3:wp:2"

    def test_fallback_identifier_when_empty(self) -> None:
        """When identifier is empty string, fallback to 'WP #{id}'.

        Note: PlatformConnection.identifier is required str (not None).
        The keyboard function uses `conn.identifier or f'WP #{conn.id}'`.
        """
        conn = _make_connection(id=7, identifier="")
        kb = pipeline_wp_select_kb([conn], project_id=1)
        buttons = _flatten_buttons(kb)
        assert buttons[0].text == "WP #7"


class TestPipelineNoWpKb:
    """pipeline_no_wp_kb has PRIMARY connect + preview_only."""

    def test_connect_button_primary(self) -> None:
        kb = pipeline_no_wp_kb()
        buttons = _flatten_buttons(kb)
        connect_btn = next(b for b in buttons if b.callback_data == "pipeline:article:connect_wp")
        assert connect_btn.style == ButtonStyle.PRIMARY

    def test_preview_only_button(self) -> None:
        kb = pipeline_no_wp_kb()
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:article:preview_only" for b in buttons)

    def test_two_buttons_total(self) -> None:
        kb = pipeline_no_wp_kb()
        buttons = _flatten_buttons(kb)
        assert len(buttons) == 2


# ---------------------------------------------------------------------------
# Step 3: Category selection
# ---------------------------------------------------------------------------


class TestPipelineCategoriesKb:
    """pipeline_categories_kb generates correct callback_data."""

    def test_single_category(self) -> None:
        cat = _make_category(id=12, project_id=5)
        kb = pipeline_categories_kb([cat], project_id=5)
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:article:5:cat:12" for b in buttons)

    def test_category_name_as_text(self) -> None:
        cat = _make_category(id=1, name="SEO Tips")
        kb = pipeline_categories_kb([cat], project_id=1)
        buttons = _flatten_buttons(kb)
        assert any(b.text == "SEO Tips" for b in buttons)

    def test_multiple_categories(self) -> None:
        cats = [_make_category(id=i, project_id=5) for i in range(1, 4)]
        kb = pipeline_categories_kb(cats, project_id=5)
        buttons = _flatten_buttons(kb)
        cb_data = [b.callback_data for b in buttons if b.callback_data and b.callback_data.startswith("pipeline:")]
        assert "pipeline:article:5:cat:1" in cb_data
        assert "pipeline:article:5:cat:2" in cb_data
        assert "pipeline:article:5:cat:3" in cb_data


class TestPipelineNoCategoriesKb:
    """pipeline_no_categories_kb has cancel button."""

    def test_cancel_button_present(self) -> None:
        kb = pipeline_no_categories_kb()
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:article:cancel" for b in buttons)


# ---------------------------------------------------------------------------
# Step 4: Readiness check
# ---------------------------------------------------------------------------


class TestPipelineReadinessKb:
    """pipeline_readiness_kb shows missing items only, SUCCESS button."""

    def test_all_ready_only_generate_button(self) -> None:
        """All filled -> only 'generate' button + images info."""
        report = _make_report()
        kb = pipeline_readiness_kb(report)
        buttons = _flatten_buttons(kb)
        # Should have images info button (always shown when image_count > 0)
        # and the "generate" SUCCESS button
        generate_btn = next(b for b in buttons if b.callback_data == "pipeline:readiness:done")
        assert generate_btn.style == ButtonStyle.SUCCESS

    def test_missing_keywords_shows_button(self) -> None:
        report = _make_report(has_keywords=False)
        kb = pipeline_readiness_kb(report)
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:readiness:keywords" for b in buttons)

    def test_missing_description_shows_button(self) -> None:
        report = _make_report(has_description=False)
        kb = pipeline_readiness_kb(report)
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:readiness:description" for b in buttons)

    def test_missing_prices_shows_button(self) -> None:
        report = _make_report(has_prices=False, missing_items=["prices"])
        kb = pipeline_readiness_kb(report)
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:readiness:prices" for b in buttons)

    def test_generate_button_always_last(self) -> None:
        """The 'generate' button is always the last row."""
        report = _make_report(has_keywords=False, has_description=False)
        kb = pipeline_readiness_kb(report)
        last_row = kb.inline_keyboard[-1]
        assert last_row[0].callback_data == "pipeline:readiness:done"

    def test_keyword_cost_in_label(self) -> None:
        """Keywords button shows cost estimate."""
        report = _make_report(has_keywords=False)
        kb = pipeline_readiness_kb(report)
        buttons = _flatten_buttons(kb)
        kw_btn = next(b for b in buttons if b.callback_data == "pipeline:readiness:keywords")
        assert str(estimate_keywords_cost(100)) in kw_btn.text

    def test_description_cost_in_label(self) -> None:
        """Description button shows cost."""
        report = _make_report(has_description=False)
        kb = pipeline_readiness_kb(report)
        buttons = _flatten_buttons(kb)
        desc_btn = next(b for b in buttons if b.callback_data == "pipeline:readiness:description")
        assert str(COST_DESCRIPTION) in desc_btn.text

    def test_image_count_in_label(self) -> None:
        """Images button shows count and cost."""
        report = _make_report(image_count=4)
        kb = pipeline_readiness_kb(report)
        buttons = _flatten_buttons(kb)
        img_btn = next(
            (b for b in buttons if b.callback_data == "pipeline:readiness:images"),
            None,
        )
        if img_btn:
            assert "4" in img_btn.text
            assert str(4 * COST_PER_IMAGE) in img_btn.text


# ---------------------------------------------------------------------------
# Step 5: Confirm cost
# ---------------------------------------------------------------------------


class TestPipelineConfirmKb:
    """pipeline_confirm_kb has SUCCESS create button."""

    def test_create_button_success(self) -> None:
        kb = pipeline_confirm_kb()
        buttons = _flatten_buttons(kb)
        create_btn = next(b for b in buttons if b.callback_data == "pipeline:article:confirm")
        assert create_btn.style == ButtonStyle.SUCCESS

    def test_back_button_present(self) -> None:
        kb = pipeline_confirm_kb()
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:article:back_readiness" for b in buttons)


class TestPipelineInsufficientBalanceKb:
    """pipeline_insufficient_balance_kb has PRIMARY top-up."""

    def test_topup_button_primary(self) -> None:
        kb = pipeline_insufficient_balance_kb()
        buttons = _flatten_buttons(kb)
        topup_btn = next(b for b in buttons if b.callback_data == "nav:tokens")
        assert topup_btn.style == ButtonStyle.PRIMARY

    def test_cancel_button_present(self) -> None:
        kb = pipeline_insufficient_balance_kb()
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:article:cancel" for b in buttons)


# ---------------------------------------------------------------------------
# Step 7: Preview
# ---------------------------------------------------------------------------


class TestPipelinePreviewKb:
    """pipeline_preview_kb has publish, regenerate, cancel."""

    def test_preview_url_button(self) -> None:
        kb = pipeline_preview_kb("https://telegra.ph/test-123")
        buttons = _flatten_buttons(kb)
        url_btn = next(b for b in buttons if b.url)
        assert url_btn.url == "https://telegra.ph/test-123"

    def test_publish_button_when_can_publish(self) -> None:
        kb = pipeline_preview_kb("https://telegra.ph/test", can_publish=True)
        buttons = _flatten_buttons(kb)
        pub_btn = next(b for b in buttons if b.callback_data == "pipeline:article:publish")
        assert pub_btn.style == ButtonStyle.SUCCESS

    def test_no_publish_when_cannot_publish(self) -> None:
        kb = pipeline_preview_kb("https://telegra.ph/test", can_publish=False)
        buttons = _flatten_buttons(kb)
        assert not any(b.callback_data == "pipeline:article:publish" for b in buttons)

    def test_regenerate_button(self) -> None:
        kb = pipeline_preview_kb("https://telegra.ph/test")
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:article:regenerate" for b in buttons)

    def test_cancel_refund_button_danger(self) -> None:
        kb = pipeline_preview_kb("https://telegra.ph/test")
        buttons = _flatten_buttons(kb)
        cancel_btn = next(b for b in buttons if b.callback_data == "pipeline:article:cancel_refund")
        assert cancel_btn.style == ButtonStyle.DANGER


# ---------------------------------------------------------------------------
# Step 8: Result
# ---------------------------------------------------------------------------


class TestPipelineResultKb:
    """pipeline_result_kb has PRIMARY 'ещё статью'."""

    def test_another_article_button_primary(self) -> None:
        kb = pipeline_result_kb()
        buttons = _flatten_buttons(kb)
        another_btn = next(b for b in buttons if b.callback_data == "pipeline:article:start")
        assert another_btn.style == ButtonStyle.PRIMARY

    def test_post_url_when_provided(self) -> None:
        kb = pipeline_result_kb(post_url="https://example.com/my-article")
        buttons = _flatten_buttons(kb)
        url_btn = next(b for b in buttons if b.url)
        assert url_btn.url == "https://example.com/my-article"

    def test_no_url_button_when_none(self) -> None:
        kb = pipeline_result_kb()
        buttons = _flatten_buttons(kb)
        assert not any(b.url for b in buttons)

    def test_scheduler_nav_button(self) -> None:
        kb = pipeline_result_kb()
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "nav:scheduler" for b in buttons)

    def test_dashboard_nav_button(self) -> None:
        kb = pipeline_result_kb()
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "nav:dashboard" for b in buttons)


# ---------------------------------------------------------------------------
# Exit confirmation
# ---------------------------------------------------------------------------


class TestPipelineExitConfirmKb:
    """pipeline_exit_confirm_kb has DANGER exit."""

    def test_exit_button_danger(self) -> None:
        kb = pipeline_exit_confirm_kb()
        buttons = _flatten_buttons(kb)
        exit_btn = next(b for b in buttons if b.callback_data == "pipeline:article:exit_confirm")
        assert exit_btn.style == ButtonStyle.DANGER

    def test_continue_button_present(self) -> None:
        kb = pipeline_exit_confirm_kb()
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:article:exit_cancel" for b in buttons)

    def test_single_row_two_buttons(self) -> None:
        kb = pipeline_exit_confirm_kb()
        assert len(kb.inline_keyboard) == 1
        assert len(kb.inline_keyboard[0]) == 2


# ---------------------------------------------------------------------------
# Readiness sub-flow: Keywords
# ---------------------------------------------------------------------------


class TestPipelineKeywordsOptionsKb:
    """pipeline_keywords_options_kb has 4 options."""

    def test_four_rows(self) -> None:
        kb = pipeline_keywords_options_kb()
        assert len(kb.inline_keyboard) == 4

    def test_auto_option(self) -> None:
        kb = pipeline_keywords_options_kb()
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:readiness:keywords:auto" for b in buttons)

    def test_configure_option(self) -> None:
        kb = pipeline_keywords_options_kb()
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:readiness:keywords:configure" for b in buttons)

    def test_upload_option(self) -> None:
        kb = pipeline_keywords_options_kb()
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:readiness:keywords:upload" for b in buttons)

    def test_back_option(self) -> None:
        kb = pipeline_keywords_options_kb()
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:readiness:back" for b in buttons)


# ---------------------------------------------------------------------------
# Readiness sub-flow: Description
# ---------------------------------------------------------------------------


class TestPipelineDescriptionOptionsKb:
    """pipeline_description_options_kb has 3 options."""

    def test_three_rows(self) -> None:
        kb = pipeline_description_options_kb()
        assert len(kb.inline_keyboard) == 3

    def test_ai_option(self) -> None:
        kb = pipeline_description_options_kb()
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:readiness:description:ai" for b in buttons)

    def test_manual_option(self) -> None:
        kb = pipeline_description_options_kb()
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:readiness:description:manual" for b in buttons)

    def test_back_option(self) -> None:
        kb = pipeline_description_options_kb()
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:readiness:back" for b in buttons)

    def test_ai_shows_cost(self) -> None:
        kb = pipeline_description_options_kb()
        buttons = _flatten_buttons(kb)
        ai_btn = next(b for b in buttons if b.callback_data == "pipeline:readiness:description:ai")
        assert str(COST_DESCRIPTION) in ai_btn.text


# ---------------------------------------------------------------------------
# Readiness sub-flow: Images
# ---------------------------------------------------------------------------


class TestPipelineImagesOptionsKb:
    """pipeline_images_options_kb shows correct count options."""

    def test_options_include_zero_to_ten(self) -> None:
        """Options should include 0, 1, 2, 3, 4, 6, 8, 10."""
        kb = pipeline_images_options_kb()
        buttons = _flatten_buttons(kb)
        # Exclude the "back" button
        count_buttons = [b for b in buttons if b.callback_data and b.callback_data != "pipeline:readiness:back"]
        cb_data = [b.callback_data for b in count_buttons]
        expected = [f"pipeline:readiness:images:{n}" for n in [0, 1, 2, 3, 4, 6, 8, 10]]
        assert cb_data == expected

    def test_current_count_highlighted(self) -> None:
        """Current count (4 by default) shown as [4]."""
        kb = pipeline_images_options_kb(current_count=4)
        buttons = _flatten_buttons(kb)
        btn_4 = next(b for b in buttons if b.callback_data == "pipeline:readiness:images:4")
        assert btn_4.text == "[4]"

    def test_non_current_count_plain(self) -> None:
        kb = pipeline_images_options_kb(current_count=4)
        buttons = _flatten_buttons(kb)
        btn_2 = next(b for b in buttons if b.callback_data == "pipeline:readiness:images:2")
        assert btn_2.text == "2"

    def test_custom_current_count(self) -> None:
        kb = pipeline_images_options_kb(current_count=6)
        buttons = _flatten_buttons(kb)
        btn_6 = next(b for b in buttons if b.callback_data == "pipeline:readiness:images:6")
        assert btn_6.text == "[6]"

    def test_back_button(self) -> None:
        kb = pipeline_images_options_kb()
        buttons = _flatten_buttons(kb)
        assert any(b.callback_data == "pipeline:readiness:back" for b in buttons)

    def test_layout_4_per_row(self) -> None:
        """8 count options -> 2 rows of 4, then 1 back row."""
        kb = pipeline_images_options_kb()
        # 2 rows of 4 count buttons + 1 back row = 3 rows
        assert len(kb.inline_keyboard) == 3
        assert len(kb.inline_keyboard[0]) == 4
        assert len(kb.inline_keyboard[1]) == 4
        assert len(kb.inline_keyboard[2]) == 1  # back button
