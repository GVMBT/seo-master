"""Tests for keyboards/inline.py."""

from keyboards.inline import (
    PROJECT_FIELDS,
    category_card_kb,
    category_delete_confirm_kb,
    category_list_kb,
    dashboard_kb,
    project_card_kb,
    project_delete_confirm_kb,
    project_edit_fields_kb,
    project_list_kb,
    settings_main_kb,
    settings_notifications_kb,
)

from .helpers import make_category, make_project, make_user


class TestDashboardKb:
    def test_has_7_buttons(self) -> None:
        builder = dashboard_kb()
        markup = builder.as_markup()
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        assert len(buttons) == 7

    def test_callback_data_values(self) -> None:
        builder = dashboard_kb()
        markup = builder.as_markup()
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "pipeline:article:start" in callbacks
        assert "pipeline:social:start" in callbacks
        assert "projects:list" in callbacks
        assert "profile:main" in callbacks
        assert "tariffs:main" in callbacks
        assert "settings:main" in callbacks
        assert "help:main" in callbacks

    def test_layout_1_1_2_2_1(self) -> None:
        builder = dashboard_kb()
        markup = builder.as_markup()
        row_sizes = [len(row) for row in markup.inline_keyboard]
        assert row_sizes == [1, 1, 2, 2, 1]

    def test_pipeline_cta_buttons_on_top(self) -> None:
        builder = dashboard_kb()
        markup = builder.as_markup()
        first_btn = markup.inline_keyboard[0][0]
        second_btn = markup.inline_keyboard[1][0]
        assert first_btn.callback_data == "pipeline:article:start"
        assert second_btn.callback_data == "pipeline:social:start"


class TestProjectListKb:
    def test_empty_list_has_create_and_help(self) -> None:
        """Empty state shows [Создать проект] + [Помощь] per spec."""
        builder = project_list_kb([])
        markup = builder.as_markup()
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        texts = [b.text for b in buttons]
        assert "Создать проект" in texts
        assert "Помощь" in texts
        assert len(buttons) == 2

    def test_shows_project_names(self) -> None:
        projects = [make_project(id=1, name="A"), make_project(id=2, name="B")]
        builder = project_list_kb(projects)
        markup = builder.as_markup()
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        texts = [b.text for b in buttons]
        assert "A" in texts
        assert "B" in texts

    def test_non_empty_has_stats_and_menu(self) -> None:
        """Non-empty list has [Создать], [Статистика], [Главное меню] per spec."""
        projects = [make_project(id=1)]
        builder = project_list_kb(projects)
        markup = builder.as_markup()
        texts = [btn.text for row in markup.inline_keyboard for btn in row]
        assert "Создать проект" in texts
        assert "Статистика" in texts
        assert "Главное меню" in texts

    def test_project_callback_data_format(self) -> None:
        projects = [make_project(id=5)]
        builder = project_list_kb(projects)
        markup = builder.as_markup()
        assert markup.inline_keyboard[0][0].callback_data == "project:5:card"

    def test_pagination_shows_more_button(self) -> None:
        projects = [make_project(id=i, name=f"P{i}") for i in range(10)]
        builder = project_list_kb(projects, page=0)
        markup = builder.as_markup()
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        texts = [b.text for b in buttons]
        assert "Ещё ▼" in texts

    def test_pagination_nav_buttons_same_row(self) -> None:
        """Nav buttons (back+more) must be side-by-side, not on separate rows."""
        projects = [make_project(id=i, name=f"P{i}") for i in range(20)]
        builder = project_list_kb(projects, page=1)
        markup = builder.as_markup()
        # Find row containing nav buttons
        nav_row = None
        for row in markup.inline_keyboard:
            texts = [b.text for b in row]
            if any("Назад" in t for t in texts):
                nav_row = row
                break
        assert nav_row is not None
        assert len(nav_row) == 2  # back + more side-by-side


class TestProjectCardKb:
    def test_has_all_action_buttons(self) -> None:
        project = make_project(id=7)
        builder = project_card_kb(project)
        markup = builder.as_markup()
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "project:7:edit" in callbacks
        assert "project:7:categories" in callbacks
        assert "project:7:cat:new" in callbacks
        assert "project:7:connections" in callbacks
        assert "project:7:scheduler" in callbacks
        assert "project:7:audit" in callbacks
        assert "project:7:timezone" in callbacks
        assert "project:7:delete" in callbacks
        assert "projects:list" in callbacks

    def test_button_order_matches_spec(self) -> None:
        """Button order per USER_FLOWS_AND_UI_MAP.md lines 507-516."""
        project = make_project(id=1)
        builder = project_card_kb(project)
        markup = builder.as_markup()
        texts = [btn.text for row in markup.inline_keyboard for btn in row]
        assert texts == [
            "Редактировать данные",
            "Управление категориями",
            "Создать категорию",
            "Подключения платформ",
            "Планировщик публикаций",
            "Анализ сайта",
            f"Часовой пояс: {project.timezone}",
            "Удалить проект",
            "К списку проектов",
        ]

    def test_scheduler_button_text(self) -> None:
        """Scheduler button must say 'Планировщик публикаций', not 'Планировщик'."""
        project = make_project(id=1)
        builder = project_card_kb(project)
        markup = builder.as_markup()
        texts = [btn.text for row in markup.inline_keyboard for btn in row]
        assert "Планировщик публикаций" in texts


