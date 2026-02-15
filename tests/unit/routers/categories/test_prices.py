"""Tests for routers/categories/prices.py — PriceInputFSM."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import Category, Project, User
from routers.categories.prices import (
    _MAX_LINES,
    PriceInputFSM,
    cb_price_clear,
    cb_price_excel,
    cb_price_text,
    cb_prices_start,
    cb_prices_update,
    fsm_price_file_upload,
    fsm_price_save_excel,
    fsm_price_save_text,
    fsm_price_text_input,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def category_with_prices(project: Project) -> Category:
    return Category(
        id=10,
        project_id=project.id,
        name="Test Category",
        prices="Товар 1 — 100 руб.\nТовар 2 — 200 руб.",
    )


@pytest.fixture
def category_no_prices(project: Project) -> Category:
    return Category(id=10, project_id=project.id, name="Test Category", prices=None)


@pytest.fixture
def mock_message() -> MagicMock:
    msg = MagicMock()
    msg.answer = AsyncMock()
    msg.text = ""
    return msg


# ---------------------------------------------------------------------------
# cb_prices_start
# ---------------------------------------------------------------------------


class TestCbPricesStart:
    @patch("routers.categories.prices.ProjectsRepository")
    @patch("routers.categories.prices.CategoriesRepository")
    async def test_existing_prices_shows_preview(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_callback: MagicMock,
        user: User,
        project: Project,
        category_with_prices: Category,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:10:prices"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=category_with_prices)
        mock_proj_repo_cls.return_value.get_by_id = AsyncMock(return_value=project)

        await cb_prices_start(mock_callback, user, mock_db)

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "2 позиций" in text

    @patch("routers.categories.prices.ProjectsRepository")
    @patch("routers.categories.prices.CategoriesRepository")
    async def test_no_prices_shows_method_choice(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_callback: MagicMock,
        user: User,
        project: Project,
        category_no_prices: Category,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:10:prices"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=category_no_prices)
        mock_proj_repo_cls.return_value.get_by_id = AsyncMock(return_value=project)

        await cb_prices_start(mock_callback, user, mock_db)

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Выберите способ" in text

    @patch("routers.categories.prices.ProjectsRepository")
    @patch("routers.categories.prices.CategoriesRepository")
    async def test_category_not_found(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:999:prices"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=None)

        await cb_prices_start(mock_callback, user, mock_db)

        mock_callback.answer.assert_called_with("Категория не найдена.", show_alert=True)


# ---------------------------------------------------------------------------
# cb_price_text
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# cb_prices_update
# ---------------------------------------------------------------------------


class TestCbPricesUpdate:
    @patch("routers.categories.prices.ProjectsRepository")
    @patch("routers.categories.prices.CategoriesRepository")
    async def test_shows_method_choice(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_callback: MagicMock,
        user: User,
        project: Project,
        category_with_prices: Category,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:10:prices:update"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=category_with_prices)
        mock_proj_repo_cls.return_value.get_by_id = AsyncMock(return_value=project)

        await cb_prices_update(mock_callback, user, mock_db)

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Выберите способ" in text

    @patch("routers.categories.prices.ProjectsRepository")
    @patch("routers.categories.prices.CategoriesRepository")
    async def test_ownership_violation(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_callback: MagicMock,
        user: User,
        category_with_prices: Category,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:10:prices:update"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=category_with_prices)
        other_project = Project(id=1, user_id=999, name="Other", company_name="X", specialization="Y")
        mock_proj_repo_cls.return_value.get_by_id = AsyncMock(return_value=other_project)

        await cb_prices_update(mock_callback, user, mock_db)

        mock_callback.answer.assert_called_with("Категория не найдена.", show_alert=True)


# ---------------------------------------------------------------------------
# cb_price_excel
# ---------------------------------------------------------------------------


class TestCbPriceExcel:
    @patch("routers.categories.prices.ensure_no_active_fsm", new_callable=AsyncMock, return_value=None)
    @patch("routers.categories.prices.ProjectsRepository")
    @patch("routers.categories.prices.CategoriesRepository")
    async def test_sets_file_upload_state(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_fsm: AsyncMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        project: Project,
        category_no_prices: Category,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "price:cat:10:excel"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=category_no_prices)
        mock_proj_repo_cls.return_value.get_by_id = AsyncMock(return_value=project)

        await cb_price_excel(mock_callback, mock_state, user, mock_db)

        mock_state.set_state.assert_called_with(PriceInputFSM.file_upload)

    @patch("routers.categories.prices.ProjectsRepository")
    @patch("routers.categories.prices.CategoriesRepository")
    async def test_category_not_found(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "price:cat:999:excel"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=None)

        await cb_price_excel(mock_callback, mock_state, user, mock_db)

        mock_callback.answer.assert_called_with("Категория не найдена.", show_alert=True)


# ---------------------------------------------------------------------------
# cb_price_text
# ---------------------------------------------------------------------------


class TestCbPriceText:
    @patch("routers.categories.prices.ensure_no_active_fsm", new_callable=AsyncMock, return_value=None)
    @patch("routers.categories.prices.ProjectsRepository")
    @patch("routers.categories.prices.CategoriesRepository")
    async def test_sets_text_input_state(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_fsm: AsyncMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        project: Project,
        category_no_prices: Category,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "price:cat:10:text"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=category_no_prices)
        mock_proj_repo_cls.return_value.get_by_id = AsyncMock(return_value=project)

        await cb_price_text(mock_callback, mock_state, user, mock_db)

        mock_state.set_state.assert_called_with(PriceInputFSM.text_input)


# ---------------------------------------------------------------------------
# fsm_price_text_input
# ---------------------------------------------------------------------------


class TestFsmPriceTextInput:
    async def test_valid_input_shows_preview(
        self, mock_state: AsyncMock, user: User, mock_db: MagicMock
    ) -> None:
        msg = MagicMock()
        msg.answer = AsyncMock()
        msg.text = "Товар 1 — 100\nТовар 2 — 200\nТовар 3 — 300"
        mock_state.get_data = AsyncMock(return_value={"category_id": 10})

        await fsm_price_text_input(msg, mock_state, user, mock_db)

        text = msg.answer.call_args[0][0]
        assert "3 позиций" in text

    async def test_empty_input_rejected(
        self, mock_state: AsyncMock, user: User, mock_db: MagicMock
    ) -> None:
        msg = MagicMock()
        msg.answer = AsyncMock()
        msg.text = "   "

        await fsm_price_text_input(msg, mock_state, user, mock_db)

        msg.answer.assert_called_with("Введите непустой прайс-лист.")

    async def test_e09_too_many_lines(
        self, mock_state: AsyncMock, user: User, mock_db: MagicMock
    ) -> None:
        msg = MagicMock()
        msg.answer = AsyncMock()
        msg.text = "\n".join(f"Товар {i} — {i}00" for i in range(1100))

        await fsm_price_text_input(msg, mock_state, user, mock_db)

        text = msg.answer.call_args[0][0]
        assert str(_MAX_LINES) in text


# ---------------------------------------------------------------------------
# fsm_price_file_upload
# ---------------------------------------------------------------------------


class TestFsmPriceFileUpload:
    async def test_non_xlsx_rejected(
        self, mock_state: AsyncMock, user: User, mock_db: MagicMock
    ) -> None:
        msg = MagicMock()
        msg.answer = AsyncMock()
        msg.document = MagicMock()
        msg.document.file_name = "data.csv"
        msg.document.file_size = 1000

        await fsm_price_file_upload(msg, mock_state, user, mock_db)

        msg.answer.assert_called_with("Поддерживается только формат .xlsx.")

    async def test_oversized_file_rejected(
        self, mock_state: AsyncMock, user: User, mock_db: MagicMock
    ) -> None:
        msg = MagicMock()
        msg.answer = AsyncMock()
        msg.document = MagicMock()
        msg.document.file_name = "data.xlsx"
        msg.document.file_size = 10 * 1024 * 1024  # 10MB

        await fsm_price_file_upload(msg, mock_state, user, mock_db)

        text = msg.answer.call_args[0][0]
        assert "слишком большой" in text.lower()

    async def test_no_document_rejected(
        self, mock_state: AsyncMock, user: User, mock_db: MagicMock
    ) -> None:
        msg = MagicMock()
        msg.answer = AsyncMock()
        msg.document = None

        await fsm_price_file_upload(msg, mock_state, user, mock_db)

        msg.answer.assert_called_with("Отправьте файл Excel (.xlsx).")


# ---------------------------------------------------------------------------
# fsm_price_save_text
# ---------------------------------------------------------------------------


class TestFsmPriceSaveText:
    @patch("routers.categories.manage._format_category_card", return_value="Card")
    @patch("routers.categories.prices.category_card_kb")
    @patch("routers.categories.prices.CategoriesRepository")
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
        mock_state.get_data = AsyncMock(
            return_value={"category_id": 10, "prices_text": "Item — 100"}
        )
        cat = Category(id=10, project_id=1, name="Test")
        mock_cat_repo_cls.return_value.update = AsyncMock(return_value=cat)
        mock_card_kb.return_value.as_markup.return_value = MagicMock()

        await fsm_price_save_text(mock_callback, mock_state, user, mock_db)

        mock_state.clear.assert_called_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "сохранён" in text.lower()

    async def test_expired_session(
        self, mock_callback: MagicMock, mock_state: AsyncMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={})

        await fsm_price_save_text(mock_callback, mock_state, user, mock_db)

        mock_state.clear.assert_called_once()


# ---------------------------------------------------------------------------
# fsm_price_save_excel
# ---------------------------------------------------------------------------


class TestFsmPriceSaveExcel:
    @patch("routers.categories.manage._format_category_card", return_value="Card")
    @patch("routers.categories.prices.category_card_kb")
    @patch("routers.categories.prices.CategoriesRepository")
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
        mock_state.get_data = AsyncMock(
            return_value={"category_id": 10, "prices_text": "Item — 100"}
        )
        cat = Category(id=10, project_id=1, name="Test")
        mock_cat_repo_cls.return_value.update = AsyncMock(return_value=cat)
        mock_card_kb.return_value.as_markup.return_value = MagicMock()

        await fsm_price_save_excel(mock_callback, mock_state, user, mock_db)

        mock_state.clear.assert_called_once()


# ---------------------------------------------------------------------------
# cb_price_clear
# ---------------------------------------------------------------------------


class TestCbPriceClear:
    @patch("routers.categories.prices.ProjectsRepository")
    @patch("routers.categories.prices.CategoriesRepository")
    async def test_clears_prices(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_callback: MagicMock,
        user: User,
        project: Project,
        category_with_prices: Category,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "price:cat:10:clear"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=category_with_prices)
        mock_proj_repo_cls.return_value.get_by_id = AsyncMock(return_value=project)
        mock_cat_repo_cls.return_value.update = AsyncMock(return_value=category_with_prices)

        await cb_price_clear(mock_callback, user, mock_db)

        mock_cat_repo_cls.return_value.update.assert_called_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "очищен" in text.lower()
