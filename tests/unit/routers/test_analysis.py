"""Tests for routers/analysis.py -- PageSpeed audit + CompetitorAnalysisFSM."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import Project, SiteAudit, User
from routers.analysis import (
    CompetitorAnalysisFSM,
    _format_audit_results,
    _format_competitor_results,
    _validate_url,
    cb_audit_run,
    cb_competitor_confirm,
    cb_competitor_start,
    cb_project_audit,
    fsm_competitor_url,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def site_audit() -> SiteAudit:
    """Sample site audit result."""
    return SiteAudit(
        id=1,
        project_id=1,
        url="https://example.com",
        performance=85,
        accessibility=92,
        best_practices=78,
        seo_score=90,
        lcp_ms=2100,
        inp_ms=81,
        cls=Decimal("0.05"),
        ttfb_ms=320,
        recommendations=[
            {"title": "Optimize images", "description": "Reduce size", "priority": "high"},
            {"title": "Add alt tags", "description": "Accessibility", "priority": "medium"},
        ],
    )


@pytest.fixture
def project_with_url(user: User) -> Project:
    """Project with website_url set."""
    return Project(
        id=1,
        user_id=user.id,
        name="Test Project",
        company_name="Test Co",
        specialization="Testing",
        website_url="https://example.com",
    )


@pytest.fixture
def project_no_url(user: User) -> Project:
    """Project without website_url."""
    return Project(
        id=1,
        user_id=user.id,
        name="Test Project",
        company_name="Test Co",
        specialization="Testing",
        website_url=None,
    )


@pytest.fixture
def competitor_data() -> dict:
    """Sample competitor analysis data."""
    return {
        "company_name": "Competitor Inc",
        "main_topics": ["furniture", "design", "home decor"],
        "unique_selling_points": ["Free delivery", "Custom designs"],
        "content_gaps": ["Blog articles", "Video content"],
        "primary_keywords": ["buy furniture", "modern design"],
        "estimated_pages": 45,
    }


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


class TestValidateUrl:
    def test_valid_https(self) -> None:
        assert _validate_url("https://example.com") is True

    def test_valid_http(self) -> None:
        assert _validate_url("http://example.com") is True

    def test_valid_with_path(self) -> None:
        assert _validate_url("https://example.com/page?q=1") is True

    def test_invalid_no_scheme(self) -> None:
        assert _validate_url("example.com") is False

    def test_invalid_empty(self) -> None:
        assert _validate_url("") is False

    def test_invalid_ftp(self) -> None:
        assert _validate_url("ftp://example.com") is False

    def test_strips_whitespace(self) -> None:
        assert _validate_url("  https://example.com  ") is True


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


class TestFormatAuditResults:
    def test_includes_all_scores(self, site_audit: SiteAudit) -> None:
        text = _format_audit_results(site_audit)
        assert "Performance: 85/100" in text
        assert "Accessibility: 92/100" in text
        assert "Best Practices: 78/100" in text
        assert "SEO: 90/100" in text

    def test_includes_cwv(self, site_audit: SiteAudit) -> None:
        text = _format_audit_results(site_audit)
        assert "LCP: 2100ms" in text
        assert "INP: 81ms" in text
        assert "CLS: 0.05" in text
        assert "TTFB: 320ms" in text

    def test_includes_recommendations(self, site_audit: SiteAudit) -> None:
        text = _format_audit_results(site_audit)
        assert "Optimize images" in text
        assert "Add alt tags" in text

    def test_limits_recommendations_to_5(self) -> None:
        audit = SiteAudit(
            id=1, project_id=1, url="https://example.com",
            recommendations=[{"title": f"Rec {i}"} for i in range(10)],
        )
        text = _format_audit_results(audit)
        assert "Rec 4" in text
        assert "Rec 5" not in text  # 0-indexed: Rec 0..4 shown

    def test_no_recommendations(self) -> None:
        audit = SiteAudit(id=1, project_id=1, url="https://example.com", recommendations=[])
        text = _format_audit_results(audit)
        assert "рекомендации" not in text.lower()

    def test_includes_url(self, site_audit: SiteAudit) -> None:
        text = _format_audit_results(site_audit)
        assert "https://example.com" in text


class TestFormatCompetitorResults:
    def test_includes_company_name(self, competitor_data: dict) -> None:
        text = _format_competitor_results(competitor_data)
        assert "Competitor Inc" in text

    def test_includes_topics(self, competitor_data: dict) -> None:
        text = _format_competitor_results(competitor_data)
        assert "furniture" in text
        assert "design" in text

    def test_includes_gaps(self, competitor_data: dict) -> None:
        text = _format_competitor_results(competitor_data)
        assert "Blog articles" in text
        assert "Video content" in text

    def test_includes_usps(self, competitor_data: dict) -> None:
        text = _format_competitor_results(competitor_data)
        assert "Free delivery" in text

    def test_includes_keywords(self, competitor_data: dict) -> None:
        text = _format_competitor_results(competitor_data)
        assert "buy furniture" in text

    def test_includes_page_count(self, competitor_data: dict) -> None:
        text = _format_competitor_results(competitor_data)
        assert "~45" in text

    def test_missing_fields(self) -> None:
        text = _format_competitor_results({})
        assert "N/A" in text

    def test_empty_gaps(self) -> None:
        text = _format_competitor_results({"company_name": "X", "main_topics": []})
        assert "Пробелы" not in text


# ---------------------------------------------------------------------------
# cb_project_audit
# ---------------------------------------------------------------------------


class TestCbProjectAudit:
    @pytest.mark.asyncio
    async def test_shows_existing_audit(
        self,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
        site_audit: SiteAudit,
    ) -> None:
        mock_callback.data = "project:1:audit"
        with (
            patch("routers.analysis.ProjectsRepository") as repo_cls,
            patch("routers.analysis.AuditsRepository") as audit_cls,
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=project)
            audit_cls.return_value.get_audit_by_project = AsyncMock(return_value=site_audit)
            await cb_project_audit(mock_callback, user, mock_db)
            text = mock_callback.message.edit_text.call_args.args[0]
            assert "Performance: 85/100" in text

    @pytest.mark.asyncio
    async def test_shows_menu_when_no_audit(
        self,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
    ) -> None:
        mock_callback.data = "project:1:audit"
        with (
            patch("routers.analysis.ProjectsRepository") as repo_cls,
            patch("routers.analysis.AuditsRepository") as audit_cls,
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=project)
            audit_cls.return_value.get_audit_by_project = AsyncMock(return_value=None)
            await cb_project_audit(mock_callback, user, mock_db)
            text = mock_callback.message.edit_text.call_args.args[0]
            assert "Анализ сайта" in text

    @pytest.mark.asyncio
    async def test_ownership_check(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "project:999:audit"
        with patch("routers.analysis.ProjectsRepository") as repo_cls:
            repo_cls.return_value.get_by_id = AsyncMock(return_value=None)
            await cb_project_audit(mock_callback, user, mock_db)
            mock_callback.answer.assert_awaited_once()
            assert mock_callback.answer.call_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# cb_audit_run
# ---------------------------------------------------------------------------


class TestCbAuditRun:
    @pytest.mark.asyncio
    async def test_no_website_url(
        self,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
        project_no_url: Project,
        mock_http_client: MagicMock,
    ) -> None:
        mock_callback.data = "project:1:audit:run"
        with patch("routers.analysis.ProjectsRepository") as repo_cls:
            repo_cls.return_value.get_by_id = AsyncMock(return_value=project_no_url)
            await cb_audit_run(mock_callback, user, mock_db, mock_http_client)
            mock_callback.answer.assert_awaited_once()
            assert "URL" in mock_callback.answer.call_args.args[0]

    @pytest.mark.asyncio
    async def test_insufficient_balance(
        self,
        mock_callback: MagicMock,
        mock_db: MagicMock,
        project_with_url: Project,
        mock_http_client: MagicMock,
    ) -> None:
        poor_user = User(id=123456789, balance=10, role="user")
        mock_callback.data = "project:1:audit:run"
        with (
            patch("routers.analysis.ProjectsRepository") as repo_cls,
            patch("routers.analysis.get_settings") as settings_mock,
            patch("routers.analysis.TokenService") as token_cls,
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=project_with_url)
            settings_mock.return_value.admin_id = 999
            token_cls.return_value.check_balance = AsyncMock(return_value=False)
            token_cls.return_value.format_insufficient_msg = MagicMock(return_value="Недостаточно")
            await cb_audit_run(mock_callback, poor_user, mock_db, mock_http_client)
            text = mock_callback.message.edit_text.call_args.args[0]
            assert "Недостаточно" in text

    @pytest.mark.asyncio
    async def test_successful_audit(
        self,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
        project_with_url: Project,
        mock_http_client: MagicMock,
        site_audit: SiteAudit,
    ) -> None:
        mock_callback.data = "project:1:audit:run"

        # Build a mock AuditResult
        from services.external.pagespeed import AuditResult

        audit_result = AuditResult(
            performance_score=85, accessibility_score=92, best_practices_score=78,
            seo_score=90, fcp_ms=1200, lcp_ms=2100, cls=0.05, tbt_ms=300,
            inp_ms=81, ttfb_ms=320, speed_index=3000,
            recommendations=[{"title": "Optimize images"}], full_report={},
        )

        with (
            patch("routers.analysis.ProjectsRepository") as repo_cls,
            patch("routers.analysis.get_settings") as settings_mock,
            patch("routers.analysis.TokenService") as token_cls,
            patch("routers.analysis.PageSpeedClient") as psi_cls,
            patch("routers.analysis.AuditsRepository") as audit_repo_cls,
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=project_with_url)
            settings_mock.return_value.admin_id = 999
            token_cls.return_value.check_balance = AsyncMock(return_value=True)
            token_cls.return_value.charge = AsyncMock(return_value=1450)
            psi_cls.return_value.audit = AsyncMock(return_value=audit_result)
            audit_repo_cls.return_value.upsert_audit = AsyncMock(return_value=site_audit)

            await cb_audit_run(mock_callback, user, mock_db, mock_http_client)

            token_cls.return_value.charge.assert_awaited_once()
            audit_repo_cls.return_value.upsert_audit.assert_awaited_once()
            # Final text should contain audit results
            last_edit_text = mock_callback.message.edit_text.call_args_list[-1].args[0]
            assert "Performance:" in last_edit_text

    @pytest.mark.asyncio
    async def test_psi_failure_refunds(
        self,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
        project_with_url: Project,
        mock_http_client: MagicMock,
    ) -> None:
        mock_callback.data = "project:1:audit:run"
        with (
            patch("routers.analysis.ProjectsRepository") as repo_cls,
            patch("routers.analysis.get_settings") as settings_mock,
            patch("routers.analysis.TokenService") as token_cls,
            patch("routers.analysis.PageSpeedClient") as psi_cls,
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=project_with_url)
            settings_mock.return_value.admin_id = 999
            token_cls.return_value.check_balance = AsyncMock(return_value=True)
            token_cls.return_value.charge = AsyncMock(return_value=1450)
            psi_cls.return_value.audit = AsyncMock(return_value=None)
            token_cls.return_value.refund = AsyncMock(return_value=1500)

            await cb_audit_run(mock_callback, user, mock_db, mock_http_client)

            token_cls.return_value.refund.assert_awaited_once()
            last_edit_text = mock_callback.message.edit_text.call_args_list[-1].args[0]
            assert "Не удалось" in last_edit_text


# ---------------------------------------------------------------------------
# cb_competitor_start
# ---------------------------------------------------------------------------


class TestCbCompetitorStart:
    @pytest.mark.asyncio
    async def test_ownership_check(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock, mock_state: AsyncMock,
    ) -> None:
        mock_callback.data = "project:999:competitor"
        with patch("routers.analysis.ProjectsRepository") as repo_cls:
            repo_cls.return_value.get_by_id = AsyncMock(return_value=None)
            await cb_competitor_start(mock_callback, user, mock_db, mock_state)
            mock_callback.answer.assert_awaited_once()
            assert mock_callback.answer.call_args.kwargs.get("show_alert") is True

    @pytest.mark.asyncio
    async def test_e38_insufficient_balance(
        self, mock_callback: MagicMock, mock_db: MagicMock, mock_state: AsyncMock, project: Project,
    ) -> None:
        poor_user = User(id=123456789, balance=10, role="user")
        mock_callback.data = "project:1:competitor"
        with (
            patch("routers.analysis.ProjectsRepository") as repo_cls,
            patch("routers.analysis.get_settings") as settings_mock,
            patch("routers.analysis.TokenService") as token_cls,
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=project)
            settings_mock.return_value.admin_id = 999
            token_cls.return_value.check_balance = AsyncMock(return_value=False)
            token_cls.return_value.format_insufficient_msg = MagicMock(return_value="Недостаточно")
            await cb_competitor_start(mock_callback, poor_user, mock_db, mock_state)
            text = mock_callback.message.edit_text.call_args.args[0]
            assert "Недостаточно" in text

    @pytest.mark.asyncio
    async def test_sets_fsm_state(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock, mock_state: AsyncMock, project: Project,
    ) -> None:
        mock_callback.data = "project:1:competitor"
        with (
            patch("routers.analysis.ProjectsRepository") as repo_cls,
            patch("routers.analysis.get_settings") as settings_mock,
            patch("routers.analysis.TokenService") as token_cls,
            patch("routers.analysis.ensure_no_active_fsm", new_callable=AsyncMock, return_value=None),
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=project)
            settings_mock.return_value.admin_id = 999
            token_cls.return_value.check_balance = AsyncMock(return_value=True)
            await cb_competitor_start(mock_callback, user, mock_db, mock_state)
            mock_state.set_state.assert_awaited_once_with(CompetitorAnalysisFSM.url)
            mock_state.update_data.assert_awaited_once_with(project_id=project.id)

    @pytest.mark.asyncio
    async def test_interrupts_active_fsm(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock, mock_state: AsyncMock, project: Project,
    ) -> None:
        mock_callback.data = "project:1:competitor"
        with (
            patch("routers.analysis.ProjectsRepository") as repo_cls,
            patch("routers.analysis.get_settings") as settings_mock,
            patch("routers.analysis.TokenService") as token_cls,
            patch("routers.analysis.ensure_no_active_fsm", new_callable=AsyncMock, return_value="создание проекта"),
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=project)
            settings_mock.return_value.admin_id = 999
            token_cls.return_value.check_balance = AsyncMock(return_value=True)
            await cb_competitor_start(mock_callback, user, mock_db, mock_state)
            # Should notify about interrupted process
            answer_text = mock_callback.message.answer.call_args_list[0].args[0]
            assert "прерван" in answer_text


# ---------------------------------------------------------------------------
# fsm_competitor_url
# ---------------------------------------------------------------------------


class TestFsmCompetitorUrl:
    @pytest.mark.asyncio
    async def test_valid_url_advances(
        self, mock_message: MagicMock, user: User, mock_state: AsyncMock,
    ) -> None:
        mock_message.text = "https://competitor.com"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1})
        await fsm_competitor_url(mock_message, user, mock_state)
        mock_state.update_data.assert_awaited_once_with(competitor_url="https://competitor.com")
        mock_state.set_state.assert_awaited_once_with(CompetitorAnalysisFSM.confirm)

    @pytest.mark.asyncio
    async def test_invalid_url_repeats(
        self, mock_message: MagicMock, user: User, mock_state: AsyncMock,
    ) -> None:
        mock_message.text = "not-a-url"
        await fsm_competitor_url(mock_message, user, mock_state)
        mock_state.set_state.assert_not_awaited()
        mock_message.answer.assert_awaited_once()
        assert "корректный URL" in mock_message.answer.call_args.args[0]

    @pytest.mark.asyncio
    async def test_empty_text_repeats(
        self, mock_message: MagicMock, user: User, mock_state: AsyncMock,
    ) -> None:
        mock_message.text = ""
        await fsm_competitor_url(mock_message, user, mock_state)
        mock_state.set_state.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_shows_cost_in_confirm(
        self, mock_message: MagicMock, user: User, mock_state: AsyncMock,
    ) -> None:
        mock_message.text = "https://competitor.com"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1})
        await fsm_competitor_url(mock_message, user, mock_state)
        text = mock_message.answer.call_args.args[0]
        assert "50" in text  # COST_COMPETITOR
        assert str(user.balance) in text


# ---------------------------------------------------------------------------
# cb_competitor_confirm
# ---------------------------------------------------------------------------


class TestCbCompetitorConfirm:
    @pytest.mark.asyncio
    async def test_successful_analysis(
        self,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
        mock_state: AsyncMock,
        mock_http_client: MagicMock,
        mock_rate_limiter: MagicMock,
        competitor_data: dict,
    ) -> None:
        mock_callback.data = "comp:confirm"
        mock_state.get_data = AsyncMock(return_value={
            "competitor_url": "https://competitor.com",
            "project_id": 1,
        })

        from services.external.firecrawl import ExtractResult

        extract_result = ExtractResult(data=competitor_data, source_url="https://competitor.com")

        with (
            patch("routers.analysis.get_settings") as settings_mock,
            patch("routers.analysis.TokenService") as token_cls,
            patch("routers.analysis.FirecrawlClient") as fc_cls,
        ):
            settings_mock.return_value.admin_id = 999
            settings_mock.return_value.firecrawl_api_key.get_secret_value.return_value = "fc-key"
            token_cls.return_value.charge = AsyncMock(return_value=1450)
            fc_cls.return_value.extract_competitor = AsyncMock(return_value=extract_result)

            await cb_competitor_confirm(mock_callback, user, mock_db, mock_state, mock_http_client, mock_rate_limiter)

            token_cls.return_value.charge.assert_awaited_once()
            mock_state.clear.assert_awaited_once()
            last_edit = mock_callback.message.edit_text.call_args_list[-1].args[0]
            assert "Competitor Inc" in last_edit

    @pytest.mark.asyncio
    async def test_e31_firecrawl_failure_refunds(
        self,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
        mock_state: AsyncMock,
        mock_http_client: MagicMock,
        mock_rate_limiter: MagicMock,
    ) -> None:
        mock_callback.data = "comp:confirm"
        mock_state.get_data = AsyncMock(return_value={
            "competitor_url": "https://competitor.com",
            "project_id": 1,
        })
        with (
            patch("routers.analysis.get_settings") as settings_mock,
            patch("routers.analysis.TokenService") as token_cls,
            patch("routers.analysis.FirecrawlClient") as fc_cls,
        ):
            settings_mock.return_value.admin_id = 999
            settings_mock.return_value.firecrawl_api_key.get_secret_value.return_value = "fc-key"
            token_cls.return_value.charge = AsyncMock(return_value=1450)
            token_cls.return_value.refund = AsyncMock(return_value=1500)
            fc_cls.return_value.extract_competitor = AsyncMock(return_value=None)

            await cb_competitor_confirm(mock_callback, user, mock_db, mock_state, mock_http_client, mock_rate_limiter)

            token_cls.return_value.refund.assert_awaited_once()
            mock_state.clear.assert_awaited_once()
            last_edit = mock_callback.message.edit_text.call_args_list[-1].args[0]
            assert "недоступен" in last_edit
