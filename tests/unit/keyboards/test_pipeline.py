"""Tests for keyboards/pipeline.py -- Goal-Oriented Pipeline keyboard builders."""

from db.models import PlatformConnection
from keyboards.pipeline import (
    pipeline_category_list_kb,
    pipeline_confirm_kb,
    pipeline_no_entities_kb,
    pipeline_preview_kb,
    pipeline_project_list_kb,
    pipeline_resume_kb,
    pipeline_wp_list_kb,
)
from tests.unit.keyboards.helpers import make_category, make_project

MAX_CB = 64


def _all_callbacks(builder) -> list[str]:  # type: ignore[no-untyped-def]
    markup = builder.as_markup()
    return [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]


def _all_texts(builder) -> list[str]:  # type: ignore[no-untyped-def]
    markup = builder.as_markup()
    return [btn.text for row in markup.inline_keyboard for btn in row]


def _button_count(builder) -> int:  # type: ignore[no-untyped-def]
    markup = builder.as_markup()
    return sum(len(row) for row in markup.inline_keyboard)


# ---------------------------------------------------------------------------
# pipeline_project_list_kb
# ---------------------------------------------------------------------------


class TestPipelineProjectListKb:
    def test_single_project_shows_button_and_cancel(self) -> None:
        projects = [make_project(id=1, name="Proj A")]
        kb = pipeline_project_list_kb(projects)
        texts = _all_texts(kb)
        cbs = _all_callbacks(kb)
        assert "Proj A" in texts
        assert "pipeline:article:project:1" in cbs
        assert "menu:main" in cbs  # cancel button

    def test_multiple_projects_all_shown(self) -> None:
        projects = [make_project(id=i, name=f"Project {i}") for i in range(1, 4)]
        kb = pipeline_project_list_kb(projects)
        cbs = _all_callbacks(kb)
        for i in range(1, 4):
            assert f"pipeline:article:project:{i}" in cbs

    def test_last_used_project_sorted_first(self) -> None:
        projects = [
            make_project(id=1, name="AAA"),
            make_project(id=2, name="BBB"),
            make_project(id=3, name="CCC"),
        ]
        kb = pipeline_project_list_kb(projects, last_used_id=3)
        cbs = _all_callbacks(kb)
        # First project callback should be project 3 (last used)
        project_cbs = [c for c in cbs if c.startswith("pipeline:article:project:")]
        assert project_cbs[0] == "pipeline:article:project:3"

    def test_pagination_more_than_8(self) -> None:
        projects = [make_project(id=i, name=f"P{i}") for i in range(1, 12)]
        kb = pipeline_project_list_kb(projects, page=0)
        cbs = _all_callbacks(kb)
        assert any("page:pipeline_proj:1" in c for c in cbs)

    def test_pagination_page_1(self) -> None:
        projects = [make_project(id=i, name=f"P{i}") for i in range(1, 12)]
        kb = pipeline_project_list_kb(projects, page=1)
        cbs = _all_callbacks(kb)
        assert any("page:pipeline_proj:0" in c for c in cbs)  # back button

    def test_callbacks_within_64_bytes(self) -> None:
        projects = [make_project(id=999999, name="Long Project Name")]
        for cb in _all_callbacks(pipeline_project_list_kb(projects)):
            assert len(cb.encode("utf-8")) <= MAX_CB


# ---------------------------------------------------------------------------
# pipeline_wp_list_kb
# ---------------------------------------------------------------------------


def _make_conn(id: int = 1, identifier: str = "site.com") -> PlatformConnection:
    return PlatformConnection(
        id=id,
        project_id=1,
        platform_type="wordpress",
        identifier=identifier,
        credentials={},
    )