class TestProjectEditFieldsKb:
    def test_has_15_fields_plus_back(self) -> None:
        project = make_project()
        builder = project_edit_fields_kb(project)
        markup = builder.as_markup()
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        assert len(buttons) == 16  # 15 fields + back

    def test_field_callback_data_format(self) -> None:
        project = make_project(id=3)
        builder = project_edit_fields_kb(project)
        markup = builder.as_markup()
        first_btn = markup.inline_keyboard[0][0]
        assert first_btn.callback_data == "project:3:field:name"


class TestProjectDeleteConfirmKb:
    def test_has_confirm_and_cancel(self) -> None:
        builder = project_delete_confirm_kb(5)
        markup = builder.as_markup()
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        callbacks = [b.callback_data for b in buttons]
        assert "project:5:delete:confirm" in callbacks
        assert "project:5:card" in callbacks


class TestProjectFields:
    def test_has_15_fields(self) -> None:
        assert len(PROJECT_FIELDS) == 15

    def test_all_field_names_are_on_project_model(self) -> None:
        from db.models import Project

        model_fields = Project.model_fields
        for field_name, _ in PROJECT_FIELDS:
            assert field_name in model_fields, f"{field_name} not on Project model"


class TestCategoryListKb:
    def test_empty_list_has_add_and_back(self) -> None:
        builder = category_list_kb([], project_id=5)
        markup = builder.as_markup()
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        callbacks = [b.callback_data for b in buttons]
        assert "project:5:cat:new" in callbacks
        assert "project:5:card" in callbacks

    def test_shows_category_names(self) -> None:
        cats = [make_category(id=1, name="Cat A"), make_category(id=2, name="Cat B")]
        builder = category_list_kb(cats, project_id=5)
        markup = builder.as_markup()
        texts = [btn.text for row in markup.inline_keyboard for btn in row]
        assert "Cat A" in texts
        assert "Cat B" in texts

    def test_pagination_callback_includes_project_id(self) -> None:
        cats = [make_category(id=i, name=f"C{i}") for i in range(10)]
        builder = category_list_kb(cats, project_id=7, page=0)
        markup = builder.as_markup()
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        more_btn = [b for b in buttons if b.text == "Ещё ▼"]
        assert len(more_btn) == 1
        assert more_btn[0].callback_data == "page:categories:7:1"

    def test_pagination_nav_buttons_same_row(self) -> None:
        cats = [make_category(id=i, name=f"C{i}") for i in range(20)]
        builder = category_list_kb(cats, project_id=1, page=1)
        markup = builder.as_markup()
        nav_row = None
        for row in markup.inline_keyboard:
            texts = [b.text for b in row]
            if any("Назад" in t for t in texts):
                nav_row = row
                break
        assert nav_row is not None
        assert len(nav_row) == 2


class TestCategoryCardKb:
    def test_has_feature_stubs_and_delete(self) -> None:
        cat = make_category(id=10, project_id=5)
        builder = category_card_kb(cat)
        markup = builder.as_markup()
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "category:10:keywords" in callbacks
        assert "category:10:img_settings" in callbacks
        assert "category:10:text_settings" in callbacks
        assert "category:10:delete" in callbacks
        assert "project:5:categories" in callbacks


class TestCategoryDeleteConfirmKb:
    def test_has_confirm_and_cancel(self) -> None:
        cat = make_category(id=8)
        builder = category_delete_confirm_kb(cat)
        markup = builder.as_markup()
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "category:8:delete:confirm" in callbacks
        assert "category:8:card" in callbacks


class TestSettingsMainKb:
    def test_has_notifications_and_menu(self) -> None:
        builder = settings_main_kb()
        markup = builder.as_markup()
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "settings:notifications" in callbacks
        assert "menu:main" in callbacks


class TestSettingsNotificationsKb:
    def test_shows_current_status(self) -> None:
        user = make_user(notify_publications=True, notify_balance=False, notify_news=True)
        builder = settings_notifications_kb(user)
        markup = builder.as_markup()
        texts = [btn.text for row in markup.inline_keyboard for btn in row]
        assert any("ВКЛ" in t and "Публикации" in t for t in texts)
        assert any("ВЫКЛ" in t and "Баланс" in t for t in texts)
        assert any("ВКЛ" in t and "Новости" in t for t in texts)

    def test_has_back_button(self) -> None:
        user = make_user()
        builder = settings_notifications_kb(user)
        markup = builder.as_markup()
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "settings:main" in callbacks

    def test_toggle_callbacks(self) -> None:
        user = make_user()
        builder = settings_notifications_kb(user)
        markup = builder.as_markup()
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "settings:notify:publications" in callbacks
        assert "settings:notify:balance" in callbacks
        assert "settings:notify:news" in callbacks
