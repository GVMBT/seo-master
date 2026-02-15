"""Tests for routers/categories/reviews.py — ReviewGenerationFSM."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import Category, Project, User
from routers.categories.reviews import (
    ReviewGenerationFSM,
    _format_reviews,
    _truncate_review_text,
    cb_review_confirm,
    cb_review_generating_guard,
    cb_review_quantity,
    cb_review_regen,
    cb_review_save,
    cb_reviews_start,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_REVIEWS = [
    {"author": "Иван", "rating": 5, "text": "Отличный товар!", "pros": "Качество", "cons": "Цена"},
    {"author": "Анна", "rating": 4, "text": "Хорошо, но дорого.", "pros": "", "cons": "Стоимость"},
]


@pytest.fixture
def category_with_reviews(project: Project) -> Category:
    return Category(id=10, project_id=project.id, name="Test Category", reviews=_SAMPLE_REVIEWS)


@pytest.fixture
def category_no_reviews(project: Project) -> Category:
    return Category(id=10, project_id=project.id, name="Test Category", reviews=[])


# ---------------------------------------------------------------------------
# _format_reviews
# ---------------------------------------------------------------------------


class TestFormatReviews:
    def test_formats_with_pros_cons(self) -> None:
        text = _format_reviews(_SAMPLE_REVIEWS)
        assert "Иван" in text
        assert "Качество" in text
        assert "Цена" in text

    def test_empty_list(self) -> None:
        assert _format_reviews([]) == ""

    def test_truncates_long_text(self) -> None:
        review = [{"author": "X", "rating": 3, "text": "a" * 300}]
        text = _format_reviews(review)
        assert len(text) < 400  # truncated at 200 chars per review text

    def test_missing_fields_use_defaults(self) -> None:
        review = [{"text": "Just text"}]
        text = _format_reviews(review)
        assert "Аноним" in text  # default author


class TestTruncateReviewText:
    def test_short_text_unchanged(self) -> None:
        assert _truncate_review_text("short") == "short"

    def test_long_text_truncated(self) -> None:
        result = _truncate_review_text("x" * 5000)
        assert len(result) == 4003  # 4000 + "..."
        assert result.endswith("...")


# ---------------------------------------------------------------------------
# cb_reviews_start
# ---------------------------------------------------------------------------


class TestCbReviewsStart:
    @patch("routers.categories.reviews.ensure_no_active_fsm", new_callable=AsyncMock, return_value=None)
    @patch("routers.categories.reviews.ProjectsRepository")
    @patch("routers.categories.reviews.CategoriesRepository")
    async def test_no_reviews_shows_quantity(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_fsm: AsyncMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        project: Project,
        category_no_reviews: Category,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:10:reviews"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=category_no_reviews)
        mock_proj_repo_cls.return_value.get_by_id = AsyncMock(return_value=project)

        await cb_reviews_start(mock_callback, mock_state, user, mock_db)

        mock_state.set_state.assert_called_with(ReviewGenerationFSM.quantity)
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Сколько отзывов" in text

    @patch("routers.categories.reviews.ProjectsRepository")
    @patch("routers.categories.reviews.CategoriesRepository")
    async def test_existing_reviews_shows_them(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        project: Project,
        category_with_reviews: Category,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:10:reviews"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=category_with_reviews)
        mock_proj_repo_cls.return_value.get_by_id = AsyncMock(return_value=project)

        await cb_reviews_start(mock_callback, mock_state, user, mock_db)

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "2 шт." in text


# ---------------------------------------------------------------------------
# cb_review_quantity
# ---------------------------------------------------------------------------


class TestCbReviewQuantity:
    @patch("routers.categories.reviews._make_token_service")
    async def test_sets_cost_and_quantity(
        self,
        mock_make_ts: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "review:qty:10:5"
        mock_make_ts.return_value.check_balance = AsyncMock(return_value=True)

        await cb_review_quantity(mock_callback, mock_state, user, mock_db)

        mock_state.set_state.assert_called_with(ReviewGenerationFSM.confirm_cost)
        update_args = mock_state.update_data.call_args[1]
        assert update_args["quantity"] == 5
        assert update_args["cost"] == 50  # 5 * COST_REVIEW_EACH(10)

    @patch("routers.categories.reviews._make_token_service")
    async def test_e38_insufficient_balance(
        self,
        mock_make_ts: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "review:qty:10:10"
        mock_make_ts.return_value.check_balance = AsyncMock(return_value=False)
        mock_make_ts.return_value.format_insufficient_msg = MagicMock(return_value="Not enough")

        await cb_review_quantity(mock_callback, mock_state, user, mock_db)

        mock_callback.answer.assert_called_with("Not enough", show_alert=True)


# ---------------------------------------------------------------------------
# cb_review_confirm
# ---------------------------------------------------------------------------


class TestCbReviewConfirm:
    @patch("routers.categories.reviews._run_generation")
    @patch("routers.categories.reviews._make_token_service")
    async def test_success(
        self,
        mock_make_ts: MagicMock,
        mock_run_gen: AsyncMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(
            return_value={"category_id": 10, "project_id": 1, "quantity": 3, "cost": 30}
        )
        mock_make_ts.return_value.charge = AsyncMock()
        mock_run_gen.return_value = _SAMPLE_REVIEWS

        await cb_review_confirm(mock_callback, mock_state, user, mock_db, ai_orchestrator=MagicMock())

        mock_state.set_state.assert_any_call(ReviewGenerationFSM.review)

    async def test_expired_session(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={})

        await cb_review_confirm(mock_callback, mock_state, user, mock_db, ai_orchestrator=MagicMock())

        mock_state.clear.assert_called_once()

    @patch("routers.categories.reviews._run_generation")
    @patch("routers.categories.reviews._make_token_service")
    async def test_error_refunds(
        self,
        mock_make_ts: MagicMock,
        mock_run_gen: AsyncMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(
            return_value={"category_id": 10, "project_id": 1, "quantity": 3, "cost": 30}
        )
        mock_make_ts.return_value.charge = AsyncMock()
        mock_make_ts.return_value.refund = AsyncMock()
        mock_run_gen.side_effect = RuntimeError("AI error")

        await cb_review_confirm(mock_callback, mock_state, user, mock_db, ai_orchestrator=MagicMock())

        mock_make_ts.return_value.refund.assert_called_once()
        mock_state.clear.assert_called_once()


# ---------------------------------------------------------------------------
# cb_review_generating_guard (E07)
# ---------------------------------------------------------------------------


class TestCbReviewGeneratingGuard:
    async def test_shows_alert(self) -> None:
        cb = MagicMock()
        cb.answer = AsyncMock()
        await cb_review_generating_guard(cb)
        cb.answer.assert_called_with("Генерация в процессе. Подождите.", show_alert=True)


# ---------------------------------------------------------------------------
# cb_review_save
# ---------------------------------------------------------------------------


class TestCbReviewSave:
    @patch("routers.categories.manage._format_category_card", return_value="Card text")
    @patch("routers.categories.reviews.category_card_kb")
    @patch("routers.categories.reviews.CategoriesRepository")
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
            return_value={"category_id": 10, "generated_reviews": _SAMPLE_REVIEWS}
        )
        cat = Category(id=10, project_id=1, name="Test")
        mock_cat_repo_cls.return_value.update_reviews = AsyncMock(return_value=cat)
        mock_card_kb.return_value.as_markup.return_value = MagicMock()

        await cb_review_save(mock_callback, mock_state, user, mock_db)

        mock_state.clear.assert_called_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "сохранены" in text.lower()


# ---------------------------------------------------------------------------
# cb_review_regen
# ---------------------------------------------------------------------------


class TestCbReviewRegen:
    @patch("routers.categories.reviews._run_generation")
    @patch("routers.categories.reviews._make_token_service")
    async def test_free_regen(
        self,
        mock_make_ts: MagicMock,
        mock_run_gen: AsyncMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(
            return_value={"category_id": 10, "project_id": 1, "quantity": 3, "regen_count": 0}
        )
        mock_run_gen.return_value = _SAMPLE_REVIEWS

        await cb_review_regen(mock_callback, mock_state, user, mock_db, ai_orchestrator=MagicMock())

        mock_make_ts.return_value.charge.assert_not_called()

    @patch("routers.categories.reviews._run_generation")
    @patch("routers.categories.reviews._make_token_service")
    async def test_paid_regen(
        self,
        mock_make_ts: MagicMock,
        mock_run_gen: AsyncMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(
            return_value={"category_id": 10, "project_id": 1, "quantity": 3, "regen_count": 2}
        )
        mock_make_ts.return_value.check_balance = AsyncMock(return_value=True)
        mock_make_ts.return_value.charge = AsyncMock()
        mock_run_gen.return_value = _SAMPLE_REVIEWS

        await cb_review_regen(mock_callback, mock_state, user, mock_db, ai_orchestrator=MagicMock())

        mock_make_ts.return_value.charge.assert_called_once()