class TestPipelineWpListKb:
    def test_single_wp_shows_button(self) -> None:
        conns = [_make_conn(id=5, identifier="blog.com")]
        kb = pipeline_wp_list_kb(conns, project_id=1)
        cbs = _all_callbacks(kb)
        assert "pipeline:article:wp:5" in cbs
        texts = _all_texts(kb)
        assert "blog.com" in texts

    def test_preview_only_button_present(self) -> None:
        conns = [_make_conn()]
        kb = pipeline_wp_list_kb(conns, project_id=1)
        cbs = _all_callbacks(kb)
        assert "pipeline:article:wp:preview_only" in cbs

    def test_cancel_button_present(self) -> None:
        conns = [_make_conn()]
        kb = pipeline_wp_list_kb(conns, project_id=1)
        cbs = _all_callbacks(kb)
        assert "menu:main" in cbs

    def test_long_identifier_truncated(self) -> None:
        long_name = "a" * 100
        conns = [_make_conn(identifier=long_name)]
        kb = pipeline_wp_list_kb(conns, project_id=1)
        texts = _all_texts(kb)
        wp_text = next(t for t in texts if "a" * 10 in t)
        assert len(wp_text) <= 55

    def test_multiple_connections(self) -> None:
        conns = [_make_conn(id=1, identifier="s1.com"), _make_conn(id=2, identifier="s2.com")]
        kb = pipeline_wp_list_kb(conns, project_id=1)
        cbs = _all_callbacks(kb)
        assert "pipeline:article:wp:1" in cbs
        assert "pipeline:article:wp:2" in cbs

    def test_callbacks_within_64_bytes(self) -> None:
        conns = [_make_conn(id=999999)]
        for cb in _all_callbacks(pipeline_wp_list_kb(conns, project_id=1)):
            assert len(cb.encode("utf-8")) <= MAX_CB


# ---------------------------------------------------------------------------
# pipeline_category_list_kb
# ---------------------------------------------------------------------------


class TestPipelineCategoryListKb:
    def test_single_category(self) -> None:
        cats = [make_category(id=10, name="SEO Tips")]
        kb = pipeline_category_list_kb(cats)
        cbs = _all_callbacks(kb)
        assert "pipeline:article:cat:10" in cbs
        texts = _all_texts(kb)
        assert "SEO Tips" in texts

    def test_cancel_button(self) -> None:
        cats = [make_category()]
        kb = pipeline_category_list_kb(cats)
        cbs = _all_callbacks(kb)
        assert "menu:main" in cbs

    def test_pagination(self) -> None:
        cats = [make_category(id=i, name=f"Cat {i}") for i in range(1, 12)]
        kb = pipeline_category_list_kb(cats, page=0)
        cbs = _all_callbacks(kb)
        assert any("page:pipeline_cat:1" in c for c in cbs)

    def test_callbacks_within_64_bytes(self) -> None:
        cats = [make_category(id=999999)]
        for cb in _all_callbacks(pipeline_category_list_kb(cats)):
            assert len(cb.encode("utf-8")) <= MAX_CB


# ---------------------------------------------------------------------------
# pipeline_confirm_kb
# ---------------------------------------------------------------------------


class TestPipelineConfirmKb:
    def test_normal_mode_shows_cost(self) -> None:
        kb = pipeline_confirm_kb(320)
        texts = _all_texts(kb)
        assert any("320" in t for t in texts)
        assert any("токенов" in t.lower() for t in texts)

    def test_god_mode_shows_free(self) -> None:
        kb = pipeline_confirm_kb(320, is_god_mode=True)
        texts = _all_texts(kb)
        assert any("GOD_MODE" in t for t in texts)
        assert any("бесплатно" in t.lower() for t in texts)

    def test_generate_callback(self) -> None:
        kb = pipeline_confirm_kb(320)
        cbs = _all_callbacks(kb)
        assert "pipeline:article:generate" in cbs

    def test_cancel_callback(self) -> None:
        kb = pipeline_confirm_kb(320)
        cbs = _all_callbacks(kb)
        assert "pipeline:article:cancel" in cbs

    def test_has_2_buttons(self) -> None:
        assert _button_count(pipeline_confirm_kb(320)) == 2


