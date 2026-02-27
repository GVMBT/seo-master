"""Tests for Sprint 4 performance optimizations.

Covers:
- C19: Parallel DataForSEO calls in keywords.py
- C20: Batch profile stats queries in tokens.py
- H24: Batch digest queries in notifications.py
- S3: ConnectionsRepository lightweight methods
- S5: Branding inline styles survive nh3 sanitization
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import Category, PlatformSchedule, Project, User
from services.ai.orchestrator import GenerationResult
from services.external.dataforseo import KeywordSuggestion
from services.keywords import _DATAFORSEO_SEMAPHORE, KeywordService
from services.notifications import NotifyService
from services.tokens import TokenService

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_user_row(user_id: int = 123, balance: int = 1500) -> dict[str, Any]:
    return {
        "id": user_id,
        "username": "test",
        "first_name": "Test",
        "last_name": None,
        "balance": balance,
        "language": "ru",
        "role": "user",
        "referrer_id": None,
        "notify_publications": True,
        "notify_balance": True,
        "notify_news": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_activity": "2026-02-01T00:00:00+00:00",
    }


def _make_gen_result(content: dict[str, Any]) -> GenerationResult:
    return GenerationResult(
        content=content,
        model_used="deepseek/deepseek-v3.2",
        prompt_version="v1",
        fallback_used=False,
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.01,
        generation_time_ms=500,
    )


def _make_suggestion(phrase: str, volume: int = 100) -> KeywordSuggestion:
    return KeywordSuggestion(phrase=phrase, volume=volume, cpc=1.0, competition=0.5)


def _make_notify_user(**overrides: Any) -> User:
    defaults = {
        "id": 1,
        "balance": 500,
        "notify_publications": True,
        "notify_balance": True,
        "notify_news": True,
        "last_activity": datetime.now(tz=UTC),
    }
    defaults.update(overrides)
    return User(**defaults)


# ---------------------------------------------------------------------------
# C19: Parallel DataForSEO calls
# ---------------------------------------------------------------------------


class TestC19ParallelDataForSEO:
    """C19: Verify DataForSEO calls are parallelized via asyncio.gather."""

    @pytest.fixture
    def service(self) -> KeywordService:
        orch = AsyncMock()
        orch.generate_without_rate_limit = AsyncMock(
            return_value=_make_gen_result({"variants": []})
        )
        dfs = AsyncMock()
        dfs.keyword_suggestions = AsyncMock(return_value=[_make_suggestion("kw1")])
        dfs.related_keywords = AsyncMock(return_value=[_make_suggestion("kw2")])
        db = MagicMock()
        svc = KeywordService(orchestrator=orch, dataforseo=dfs, db=db)
        return svc

    async def test_parallel_calls_for_multiple_seeds(self, service: KeywordService) -> None:
        """Multiple seeds should call suggestions+related in parallel."""
        result = await service.fetch_raw_phrases(
            products="a, b, c",
            geography="Moscow",
            quantity=100,
            project_id=1,
            user_id=1,
        )
        # Each of 3 seeds should trigger suggestions + related (6 calls total)
        dfs = service._dataforseo
        assert dfs.keyword_suggestions.await_count == 3  # type: ignore[union-attr]
        assert dfs.related_keywords.await_count == 3  # type: ignore[union-attr]
        assert len(result) >= 1

    async def test_semaphore_limits_concurrency(self) -> None:
        """Verify semaphore(5) is used and limits concurrent DataForSEO calls."""
        # The semaphore is module-level
        assert _DATAFORSEO_SEMAPHORE._value == 5

    async def test_fetch_seeds_parallel_returns_combined_results(self) -> None:
        """_fetch_seeds_parallel combines suggestions+related from all seeds."""
        orch = AsyncMock()
        dfs = AsyncMock()
        # Each seed returns different suggestions
        dfs.keyword_suggestions = AsyncMock(
            side_effect=[
                [_make_suggestion("from_seed_1")],
                [_make_suggestion("from_seed_2")],
            ]
        )
        dfs.related_keywords = AsyncMock(
            side_effect=[
                [_make_suggestion("related_1")],
                [_make_suggestion("related_2")],
            ]
        )
        svc = KeywordService(orchestrator=orch, dataforseo=dfs, db=MagicMock())

        results = await svc._fetch_seeds_parallel(["seed1", "seed2"], 2804, 100)

        assert len(results) == 2  # 2 seeds
        assert len(results[0]) == 2  # suggestions + related for seed1
        assert len(results[1]) == 2  # suggestions + related for seed2

    async def test_parallel_empty_result_falls_back_to_next_location(self) -> None:
        """Empty results from Ukraine -> tries Kazakhstan (location fallback still works)."""
        orch = AsyncMock()
        orch.generate_without_rate_limit = AsyncMock(
            return_value=_make_gen_result({"variants": []})
        )
        dfs = AsyncMock()

        call_count = 0

        async def suggestions_side_effect(
            seed: str, location_code: int, limit: int
        ) -> list[KeywordSuggestion]:
            nonlocal call_count
            call_count += 1
            if location_code == 2804:
                return []
            return [_make_suggestion("kz_result")]

        dfs.keyword_suggestions.side_effect = suggestions_side_effect
        dfs.related_keywords.return_value = []

        svc = KeywordService(orchestrator=orch, dataforseo=dfs, db=MagicMock())
        result = await svc.fetch_raw_phrases(
            products="test", geography="Moscow", quantity=100, project_id=1, user_id=1
        )
        assert len(result) >= 1
        assert result[0]["phrase"] == "kz_result"


# ---------------------------------------------------------------------------
# C20: Batch profile stats
# ---------------------------------------------------------------------------


class TestC20BatchProfileStats:
    """C20: get_profile_stats uses batch queries instead of N+1."""

    @pytest.fixture
    def service(self) -> TokenService:
        svc = TokenService.__new__(TokenService)
        svc._db = AsyncMock()
        svc._users = AsyncMock()
        svc._payments = AsyncMock()
        svc._admin_ids = [999]
        return svc

    async def test_uses_get_by_projects_batch(self, service: TokenService) -> None:
        """Verify get_by_projects (plural) is called instead of get_by_project (singular)."""
        user = User(**_make_user_row(balance=2000))

        with (
            patch("services.tokens.ProjectsRepository") as mock_proj_cls,
            patch("services.tokens.SchedulesRepository") as mock_sched_cls,
            patch("services.tokens.CategoriesRepository") as mock_cat_cls,
        ):
            proj_repo = AsyncMock()
            proj_repo.get_by_user.return_value = [
                Project(id=1, user_id=123, name="P1", company_name="C", specialization="S"),
                Project(id=2, user_id=123, name="P2", company_name="C2", specialization="S2"),
            ]
            mock_proj_cls.return_value = proj_repo

            cat_repo = AsyncMock()
            cat_repo.get_by_projects.return_value = [
                Category(id=1, project_id=1, name="Cat1"),
                Category(id=2, project_id=1, name="Cat2"),
                Category(id=3, project_id=2, name="Cat3"),
            ]
            mock_cat_cls.return_value = cat_repo

            sched_repo = AsyncMock()
            sched_repo.get_by_project.return_value = []
            mock_sched_cls.return_value = sched_repo

            service._users.get_referral_count.return_value = 0
            stats = await service.get_profile_stats(user)

            # Should call get_by_projects (batch) ONCE, not get_by_project N times
            cat_repo.get_by_projects.assert_awaited_once_with([1, 2])
            # get_by_project (singular) should NOT be called
            cat_repo.get_by_project.assert_not_awaited()

        assert stats["project_count"] == 2
        assert stats["category_count"] == 3

    async def test_batch_schedules_uses_all_category_ids(self, service: TokenService) -> None:
        """Schedules query uses all category IDs from batch, not per-project."""
        user = User(**_make_user_row())

        with (
            patch("services.tokens.ProjectsRepository") as mock_proj_cls,
            patch("services.tokens.SchedulesRepository") as mock_sched_cls,
            patch("services.tokens.CategoriesRepository") as mock_cat_cls,
        ):
            proj_repo = AsyncMock()
            proj_repo.get_by_user.return_value = [
                Project(id=1, user_id=123, name="P1", company_name="C", specialization="S"),
            ]
            mock_proj_cls.return_value = proj_repo

            cat_repo = AsyncMock()
            cat_repo.get_by_projects.return_value = [
                Category(id=10, project_id=1, name="Cat10"),
                Category(id=20, project_id=1, name="Cat20"),
            ]
            mock_cat_cls.return_value = cat_repo

            sched_repo = AsyncMock()
            sched_repo.get_by_project.return_value = [
                PlatformSchedule(
                    id=1, category_id=10, platform_type="wordpress",
                    connection_id=1, enabled=True,
                    schedule_days=["mon"], posts_per_day=1,
                ),
            ]
            mock_sched_cls.return_value = sched_repo

            service._users.get_referral_count.return_value = 0
            stats = await service.get_profile_stats(user)

            # Schedules query should use ALL category IDs at once
            sched_repo.get_by_project.assert_awaited_once_with([10, 20])

        assert stats["schedule_count"] == 1
        assert stats["posts_per_week"] == 1


# ---------------------------------------------------------------------------
# H24: Batch digest queries
# ---------------------------------------------------------------------------


class TestH24BatchDigest:
    """H24: build_weekly_digest uses batch publication counts."""

    async def test_uses_batch_stats_query(self) -> None:
        """Verify batch method get_stats_by_users_batch is used."""
        svc = NotifyService(db=MagicMock())
        svc._users.get_active_users = AsyncMock(
            return_value=[
                _make_notify_user(id=1, notify_news=True, balance=100),
                _make_notify_user(id=2, notify_news=True, balance=200),
                _make_notify_user(id=3, notify_news=False, balance=300),
            ]
        )

        with patch("services.notifications.PublicationsRepository") as mock_pubs_cls:
            mock_pubs = MagicMock()
            mock_pubs.get_stats_by_users_batch = AsyncMock(
                return_value={1: 10, 2: 25}
            )
            mock_pubs_cls.return_value = mock_pubs

            result = await svc.build_weekly_digest()

            # Should call batch method with only eligible user IDs
            mock_pubs.get_stats_by_users_batch.assert_awaited_once_with([1, 2])
            # Should NOT call per-user get_stats_by_user
            mock_pubs.get_stats_by_user.assert_not_called()

        assert len(result) == 2
        assert "10" in result[0][1]
        assert "25" in result[1][1]

    async def test_zero_publications_for_user(self) -> None:
        """User not in batch result should show 0 publications."""
        svc = NotifyService(db=MagicMock())
        svc._users.get_active_users = AsyncMock(
            return_value=[_make_notify_user(id=99, notify_news=True, balance=500)]
        )

        with patch("services.notifications.PublicationsRepository") as mock_pubs_cls:
            mock_pubs = MagicMock()
            # User 99 has no publications, so not in the result dict
            mock_pubs.get_stats_by_users_batch = AsyncMock(return_value={})
            mock_pubs_cls.return_value = mock_pubs

            result = await svc.build_weekly_digest()

        assert len(result) == 1
        assert "0" in result[0][1]  # Shows "0" publications

    async def test_no_eligible_users_skips_db_query(self) -> None:
        """If all users have notify_news=False, skip publication query entirely."""
        svc = NotifyService(db=MagicMock())
        svc._users.get_active_users = AsyncMock(
            return_value=[
                _make_notify_user(id=1, notify_news=False),
                _make_notify_user(id=2, notify_news=False),
            ]
        )

        with patch("services.notifications.PublicationsRepository") as mock_pubs_cls:
            result = await svc.build_weekly_digest()
            # Should NOT even create a PublicationsRepository
            mock_pubs_cls.assert_not_called()

        assert result == []


# ---------------------------------------------------------------------------
# S3: ConnectionsRepository lightweight methods
# ---------------------------------------------------------------------------


class TestS3ConnectionLightweight:
    """S3: New lightweight methods that skip credential decryption."""

    async def test_get_list_by_project_returns_dicts(self) -> None:
        """get_list_by_project returns raw dicts without credentials."""
        from db.credential_manager import CredentialManager
        from db.repositories.connections import ConnectionsRepository
        from tests.unit.db.repositories.conftest import MockResponse, MockSupabaseClient

        mock_db = MockSupabaseClient()
        mock_db.set_response(
            "platform_connections",
            MockResponse(
                data=[
                    {
                        "id": 1,
                        "project_id": 5,
                        "platform_type": "wordpress",
                        "identifier": "example.com",
                        "status": "active",
                        "metadata": {},
                        "created_at": "2026-01-01T00:00:00+00:00",
                    }
                ]
            ),
        )
        cm = MagicMock(spec=CredentialManager)
        repo = ConnectionsRepository(mock_db, cm)  # type: ignore[arg-type]

        result = await repo.get_list_by_project(5)

        assert len(result) == 1
        assert result[0]["platform_type"] == "wordpress"
        assert "credentials" not in result[0]
        # CredentialManager.decrypt should NOT be called
        cm.decrypt.assert_not_called()

    async def test_exists_by_identifier_returns_true(self) -> None:
        """exists_by_identifier returns True when connection exists."""
        from db.credential_manager import CredentialManager
        from db.repositories.connections import ConnectionsRepository
        from tests.unit.db.repositories.conftest import MockResponse, MockSupabaseClient

        mock_db = MockSupabaseClient()
        mock_db.set_response(
            "platform_connections",
            MockResponse(data=[], count=1),
        )
        cm = MagicMock(spec=CredentialManager)
        repo = ConnectionsRepository(mock_db, cm)  # type: ignore[arg-type]

        result = await repo.exists_by_identifier("example.com", "wordpress")

        assert result is True
        cm.decrypt.assert_not_called()

    async def test_exists_by_identifier_returns_false(self) -> None:
        """exists_by_identifier returns False when no match."""
        from db.credential_manager import CredentialManager
        from db.repositories.connections import ConnectionsRepository
        from tests.unit.db.repositories.conftest import MockResponse, MockSupabaseClient

        mock_db = MockSupabaseClient()
        mock_db.set_response(
            "platform_connections",
            MockResponse(data=[], count=0),
        )
        cm = MagicMock(spec=CredentialManager)
        repo = ConnectionsRepository(mock_db, cm)  # type: ignore[arg-type]

        result = await repo.exists_by_identifier("nope.com", "wordpress")

        assert result is False


# ---------------------------------------------------------------------------
# S3: CategoriesRepository batch method
# ---------------------------------------------------------------------------


class TestS3CategoriesBatch:
    """S3/C20: get_by_projects batch method."""

    async def test_get_by_projects_returns_all_categories(self) -> None:
        """get_by_projects returns categories for multiple project IDs."""
        from db.repositories.categories import CategoriesRepository
        from tests.unit.db.repositories.conftest import MockResponse, MockSupabaseClient

        mock_db = MockSupabaseClient()
        mock_db.set_response(
            "categories",
            MockResponse(
                data=[
                    {"id": 1, "project_id": 10, "name": "Cat1"},
                    {"id": 2, "project_id": 20, "name": "Cat2"},
                ]
            ),
        )
        repo = CategoriesRepository(mock_db)  # type: ignore[arg-type]
        result = await repo.get_by_projects([10, 20])
        assert len(result) == 2
        assert result[0].project_id == 10
        assert result[1].project_id == 20

    async def test_get_by_projects_empty_ids_returns_empty(self) -> None:
        """get_by_projects with empty list returns empty without DB call."""
        from db.repositories.categories import CategoriesRepository
        from tests.unit.db.repositories.conftest import MockSupabaseClient

        mock_db = MockSupabaseClient()
        repo = CategoriesRepository(mock_db)  # type: ignore[arg-type]
        result = await repo.get_by_projects([])
        assert result == []


# ---------------------------------------------------------------------------
# H24: PublicationsRepository batch method
# ---------------------------------------------------------------------------


class TestH24PublicationsBatch:
    """H24: get_stats_by_users_batch."""

    async def test_returns_counts_per_user(self) -> None:
        """Batch method returns {user_id: count} dict."""
        from db.repositories.publications import PublicationsRepository
        from tests.unit.db.repositories.conftest import MockResponse, MockSupabaseClient

        mock_db = MockSupabaseClient()
        mock_db.set_response(
            "publication_logs",
            MockResponse(
                data=[
                    {"user_id": 1},
                    {"user_id": 1},
                    {"user_id": 1},
                    {"user_id": 2},
                ]
            ),
        )
        repo = PublicationsRepository(mock_db)  # type: ignore[arg-type]
        result = await repo.get_stats_by_users_batch([1, 2, 3])
        assert result == {1: 3, 2: 1}
        assert 3 not in result  # no publications for user 3

    async def test_empty_user_ids_returns_empty_dict(self) -> None:
        """Empty user_ids list returns empty dict without DB call."""
        from db.repositories.publications import PublicationsRepository
        from tests.unit.db.repositories.conftest import MockSupabaseClient

        mock_db = MockSupabaseClient()
        repo = PublicationsRepository(mock_db)  # type: ignore[arg-type]
        result = await repo.get_stats_by_users_batch([])
        assert result == {}


# ---------------------------------------------------------------------------
# S5: Branding inline styles survive nh3
# ---------------------------------------------------------------------------


class TestS5BrandingInlineStyles:
    """S5: Branding CSS applied as inline styles that survive nh3 sanitization."""

    def test_heading_gets_accent_inline_style(self) -> None:
        """SEORenderer applies accent color as inline style on headings."""
        from services.ai.markdown_renderer import SEORenderer

        renderer = SEORenderer(branding={"accent": "#0066cc"})
        html = renderer.heading("Test Heading", 2)
        assert 'style="color: #0066cc"' in html

    def test_heading_no_style_without_branding(self) -> None:
        """Without branding, no inline style on headings."""
        from services.ai.markdown_renderer import SEORenderer

        renderer = SEORenderer()
        html = renderer.heading("Plain Heading", 2)
        assert "style" not in html

    def test_paragraph_gets_text_color(self) -> None:
        """Paragraph gets text color from branding."""
        from services.ai.markdown_renderer import SEORenderer

        renderer = SEORenderer(branding={"text": "#333333"})
        html = renderer.paragraph("Some text")
        assert 'style="color: #333333"' in html

    def test_link_gets_accent_color(self) -> None:
        """Links get accent color inline style."""
        from services.ai.markdown_renderer import SEORenderer

        renderer = SEORenderer(branding={"accent": "#ff0000"})
        html = renderer.link("Click", "https://example.com", "Title")
        assert 'style="color: #ff0000"' in html
        assert 'href="https://example.com"' in html

    def test_render_markdown_no_style_block(self) -> None:
        """render_markdown with branding should NOT produce a <style> block."""
        from services.ai.markdown_renderer import render_markdown

        html = render_markdown(
            "# Title\n\nParagraph.",
            branding={"accent": "#ff0000", "text": "#333"},
            insert_toc=False,
        )
        assert "<style>" not in html
        assert "#ff0000" in html
        assert "#333" in html

    def test_inline_styles_survive_nh3_sanitization(self) -> None:
        """End-to-end: inline styles survive nh3 sanitization."""
        from services.ai.articles import sanitize_html
        from services.ai.markdown_renderer import render_markdown

        html = render_markdown(
            "## Section\n\nText with [link](https://example.com).",
            branding={"accent": "#0066cc", "text": "#222222"},
            insert_toc=False,
        )
        sanitized = sanitize_html(html)

        # Accent color on heading and link should survive
        assert "#0066cc" in sanitized
        # Text color on paragraph should survive
        assert "#222222" in sanitized
        # No <style> block anywhere
        assert "<style>" not in sanitized

    def test_old_build_branding_css_still_works(self) -> None:
        """_build_branding_css is preserved for backward compatibility."""
        from services.ai.markdown_renderer import _build_branding_css

        css = _build_branding_css({"text": "#333", "accent": "#0066cc"})
        assert "<style>" in css
        assert "#333" in css
        assert "#0066cc" in css

    def test_build_branding_css_empty(self) -> None:
        """Empty branding returns empty string."""
        from services.ai.markdown_renderer import _build_branding_css

        assert _build_branding_css({}) == ""
