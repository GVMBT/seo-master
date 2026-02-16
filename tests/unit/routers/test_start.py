"""Tests for routers/start.py."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import Project, User
from routers.start import (
    _build_dashboard_text,
    btn_admin_redirect,
    btn_cancel,
    btn_menu,
    btn_write_article,
    cb_help,
    cb_main_menu,
    cb_stub,
    cmd_cancel,
    cmd_help,
    cmd_start,
    cmd_start_deep_link,
    fsm_non_text_guard,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MOCK_STATS_EMPTY: dict[str, int] = {
    "project_count": 0,
    "category_count": 0,
    "schedule_count": 0,
    "referral_count": 0,
    "posts_per_week": 0,
    "tokens_per_week": 0,
    "tokens_per_month": 0,
}

_MOCK_STATS_ACTIVE: dict[str, int] = {
    "project_count": 3,
    "category_count": 8,
    "schedule_count": 5,
    "referral_count": 1,
    "posts_per_week": 17,
    "tokens_per_week": 680,
    "tokens_per_month": 2720,
}


# ---------------------------------------------------------------------------
# _build_dashboard_text
# ---------------------------------------------------------------------------


class TestBuildDashboardText:
    @pytest.mark.asyncio
    async def test_new_user_welcome(self, user: User, mock_db: MagicMock) -> None:
        text = await _build_dashboard_text(user, mock_db, is_new_user=True)
        assert "1500 токенов" in text
        assert "Добро пожаловать" in text
        assert "Что хотите сделать?" in text

    @pytest.mark.asyncio
    async def test_returning_no_projects(self, user: User, mock_db: MagicMock) -> None:
        with patch("routers.start.TokenService") as ts_cls:
            ts_cls.return_value.get_profile_stats = AsyncMock(return_value=_MOCK_STATS_EMPTY)
            text = await _build_dashboard_text(user, mock_db)
        assert str(user.balance) in text
        assert "нет проектов" in text.lower()

    @pytest.mark.asyncio
    async def test_returning_with_projects_and_schedules(self, user: User, mock_db: MagicMock) -> None:
        with patch("routers.start.TokenService") as ts_cls:
            ts_cls.return_value.get_profile_stats = AsyncMock(return_value=_MOCK_STATS_ACTIVE)
            text = await _build_dashboard_text(user, mock_db)
        assert str(user.balance) in text
        assert "Проектов: 3" in text
        assert "Категорий: 8" in text
        assert "Расписаний: 5" in text
        assert "Постов/нед: 17" in text

    @pytest.mark.asyncio
    async def test_returning_with_projects_no_schedules(self, user: User, mock_db: MagicMock) -> None:
        stats = {**_MOCK_STATS_ACTIVE, "schedule_count": 0}
        with patch("routers.start.TokenService") as ts_cls:
            ts_cls.return_value.get_profile_stats = AsyncMock(return_value=stats)
            text = await _build_dashboard_text(user, mock_db)
        assert "Проектов: 3" in text
        assert "Расписаний" not in text

    @pytest.mark.asyncio
    async def test_articles_left_forecast(self, user: User, mock_db: MagicMock) -> None:
        """Returning user with projects sees articles_left instead of weeks_left."""
        user.balance = 960  # 960 / 320 = 3 articles
        with patch("routers.start.TokenService") as ts_cls:
            ts_cls.return_value.get_profile_stats = AsyncMock(return_value=_MOCK_STATS_ACTIVE)
            text = await _build_dashboard_text(user, mock_db)
        assert "~3 статей" in text
        # Old weeks_left format must NOT be present
        assert "нед." not in text


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------


class TestCmdStart:
    @pytest.mark.asyncio
    async def test_new_user_sees_welcome_dashboard(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        with patch("routers.start._build_dashboard_text", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = "Welcome dashboard"
            await cmd_start(mock_message, mock_state, user, mock_db, mock_redis, is_new_user=True)
        mock_state.clear.assert_awaited_once()
        # Two messages: reply-KB restore + dashboard with inline
        assert mock_message.answer.await_count == 2
        mock_build.assert_awaited_once_with(user, mock_db, is_new_user=True)

    @pytest.mark.asyncio
    async def test_returning_user_gets_dashboard(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        with patch("routers.start._build_dashboard_text", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = "Returning dashboard"
            await cmd_start(mock_message, mock_state, user, mock_db, mock_redis, is_new_user=False)
        mock_build.assert_awaited_once_with(user, mock_db, is_new_user=False)
        # Second message has inline keyboard (dashboard)
        second_call = mock_message.answer.call_args_list[1]
        assert second_call.args[0] == "Returning dashboard"

    @pytest.mark.asyncio
    async def test_admin_gets_admin_button_in_reply_kb(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        admin_user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        with patch("routers.start._build_dashboard_text", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = "Admin dashboard"
            await cmd_start(mock_message, mock_state, admin_user, mock_db, mock_redis)
        # First message restores reply keyboard
        first_call = mock_message.answer.call_args_list[0]
        kb = first_call.kwargs["reply_markup"]
        buttons = [btn.text for row in kb.keyboard for btn in row]
        assert "АДМИНКА" in buttons

    @pytest.mark.asyncio
    async def test_pipeline_checkpoint_shown_for_returning_user(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
        project: Project,
    ) -> None:
        """Returning user with pipeline checkpoint sees resume prompt (section 16.10)."""
        checkpoint = {"project_id": project.id, "current_step": "select_category"}
        mock_redis.get = AsyncMock(return_value=json.dumps(checkpoint))
        with (
            patch("routers.start.ProjectsRepository") as repo_cls,
            patch("routers.start._build_dashboard_text", new_callable=AsyncMock, return_value="Dashboard"),
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=project)
            await cmd_start(mock_message, mock_state, user, mock_db, mock_redis, is_new_user=False)
        # Should have 3 messages: reply-KB + checkpoint resume + dashboard
        assert mock_message.answer.await_count == 3
        resume_call = mock_message.answer.call_args_list[1]
        assert "незавершённая статья" in resume_call.args[0]
        assert project.name in resume_call.args[0]

    @pytest.mark.asyncio
    async def test_no_checkpoint_for_new_user(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """New users skip pipeline checkpoint check even if redis has data."""
        mock_redis.get = AsyncMock(return_value='{"project_id": 1, "current_step": "test"}')
        with patch("routers.start._build_dashboard_text", new_callable=AsyncMock, return_value="Welcome"):
            await cmd_start(mock_message, mock_state, user, mock_db, mock_redis, is_new_user=True)
        # Only 2 messages (reply-KB + dashboard), no checkpoint prompt
        assert mock_message.answer.await_count == 2


# ---------------------------------------------------------------------------
# /start with deep link
# ---------------------------------------------------------------------------


class TestCmdStartDeepLink:
    @pytest.mark.asyncio
    async def test_referral_sets_referrer_id_when_referrer_exists(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
        mock_http_client: MagicMock,
    ) -> None:
        """Referrer must exist in DB (P4.2) before setting referrer_id."""
        user.referrer_id = None
        mock_message.text = "/start ref_555"
        referrer = User(id=555, balance=1500, role="user")
        with (
            patch("routers.start.UsersRepository") as repo_cls,
            patch("routers.start._build_dashboard_text", new_callable=AsyncMock, return_value="d"),
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=referrer)
            repo_cls.return_value.update = AsyncMock(return_value=user)
            await cmd_start_deep_link(mock_message, mock_state, user, mock_db, mock_redis, mock_http_client)
            repo_cls.return_value.get_by_id.assert_awaited_once_with(555)
            repo_cls.return_value.update.assert_awaited_once()
            update_arg = repo_cls.return_value.update.call_args.args[1]
            assert update_arg.referrer_id == 555

    @pytest.mark.asyncio
    async def test_referral_rejected_when_referrer_not_found(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
        mock_http_client: MagicMock,
    ) -> None:
        user.referrer_id = None
        mock_message.text = "/start ref_555"
        with (
            patch("routers.start.UsersRepository") as repo_cls,
            patch("routers.start._build_dashboard_text", new_callable=AsyncMock, return_value="d"),
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=None)
            repo_cls.return_value.update = AsyncMock()
            await cmd_start_deep_link(mock_message, mock_state, user, mock_db, mock_redis, mock_http_client)
            repo_cls.return_value.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_self_referral(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
        mock_http_client: MagicMock,
    ) -> None:
        user.referrer_id = None
        mock_message.text = f"/start ref_{user.id}"
        with (
            patch("routers.start.UsersRepository") as repo_cls,
            patch("routers.start._build_dashboard_text", new_callable=AsyncMock, return_value="d"),
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=user)
            repo_cls.return_value.update = AsyncMock()
            await cmd_start_deep_link(mock_message, mock_state, user, mock_db, mock_redis, mock_http_client)
            repo_cls.return_value.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_existing_referrer_not_overwritten(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
        mock_http_client: MagicMock,
    ) -> None:
        user.referrer_id = 111
        mock_message.text = "/start ref_555"
        referrer = User(id=555, balance=1500, role="user")
        with (
            patch("routers.start.UsersRepository") as repo_cls,
            patch("routers.start._build_dashboard_text", new_callable=AsyncMock, return_value="d"),
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=referrer)
            repo_cls.return_value.update = AsyncMock()
            await cmd_start_deep_link(mock_message, mock_state, user, mock_db, mock_redis, mock_http_client)
            repo_cls.return_value.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_new_user_with_deep_link_sees_welcome(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
        mock_http_client: MagicMock,
    ) -> None:
        mock_message.text = "/start ref_555"
        referrer = User(id=555, balance=1500, role="user")
        with (
            patch("routers.start.UsersRepository") as repo_cls,
            patch("routers.start._build_dashboard_text", new_callable=AsyncMock) as mock_build,
        ):
            mock_build.return_value = "Welcome"
            repo_cls.return_value.get_by_id = AsyncMock(return_value=referrer)
            repo_cls.return_value.update = AsyncMock(return_value=user)
            await cmd_start_deep_link(
                mock_message,
                mock_state,
                user,
                mock_db,
                mock_redis,
                mock_http_client,
                is_new_user=True,
            )
            mock_build.assert_awaited_once_with(user, mock_db, is_new_user=True)


# ---------------------------------------------------------------------------
# /cancel
# ---------------------------------------------------------------------------


class TestCmdCancel:
    @pytest.mark.asyncio
    async def test_cancel_with_active_fsm(self, mock_message: MagicMock, mock_state: AsyncMock, user: User) -> None:
        mock_state.get_state.return_value = "SomeState:step"
        await cmd_cancel(mock_message, mock_state, user)
        mock_state.clear.assert_awaited_once()
        assert "отменено" in mock_message.answer.call_args.args[0].lower()

    @pytest.mark.asyncio
    async def test_cancel_without_active_fsm(self, mock_message: MagicMock, mock_state: AsyncMock, user: User) -> None:
        mock_state.get_state.return_value = None
        await cmd_cancel(mock_message, mock_state, user)
        mock_state.clear.assert_awaited_once()
        assert "нет активного" in mock_message.answer.call_args.args[0].lower()


class TestBtnCancel:
    @pytest.mark.asyncio
    async def test_clears_when_in_fsm(self, mock_message: MagicMock, mock_state: AsyncMock, user: User) -> None:
        mock_state.get_state.return_value = "SomeState:some_step"
        await btn_cancel(mock_message, mock_state, user)
        mock_state.clear.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_action_when_no_state(self, mock_message: MagicMock, mock_state: AsyncMock, user: User) -> None:
        mock_state.get_state.return_value = None
        await btn_cancel(mock_message, mock_state, user)
        mock_state.clear.assert_not_awaited()


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------


class TestCmdHelp:
    @pytest.mark.asyncio
    async def test_sends_help_text(self, mock_message: MagicMock) -> None:
        await cmd_help(mock_message)
        mock_message.answer.assert_awaited_once()
        assert "/start" in mock_message.answer.call_args.args[0]


# ---------------------------------------------------------------------------
# menu:main callback -- dashboard (single edit, no second message)
# ---------------------------------------------------------------------------


class TestCbMainMenu:
    @pytest.mark.asyncio
    async def test_edits_to_dashboard_single_message(
        self, mock_callback: MagicMock, mock_state: AsyncMock, user: User, mock_db: MagicMock
    ) -> None:
        with patch("routers.start._build_dashboard_text", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = "Dashboard text"
            await cb_main_menu(mock_callback, mock_state, user, mock_db)
        mock_state.clear.assert_awaited_once()
        mock_callback.message.edit_text.assert_awaited_once()
        assert mock_callback.message.edit_text.call_args.args[0] == "Dashboard text"
        # No second message (reply-KB already set)
        mock_callback.message.answer.assert_not_awaited()
        mock_callback.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# help:main callback
# ---------------------------------------------------------------------------


class TestCbHelp:
    @pytest.mark.asyncio
    @patch("routers.help.cb_help_main", new_callable=AsyncMock)
    async def test_delegates_to_help_main(self, mock_help_main: AsyncMock, mock_callback: MagicMock) -> None:
        await cb_help(mock_callback)
        mock_help_main.assert_awaited_once_with(mock_callback)


# ---------------------------------------------------------------------------
# Reply button: Menu
# ---------------------------------------------------------------------------


class TestBtnMenu:
    @pytest.mark.asyncio
    async def test_sends_dashboard(self, mock_message: MagicMock, user: User, mock_db: MagicMock) -> None:
        with patch("routers.start._build_dashboard_text", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = "Menu dashboard"
            await btn_menu(mock_message, user, mock_db)
        mock_message.answer.assert_awaited_once()
        assert mock_message.answer.call_args.args[0] == "Menu dashboard"


# ---------------------------------------------------------------------------
# Reply button: Write Article (pipeline entry)
# ---------------------------------------------------------------------------


class TestBtnWriteArticle:
    @pytest.mark.asyncio
    async def test_checkpoint_resume_offered(
        self,
        mock_message: MagicMock,
        user: User,
        mock_db: MagicMock,
        mock_state: AsyncMock,
        mock_redis: MagicMock,
    ) -> None:
        """If pipeline checkpoint exists, offer resume instead of starting fresh."""
        checkpoint = {"project_id": 1, "current_step": "select_wp"}
        mock_redis.get = AsyncMock(return_value=json.dumps(checkpoint))
        await btn_write_article(mock_message, user, mock_db, mock_state, mock_redis)
        mock_message.answer.assert_awaited_once()
        text = mock_message.answer.call_args.args[0]
        assert "незавершённая статья" in text
        assert "select_wp" in text

    @pytest.mark.asyncio
    async def test_no_projects_shows_create_cta(
        self,
        mock_message: MagicMock,
        user: User,
        mock_db: MagicMock,
        mock_state: AsyncMock,
        mock_redis: MagicMock,
    ) -> None:
        """User with no projects sees 'create project' CTA."""
        mock_redis.get = AsyncMock(return_value=None)
        with patch("routers.start.ProjectsRepository") as repo_cls:
            repo_cls.return_value.get_by_user = AsyncMock(return_value=[])
            await btn_write_article(mock_message, user, mock_db, mock_state, mock_redis)
        text = mock_message.answer.call_args.args[0]
        assert "нет проектов" in text.lower()

    @pytest.mark.asyncio
    async def test_single_project_auto_selects_and_shows_wp(
        self,
        mock_message: MagicMock,
        user: User,
        mock_db: MagicMock,
        mock_state: AsyncMock,
        mock_redis: MagicMock,
        project: Project,
    ) -> None:
        """Single project auto-selected, transitions to select_wp state."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_show_wp = AsyncMock()
        mock_fsm_cls = MagicMock()
        mock_fsm_cls.select_wp = "ArticlePipelineFSM:select_wp"

        with (
            patch("routers.start.ProjectsRepository") as repo_cls,
            patch(
                "routers.publishing.pipeline.article.ArticlePipelineFSM",
                mock_fsm_cls,
            ),
            patch(
                "routers.publishing.pipeline.article.show_wp_selection",
                mock_show_wp,
            ),
        ):
            repo_cls.return_value.get_by_user = AsyncMock(return_value=[project])
            await btn_write_article(mock_message, user, mock_db, mock_state, mock_redis)

        mock_state.set_state.assert_awaited_once_with("ArticlePipelineFSM:select_wp")
        mock_state.update_data.assert_awaited_once_with(project_id=project.id)
        mock_show_wp.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multiple_projects_shows_selection(
        self,
        mock_message: MagicMock,
        user: User,
        mock_db: MagicMock,
        mock_state: AsyncMock,
        mock_redis: MagicMock,
    ) -> None:
        """Multiple projects shows project selection keyboard."""
        mock_redis.get = AsyncMock(return_value=None)
        projects = [
            Project(id=1, user_id=user.id, name="Project A", company_name="Co A", specialization="SEO"),
            Project(id=2, user_id=user.id, name="Project B", company_name="Co B", specialization="SEO"),
        ]
        mock_fsm_cls = MagicMock()
        mock_fsm_cls.select_project = "ArticlePipelineFSM:select_project"

        with (
            patch("routers.start.ProjectsRepository") as proj_repo_cls,
            patch("routers.publishing.pipeline.article.ArticlePipelineFSM", mock_fsm_cls),
            patch("db.repositories.publications.PublicationsRepository") as pub_repo_cls,
        ):
            proj_repo_cls.return_value.get_by_user = AsyncMock(return_value=projects)
            pub_repo_cls.return_value.get_by_user = AsyncMock(return_value=[])
            await btn_write_article(mock_message, user, mock_db, mock_state, mock_redis)

        mock_state.set_state.assert_awaited_once_with("ArticlePipelineFSM:select_project")
        text = mock_message.answer.call_args.args[0]
        assert "Для какого проекта?" in text

    @pytest.mark.asyncio
    async def test_interrupts_active_fsm(
        self,
        mock_message: MagicMock,
        user: User,
        mock_db: MagicMock,
        mock_state: AsyncMock,
        mock_redis: MagicMock,
    ) -> None:
        """Active FSM is interrupted (E26) before entering pipeline."""
        mock_redis.get = AsyncMock(return_value=None)
        with (
            patch("routers.start.ProjectsRepository") as repo_cls,
            patch("bot.fsm_utils.ensure_no_active_fsm", new_callable=AsyncMock) as mock_ensure,
        ):
            mock_ensure.return_value = "создание проекта"
            repo_cls.return_value.get_by_user = AsyncMock(return_value=[])
            await btn_write_article(mock_message, user, mock_db, mock_state, mock_redis)
        # First answer: interruption message, second: no projects CTA
        assert mock_message.answer.await_count == 2
        first_text = mock_message.answer.call_args_list[0].args[0]
        assert "прерван" in first_text


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class TestBtnAdminRedirect:
    @pytest.mark.asyncio
    @patch("routers.admin.dashboard.btn_admin_main", new_callable=AsyncMock)
    async def test_redirects_to_admin_dashboard(
        self, mock_admin_main: AsyncMock, mock_message: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        await btn_admin_redirect(mock_message, user, mock_db)
        mock_admin_main.assert_awaited_once_with(mock_message, user, mock_db)


class TestFsmNonTextGuard:
    @pytest.mark.asyncio
    async def test_rejects_non_text_during_fsm(self, mock_message: MagicMock) -> None:
        await fsm_non_text_guard(mock_message)
        mock_message.answer.assert_awaited_once()
        assert "текстовое" in mock_message.answer.call_args.args[0].lower()


class TestCbStub:
    @pytest.mark.asyncio
    async def test_shows_in_development(self, mock_callback: MagicMock) -> None:
        await cb_stub(mock_callback)
        mock_callback.answer.assert_awaited_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True
