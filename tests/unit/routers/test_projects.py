"""Tests for routers/projects/."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import Project, User
from routers.projects import (
    ProjectCreateFSM,
    ProjectEditFSM,
    _format_project_card,
    _validate_field,
    cb_project_card,
    cb_project_delete,
    cb_project_delete_confirm,
    cb_project_edit,
    cb_project_field,
    cb_project_list,
    cb_project_new,
    cb_project_page,
    fsm_project_company,
    fsm_project_field_value,
    fsm_project_name,
    fsm_project_spec,
    fsm_project_url,
)

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidateField:
    def test_name_valid(self) -> None:
        assert _validate_field("name", "My Project") is None

    def test_name_too_short(self) -> None:
        assert _validate_field("name", "A") is not None

    def test_name_too_long(self) -> None:
        assert _validate_field("name", "x" * 101) is not None

    def test_company_name_valid(self) -> None:
        assert _validate_field("company_name", "Test Co") is None

    def test_company_name_too_short(self) -> None:
        assert _validate_field("company_name", "A") is not None

    def test_specialization_valid(self) -> None:
        assert _validate_field("specialization", "Web development") is None

    def test_specialization_too_short(self) -> None:
        assert _validate_field("specialization", "Web") is not None

    def test_website_url_valid(self) -> None:
        assert _validate_field("website_url", "https://example.com") is None

    def test_website_url_invalid(self) -> None:
        assert _validate_field("website_url", "not-a-url") is not None

    def test_email_valid(self) -> None:
        assert _validate_field("company_email", "test@example.com") is None

    def test_email_invalid(self) -> None:
        assert _validate_field("company_email", "not-an-email") is not None

    def test_phone_valid(self) -> None:
        assert _validate_field("company_phone", "+7 (999) 123-45-67") is None

    def test_phone_invalid(self) -> None:
        assert _validate_field("company_phone", "abc") is not None

    def test_generic_field_valid(self) -> None:
        assert _validate_field("company_city", "Moscow") is None

    def test_generic_field_too_short(self) -> None:
        assert _validate_field("company_city", "M") is not None


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------


class TestFormatProjectCard:
    def test_includes_name_and_company(self, project: Project) -> None:
        text = _format_project_card(project)
        assert project.name in text
        assert project.company_name in text

    def test_counts_filled_fields(self, project: Project) -> None:
        text = _format_project_card(project)
        assert "3/15" in text  # name + company_name + specialization

    def test_shows_category_count(self, project: Project) -> None:
        text = _format_project_card(project, category_count=5)
        assert "Категорий: 5" in text

    def test_shows_platforms(self, project: Project) -> None:
        text = _format_project_card(project, platform_names=["WordPress", "Telegram"])
        assert "Платформы: WordPress, Telegram" in text

    def test_shows_no_platforms(self, project: Project) -> None:
        text = _format_project_card(project)
        assert "Платформы: не подключены" in text


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


class TestCbProjectList:
    @pytest.mark.asyncio
    async def test_shows_empty_list(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        with patch("routers.projects.list.ProjectsRepository") as repo_cls:
            repo_cls.return_value.get_by_user = AsyncMock(return_value=[])
            await cb_project_list(mock_callback, user, mock_db)
            mock_callback.message.edit_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shows_projects(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock, project: Project
    ) -> None:
        with patch("routers.projects.list.ProjectsRepository") as repo_cls:
            repo_cls.return_value.get_by_user = AsyncMock(return_value=[project])
            await cb_project_list(mock_callback, user, mock_db)
            text = mock_callback.message.edit_text.call_args.args[0]
            assert "1" in text


class TestCbProjectPage:
    @pytest.mark.asyncio
    async def test_handles_pagination(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_callback.data = "page:projects:1"
        with patch("routers.projects.list.ProjectsRepository") as repo_cls:
            repo_cls.return_value.get_by_user = AsyncMock(return_value=[])
            await cb_project_page(mock_callback, user, mock_db)
            mock_callback.message.edit_text.assert_awaited_once()


class TestCbProjectCard:
    @pytest.mark.asyncio
    async def test_shows_card(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock, project: Project
    ) -> None:
        mock_callback.data = f"project:{project.id}:card"
        with (
            patch("routers.projects.card.ProjectsRepository") as repo_cls,
            patch("db.repositories.categories.CategoriesRepository") as cat_cls,
            patch("db.repositories.connections.ConnectionsRepository") as conn_cls,
            patch("bot.config.get_settings") as settings_mock,
            patch("db.credential_manager.CredentialManager"),
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=project)
            cat_cls.return_value.get_by_project = AsyncMock(return_value=[])
            conn_cls.return_value.get_platform_types_by_project = AsyncMock(return_value=[])
            settings_mock.return_value.encryption_key.get_secret_value.return_value = "test-key"
            await cb_project_card(mock_callback, user, mock_db)
            mock_callback.message.edit_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_found_shows_alert(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_callback.data = "project:999:card"
        with patch("routers.projects.card.ProjectsRepository") as repo_cls:
            repo_cls.return_value.get_by_id = AsyncMock(return_value=None)
            await cb_project_card(mock_callback, user, mock_db)
            mock_callback.answer.assert_awaited_once()
            assert mock_callback.answer.call_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# Create FSM
# ---------------------------------------------------------------------------


class TestProjectCreateFSM:
    @pytest.mark.asyncio
    async def test_new_starts_fsm(
        self, mock_callback: MagicMock, mock_state: AsyncMock,
        user: User, mock_db: MagicMock
    ) -> None:
        mock_callback.data = "projects:new"
        mock_state.get_state = AsyncMock(return_value=None)
        with patch("routers.projects.create.ProjectsRepository") as repo_cls:
            repo_cls.return_value.get_count_by_user = AsyncMock(return_value=0)
            await cb_project_new(mock_callback, mock_state, user, mock_db)
            mock_state.set_state.assert_awaited_once_with(ProjectCreateFSM.name)

    @pytest.mark.asyncio
    async def test_name_valid_advances(
        self, mock_message: MagicMock, mock_state: AsyncMock
    ) -> None:
        mock_message.text = "My Project"
        await fsm_project_name(mock_message, mock_state)
        mock_state.update_data.assert_awaited_once()
        mock_state.set_state.assert_awaited_once_with(ProjectCreateFSM.company_name)

    @pytest.mark.asyncio
    async def test_name_invalid_repeats(
        self, mock_message: MagicMock, mock_state: AsyncMock
    ) -> None:
        mock_message.text = "X"
        await fsm_project_name(mock_message, mock_state)
        mock_state.update_data.assert_not_awaited()
        mock_message.answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_company_advances(
        self, mock_message: MagicMock, mock_state: AsyncMock
    ) -> None:
        mock_message.text = "Test Company"
        await fsm_project_company(mock_message, mock_state)
        mock_state.set_state.assert_awaited_once_with(ProjectCreateFSM.specialization)

    @pytest.mark.asyncio
    async def test_spec_advances(
        self, mock_message: MagicMock, mock_state: AsyncMock
    ) -> None:
        mock_message.text = "Web development services"
        await fsm_project_spec(mock_message, mock_state)
        mock_state.set_state.assert_awaited_once_with(ProjectCreateFSM.website_url)

    @pytest.mark.asyncio
    async def test_url_creates_project(
        self, mock_message: MagicMock, mock_state: AsyncMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_message.text = "https://example.com"
        mock_state.get_data.return_value = {
            "name": "Test", "company_name": "Co", "specialization": "Testing things"
        }
        with patch("routers.projects.create.ProjectsRepository") as repo_cls:
            repo_cls.return_value.create = AsyncMock(
                return_value=Project(
                    id=1, user_id=user.id, name="Test",
                    company_name="Co", specialization="Testing things",
                    website_url="https://example.com",
                )
            )
            await fsm_project_url(mock_message, mock_state, user, mock_db)
            mock_state.clear.assert_awaited_once()
            repo_cls.return_value.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skip_creates_without_url(
        self, mock_message: MagicMock, mock_state: AsyncMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_message.text = "Пропустить"
        mock_state.get_data.return_value = {
            "name": "Test", "company_name": "Co", "specialization": "Testing things"
        }
        with patch("routers.projects.create.ProjectsRepository") as repo_cls:
            repo_cls.return_value.create = AsyncMock(
                return_value=Project(
                    id=1, user_id=user.id, name="Test",
                    company_name="Co", specialization="Testing things",
                )
            )
            await fsm_project_url(mock_message, mock_state, user, mock_db)
            create_arg = repo_cls.return_value.create.call_args.args[0]
            assert create_arg.website_url is None


# ---------------------------------------------------------------------------
# Edit FSM
# ---------------------------------------------------------------------------


class TestProjectEditFSM:
    @pytest.mark.asyncio
    async def test_edit_shows_fields(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock, project: Project
    ) -> None:
        mock_callback.data = f"project:{project.id}:edit"
        with patch("routers.projects.card.ProjectsRepository") as repo_cls:
            repo_cls.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_project_edit(mock_callback, user, mock_db)
            mock_callback.message.edit_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_field_starts_fsm(
        self, mock_callback: MagicMock, mock_state: AsyncMock, user: User,
        mock_db: MagicMock, project: Project
    ) -> None:
        mock_callback.data = f"project:{project.id}:field:company_city"
        with patch("routers.projects.card.ProjectsRepository") as repo_cls:
            repo_cls.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_project_field(mock_callback, mock_state, user, mock_db)
            mock_state.set_state.assert_awaited_once_with(ProjectEditFSM.field_value)

    @pytest.mark.asyncio
    async def test_field_value_saves(
        self, mock_message: MagicMock, mock_state: AsyncMock, user: User,
        mock_db: MagicMock, project: Project
    ) -> None:
        mock_message.text = "Moscow"
        mock_state.get_data.return_value = {
            "project_id": project.id, "field_name": "company_city"
        }
        with patch("routers.projects.create.ProjectsRepository") as repo_cls:
            updated = Project(**{**project.model_dump(), "company_city": "Moscow"})
            repo_cls.return_value.update = AsyncMock(return_value=updated)
            await fsm_project_field_value(mock_message, mock_state, user, mock_db)
            mock_state.clear.assert_awaited_once()
            repo_cls.return_value.update.assert_awaited_once()


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestProjectDelete:
    @pytest.mark.asyncio
    async def test_delete_shows_confirmation(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock, project: Project
    ) -> None:
        mock_callback.data = f"project:{project.id}:delete"
        with patch("routers.projects.card.ProjectsRepository") as repo_cls:
            repo_cls.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_project_delete(mock_callback, user, mock_db)
            text = mock_callback.message.edit_text.call_args.args[0]
            assert "удалить" in text.lower()

    @pytest.mark.asyncio
    async def test_delete_confirm_deletes(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock, project: Project
    ) -> None:
        mock_callback.data = f"project:{project.id}:delete:confirm"
        with patch("routers.projects.card.ProjectsRepository") as repo_cls:
            repo_cls.return_value.get_by_id = AsyncMock(return_value=project)
            repo_cls.return_value.delete = AsyncMock(return_value=True)
            repo_cls.return_value.get_by_user = AsyncMock(return_value=[])
            await cb_project_delete_confirm(mock_callback, user, mock_db)
            repo_cls.return_value.delete.assert_awaited_once_with(project.id)
