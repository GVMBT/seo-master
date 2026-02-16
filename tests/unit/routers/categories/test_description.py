"""Tests for routers/categories/description.py — DescriptionGenerateFSM."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import Category, Project, User
from routers.categories.description import (
    DescriptionGenerateFSM,
    cb_description_confirm,
    cb_description_regen,
    cb_description_regen_entry,
    cb_description_save,
    cb_description_start,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def category_with_desc(project: Project) -> Category:
    return Category(id=10, project_id=project.id, name="Test Category", description="Existing description text.")


@pytest.fixture
def category_no_desc(project: Project) -> Category:
    return Category(id=10, project_id=project.id, name="Test Category", description=None)


# ---------------------------------------------------------------------------
# cb_description_start
# ---------------------------------------------------------------------------


class TestCbDescriptionStart:
    @patch("routers.categories.description.ProjectsRepository")
    @patch("routers.categories.description.CategoriesRepository")
    async def test_existing_description_shows_preview(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        project: Project,
        category_with_desc: Category,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:10:description"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=category_with_desc)
        mock_proj_repo_cls.return_value.get_by_id = AsyncMock(return_value=project)

        await cb_description_start(mock_callback, mock_state, user, mock_db)

        mock_callback.message.edit_text.assert_called_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Existing description text" in text

    @patch("routers.categories.description.ensure_no_active_fsm", new_callable=AsyncMock, return_value=None)
    @patch("routers.categories.description.ProjectsRepository")
    @patch("routers.categories.description.CategoriesRepository")
    async def test_no_description_sets_fsm_and_offers_generation(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_fsm: AsyncMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        project: Project,
        category_no_desc: Category,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:10:description"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=category_no_desc)
        mock_proj_repo_cls.return_value.get_by_id = AsyncMock(return_value=project)

        await cb_description_start(mock_callback, mock_state, user, mock_db)

        mock_state.set_state.assert_called_with(DescriptionGenerateFSM.confirm)
        mock_state.update_data.assert_called_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Сгенерировать описание" in text

    @patch("routers.categories.description.ProjectsRepository")
    @patch("routers.categories.description.CategoriesRepository")
    async def test_category_not_found(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:999:description"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=None)

        await cb_description_start(mock_callback, mock_state, user, mock_db)

        mock_callback.answer.assert_called_with("Категория не найдена.", show_alert=True)

    @patch("routers.categories.description.ProjectsRepository")
    @patch("routers.categories.description.CategoriesRepository")
    async def test_ownership_violation(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        category_no_desc: Category,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:10:description"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=category_no_desc)
        other_project = Project(id=1, user_id=999, name="Other", company_name="X", specialization="Y")
        mock_proj_repo_cls.return_value.get_by_id = AsyncMock(return_value=other_project)

        await cb_description_start(mock_callback, mock_state, user, mock_db)

        mock_callback.answer.assert_called_with("Категория не найдена.", show_alert=True)


# ---------------------------------------------------------------------------
# cb_description_regen_entry
# ---------------------------------------------------------------------------


class TestCbDescriptionRegenEntry:
    @patch("routers.categories.description.ensure_no_active_fsm", new_callable=AsyncMock, return_value=None)
    @patch("routers.categories.description.ProjectsRepository")
    @patch("routers.categories.description.CategoriesRepository")
    async def test_sets_fsm_state(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_fsm: AsyncMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        project: Project,
        category_with_desc: Category,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:10:description:regen"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=category_with_desc)
        mock_proj_repo_cls.return_value.get_by_id = AsyncMock(return_value=project)

        await cb_description_regen_entry(mock_callback, mock_state, user, mock_db)

        mock_state.set_state.assert_called_with(DescriptionGenerateFSM.confirm)
        mock_state.update_data.assert_called_once()


# ---------------------------------------------------------------------------
# cb_description_confirm
# ---------------------------------------------------------------------------


class TestCbDescriptionConfirm:
    @patch("routers.categories.description.DescriptionService")
    @patch("routers.categories.description.get_settings")
    @patch("routers.categories.description.TokenService")
    async def test_success_generates_and_shows_review(
        self,
        mock_token_cls: MagicMock,
        mock_settings: MagicMock,
        mock_desc_cls: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={"category_id": 10, "project_id": 1, "regen_count": 0})
        mock_settings.return_value.admin_ids = [0]
        mock_token_cls.return_value.check_balance = AsyncMock(return_value=True)
        mock_token_cls.return_value.charge = AsyncMock()

        mock_result = MagicMock()
        mock_result.content = "Generated description"
        mock_desc_cls.return_value.generate = AsyncMock(return_value=mock_result)

        await cb_description_confirm(mock_callback, mock_state, user, mock_db, ai_orchestrator=MagicMock())

        mock_state.set_state.assert_called_with(DescriptionGenerateFSM.review)
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Generated description" in text

    @patch("routers.categories.description.get_settings")
    @patch("routers.categories.description.TokenService")
    async def test_insufficient_balance_e38(
        self,
        mock_token_cls: MagicMock,
        mock_settings: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={"category_id": 10, "project_id": 1})
        mock_settings.return_value.admin_ids = [0]
        mock_token_cls.return_value.check_balance = AsyncMock(return_value=False)
        mock_token_cls.return_value.format_insufficient_msg = MagicMock(return_value="Not enough tokens")

        await cb_description_confirm(mock_callback, mock_state, user, mock_db, ai_orchestrator=MagicMock())

        mock_callback.answer.assert_called_with("Not enough tokens", show_alert=True)

    async def test_expired_session(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={})

        await cb_description_confirm(mock_callback, mock_state, user, mock_db, ai_orchestrator=MagicMock())

        mock_state.clear.assert_called_once()
        mock_callback.answer.assert_called_with("Сессия истекла.", show_alert=True)

    @patch("routers.categories.description.DescriptionService")
    @patch("routers.categories.description.get_settings")
    @patch("routers.categories.description.TokenService")
    async def test_generation_error_refunds(
        self,
        mock_token_cls: MagicMock,
        mock_settings: MagicMock,
        mock_desc_cls: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={"category_id": 10, "project_id": 1})
        mock_settings.return_value.admin_ids = [0]
        mock_token_cls.return_value.check_balance = AsyncMock(return_value=True)
        mock_token_cls.return_value.charge = AsyncMock()
        mock_token_cls.return_value.refund = AsyncMock()
        mock_desc_cls.return_value.generate = AsyncMock(side_effect=RuntimeError("AI error"))

        await cb_description_confirm(mock_callback, mock_state, user, mock_db, ai_orchestrator=MagicMock())

        mock_token_cls.return_value.refund.assert_called_once()
        mock_state.clear.assert_called_once()


# ---------------------------------------------------------------------------
# cb_description_save
# ---------------------------------------------------------------------------


class TestCbDescriptionSave:
    @patch("routers.categories.manage._format_category_card", return_value="Card text")
    @patch("routers.categories.description.category_card_kb")
    @patch("routers.categories.description.CategoriesRepository")
    async def test_save_success(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_card_kb: MagicMock,
        mock_format: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={"category_id": 10, "generated_text": "My desc"})
        cat = Category(id=10, project_id=1, name="Test")
        mock_cat_repo_cls.return_value.update = AsyncMock(return_value=cat)
        mock_card_kb.return_value.as_markup.return_value = MagicMock()

        await cb_description_save(mock_callback, mock_state, user, mock_db)

        mock_state.clear.assert_called_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "сохранено" in text.lower()

    async def test_save_expired_session(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={})

        await cb_description_save(mock_callback, mock_state, user, mock_db)

        mock_state.clear.assert_called_once()


# ---------------------------------------------------------------------------
# cb_description_regen
# ---------------------------------------------------------------------------


class TestCbDescriptionRegen:
    @patch("routers.categories.description.DescriptionService")
    @patch("routers.categories.description.get_settings")
    @patch("routers.categories.description.TokenService")
    async def test_free_regen_no_charge(
        self,
        mock_token_cls: MagicMock,
        mock_settings: MagicMock,
        mock_desc_cls: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """Regen count 0 -> 1 (regen_count + 1 = 1, <= 2) — no charge."""
        mock_state.get_data = AsyncMock(return_value={"category_id": 10, "project_id": 1, "regen_count": 0})
        mock_settings.return_value.admin_ids = [0]
        mock_result = MagicMock()
        mock_result.content = "New description"
        mock_desc_cls.return_value.generate = AsyncMock(return_value=mock_result)

        await cb_description_regen(mock_callback, mock_state, user, mock_db, ai_orchestrator=MagicMock())

        mock_token_cls.return_value.charge.assert_not_called()

    @patch("routers.categories.description.DescriptionService")
    @patch("routers.categories.description.get_settings")
    @patch("routers.categories.description.TokenService")
    async def test_paid_regen_charges(
        self,
        mock_token_cls: MagicMock,
        mock_settings: MagicMock,
        mock_desc_cls: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """Regen count 2 -> 3 (regen_count + 1 = 3, > 2) — paid."""
        mock_state.get_data = AsyncMock(return_value={"category_id": 10, "project_id": 1, "regen_count": 2})
        mock_settings.return_value.admin_ids = [0]
        mock_token_cls.return_value.check_balance = AsyncMock(return_value=True)
        mock_token_cls.return_value.charge = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = "New description"
        mock_desc_cls.return_value.generate = AsyncMock(return_value=mock_result)

        await cb_description_regen(mock_callback, mock_state, user, mock_db, ai_orchestrator=MagicMock())

        mock_token_cls.return_value.charge.assert_called_once()
