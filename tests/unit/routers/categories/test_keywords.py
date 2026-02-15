"""Tests for routers/categories/keywords.py — KeywordGenerationFSM + KeywordUploadFSM."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import Category, Project, User
from routers.categories.keywords import (
    KeywordGenerationFSM,
    KeywordUploadFSM,
    _build_upload_clusters,
    _format_cluster_summary,
    _select_keyword_from_clusters,
    cb_keywords_main,
    cb_kw_confirm,
    cb_kw_generate_start,
    cb_kw_quantity,
    cb_kw_save,
    cb_kw_upload_save,
    cb_kw_upload_start,
    fsm_kw_geography,
    fsm_kw_products,
    fsm_kw_upload_file,
)

# Re-use fixtures from conftest.py (user, project, category, mock_callback, etc.)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def category_with_keywords(project: Project) -> Category:
    """Category with existing clustered keywords."""
    return Category(
        id=10,
        project_id=project.id,
        name="Test Category",
        keywords=[
            {
                "cluster_name": "SEO tools",
                "cluster_type": "article",
                "main_phrase": "seo tools",
                "total_volume": 500,
                "avg_difficulty": 30,
                "phrases": [
                    {"phrase": "seo tools", "volume": 300, "difficulty": 25, "cpc": 10.0},
                    {"phrase": "seo software", "volume": 200, "difficulty": 35, "cpc": 12.0},
                ],
            },
            {
                "cluster_name": "SEO pricing",
                "cluster_type": "article",
                "main_phrase": "seo pricing",
                "total_volume": 200,
                "avg_difficulty": 40,
                "phrases": [
                    {"phrase": "seo pricing", "volume": 200, "difficulty": 40, "cpc": 15.0},
                ],
            },
        ],
    )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestSelectKeywordFromClusters:
    def test_selects_article_cluster(self) -> None:
        kw = [
            {"cluster_type": "product_page", "main_phrase": "buy seo"},
            {"cluster_type": "article", "main_phrase": "seo guide"},
        ]
        assert _select_keyword_from_clusters(kw) == "seo guide"

    def test_first_article_cluster(self) -> None:
        kw = [
            {"cluster_type": "article", "main_phrase": "first"},
            {"cluster_type": "article", "main_phrase": "second"},
        ]
        assert _select_keyword_from_clusters(kw) == "first"

    def test_legacy_flat_format(self) -> None:
        kw = [{"phrase": "old keyword", "volume": 100}]
        assert _select_keyword_from_clusters(kw) == "old keyword"

    def test_empty_list(self) -> None:
        assert _select_keyword_from_clusters([]) is None

    def test_no_article_clusters(self) -> None:
        kw = [{"cluster_type": "product_page", "main_phrase": "buy"}]
        assert _select_keyword_from_clusters(kw) is None


class TestFormatClusterSummary:
    def test_basic_format(self) -> None:
        clusters = [{"cluster_name": "Test", "phrases": [{"phrase": "a"}], "total_volume": 100}]
        result = _format_cluster_summary(clusters)
        assert "1 кластеров" in result
        assert "Test" in result
        assert "100" in result

    def test_truncates_at_10(self) -> None:
        clusters = [{"cluster_name": f"Cluster {i}", "phrases": [], "total_volume": 0} for i in range(15)]
        result = _format_cluster_summary(clusters)
        assert "ещё 5" in result

    def test_shows_phrase_count(self) -> None:
        clusters = [
            {
                "cluster_name": "SEO",
                "phrases": [{"phrase": "a"}, {"phrase": "b"}, {"phrase": "c"}],
                "total_volume": 300,
            }
        ]
        result = _format_cluster_summary(clusters)
        assert "3 фраз" in result


class TestBuildUploadClusters:
    def test_single_cluster(self) -> None:
        result = _build_upload_clusters(["seo", "marketing", "content"])
        assert len(result) == 1
        assert result[0]["cluster_name"] == "Загруженные фразы"
        assert len(result[0]["phrases"]) == 3

    def test_main_phrase_is_first(self) -> None:
        result = _build_upload_clusters(["first phrase", "second phrase"])
        assert result[0]["main_phrase"] == "first phrase"


# ---------------------------------------------------------------------------
# cb_keywords_main
# ---------------------------------------------------------------------------


class TestCbKeywordsMain:
    async def test_shows_empty_state(
        self,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
        category: Category,
    ) -> None:
        mock_callback.data = f"category:{category.id}:keywords"
        with (
            patch("routers.categories.keywords.CategoriesRepository") as cat_cls,
            patch("routers.categories.keywords.ProjectsRepository") as proj_cls,
        ):
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_keywords_main(mock_callback, user, mock_db)
            text = mock_callback.message.edit_text.call_args.args[0]
            assert "не добавлены" in text

    async def test_shows_keyword_summary(
        self,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
        category_with_keywords: Category,
    ) -> None:
        mock_callback.data = f"category:{category_with_keywords.id}:keywords"
        with (
            patch("routers.categories.keywords.CategoriesRepository") as cat_cls,
            patch("routers.categories.keywords.ProjectsRepository") as proj_cls,
        ):
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category_with_keywords)
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_keywords_main(mock_callback, user, mock_db)
            text = mock_callback.message.edit_text.call_args.args[0]
            assert "2 кластеров" in text
            assert "3 фраз" in text

    async def test_unauthorized_shows_alert(
        self,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:999:keywords"
        with patch("routers.categories.keywords.CategoriesRepository") as cat_cls:
            cat_cls.return_value.get_by_id = AsyncMock(return_value=None)
            await cb_keywords_main(mock_callback, user, mock_db)
            mock_callback.answer.assert_awaited()
            assert mock_callback.answer.call_args.kwargs.get("show_alert") is True

    async def test_wrong_owner_shows_alert(
        self,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
        category: Category,
    ) -> None:
        mock_callback.data = f"category:{category.id}:keywords"
        other_project = Project(id=1, user_id=999, name="Other", company_name="Other", specialization="Other")
        with (
            patch("routers.categories.keywords.CategoriesRepository") as cat_cls,
            patch("routers.categories.keywords.ProjectsRepository") as proj_cls,
        ):
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            proj_cls.return_value.get_by_id = AsyncMock(return_value=other_project)
            await cb_keywords_main(mock_callback, user, mock_db)
            mock_callback.answer.assert_awaited()
            assert mock_callback.answer.call_args.kwargs.get("show_alert") is True

    async def test_inaccessible_message(
        self,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:10:keywords"
        mock_callback.message = MagicMock()  # Not a Message instance
        await cb_keywords_main(mock_callback, user, mock_db)
        # Should not crash; guard returns None


# ---------------------------------------------------------------------------
# cb_kw_generate_start
# ---------------------------------------------------------------------------


class TestCbKwGenerateStart:
    async def test_sets_fsm_state(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
        category: Category,
    ) -> None:
        mock_callback.data = f"category:{category.id}:kw:generate"
        mock_state.get_state = AsyncMock(return_value=None)
        with (
            patch("routers.categories.keywords.CategoriesRepository") as cat_cls,
            patch("routers.categories.keywords.ProjectsRepository") as proj_cls,
        ):
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_kw_generate_start(mock_callback, mock_state, user, mock_db)
            mock_state.set_state.assert_awaited_once_with(KeywordGenerationFSM.products)
            mock_state.update_data.assert_awaited_once_with(category_id=category.id)

    async def test_clears_previous_fsm(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
        category: Category,
    ) -> None:
        mock_callback.data = f"category:{category.id}:kw:generate"
        mock_state.get_state = AsyncMock(return_value="CategoryCreateFSM:name")
        with (
            patch("routers.categories.keywords.CategoriesRepository") as cat_cls,
            patch("routers.categories.keywords.ProjectsRepository") as proj_cls,
        ):
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_kw_generate_start(mock_callback, mock_state, user, mock_db)
            mock_state.clear.assert_awaited()
            # Should also notify about interrupted process
            answered_text = mock_callback.message.answer.call_args_list[0].args[0]
            assert "прерван" in answered_text

    async def test_unauthorized_denied(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:999:kw:generate"
        with patch("routers.categories.keywords.CategoriesRepository") as cat_cls:
            cat_cls.return_value.get_by_id = AsyncMock(return_value=None)
            await cb_kw_generate_start(mock_callback, mock_state, user, mock_db)
            mock_state.set_state.assert_not_awaited()


# ---------------------------------------------------------------------------
# fsm_kw_products
# ---------------------------------------------------------------------------


class TestFsmKwProducts:
    async def test_valid_input(self, mock_message: MagicMock, mock_state: AsyncMock) -> None:
        mock_message.text = "Shoes, boots, and sneakers"
        await fsm_kw_products(mock_message, mock_state)
        mock_state.update_data.assert_awaited_once()
        mock_state.set_state.assert_awaited_once_with(KeywordGenerationFSM.geography)

    async def test_too_short(self, mock_message: MagicMock, mock_state: AsyncMock) -> None:
        mock_message.text = "AB"
        await fsm_kw_products(mock_message, mock_state)
        mock_state.set_state.assert_not_awaited()
        mock_message.answer.assert_awaited_once()
        assert "минимум 3" in mock_message.answer.call_args.args[0].lower()

    async def test_too_long(self, mock_message: MagicMock, mock_state: AsyncMock) -> None:
        mock_message.text = "x" * 1001
        await fsm_kw_products(mock_message, mock_state)
        mock_state.set_state.assert_not_awaited()
        assert "максимум 1000" in mock_message.answer.call_args.args[0].lower()

    async def test_whitespace_only(self, mock_message: MagicMock, mock_state: AsyncMock) -> None:
        mock_message.text = "   "
        await fsm_kw_products(mock_message, mock_state)
        mock_state.set_state.assert_not_awaited()


# ---------------------------------------------------------------------------
# fsm_kw_geography
# ---------------------------------------------------------------------------


class TestFsmKwGeography:
    async def test_valid_input(self, mock_message: MagicMock, mock_state: AsyncMock) -> None:
        mock_message.text = "Moscow, Russia"
        mock_state.get_data.return_value = {"category_id": 10}
        await fsm_kw_geography(mock_message, mock_state)
        mock_state.update_data.assert_awaited_once()
        mock_state.set_state.assert_awaited_once_with(KeywordGenerationFSM.quantity)

    async def test_too_short(self, mock_message: MagicMock, mock_state: AsyncMock) -> None:
        mock_message.text = "M"
        await fsm_kw_geography(mock_message, mock_state)
        mock_state.set_state.assert_not_awaited()
        assert "минимум 2" in mock_message.answer.call_args.args[0].lower()

    async def test_too_long(self, mock_message: MagicMock, mock_state: AsyncMock) -> None:
        mock_message.text = "x" * 201
        await fsm_kw_geography(mock_message, mock_state)
        mock_state.set_state.assert_not_awaited()
        assert "максимум 200" in mock_message.answer.call_args.args[0].lower()

    async def test_shows_quantity_keyboard(self, mock_message: MagicMock, mock_state: AsyncMock) -> None:
        mock_message.text = "Saint Petersburg"
        mock_state.get_data.return_value = {"category_id": 10}
        await fsm_kw_geography(mock_message, mock_state)
        # Should show quantity selection keyboard
        mock_message.answer.assert_awaited()
        call_kwargs = mock_message.answer.call_args.kwargs
        assert "reply_markup" in call_kwargs


# ---------------------------------------------------------------------------
# cb_kw_quantity
# ---------------------------------------------------------------------------


class TestCbKwQuantity:
    async def test_valid_quantity_with_balance(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "kw:qty:10:100"
        with (
            patch("routers.categories.keywords.TokenService") as svc_cls,
            patch("routers.categories.keywords.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(admin_id=999)
            svc_cls.return_value.check_balance = AsyncMock(return_value=True)
            await cb_kw_quantity(mock_callback, mock_state, user, mock_db)
            mock_state.set_state.assert_awaited_once_with(KeywordGenerationFSM.confirm)
            # Verify cost and quantity stored
            call_kwargs = mock_state.update_data.call_args.kwargs
            assert call_kwargs["quantity"] == 100
            assert call_kwargs["cost"] == 100

    async def test_insufficient_balance(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "kw:qty:10:200"
        with (
            patch("routers.categories.keywords.TokenService") as svc_cls,
            patch("routers.categories.keywords.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(admin_id=999)
            svc_cls.return_value.check_balance = AsyncMock(return_value=False)
            svc_cls.return_value.get_balance = AsyncMock(return_value=50)
            svc_cls.return_value.format_insufficient_msg = MagicMock(return_value="Недостаточно токенов.")
            await cb_kw_quantity(mock_callback, mock_state, user, mock_db)
            mock_state.set_state.assert_not_awaited()
            text = mock_callback.message.edit_text.call_args.args[0]
            assert "Недостаточно" in text

    async def test_invalid_quantity_value(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "kw:qty:10:99"
        await cb_kw_quantity(mock_callback, mock_state, user, mock_db)
        mock_callback.answer.assert_awaited()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# cb_kw_confirm
# ---------------------------------------------------------------------------


class TestCbKwConfirm:
    async def test_charges_and_runs_pipeline(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_rate_limiter: MagicMock,
    ) -> None:
        mock_callback.data = "kw:confirm"
        mock_state.get_data.return_value = {
            "category_id": 10,
            "cost": 100,
            "quantity": 100,
            "products": "shoes and boots",
            "geography": "Moscow",
        }
        with (
            patch("routers.categories.keywords.TokenService") as svc_cls,
            patch("routers.categories.keywords.get_settings") as mock_settings,
            patch("routers.categories.keywords.CategoriesRepository") as mock_cat_cls,
            patch("services.keywords.KeywordService") as mock_kw_cls,
        ):
            mock_settings.return_value = MagicMock(admin_id=999)
            svc_cls.return_value.charge = AsyncMock(return_value=1400)
            mock_cat_cls.return_value.get_by_id = AsyncMock(
                return_value=MagicMock(project_id=1),
            )
            kw_svc = mock_kw_cls.return_value
            kw_svc.fetch_raw_phrases = AsyncMock(return_value=[{"phrase": "test"}])
            kw_svc.cluster_phrases = AsyncMock(
                return_value=[
                    {"cluster_name": "Test", "phrases": [{"phrase": "test"}], "total_volume": 100},
                ]
            )
            kw_svc.enrich_clusters = AsyncMock(
                return_value=[
                    {"cluster_name": "Test", "phrases": [{"phrase": "test"}], "total_volume": 100},
                ]
            )
            mock_ai = MagicMock()
            mock_dataforseo = MagicMock()
            await cb_kw_confirm(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_rate_limiter,
                mock_ai,
                mock_dataforseo,
            )
            svc_cls.return_value.charge.assert_awaited_once()
            # Pipeline should reach results state
            state_calls = [c.args[0] for c in mock_state.set_state.call_args_list]
            assert KeywordGenerationFSM.fetching in state_calls
            assert KeywordGenerationFSM.clustering in state_calls
            assert KeywordGenerationFSM.enriching in state_calls
            assert KeywordGenerationFSM.results in state_calls

    async def test_charge_failure_shows_insufficient(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_rate_limiter: MagicMock,
    ) -> None:
        mock_callback.data = "kw:confirm"
        mock_state.get_data.return_value = {
            "category_id": 10,
            "cost": 100,
            "quantity": 100,
            "products": "test",
            "geography": "test",
        }
        from bot.exceptions import InsufficientBalanceError

        with (
            patch("routers.categories.keywords.TokenService") as svc_cls,
            patch("routers.categories.keywords.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(admin_id=999)
            svc_cls.return_value.charge = AsyncMock(side_effect=InsufficientBalanceError())
            svc_cls.return_value.get_balance = AsyncMock(return_value=10)
            svc_cls.return_value.format_insufficient_msg = MagicMock(return_value="Недостаточно токенов.")
            await cb_kw_confirm(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_rate_limiter,
                MagicMock(),
                MagicMock(),
            )
            text = mock_callback.message.edit_text.call_args.args[0]
            assert "Недостаточно" in text

    async def test_stores_clusters_in_state(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_rate_limiter: MagicMock,
    ) -> None:
        mock_callback.data = "kw:confirm"
        mock_state.get_data.return_value = {
            "category_id": 10,
            "cost": 50,
            "quantity": 50,
            "products": "test products",
            "geography": "Russia",
        }
        with (
            patch("routers.categories.keywords.TokenService") as svc_cls,
            patch("routers.categories.keywords.get_settings") as mock_settings,
            patch("routers.categories.keywords.CategoriesRepository") as mock_cat_cls,
            patch("services.keywords.KeywordService") as mock_kw_cls,
        ):
            mock_settings.return_value = MagicMock(admin_id=999)
            svc_cls.return_value.charge = AsyncMock(return_value=1450)
            mock_cat_cls.return_value.get_by_id = AsyncMock(
                return_value=MagicMock(project_id=1),
            )
            kw_svc = mock_kw_cls.return_value
            kw_svc.fetch_raw_phrases = AsyncMock(return_value=[{"phrase": "test"}])
            kw_svc.cluster_phrases = AsyncMock(
                return_value=[
                    {"cluster_name": "Test", "phrases": [{"phrase": "test"}], "total_volume": 100},
                ]
            )
            kw_svc.enrich_clusters = AsyncMock(
                return_value=[
                    {"cluster_name": "Test", "phrases": [{"phrase": "test"}], "total_volume": 100},
                ]
            )
            mock_ai = MagicMock()
            mock_dataforseo = MagicMock()
            await cb_kw_confirm(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_rate_limiter,
                mock_ai,
                mock_dataforseo,
            )
            # Check clusters were stored in state
            update_calls = mock_state.update_data.call_args_list
            clusters_stored = any("clusters" in (c.kwargs or {}) for c in update_calls)
            assert clusters_stored


# ---------------------------------------------------------------------------
# cb_kw_save
# ---------------------------------------------------------------------------


class TestCbKwSave:
    async def test_saves_to_db_and_clears_fsm(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        category: Category,
    ) -> None:
        mock_callback.data = "kw:save"
        clusters = [{"cluster_name": "Test", "phrases": [{"phrase": "test"}], "total_volume": 100}]
        mock_state.get_data.return_value = {"clusters": clusters, "category_id": category.id}

        with (
            patch("routers.categories.keywords.CategoriesRepository") as cat_cls,
            patch("keyboards.inline.category_card_kb"),
        ):
            cat_cls.return_value.update_keywords = AsyncMock(return_value=category)
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            await cb_kw_save(mock_callback, mock_state, user, mock_db)
            mock_state.clear.assert_awaited_once()
            cat_cls.return_value.update_keywords.assert_awaited_once_with(category.id, clusters)

    async def test_shows_saved_message(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        category: Category,
    ) -> None:
        mock_callback.data = "kw:save"
        mock_state.get_data.return_value = {"clusters": [], "category_id": category.id}

        with (
            patch("routers.categories.keywords.CategoriesRepository") as cat_cls,
            patch("keyboards.inline.category_card_kb"),
        ):
            cat_cls.return_value.update_keywords = AsyncMock(return_value=category)
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            await cb_kw_save(mock_callback, mock_state, user, mock_db)
            text = mock_callback.message.edit_text.call_args.args[0]
            assert "сохранены" in text.lower()

    async def test_restores_main_menu(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        category: Category,
    ) -> None:
        mock_callback.data = "kw:save"
        mock_state.get_data.return_value = {"clusters": [], "category_id": category.id}

        with (
            patch("routers.categories.keywords.CategoriesRepository") as cat_cls,
            patch("keyboards.inline.category_card_kb"),
        ):
            cat_cls.return_value.update_keywords = AsyncMock(return_value=category)
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            await cb_kw_save(mock_callback, mock_state, user, mock_db)
            # Should have answer calls: edit_text + category card + main menu
            answer_calls = mock_callback.message.answer.call_args_list
            last_call = answer_calls[-1]
            assert last_call.args[0] == "\u200b"


# ---------------------------------------------------------------------------
# cb_kw_upload_start
# ---------------------------------------------------------------------------


class TestCbKwUploadStart:
    async def test_sets_upload_fsm(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
        category: Category,
    ) -> None:
        mock_callback.data = f"category:{category.id}:kw:upload"
        mock_state.get_state = AsyncMock(return_value=None)
        with (
            patch("routers.categories.keywords.CategoriesRepository") as cat_cls,
            patch("routers.categories.keywords.ProjectsRepository") as proj_cls,
        ):
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_kw_upload_start(mock_callback, mock_state, user, mock_db)
            mock_state.set_state.assert_awaited_once_with(KeywordUploadFSM.file_upload)
            mock_state.update_data.assert_awaited_once_with(category_id=category.id)

    async def test_shows_upload_instructions(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
        category: Category,
    ) -> None:
        mock_callback.data = f"category:{category.id}:kw:upload"
        mock_state.get_state = AsyncMock(return_value=None)
        with (
            patch("routers.categories.keywords.CategoriesRepository") as cat_cls,
            patch("routers.categories.keywords.ProjectsRepository") as proj_cls,
        ):
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_kw_upload_start(mock_callback, mock_state, user, mock_db)
            text = mock_callback.message.answer.call_args.args[0]
            assert "TXT" in text
            assert "500" in text

    async def test_clears_previous_fsm(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
        category: Category,
    ) -> None:
        mock_callback.data = f"category:{category.id}:kw:upload"
        mock_state.get_state = AsyncMock(return_value="KeywordGenerationFSM:products")
        with (
            patch("routers.categories.keywords.CategoriesRepository") as cat_cls,
            patch("routers.categories.keywords.ProjectsRepository") as proj_cls,
        ):
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_kw_upload_start(mock_callback, mock_state, user, mock_db)
            mock_state.clear.assert_awaited()

    async def test_unauthorized_denied(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:999:kw:upload"
        with patch("routers.categories.keywords.CategoriesRepository") as cat_cls:
            cat_cls.return_value.get_by_id = AsyncMock(return_value=None)
            await cb_kw_upload_start(mock_callback, mock_state, user, mock_db)
            mock_state.set_state.assert_not_awaited()


# ---------------------------------------------------------------------------
# fsm_kw_upload_file
# ---------------------------------------------------------------------------


def _make_document(file_name: str = "keywords.txt", file_size: int = 100) -> MagicMock:
    """Create a mock document object."""
    doc = MagicMock()
    doc.file_name = file_name
    doc.file_size = file_size
    doc.file_id = "test_file_id"
    return doc


class TestFsmKwUploadFile:
    async def test_valid_file(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        content = "seo tools\nmarketing automation\ncontent strategy\n"
        doc = _make_document(file_size=len(content.encode()))
        mock_message.document = doc
        mock_message.bot = MagicMock()
        mock_message.bot.download = AsyncMock(side_effect=lambda d, destination: destination.write(content.encode()))
        mock_state.get_data.return_value = {"category_id": 10}

        await fsm_kw_upload_file(mock_message, mock_state, user, mock_db)
        # Should reach results state
        state_calls = [c.args[0] for c in mock_state.set_state.call_args_list]
        assert KeywordUploadFSM.results in state_calls

    async def test_wrong_extension(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        doc = _make_document(file_name="keywords.csv")
        mock_message.document = doc
        await fsm_kw_upload_file(mock_message, mock_state, user, mock_db)
        mock_message.answer.assert_awaited()
        text = mock_message.answer.call_args.args[0]
        assert "TXT" in text
        mock_state.set_state.assert_not_awaited()

    async def test_file_too_large(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        doc = _make_document(file_size=2 * 1024 * 1024)  # 2 MB
        mock_message.document = doc
        await fsm_kw_upload_file(mock_message, mock_state, user, mock_db)
        mock_message.answer.assert_awaited()
        text = mock_message.answer.call_args.args[0]
        assert "1 МБ" in text
        mock_state.set_state.assert_not_awaited()

    async def test_too_many_phrases(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        phrases = [f"phrase {i}" for i in range(501)]
        content = "\n".join(phrases)
        doc = _make_document(file_size=len(content.encode()))
        mock_message.document = doc
        mock_message.bot = MagicMock()
        mock_message.bot.download = AsyncMock(side_effect=lambda d, destination: destination.write(content.encode()))
        mock_state.get_data.return_value = {"category_id": 10}

        await fsm_kw_upload_file(mock_message, mock_state, user, mock_db)
        mock_message.answer.assert_awaited()
        text = mock_message.answer.call_args.args[0]
        assert "501" in text or "500" in text

    async def test_empty_file(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        content = "\n\n  \n  "
        doc = _make_document(file_size=len(content.encode()))
        mock_message.document = doc
        mock_message.bot = MagicMock()
        mock_message.bot.download = AsyncMock(side_effect=lambda d, destination: destination.write(content.encode()))
        mock_state.get_data.return_value = {"category_id": 10}

        await fsm_kw_upload_file(mock_message, mock_state, user, mock_db)
        text = mock_message.answer.call_args.args[0]
        assert "не содержит" in text.lower()

    async def test_phrase_too_short(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        content = "a\nvalid phrase\n"
        doc = _make_document(file_size=len(content.encode()))
        mock_message.document = doc
        mock_message.bot = MagicMock()
        mock_message.bot.download = AsyncMock(side_effect=lambda d, destination: destination.write(content.encode()))
        mock_state.get_data.return_value = {"category_id": 10}

        await fsm_kw_upload_file(mock_message, mock_state, user, mock_db)
        mock_message.answer.assert_awaited()
        # Should report validation error for short phrase

    async def test_phrase_too_long(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        content = "x" * 201 + "\nvalid phrase\n"
        doc = _make_document(file_size=len(content.encode()))
        mock_message.document = doc
        mock_message.bot = MagicMock()
        mock_message.bot.download = AsyncMock(side_effect=lambda d, destination: destination.write(content.encode()))
        mock_state.get_data.return_value = {"category_id": 10}

        await fsm_kw_upload_file(mock_message, mock_state, user, mock_db)
        mock_message.answer.assert_awaited()

    async def test_no_bot_reference(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        doc = _make_document()
        mock_message.document = doc
        mock_message.bot = None
        await fsm_kw_upload_file(mock_message, mock_state, user, mock_db)
        mock_message.answer.assert_awaited()
        assert "загрузки" in mock_message.answer.call_args.args[0].lower()

    async def test_no_document(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_message.document = None
        await fsm_kw_upload_file(mock_message, mock_state, user, mock_db)
        mock_message.answer.assert_awaited()


# ---------------------------------------------------------------------------
# cb_kw_upload_save
# ---------------------------------------------------------------------------


class TestCbKwUploadSave:
    async def test_saves_uploaded_keywords(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        category: Category,
    ) -> None:
        mock_callback.data = "kw:save"
        clusters = [
            {
                "cluster_name": "Uploaded",
                "cluster_type": "article",
                "main_phrase": "test phrase",
                "phrases": [{"phrase": "test phrase"}],
            }
        ]
        mock_state.get_data.return_value = {"clusters": clusters, "category_id": category.id}

        with (
            patch("routers.categories.keywords.CategoriesRepository") as cat_cls,
            patch("keyboards.inline.category_card_kb"),
        ):
            cat_cls.return_value.update_keywords = AsyncMock(return_value=category)
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            await cb_kw_upload_save(mock_callback, mock_state, user, mock_db)
            mock_state.clear.assert_awaited_once()
            cat_cls.return_value.update_keywords.assert_awaited_once_with(category.id, clusters)

    async def test_clears_fsm_on_save(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        category: Category,
    ) -> None:
        mock_callback.data = "kw:save"
        mock_state.get_data.return_value = {"clusters": [], "category_id": category.id}

        with (
            patch("routers.categories.keywords.CategoriesRepository") as cat_cls,
            patch("keyboards.inline.category_card_kb"),
        ):
            cat_cls.return_value.update_keywords = AsyncMock(return_value=category)
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            await cb_kw_upload_save(mock_callback, mock_state, user, mock_db)
            mock_state.clear.assert_awaited_once()
