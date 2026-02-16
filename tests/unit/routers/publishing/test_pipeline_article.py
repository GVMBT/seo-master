"""Tests for routers/publishing/pipeline/article.py -- ArticlePipeline handlers.

Covers:
- Entry (start): 0/1/N projects, checkpoint E49
- Step 1: project selection + ownership check
- Step 2: WP selection (0/1/N WP, preview_only)
- Step 3: category selection (0/1/N categories)
- Step 5: confirm cost (GOD_MODE, normal)
- Step 6: generate (E01 balance, E25 rate limit, refund on error)
- Step 7: preview (publish, regen free/paid, cancel_refund)
- Step 8: publish (WP, preview_only Telegraph)
- Guards E07: generating/publishing/regenerating states
- Pagination: project/category page navigation
- Cancel/Resume/Restart
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import Message

from db.models import ArticlePreview, Category, PlatformConnection, Project, User
from routers.publishing.pipeline.article import (
    ArticlePipelineFSM,
    _format_pipeline_preview,
    cb_pipeline_article_start,
    cb_pipeline_cancel,
    cb_pipeline_cancel_full,
    cb_pipeline_cancel_refund,
    cb_pipeline_cat_page,
    cb_pipeline_generate,
    cb_pipeline_generating_guard,
    cb_pipeline_proj_page,
    cb_pipeline_publish,
    cb_pipeline_publishing_guard,
    cb_pipeline_regen,
    cb_pipeline_regen_guard,
    cb_pipeline_restart,
    cb_pipeline_resume,
    cb_pipeline_select_category,
    cb_pipeline_select_project,
    cb_pipeline_select_wp,
    show_wp_selection,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn(
    id: int = 1,
    platform_type: str = "wordpress",
    identifier: str = "blog.com",
    status: str = "active",
) -> PlatformConnection:
    return PlatformConnection(
        id=id,
        project_id=1,
        platform_type=platform_type,
        identifier=identifier,
        credentials={},
        status=status,
    )


def _make_preview(
    id: int = 1,
    user_id: int = 123456789,
    project_id: int = 1,
    category_id: int = 10,
    title: str = "Test Article",
    word_count: int = 2000,
    images_count: int = 4,
    tokens_charged: int = 320,
    status: str = "draft",
    telegraph_url: str | None = "https://telegra.ph/test",
    content_html: str | None = "<p>Content</p>",
) -> ArticlePreview:
    return ArticlePreview(
        id=id,
        user_id=user_id,
        project_id=project_id,
        category_id=category_id,
        title=title,
        word_count=word_count,
        images_count=images_count,
        tokens_charged=tokens_charged,
        status=status,
        telegraph_url=telegraph_url,
        content_html=content_html,
    )


# ---------------------------------------------------------------------------
# _format_pipeline_preview
# ---------------------------------------------------------------------------


class TestFormatPipelinePreview:
    def test_basic_format(self) -> None:
        preview = _make_preview()
        text = _format_pipeline_preview(preview, 320, "https://telegra.ph/test")
        assert "Test Article" in text
        assert "2000" in text
        assert "320" in text
        assert "telegra.ph" in text

    def test_no_title_fallback(self) -> None:
        preview = _make_preview(title=None)
        text = _format_pipeline_preview(preview, 320, None)
        assert "Без заголовка" in text

    def test_no_telegraph_shows_snippet(self) -> None:
        preview = _make_preview(telegraph_url=None)
        text = _format_pipeline_preview(preview, 320, None)
        assert "Content" in text

    def test_html_escaping(self) -> None:
        preview = _make_preview(title="<script>alert('xss')</script>")
        text = _format_pipeline_preview(preview, 320, None)
        assert "<script>" not in text
        assert "&lt;script&gt;" in text

    def test_always_shows_approximate_note(self) -> None:
        preview = _make_preview()
        text = _format_pipeline_preview(preview, 320, None)
        assert "приблизительное" in text.lower()


# ---------------------------------------------------------------------------
# Entry: pipeline:article:start
# ---------------------------------------------------------------------------


class TestPipelineArticleStart:
    async def test_e49_checkpoint_exists_shows_resume(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """E49: existing checkpoint -> show resume dialog."""
        mock_callback.data = "pipeline:article:start"
        checkpoint = {"current_step": "select_category", "project_id": 1}
        mock_redis.get = AsyncMock(return_value=json.dumps(checkpoint))
        await cb_pipeline_article_start(mock_callback, mock_state, user, mock_db, mock_redis)
        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "незавершённая" in text.lower()
        assert "select_category" in text

    async def test_no_projects_redirect(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """No projects -> redirect to create project."""
        mock_callback.data = "pipeline:article:start"
        mock_redis.get = AsyncMock(return_value=None)
        with patch("routers.publishing.pipeline.article.ProjectsRepository") as repo:
            repo.return_value.get_by_user = AsyncMock(return_value=[])
            await cb_pipeline_article_start(mock_callback, mock_state, user, mock_db, mock_redis)
        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "нет проектов" in text.lower()

    async def test_single_project_auto_selects(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
        project: Project,
    ) -> None:
        """1 project -> auto-select, move to WP step."""
        mock_callback.data = "pipeline:article:start"
        mock_redis.get = AsyncMock(return_value=None)
        with (
            patch("routers.publishing.pipeline.article.ProjectsRepository") as repo,
            patch("routers.publishing.pipeline.article.show_wp_selection", new_callable=AsyncMock) as mock_wp,
        ):
            repo.return_value.get_by_user = AsyncMock(return_value=[project])
            await cb_pipeline_article_start(mock_callback, mock_state, user, mock_db, mock_redis)
        mock_state.set_state.assert_awaited_with(ArticlePipelineFSM.select_wp)
        mock_state.update_data.assert_awaited_with(project_id=project.id)
        mock_wp.assert_awaited_once()

    async def test_multiple_projects_shows_list(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """N projects -> show project selection list."""
        mock_callback.data = "pipeline:article:start"
        mock_redis.get = AsyncMock(return_value=None)
        projects = [
            Project(id=1, user_id=user.id, name="P1", company_name="C1", specialization="S1"),
            Project(id=2, user_id=user.id, name="P2", company_name="C2", specialization="S2"),
        ]
        with (
            patch("routers.publishing.pipeline.article.ProjectsRepository") as proj_repo,
            patch("routers.publishing.pipeline.article.PublicationsRepository") as pub_repo,
        ):
            proj_repo.return_value.get_by_user = AsyncMock(return_value=projects)
            pub_repo.return_value.get_by_user = AsyncMock(return_value=[])
            await cb_pipeline_article_start(mock_callback, mock_state, user, mock_db, mock_redis)
        mock_state.set_state.assert_awaited_with(ArticlePipelineFSM.select_project)
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "проект" in text.lower()

    async def test_e49_corrupted_checkpoint_treated_as_empty(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """E49: corrupted JSON in checkpoint -> treat as no checkpoint."""
        mock_callback.data = "pipeline:article:start"
        mock_redis.get = AsyncMock(return_value="NOT_VALID_JSON{{{")
        with patch("routers.publishing.pipeline.article.ProjectsRepository") as repo:
            repo.return_value.get_by_user = AsyncMock(return_value=[])
            await cb_pipeline_article_start(mock_callback, mock_state, user, mock_db, mock_redis)
        # Should proceed to no-projects (not crash)
        mock_callback.message.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# Step 1: select project
# ---------------------------------------------------------------------------


class TestPipelineSelectProject:
    async def test_valid_project_moves_to_wp(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
    ) -> None:
        mock_callback.data = f"pipeline:article:project:{project.id}"
        with (
            patch("routers.publishing.pipeline.article.ProjectsRepository") as repo,
            patch("routers.publishing.pipeline.article.show_wp_selection", new_callable=AsyncMock) as mock_wp,
        ):
            repo.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_pipeline_select_project(mock_callback, mock_state, user, mock_db)
        mock_state.set_state.assert_awaited_with(ArticlePipelineFSM.select_wp)
        mock_state.update_data.assert_awaited_with(project_id=project.id)
        mock_wp.assert_awaited_once()

    async def test_ownership_check_rejects_other_user(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """Security: project owned by another user -> alert."""
        other_project = Project(id=99, user_id=999, name="Other", company_name="X", specialization="Y")
        mock_callback.data = "pipeline:article:project:99"
        with patch("routers.publishing.pipeline.article.ProjectsRepository") as repo:
            repo.return_value.get_by_id = AsyncMock(return_value=other_project)
            await cb_pipeline_select_project(mock_callback, mock_state, user, mock_db)
        mock_callback.answer.assert_awaited_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True

    async def test_project_not_found_shows_alert(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "pipeline:article:project:999"
        with patch("routers.publishing.pipeline.article.ProjectsRepository") as repo:
            repo.return_value.get_by_id = AsyncMock(return_value=None)
            await cb_pipeline_select_project(mock_callback, mock_state, user, mock_db)
        mock_callback.answer.assert_awaited_once()
        assert "не найден" in mock_callback.answer.call_args.args[0].lower()


# ---------------------------------------------------------------------------
# Step 2: WP selection (show_wp_selection + handler)
# ---------------------------------------------------------------------------


class TestShowWpSelection:
    async def test_zero_wp_shows_no_entities(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """0 WP connections -> no-entities keyboard."""
        msg = mock_callback.message
        with (
            patch("routers.publishing.pipeline.article.ConnectionsRepository") as conn_repo,
            patch("routers.publishing.pipeline.article.get_settings"),
            patch("routers.publishing.pipeline.article.CredentialManager"),
        ):
            conn_repo.return_value.get_by_project = AsyncMock(return_value=[])
            await show_wp_selection(msg, user, mock_db, 1, mock_state)
        msg.edit_text.assert_awaited_once()
        text = msg.edit_text.call_args.args[0]
        assert "WordPress" in text

    async def test_single_wp_auto_selects(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """1 WP connection -> auto-select, move to category."""
        msg = mock_callback.message
        wp_conn = _make_conn(id=5)
        mock_state.get_data = AsyncMock(return_value={"project_id": 1})
        with (
            patch("routers.publishing.pipeline.article.ConnectionsRepository") as conn_repo,
            patch("routers.publishing.pipeline.article.get_settings"),
            patch("routers.publishing.pipeline.article.CredentialManager"),
            patch("routers.publishing.pipeline.article._show_category_selection", new_callable=AsyncMock) as mock_cat,
        ):
            conn_repo.return_value.get_by_project = AsyncMock(return_value=[wp_conn])
            await show_wp_selection(msg, user, mock_db, 1, mock_state)
        mock_state.update_data.assert_any_await(connection_id=5, preview_only=False)
        mock_state.set_state.assert_awaited_with(ArticlePipelineFSM.select_category)
        mock_cat.assert_awaited_once()

    async def test_multiple_wp_shows_list(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """N WP connections -> show WP list keyboard."""
        msg = mock_callback.message
        conns = [_make_conn(id=1, identifier="a.com"), _make_conn(id=2, identifier="b.com")]
        with (
            patch("routers.publishing.pipeline.article.ConnectionsRepository") as conn_repo,
            patch("routers.publishing.pipeline.article.get_settings"),
            patch("routers.publishing.pipeline.article.CredentialManager"),
        ):
            conn_repo.return_value.get_by_project = AsyncMock(return_value=conns)
            await show_wp_selection(msg, user, mock_db, 1, mock_state)
        msg.edit_text.assert_awaited_once()
        text = msg.edit_text.call_args.args[0]
        assert "какой сайт" in text.lower()

    async def test_inactive_wp_filtered_out(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """Only active WP connections considered; inactive connections filtered out."""
        msg = mock_callback.message
        conns = [
            _make_conn(id=1, status="inactive"),
            _make_conn(id=2, platform_type="telegram"),  # not WP
        ]
        with (
            patch("routers.publishing.pipeline.article.ConnectionsRepository") as conn_repo,
            patch("routers.publishing.pipeline.article.get_settings"),
            patch("routers.publishing.pipeline.article.CredentialManager"),
        ):
            conn_repo.return_value.get_by_project = AsyncMock(return_value=conns)
            await show_wp_selection(msg, user, mock_db, 1, mock_state)
        msg.edit_text.assert_awaited_once()
        text = msg.edit_text.call_args.args[0]
        assert "WordPress" in text  # no entities


class TestPipelineSelectWp:
    async def test_select_wp_connection(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "pipeline:article:wp:5"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1})
        with patch("routers.publishing.pipeline.article._show_category_selection", new_callable=AsyncMock):
            await cb_pipeline_select_wp(mock_callback, mock_state, user, mock_db)
        mock_state.update_data.assert_any_await(connection_id=5, preview_only=False)

    async def test_preview_only_selection(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "pipeline:article:wp:preview_only"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1})
        with patch("routers.publishing.pipeline.article._show_category_selection", new_callable=AsyncMock):
            await cb_pipeline_select_wp(mock_callback, mock_state, user, mock_db)
        mock_state.update_data.assert_any_await(connection_id=None, preview_only=True)


# ---------------------------------------------------------------------------
# Step 3: category selection
# ---------------------------------------------------------------------------


class TestPipelineSelectCategory:
    async def test_valid_category_moves_to_readiness(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        category: Category,
    ) -> None:
        mock_callback.data = f"pipeline:article:cat:{category.id}"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1, "category_id": category.id})
        with (
            patch("routers.publishing.pipeline.article.CategoriesRepository") as cat_repo,
            patch("routers.publishing.pipeline.article._show_readiness", new_callable=AsyncMock) as mock_readiness,
        ):
            cat_repo.return_value.get_by_id = AsyncMock(return_value=category)
            await cb_pipeline_select_category(mock_callback, mock_state, user, mock_db)
        mock_state.set_state.assert_awaited_with(ArticlePipelineFSM.readiness_check)
        mock_readiness.assert_awaited_once()

    async def test_category_not_found(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "pipeline:article:cat:999"
        with patch("routers.publishing.pipeline.article.CategoriesRepository") as cat_repo:
            cat_repo.return_value.get_by_id = AsyncMock(return_value=None)
            await cb_pipeline_select_category(mock_callback, mock_state, user, mock_db)
        mock_callback.answer.assert_awaited_once()
        assert "не найдена" in mock_callback.answer.call_args.args[0].lower()


# ---------------------------------------------------------------------------
# Step 5: confirm cost (_show_confirm is tested indirectly via handlers)
# ---------------------------------------------------------------------------


class TestShowConfirm:
    async def test_god_mode_text(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        mock_db: MagicMock,
    ) -> None:
        """GOD_MODE user sees free label."""
        admin_user = User(id=203473623, balance=99999, role="admin")
        project = Project(id=1, user_id=admin_user.id, name="Admin Proj", company_name="Co", specialization="S")
        category = Category(id=10, project_id=1, name="Cat")
        mock_state.get_data = AsyncMock(
            return_value={
                "project_id": 1,
                "category_id": 10,
                "preview_only": False,
            }
        )
        msg = mock_callback.message
        with (
            patch("routers.publishing.pipeline.article.get_settings") as gs,
            patch("routers.publishing.pipeline.article.ProjectsRepository") as proj_repo,
            patch("routers.publishing.pipeline.article.CategoriesRepository") as cat_repo,
        ):
            gs.return_value.admin_ids = [203473623]
            proj_repo.return_value.get_by_id = AsyncMock(return_value=project)
            cat_repo.return_value.get_by_id = AsyncMock(return_value=category)

            from routers.publishing.pipeline.article import _show_confirm

            await _show_confirm(msg, admin_user, mock_db, mock_state)

        text = msg.edit_text.call_args.args[0]
        assert "GOD_MODE" in text
        assert "бесплатно" in text.lower()

    async def test_normal_user_sees_cost_and_balance(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
        category: Category,
    ) -> None:
        """Normal user sees cost and balance."""
        mock_state.get_data = AsyncMock(
            return_value={
                "project_id": project.id,
                "category_id": category.id,
                "preview_only": False,
            }
        )
        msg = mock_callback.message
        with (
            patch("routers.publishing.pipeline.article.get_settings") as gs,
            patch("routers.publishing.pipeline.article.ProjectsRepository") as proj_repo,
            patch("routers.publishing.pipeline.article.CategoriesRepository") as cat_repo,
        ):
            gs.return_value.admin_ids = []
            proj_repo.return_value.get_by_id = AsyncMock(return_value=project)
            cat_repo.return_value.get_by_id = AsyncMock(return_value=category)

            from routers.publishing.pipeline.article import _show_confirm

            await _show_confirm(msg, user, mock_db, mock_state)

        text = msg.edit_text.call_args.args[0]
        assert str(user.balance) in text
        assert "GOD_MODE" not in text

    async def test_preview_only_shows_telegraph(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
        category: Category,
    ) -> None:
        mock_state.get_data = AsyncMock(
            return_value={
                "project_id": project.id,
                "category_id": category.id,
                "preview_only": True,
            }
        )
        msg = mock_callback.message
        with (
            patch("routers.publishing.pipeline.article.get_settings") as gs,
            patch("routers.publishing.pipeline.article.ProjectsRepository") as proj_repo,
            patch("routers.publishing.pipeline.article.CategoriesRepository") as cat_repo,
        ):
            gs.return_value.admin_ids = []
            proj_repo.return_value.get_by_id = AsyncMock(return_value=project)
            cat_repo.return_value.get_by_id = AsyncMock(return_value=category)

            from routers.publishing.pipeline.article import _show_confirm

            await _show_confirm(msg, user, mock_db, mock_state)

        text = msg.edit_text.call_args.args[0]
        assert "Telegraph" in text


# ---------------------------------------------------------------------------
# Step 6: generate (cb_pipeline_generate)
# ---------------------------------------------------------------------------


class TestPipelineGenerate:
    async def test_e01_insufficient_balance_blocks(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
        mock_rate_limiter: MagicMock,
    ) -> None:
        """E01: insufficient balance -> show top-up keyboard."""
        user.balance = 0
        mock_callback.data = "pipeline:article:generate"
        mock_state.get_data = AsyncMock(
            return_value={
                "estimated_cost": 320,
                "project_id": 1,
                "category_id": 10,
            }
        )
        with (
            patch("routers.publishing.pipeline.article.get_settings") as gs,
            patch("routers.publishing.pipeline.article.TokenService") as ts_cls,
        ):
            gs.return_value.admin_ids = []
            ts_cls.return_value.check_balance = AsyncMock(return_value=False)
            ts_cls.return_value.get_balance = AsyncMock(return_value=0)
            ts_cls.return_value.format_insufficient_msg = MagicMock(return_value="Недостаточно токенов.")
            await cb_pipeline_generate(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_redis,
                mock_rate_limiter,
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )
        mock_callback.message.edit_text.assert_awaited()
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "Недостаточно" in text

    async def test_session_data_lost_aborts(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
        mock_rate_limiter: MagicMock,
    ) -> None:
        """Missing project_id/category_id -> abort with alert."""
        mock_callback.data = "pipeline:article:generate"
        mock_state.get_data = AsyncMock(return_value={"estimated_cost": 320})
        with patch("routers.publishing.pipeline.article.get_settings") as gs:
            gs.return_value.admin_ids = []
            await cb_pipeline_generate(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_redis,
                mock_rate_limiter,
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )
        mock_callback.answer.assert_awaited_once()
        assert "заново" in mock_callback.answer.call_args.args[0].lower()
        mock_state.clear.assert_awaited_once()


# ---------------------------------------------------------------------------
# Step 7: preview actions
# ---------------------------------------------------------------------------


class TestPipelinePublish:
    async def test_preview_only_shows_telegraph_link(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """preview_only=True -> show Telegraph link, clear state."""
        mock_callback.data = "pipeline:article:publish"
        mock_state.get_data = AsyncMock(
            return_value={
                "preview_only": True,
                "telegraph_url": "https://telegra.ph/test",
            }
        )
        await cb_pipeline_publish(
            mock_callback,
            mock_state,
            user,
            mock_db,
            mock_redis,
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "telegra.ph" in text
        mock_state.clear.assert_awaited_once()
        mock_redis.delete.assert_awaited_once()

    async def test_missing_preview_id_aborts(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        mock_callback.data = "pipeline:article:publish"
        mock_state.get_data = AsyncMock(return_value={"preview_only": False})
        await cb_pipeline_publish(
            mock_callback,
            mock_state,
            user,
            mock_db,
            mock_redis,
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "не найдено" in text.lower()
        mock_state.clear.assert_awaited()


class TestPipelineRegen:
    async def test_free_regen_increments_count(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Free regen (count < max_regenerations_free) does not charge."""
        mock_callback.data = "pipeline:article:regen"
        mock_state.get_data = AsyncMock(
            return_value={
                "regeneration_count": 0,
                "estimated_cost": 320,
                "preview_id": 1,
                "keyword": "seo tips",
                "project_id": 1,
                "category_id": 10,
                "preview_only": False,
            }
        )

        # Mock article result
        mock_article = MagicMock()
        mock_article.title = "New Article"
        mock_article.word_count = 2000
        mock_article.images_count = 4
        mock_article.content_html = "<p>New</p>"
        mock_article.stored_images = []

        updated_preview = _make_preview(title="New Article")

        with (
            patch("routers.publishing.pipeline.article.get_settings") as gs,
            patch("routers.publishing.pipeline.article.PreviewsRepository") as prev_repo,
            patch("services.preview.PreviewService") as ps_cls,
        ):
            gs.return_value.admin_ids = []
            gs.return_value.max_regenerations_free = 2
            ps_cls.return_value.generate_article_content = AsyncMock(return_value=mock_article)
            prev_repo.return_value.update = AsyncMock()
            prev_repo.return_value.get_by_id = AsyncMock(return_value=updated_preview)
            await cb_pipeline_regen(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_redis,
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )

        mock_state.update_data.assert_any_await(regeneration_count=1)

    async def test_paid_regen_charges_tokens(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Paid regen (count >= max_free) charges tokens."""
        mock_callback.data = "pipeline:article:regen"
        mock_state.get_data = AsyncMock(
            return_value={
                "regeneration_count": 2,  # Already used 2 free
                "estimated_cost": 320,
                "preview_id": 1,
                "keyword": "seo tips",
                "project_id": 1,
                "category_id": 10,
                "preview_only": False,
            }
        )

        mock_article = MagicMock()
        mock_article.title = "Regen Article"
        mock_article.word_count = 2000
        mock_article.images_count = 4
        mock_article.content_html = "<p>Regen</p>"
        mock_article.stored_images = []

        with (
            patch("routers.publishing.pipeline.article.get_settings") as gs,
            patch("routers.publishing.pipeline.article.TokenService") as ts_cls,
            patch("routers.publishing.pipeline.article.PreviewsRepository") as prev_repo,
            patch("services.preview.PreviewService") as ps_cls,
        ):
            gs.return_value.admin_ids = []
            gs.return_value.max_regenerations_free = 2
            ts_cls.return_value.charge = AsyncMock(return_value=1180)
            ps_cls.return_value.generate_article_content = AsyncMock(return_value=mock_article)
            prev_repo.return_value.update = AsyncMock()
            prev_repo.return_value.get_by_id = AsyncMock(return_value=_make_preview())
            await cb_pipeline_regen(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_redis,
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )

        ts_cls.return_value.charge.assert_awaited_once()

    async def test_paid_regen_insufficient_balance(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Paid regen with insufficient balance -> show alert."""
        from bot.exceptions import InsufficientBalanceError

        mock_callback.data = "pipeline:article:regen"
        mock_state.get_data = AsyncMock(
            return_value={
                "regeneration_count": 2,
                "estimated_cost": 320,
            }
        )
        with (
            patch("routers.publishing.pipeline.article.get_settings") as gs,
            patch("routers.publishing.pipeline.article.TokenService") as ts_cls,
        ):
            gs.return_value.admin_ids = []
            gs.return_value.max_regenerations_free = 2
            ts_cls.return_value.charge = AsyncMock(side_effect=InsufficientBalanceError(320, 100))
            ts_cls.return_value.get_balance = AsyncMock(return_value=100)
            await cb_pipeline_regen(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_redis,
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )
        mock_callback.answer.assert_awaited_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True


class TestPipelineCancelRefund:
    async def test_refunds_tokens_and_clears(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        mock_callback.data = "pipeline:article:cancel_refund"
        mock_state.get_data = AsyncMock(return_value={"tokens_charged": 320})
        with (
            patch("routers.publishing.pipeline.article.get_settings") as gs,
            patch("routers.publishing.pipeline.article.TokenService") as ts_cls,
        ):
            gs.return_value.admin_ids = []
            ts_cls.return_value.refund = AsyncMock(return_value=1820)
            await cb_pipeline_cancel_refund(mock_callback, mock_state, user, mock_db, mock_redis)
        ts_cls.return_value.refund.assert_awaited_once_with(
            user.id,
            320,
            reason="refund",
            description="Pipeline cancelled by user",
        )
        mock_state.clear.assert_awaited_once()
        mock_redis.delete.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "320" in text

    async def test_god_mode_no_refund(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """GOD_MODE user with 0 tokens_charged -> no refund call."""
        admin = User(id=203473623, balance=99999, role="admin")
        mock_callback.data = "pipeline:article:cancel_refund"
        mock_state.get_data = AsyncMock(return_value={"tokens_charged": 0})
        with (
            patch("routers.publishing.pipeline.article.get_settings") as gs,
            patch("routers.publishing.pipeline.article.TokenService") as ts_cls,
        ):
            gs.return_value.admin_ids = [203473623]
            ts_cls.return_value.refund = AsyncMock()
            await cb_pipeline_cancel_refund(mock_callback, mock_state, admin, mock_db, mock_redis)
        # refund not called because tokens_charged=0
        ts_cls.return_value.refund.assert_not_awaited()
        mock_state.clear.assert_awaited_once()


# ---------------------------------------------------------------------------
# Guards E07
# ---------------------------------------------------------------------------


class TestPipelineGuards:
    async def test_generating_guard_blocks(self, mock_callback: MagicMock) -> None:
        """E07: All callbacks during generating state are blocked."""
        await cb_pipeline_generating_guard(mock_callback)
        mock_callback.answer.assert_awaited_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True
        assert "генерация" in mock_callback.answer.call_args.args[0].lower()

    async def test_publishing_guard_blocks(self, mock_callback: MagicMock) -> None:
        """E07: All callbacks during publishing state are blocked."""
        await cb_pipeline_publishing_guard(mock_callback)
        mock_callback.answer.assert_awaited_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True

    async def test_regenerating_guard_blocks(self, mock_callback: MagicMock) -> None:
        await cb_pipeline_regen_guard(mock_callback)
        mock_callback.answer.assert_awaited_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# Cancel / Resume / Restart
# ---------------------------------------------------------------------------


class TestPipelineCancel:
    async def test_cancel_clears_state_and_checkpoint(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_redis: MagicMock,
    ) -> None:
        mock_callback.data = "pipeline:article:cancel"
        await cb_pipeline_cancel(mock_callback, mock_state, user, mock_redis)
        mock_state.clear.assert_awaited_once()
        mock_redis.delete.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "отменено" in text.lower()


class TestPipelineCancelFull:
    async def test_cancel_full_clears_everything(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_redis: MagicMock,
    ) -> None:
        mock_callback.data = "pipeline:cancel"
        await cb_pipeline_cancel_full(mock_callback, mock_state, user, mock_redis)
        mock_state.clear.assert_awaited_once()
        mock_redis.delete.assert_awaited_once()


class TestPipelineResume:
    async def test_resume_restores_from_checkpoint(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """E49: resume loads checkpoint and shows confirm step."""
        checkpoint = {
            "pipeline_type": "article",
            "current_step": "generating",
            "project_id": 1,
            "category_id": 10,
            "connection_id": 5,
        }
        mock_callback.data = "pipeline:resume"
        mock_redis.get = AsyncMock(return_value=json.dumps(checkpoint))
        with (
            patch("routers.publishing.pipeline.article._show_confirm", new_callable=AsyncMock) as mock_confirm,
        ):
            await cb_pipeline_resume(mock_callback, mock_state, user, mock_db, mock_redis)
        mock_state.update_data.assert_awaited_once_with(**checkpoint)
        mock_state.set_state.assert_awaited_with(ArticlePipelineFSM.confirm_cost)
        mock_confirm.assert_awaited_once()

    async def test_resume_no_checkpoint_shows_error(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        mock_callback.data = "pipeline:resume"
        mock_redis.get = AsyncMock(return_value=None)
        await cb_pipeline_resume(mock_callback, mock_state, user, mock_db, mock_redis)
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "не найден" in text.lower()

    async def test_resume_corrupted_checkpoint(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Corrupted checkpoint JSON -> clean up and show error."""
        mock_callback.data = "pipeline:resume"
        mock_redis.get = AsyncMock(return_value="NOT_JSON{{{")
        await cb_pipeline_resume(mock_callback, mock_state, user, mock_db, mock_redis)
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "повреждена" in text.lower()
        mock_redis.delete.assert_awaited_once()


class TestPipelineRestart:
    async def test_restart_clears_and_re_triggers(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Restart clears checkpoint and re-runs start handler."""
        mock_callback.data = "pipeline:restart"
        # After clearing, re-trigger start which will see no checkpoint
        mock_redis.get = AsyncMock(return_value=None)
        with patch("routers.publishing.pipeline.article.ProjectsRepository") as repo:
            repo.return_value.get_by_user = AsyncMock(return_value=[])
            await cb_pipeline_restart(mock_callback, mock_state, user, mock_db, mock_redis)
        mock_state.clear.assert_awaited()
        mock_redis.delete.assert_awaited()


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestPipelinePagination:
    async def test_project_page_navigation(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "page:pipeline_proj:1"
        projects = [
            Project(id=i, user_id=user.id, name=f"P{i}", company_name="C", specialization="S") for i in range(1, 12)
        ]
        with (
            patch("routers.publishing.pipeline.article.ProjectsRepository") as proj_repo,
            patch("routers.publishing.pipeline.article.PublicationsRepository") as pub_repo,
        ):
            proj_repo.return_value.get_by_user = AsyncMock(return_value=projects)
            pub_repo.return_value.get_by_user = AsyncMock(return_value=[])
            await cb_pipeline_proj_page(mock_callback, mock_state, user, mock_db)
        mock_callback.message.edit_text.assert_awaited_once()

    async def test_category_page_navigation(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "page:pipeline_cat:1"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1})
        categories = [Category(id=i, project_id=1, name=f"Cat {i}") for i in range(1, 12)]
        with patch("routers.publishing.pipeline.article.CategoriesRepository") as cat_repo:
            cat_repo.return_value.get_by_project = AsyncMock(return_value=categories)
            await cb_pipeline_cat_page(mock_callback, mock_state, user, mock_db)
        mock_callback.message.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# CacheKeys.pipeline_state
# ---------------------------------------------------------------------------


class TestCacheKeysPipelineState:
    def test_format(self) -> None:
        from cache.keys import CacheKeys

        assert CacheKeys.pipeline_state(12345) == "pipeline:12345:state"

    def test_different_users_different_keys(self) -> None:
        from cache.keys import CacheKeys

        assert CacheKeys.pipeline_state(1) != CacheKeys.pipeline_state(2)

    def test_ttl_constant(self) -> None:
        from cache.keys import PIPELINE_CHECKPOINT_TTL

        assert PIPELINE_CHECKPOINT_TTL == 86400  # 24 hours


# ---------------------------------------------------------------------------
# Step 4: readiness check (_show_readiness + cb_readiness_proceed)
# ---------------------------------------------------------------------------


class TestPipelineReadiness:
    """Tests for readiness checklist display and proceed action."""

    async def test_show_readiness_all_filled(
        self,
        mock_callback: MagicMock,
        mock_db: MagicMock,
        category: Category,
    ) -> None:
        """All data filled -> checklist with green checkmarks and proceed button."""
        from services.readiness import ReadinessItem, ReadinessResult

        mock_result = ReadinessResult(
            items=[
                ReadinessItem(key="keywords", label="Ключевые фразы", hint="SEO", ready=True, cost=0),
                ReadinessItem(key="description", label="Описание компании", hint="контекст", ready=True, cost=0),
                ReadinessItem(key="prices", label="Цены", hint="реальные цены", ready=True, cost=0),
                ReadinessItem(key="media", label="Фото", hint="AI-изображения", ready=True, cost=0),
            ]
        )

        msg = mock_callback.message
        data = {"project_id": 1, "category_id": category.id}

        from routers.publishing.pipeline.article import _show_readiness

        with patch("routers.publishing.pipeline.article.ReadinessService") as svc_cls:
            svc_cls.return_value.check = AsyncMock(return_value=mock_result)
            await _show_readiness(msg, mock_db, data)

        msg.edit_text.assert_awaited_once()
        text = msg.edit_text.call_args.args[0]
        assert "\u2705" in text  # green checkmark
        assert "Все данные заполнены" in text

    async def test_show_readiness_missing_keywords(
        self,
        mock_callback: MagicMock,
        mock_db: MagicMock,
        category: Category,
    ) -> None:
        """Keywords missing -> checklist with hint for keywords."""
        from services.readiness import ReadinessItem, ReadinessResult

        mock_result = ReadinessResult(
            items=[
                ReadinessItem(key="keywords", label="Ключевые фразы", hint="SEO-оптимизация", ready=False, cost=100),
                ReadinessItem(key="description", label="Описание компании", hint="контекст", ready=True, cost=0),
                ReadinessItem(key="prices", label="Цены", hint="реальные цены", ready=True, cost=0),
                ReadinessItem(key="media", label="Фото", hint="AI-изображения", ready=True, cost=0),
            ]
        )

        msg = mock_callback.message
        data = {"project_id": 1, "category_id": category.id}

        from routers.publishing.pipeline.article import _show_readiness

        with patch("routers.publishing.pipeline.article.ReadinessService") as svc_cls:
            svc_cls.return_value.check = AsyncMock(return_value=mock_result)
            await _show_readiness(msg, mock_db, data)

        msg.edit_text.assert_awaited_once()
        text = msg.edit_text.call_args.args[0]
        assert "\u2b1c" in text  # white square (not ready)
        assert "Можно улучшить статью" in text
        assert "SEO-оптимизация" in text

    async def test_readiness_proceed_moves_to_confirm(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """Click 'Proceed' -> transition to confirm_cost state."""
        mock_callback.data = "pipeline:article:ready:proceed"
        from routers.publishing.pipeline.article import cb_readiness_proceed

        with patch("routers.publishing.pipeline.article._show_confirm", new_callable=AsyncMock) as mock_confirm:
            await cb_readiness_proceed(mock_callback, mock_state, user, mock_db)

        mock_state.set_state.assert_awaited_with(ArticlePipelineFSM.confirm_cost)
        mock_confirm.assert_awaited_once()
        mock_callback.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# Step 4a: keyword options
# ---------------------------------------------------------------------------


class TestPipelineKeywordOptions:
    """Tests for keyword option buttons (auto/custom/back)."""

    async def test_readiness_keywords_shows_options(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
    ) -> None:
        """Click 'keywords' -> show 3 buttons (auto/custom/back)."""
        mock_callback.data = "pipeline:article:ready:keywords"
        from routers.publishing.pipeline.article import cb_readiness_keywords

        await cb_readiness_keywords(mock_callback, mock_state)

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "Как получить ключевые фразы" in text
        mock_callback.answer.assert_awaited_once()

    async def test_kw_back_returns_to_readiness(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        mock_db: MagicMock,
    ) -> None:
        """Click 'back' -> return to readiness checklist."""
        mock_callback.data = "pipeline:article:kw:back"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1, "category_id": 10})
        from routers.publishing.pipeline.article import cb_kw_back

        with patch("routers.publishing.pipeline.article._show_readiness", new_callable=AsyncMock) as mock_readiness:
            await cb_kw_back(mock_callback, mock_state, mock_db)

        mock_readiness.assert_awaited_once()
        mock_callback.answer.assert_awaited_once()

    async def test_kw_custom_asks_products(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
    ) -> None:
        """Click 'custom' -> transition to readiness_keywords_products state."""
        mock_callback.data = "pipeline:article:kw:custom"
        from routers.publishing.pipeline.article import cb_kw_custom

        await cb_kw_custom(mock_callback, mock_state)

        mock_state.set_state.assert_awaited_with(ArticlePipelineFSM.readiness_keywords_products)
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "товары" in text.lower() or "услуги" in text.lower()
        mock_callback.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# Step 4a: auto keyword flow
# ---------------------------------------------------------------------------


class TestPipelineKeywordAuto:
    """Tests for auto keyword generation flow."""

    async def test_auto_with_city_generates_immediately(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
    ) -> None:
        """Project with company_city -> immediate transition to generating."""
        project.company_city = "Москва"
        mock_callback.data = "pipeline:article:kw:auto"
        mock_state.get_data = AsyncMock(return_value={"project_id": project.id, "category_id": 10})

        from routers.publishing.pipeline.article import cb_kw_auto

        with (
            patch("routers.publishing.pipeline.article.ProjectsRepository") as proj_repo,
            patch("routers.publishing.pipeline.article._generate_keywords_inline", new_callable=AsyncMock) as mock_gen,
        ):
            proj_repo.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_kw_auto(mock_callback, mock_state, user, mock_db)

        mock_state.set_state.assert_awaited_with(ArticlePipelineFSM.readiness_keywords_generating)
        mock_state.update_data.assert_any_await(kw_geo="Москва")
        mock_gen.assert_awaited_once()
        mock_callback.answer.assert_awaited()

    async def test_auto_without_city_asks_geo(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
    ) -> None:
        """Project without company_city -> show geo keyboard."""
        project.company_city = None
        mock_callback.data = "pipeline:article:kw:auto"
        mock_state.get_data = AsyncMock(return_value={"project_id": project.id, "category_id": 10})

        from routers.publishing.pipeline.article import cb_kw_auto

        with patch("routers.publishing.pipeline.article.ProjectsRepository") as proj_repo:
            proj_repo.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_kw_auto(mock_callback, mock_state, user, mock_db)

        mock_callback.message.edit_text.assert_awaited()
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "город" in text.lower()
        # Should NOT transition to generating
        mock_state.set_state.assert_not_awaited()
        mock_callback.answer.assert_awaited()


# ---------------------------------------------------------------------------
# Step 4a: geo selection
# ---------------------------------------------------------------------------


class TestPipelineKeywordGeo:
    """Tests for geo selection callbacks and text input."""

    async def test_geo_msk_saves_and_generates(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """Select 'Moscow' from readiness state -> save city, transition to generating."""
        mock_callback.data = "pipeline:article:kw:geo:msk"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1, "category_id": 10})

        from routers.publishing.pipeline.article import cb_kw_geo_from_readiness

        with (
            patch("routers.publishing.pipeline.article.ProjectsRepository") as proj_repo,
            patch("routers.publishing.pipeline.article._generate_keywords_inline", new_callable=AsyncMock) as mock_gen,
        ):
            proj_repo.return_value.update = AsyncMock()
            await cb_kw_geo_from_readiness(mock_callback, mock_state, user, mock_db)

        mock_state.update_data.assert_any_await(kw_geo="Москва")
        mock_state.set_state.assert_awaited_with(ArticlePipelineFSM.readiness_keywords_generating)
        proj_repo.return_value.update.assert_awaited_once()
        mock_gen.assert_awaited_once()

    async def test_geo_custom_asks_text_input(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """Select 'custom' -> transition to text input state."""
        mock_callback.data = "pipeline:article:kw:geo:custom"

        from routers.publishing.pipeline.article import cb_kw_geo_from_readiness

        await cb_kw_geo_from_readiness(mock_callback, mock_state, user, mock_db)

        mock_state.set_state.assert_awaited_with(ArticlePipelineFSM.readiness_keywords_geo)
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "город" in text.lower() or "регион" in text.lower()

    async def test_geo_text_input_auto_mode_generates(
        self,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """Text geo input in auto mode -> transition to generating."""
        mock_message = MagicMock(spec=Message)
        mock_message.text = "Казань"
        mock_message.answer = AsyncMock()
        mock_message.edit_text = AsyncMock()
        mock_message.bot = MagicMock()
        mock_state.get_data = AsyncMock(
            return_value={
                "project_id": 1,
                "category_id": 10,
                "kw_mode": "auto",
            }
        )

        from routers.publishing.pipeline.article import msg_kw_geo

        with patch("routers.publishing.pipeline.article._generate_keywords_inline", new_callable=AsyncMock) as mock_gen:
            await msg_kw_geo(mock_message, mock_state, user, mock_db)

        mock_state.update_data.assert_any_await(kw_geo="Казань")
        mock_state.set_state.assert_awaited_with(ArticlePipelineFSM.readiness_keywords_generating)
        mock_gen.assert_awaited_once()

    async def test_geo_text_input_custom_mode_asks_qty(
        self,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """Text geo input in custom mode -> ask quantity."""
        mock_message = MagicMock(spec=Message)
        mock_message.text = "Новосибирск"
        mock_message.answer = AsyncMock()
        mock_message.edit_text = AsyncMock()
        mock_state.get_data = AsyncMock(
            return_value={
                "project_id": 1,
                "category_id": 10,
                "kw_mode": "custom",
            }
        )

        from routers.publishing.pipeline.article import msg_kw_geo

        await msg_kw_geo(mock_message, mock_state, user, mock_db)

        mock_state.set_state.assert_awaited_with(ArticlePipelineFSM.readiness_keywords_qty)
        text = mock_message.answer.call_args.args[0]
        assert "фраз" in text.lower()


# ---------------------------------------------------------------------------
# Step 4a: quantity selection + generating guard
# ---------------------------------------------------------------------------


class TestPipelineKeywordQty:
    """Tests for keyword quantity selection and generating guard."""

    async def test_qty_50_starts_generation(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """Select 50 keywords -> transition to generating."""
        mock_callback.data = "pipeline:article:kw:qty:50"

        from routers.publishing.pipeline.article import cb_kw_qty

        with patch("routers.publishing.pipeline.article._generate_keywords_inline", new_callable=AsyncMock) as mock_gen:
            await cb_kw_qty(mock_callback, mock_state, user, mock_db)

        mock_state.update_data.assert_any_await(kw_quantity=50)
        mock_state.set_state.assert_awaited_with(ArticlePipelineFSM.readiness_keywords_generating)
        mock_gen.assert_awaited_once()
        mock_callback.answer.assert_awaited()

    async def test_generating_guard_blocks_callback(
        self,
        mock_callback: MagicMock,
    ) -> None:
        """E07: Callback during generating state -> alert 'in progress'."""
        from routers.publishing.pipeline.article import cb_kw_generating_guard

        await cb_kw_generating_guard(mock_callback)

        mock_callback.answer.assert_awaited_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True
        assert "процессе" in mock_callback.answer.call_args.args[0].lower()


# ---------------------------------------------------------------------------
# _generate_keywords_inline
# ---------------------------------------------------------------------------


class TestGenerateKeywordsInline:
    """Tests for inline keyword generation helper."""

    async def test_successful_generation_saves_and_returns_to_readiness(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """Successful generation -> save clusters to category, return to readiness."""
        from services.readiness import ReadinessItem, ReadinessResult

        mock_state.get_data = AsyncMock(
            return_value={
                "project_id": 1,
                "category_id": 10,
                "kw_products": "тестовые товары",
                "kw_geo": "Москва",
                "kw_quantity": 100,
            }
        )

        mock_clusters = [
            {"cluster_name": "SEO", "main_phrase": "seo оптимизация", "phrases": ["seo", "оптимизация сайтов"]},
            {"cluster_name": "Продвижение", "main_phrase": "продвижение сайта", "phrases": ["продвижение"]},
        ]

        mock_readiness_result = ReadinessResult(
            items=[
                ReadinessItem(key="keywords", label="Ключевые фразы", hint="SEO", ready=True, cost=0),
                ReadinessItem(key="description", label="Описание", hint="контекст", ready=False, cost=20),
            ]
        )

        msg = mock_callback.message
        msg.bot = MagicMock()
        msg.bot.workflow_data = {
            "ai_orchestrator": MagicMock(),
            "dataforseo_client": MagicMock(),
        }

        from routers.publishing.pipeline.article import _generate_keywords_inline

        with (
            patch("routers.publishing.pipeline.article.get_settings") as gs,
            patch("routers.publishing.pipeline.article.TokenService") as ts_cls,
            patch("routers.publishing.pipeline.article.CategoriesRepository") as cat_repo,
            patch("routers.publishing.pipeline.article.ReadinessService") as readiness_cls,
            patch("services.keywords.KeywordService") as kw_svc_cls,
        ):
            gs.return_value.admin_ids = []
            ts_cls.return_value.check_balance = AsyncMock(return_value=True)
            ts_cls.return_value.charge = AsyncMock(return_value=1400)
            cat_repo.return_value.update_keywords = AsyncMock()
            readiness_cls.return_value.check = AsyncMock(return_value=mock_readiness_result)

            kw_svc = kw_svc_cls.return_value
            kw_svc.fetch_raw_phrases = AsyncMock(return_value=["seo", "продвижение"])
            kw_svc.cluster_phrases = AsyncMock(return_value=mock_clusters)
            kw_svc.enrich_clusters = AsyncMock(return_value=mock_clusters)

            await _generate_keywords_inline(msg, mock_state, user, mock_db)

        # Clusters saved to category
        cat_repo.return_value.update_keywords.assert_awaited_once_with(10, mock_clusters)
        # State returned to readiness_check
        mock_state.set_state.assert_any_await(ArticlePipelineFSM.readiness_check)
        # Success text displayed
        text = msg.edit_text.call_args.args[0]
        assert "2 кластеров" in text
        assert "3 фраз" in text

    async def test_insufficient_balance_returns_to_readiness(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """Insufficient balance -> error message + return to readiness."""
        from services.readiness import ReadinessItem, ReadinessResult

        user.balance = 0
        mock_state.get_data = AsyncMock(
            return_value={
                "project_id": 1,
                "category_id": 10,
                "kw_products": "товары",
                "kw_geo": "Москва",
                "kw_quantity": 100,
            }
        )

        mock_readiness_result = ReadinessResult(
            items=[
                ReadinessItem(key="keywords", label="Ключевые фразы", hint="SEO", ready=False, cost=100),
            ]
        )

        msg = mock_callback.message

        from routers.publishing.pipeline.article import _generate_keywords_inline

        with (
            patch("routers.publishing.pipeline.article.get_settings") as gs,
            patch("routers.publishing.pipeline.article.TokenService") as ts_cls,
            patch("routers.publishing.pipeline.article.ReadinessService") as readiness_cls,
        ):
            gs.return_value.admin_ids = []
            ts_cls.return_value.check_balance = AsyncMock(return_value=False)
            ts_cls.return_value.get_balance = AsyncMock(return_value=0)
            readiness_cls.return_value.check = AsyncMock(return_value=mock_readiness_result)

            await _generate_keywords_inline(msg, mock_state, user, mock_db)

        # Error message shown
        calls = msg.edit_text.call_args_list
        balance_msg = calls[0].args[0]
        assert "Недостаточно" in balance_msg
        # State returned to readiness_check
        mock_state.set_state.assert_any_await(ArticlePipelineFSM.readiness_check)

    async def test_generation_error_refunds_and_returns(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """Generation error -> refund tokens + return to readiness."""
        from services.readiness import ReadinessItem, ReadinessResult

        mock_state.get_data = AsyncMock(
            return_value={
                "project_id": 1,
                "category_id": 10,
                "kw_products": "товары",
                "kw_geo": "Москва",
                "kw_quantity": 100,
            }
        )

        mock_readiness_result = ReadinessResult(
            items=[
                ReadinessItem(key="keywords", label="Ключевые фразы", hint="SEO", ready=False, cost=100),
            ]
        )

        msg = mock_callback.message
        msg.bot = MagicMock()
        msg.bot.workflow_data = {
            "ai_orchestrator": MagicMock(),
            "dataforseo_client": MagicMock(),
        }

        from routers.publishing.pipeline.article import _generate_keywords_inline

        with (
            patch("routers.publishing.pipeline.article.get_settings") as gs,
            patch("routers.publishing.pipeline.article.TokenService") as ts_cls,
            patch("routers.publishing.pipeline.article.ReadinessService") as readiness_cls,
            patch("services.keywords.KeywordService") as kw_svc_cls,
        ):
            gs.return_value.admin_ids = []
            ts_cls.return_value.check_balance = AsyncMock(return_value=True)
            ts_cls.return_value.charge = AsyncMock(return_value=1400)
            ts_cls.return_value.refund = AsyncMock(return_value=1500)
            readiness_cls.return_value.check = AsyncMock(return_value=mock_readiness_result)

            kw_svc = kw_svc_cls.return_value
            kw_svc.fetch_raw_phrases = AsyncMock(side_effect=RuntimeError("DataForSEO unavailable"))

            await _generate_keywords_inline(msg, mock_state, user, mock_db)

        # Refund called
        ts_cls.return_value.refund.assert_awaited_once()
        refund_args = ts_cls.return_value.refund.call_args
        assert refund_args.args[0] == user.id
        assert refund_args.args[1] == 100  # estimate_keywords_cost(100)
        # Error message shown
        error_text = msg.edit_text.call_args_list[-2].args[0]  # -2 because _show_readiness calls edit_text again
        assert "Ошибка" in error_text
        assert "возвращены" in error_text.lower()
        # State returned to readiness_check
        mock_state.set_state.assert_any_await(ArticlePipelineFSM.readiness_check)