# ---------------------------------------------------------------------------
# pipeline_preview_kb
# ---------------------------------------------------------------------------


class TestPipelinePreviewKb:
    def test_with_wp_has_3_buttons(self) -> None:
        kb = pipeline_preview_kb(0, has_wp=True)
        assert _button_count(kb) == 3

    def test_without_wp_has_2_buttons(self) -> None:
        kb = pipeline_preview_kb(0, has_wp=False)
        assert _button_count(kb) == 2

    def test_publish_button_present_when_wp(self) -> None:
        kb = pipeline_preview_kb(0, has_wp=True)
        cbs = _all_callbacks(kb)
        assert "pipeline:article:publish" in cbs

    def test_publish_button_absent_without_wp(self) -> None:
        kb = pipeline_preview_kb(0, has_wp=False)
        cbs = _all_callbacks(kb)
        assert "pipeline:article:publish" not in cbs

    def test_regen_shows_remaining_2_of_2(self) -> None:
        kb = pipeline_preview_kb(0)
        texts = _all_texts(kb)
        assert any("2/2" in t for t in texts)

    def test_regen_shows_remaining_1_of_2(self) -> None:
        kb = pipeline_preview_kb(1)
        texts = _all_texts(kb)
        assert any("1/2" in t for t in texts)

    def test_regen_shows_remaining_0_of_2(self) -> None:
        kb = pipeline_preview_kb(2)
        texts = _all_texts(kb)
        assert any("0/2" in t for t in texts)

    def test_regen_callback(self) -> None:
        kb = pipeline_preview_kb(0)
        cbs = _all_callbacks(kb)
        assert "pipeline:article:regen" in cbs

    def test_cancel_refund_callback(self) -> None:
        kb = pipeline_preview_kb(0)
        cbs = _all_callbacks(kb)
        assert "pipeline:article:cancel_refund" in cbs


# ---------------------------------------------------------------------------
# pipeline_resume_kb
# ---------------------------------------------------------------------------


class TestPipelineResumeKb:
    def test_has_3_buttons(self) -> None:
        kb = pipeline_resume_kb()
        assert _button_count(kb) == 3

    def test_resume_callback(self) -> None:
        cbs = _all_callbacks(pipeline_resume_kb())
        assert "pipeline:resume" in cbs

    def test_restart_callback(self) -> None:
        cbs = _all_callbacks(pipeline_resume_kb())
        assert "pipeline:restart" in cbs

    def test_cancel_callback(self) -> None:
        cbs = _all_callbacks(pipeline_resume_kb())
        assert "pipeline:cancel" in cbs

    def test_button_texts(self) -> None:
        texts = _all_texts(pipeline_resume_kb())
        assert "Продолжить" in texts
        assert "Начать заново" in texts
        assert "Отменить" in texts


# ---------------------------------------------------------------------------
# pipeline_no_entities_kb
# ---------------------------------------------------------------------------


class TestPipelineNoEntitiesKb:
    def test_project_entity_has_create_project(self) -> None:
        kb = pipeline_no_entities_kb("project")
        cbs = _all_callbacks(kb)
        assert "projects:new" in cbs
        assert "menu:main" in cbs

    def test_wp_entity_has_connect_and_preview_only(self) -> None:
        kb = pipeline_no_entities_kb("wp")
        cbs = _all_callbacks(kb)
        assert any("connections" in c for c in cbs)
        assert "pipeline:article:wp:preview_only" in cbs
        assert "menu:main" in cbs

    def test_category_entity_has_create_category(self) -> None:
        kb = pipeline_no_entities_kb("category")
        cbs = _all_callbacks(kb)
        assert any("categories" in c for c in cbs)
        assert "menu:main" in cbs

    def test_always_has_cancel(self) -> None:
        for entity in ("project", "wp", "category"):
            kb = pipeline_no_entities_kb(entity)
            cbs = _all_callbacks(kb)
            assert "menu:main" in cbs
