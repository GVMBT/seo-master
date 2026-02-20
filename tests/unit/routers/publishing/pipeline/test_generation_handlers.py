"""Tests for routers/publishing/pipeline/generation.py handlers.

Covers steps 5-8 of the Article Pipeline:
- Step 5: show_confirm, confirm_generate, back_to_readiness, cancel
- Step 6: _run_generation, progress messages, E35 (text fail), E34 (partial images)
- Step 7: publish (E07 double-click, E18 expired), regenerate (free + paid E10),
          cancel+refund, copy_html, connect_wp_publish, preview-only (G1)
- Step 8: more_articles (G5), result display
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from routers.publishing.pipeline._common import ArticlePipelineFSM
from routers.publishing.pipeline.generation import (
    MAX_REGENERATIONS_FREE,
    _build_preview_text,
    _select_keyword,
    back_to_readiness,
    cancel_refund,
    confirm_generate,
    connect_wp_publish,
    copy_html,
    more_articles,
    publish_article,
    regenerate_article,
    show_confirm,
    show_confirm_msg,
)
from services.preview import ArticleContent
from services.readiness import ReadinessReport
from tests.unit.routers.conftest import make_category, make_connection, make_user

_MODULE = "routers.publishing.pipeline.generation"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_report(**overrides: Any) -> ReadinessReport:
    defaults: dict[str, Any] = {
        "has_keywords": True,
        "keyword_count": 50,
        "cluster_count": 5,
        "has_description": True,
        "has_prices": True,
        "image_count": 4,
        "estimated_cost": 320,
        "user_balance": 1500,
        "is_sufficient_balance": True,
        "publication_count": 0,
        "missing_items": [],
    }
    defaults.update(overrides)
    return ReadinessReport(**defaults)


def _make_fsm_data(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "project_id": 1,
        "project_name": "Test Project",
        "category_id": 10,
        "category_name": "Test Category",
        "connection_id": 5,
        "wp_identifier": "blog.example.com",
        "image_count": 4,
        "preview_only": False,
    }
    defaults.update(overrides)
    return defaults


def _make_preview(**overrides: Any) -> MagicMock:
    """Create a mock ArticlePreview."""
    preview = MagicMock()
    defaults: dict[str, Any] = {
        "id": 100,
        "user_id": 123456,
        "project_id": 1,
        "category_id": 10,
        "connection_id": 5,
        "telegraph_url": "https://telegra.ph/test-123",
        "telegraph_path": "test-123",
        "title": "Test Article",
        "keyword": "test keyword",
        "word_count": 2000,
        "images_count": 4,
        "tokens_charged": 320,
        "regeneration_count": 0,
        "status": "draft",
        "content_html": "<h1>Test</h1><p>Content</p>",
        "images": [],
    }
    defaults.update(overrides)
    for key, val in defaults.items():
        setattr(preview, key, val)
    return preview


def _patch_settings(admin_ids: list[int] | None = None):
    """Patch get_settings()."""
    settings = MagicMock()
    settings.admin_ids = admin_ids or []
    settings.openrouter_api_key.get_secret_value.return_value = "test-key"
    settings.serper_api_key.get_secret_value.return_value = ""
    settings.firecrawl_api_key.get_secret_value.return_value = ""
    return patch(f"{_MODULE}.get_settings", return_value=settings)


def _patch_token_svc(balance: int = 1500, *, has_balance: bool = True):
    token_mock = MagicMock()
    token_mock.get_balance = AsyncMock(return_value=balance)
    token_mock.check_balance = AsyncMock(return_value=has_balance)
    token_mock.charge = AsyncMock(return_value=balance)
    token_mock.refund = AsyncMock(return_value=balance)
    token_mock.format_insufficient_msg = MagicMock(return_value="Недостаточно токенов. Нужно 320, у вас 100.")
    return patch(f"{_MODULE}.TokenService", return_value=token_mock), token_mock


# ---------------------------------------------------------------------------
# Step 5: show_confirm
# ---------------------------------------------------------------------------


class TestShowConfirm:
    """show_confirm renders step 5 and sets FSM state."""

    async def test_shows_project_and_category(
        self, mock_callback: MagicMock, mock_state: MagicMock, user: Any, mock_redis: MagicMock
    ) -> None:
        report = _make_report()
        data = _make_fsm_data()
        with _patch_settings():
            await show_confirm(mock_callback, mock_state, user, mock_redis, report, data)
        mock_callback.message.edit_text.assert_called_once()
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "Test Project" in text
        assert "Test Category" in text

    async def test_sets_confirm_cost_state(
        self, mock_callback: MagicMock, mock_state: MagicMock, user: Any, mock_redis: MagicMock
    ) -> None:
        report = _make_report()
        data = _make_fsm_data()
        with _patch_settings():
            await show_confirm(mock_callback, mock_state, user, mock_redis, report, data)
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.confirm_cost)

    async def test_shows_insufficient_balance_kb(
        self, mock_callback: MagicMock, mock_state: MagicMock, user: Any, mock_redis: MagicMock
    ) -> None:
        report = _make_report(is_sufficient_balance=False, user_balance=100)
        data = _make_fsm_data()
        with _patch_settings():
            await show_confirm(mock_callback, mock_state, user, mock_redis, report, data)
        kb = mock_callback.message.edit_text.call_args.kwargs["reply_markup"]
        buttons = [b for row in kb.inline_keyboard for b in row]
        assert any(b.callback_data == "nav:tokens" for b in buttons)

    async def test_god_mode_text(self, mock_callback: MagicMock, mock_state: MagicMock, mock_redis: MagicMock) -> None:
        user = make_user(id=999)
        report = _make_report()
        data = _make_fsm_data()
        with _patch_settings(admin_ids=[999]):
            await show_confirm(mock_callback, mock_state, user, mock_redis, report, data)
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "GOD_MODE" in text

    async def test_saves_checkpoint(
        self, mock_callback: MagicMock, mock_state: MagicMock, user: Any, mock_redis: MagicMock
    ) -> None:
        report = _make_report()
        data = _make_fsm_data()
        with _patch_settings():
            await show_confirm(mock_callback, mock_state, user, mock_redis, report, data)
        mock_redis.set.assert_called_once()

    async def test_preview_only_wp_display(
        self, mock_callback: MagicMock, mock_state: MagicMock, user: Any, mock_redis: MagicMock
    ) -> None:
        report = _make_report()
        data = _make_fsm_data(wp_identifier="", preview_only=True)
        with _patch_settings():
            await show_confirm(mock_callback, mock_state, user, mock_redis, report, data)
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "только превью" in text.lower()


class TestShowConfirmMsg:
    """show_confirm_msg sends new message."""

    async def test_sends_answer(
        self, mock_message: MagicMock, mock_state: MagicMock, user: Any, mock_redis: MagicMock
    ) -> None:
        report = _make_report()
        data = _make_fsm_data()
        with _patch_settings():
            await show_confirm_msg(mock_message, mock_state, user, mock_redis, report, data)
        mock_message.answer.assert_called_once()


# ---------------------------------------------------------------------------
# Step 5: confirm_generate
# ---------------------------------------------------------------------------


class TestConfirmGenerate:
    """confirm_generate charges and starts generation."""

    async def test_e01_insufficient_balance(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value=_make_fsm_data())
        token_patch, token_mock = _patch_token_svc(balance=100, has_balance=False)
        with _patch_settings(), token_patch, patch(f"{_MODULE}.RateLimiter") as rate_cls:
            rate_cls.return_value.check = AsyncMock()
            await confirm_generate(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_redis,
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )
        mock_callback.answer.assert_called_once()
        assert "Недостаточно" in mock_callback.answer.call_args.args[0]

    async def test_e25_rate_limit(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        from bot.exceptions import RateLimitError

        mock_state.get_data = AsyncMock(return_value=_make_fsm_data())
        with _patch_settings(), patch(f"{_MODULE}.RateLimiter") as rate_cls:
            rate_cls.return_value.check = AsyncMock(
                side_effect=RateLimitError(
                    message="Rate limit exceeded",
                    user_message="Подождите 5 мин.",
                    retry_after_seconds=300,
                )
            )
            await confirm_generate(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_redis,
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )
        mock_callback.answer.assert_called()
        assert "Подождите" in mock_callback.answer.call_args.args[0]

    async def test_god_mode_skips_charge(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        god_user = make_user(id=999)
        mock_state.get_data = AsyncMock(return_value=_make_fsm_data())
        token_patch, token_mock = _patch_token_svc()
        with (
            _patch_settings(admin_ids=[999]),
            token_patch,
            patch(f"{_MODULE}.RateLimiter") as rate_cls,
            patch(f"{_MODULE}._run_generation", new_callable=AsyncMock),
        ):
            rate_cls.return_value.check = AsyncMock()
            await confirm_generate(
                mock_callback,
                mock_state,
                god_user,
                mock_db,
                mock_redis,
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )
        # check_balance should NOT be called for god mode
        token_mock.check_balance.assert_not_called()

    async def test_sets_generating_state(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value=_make_fsm_data())
        token_patch, _ = _patch_token_svc()
        with (
            _patch_settings(),
            token_patch,
            patch(f"{_MODULE}.RateLimiter") as rate_cls,
            patch(f"{_MODULE}._run_generation", new_callable=AsyncMock),
        ):
            rate_cls.return_value.check = AsyncMock()
            await confirm_generate(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_redis,
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.generating)

    async def test_missing_category_shows_alert(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={})
        await confirm_generate(
            mock_callback,
            mock_state,
            user,
            mock_db,
            mock_redis,
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )
        mock_callback.answer.assert_called_once()
        assert "устарели" in mock_callback.answer.call_args.args[0]


# ---------------------------------------------------------------------------
# Step 5: back_to_readiness
# ---------------------------------------------------------------------------


class TestBackToReadiness:
    """back_to_readiness returns to step 4."""

    async def test_calls_show_readiness_check(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        with patch("routers.publishing.pipeline.readiness.show_readiness_check", new_callable=AsyncMock) as show_mock:
            await back_to_readiness(mock_callback, mock_state, user, mock_db, mock_redis)
            show_mock.assert_called_once()


# ---------------------------------------------------------------------------
# Step 6: _select_keyword
# ---------------------------------------------------------------------------


class TestSelectKeyword:
    """_select_keyword extracts phrases from flat and cluster formats."""

    async def test_flat_format(self, mock_db: MagicMock) -> None:
        cat = make_category(keywords=[{"phrase": "seo tips"}, {"phrase": "marketing"}])
        with patch(f"{_MODULE}.CategoriesRepository") as cls:
            cls.return_value.get_by_id = AsyncMock(return_value=cat)
            result = await _select_keyword(mock_db, 10)
        assert result in ("seo tips", "marketing")

    async def test_cluster_format(self, mock_db: MagicMock) -> None:
        cat = make_category(
            keywords=[
                {"main_phrase": "seo tools", "phrases": ["seo tools", "best seo"]},
            ]
        )
        with patch(f"{_MODULE}.CategoriesRepository") as cls:
            cls.return_value.get_by_id = AsyncMock(return_value=cat)
            result = await _select_keyword(mock_db, 10)
        assert result == "seo tools"

    async def test_no_keywords_returns_none(self, mock_db: MagicMock) -> None:
        cat = make_category(keywords=[])
        with patch(f"{_MODULE}.CategoriesRepository") as cls:
            cls.return_value.get_by_id = AsyncMock(return_value=cat)
            result = await _select_keyword(mock_db, 10)
        assert result is None

    async def test_no_category_returns_none(self, mock_db: MagicMock) -> None:
        with patch(f"{_MODULE}.CategoriesRepository") as cls:
            cls.return_value.get_by_id = AsyncMock(return_value=None)
            result = await _select_keyword(mock_db, 10)
        assert result is None


# ---------------------------------------------------------------------------
# Step 7: publish_article (E07, E18)
# ---------------------------------------------------------------------------


class TestPublishArticle:
    """publish_article with CAS and NX lock."""

    async def test_e07_double_click_nx_lock(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={"preview_id": 100, "connection_id": 5})
        # NX lock already held
        mock_redis.set = AsyncMock(return_value=None)
        await publish_article(
            mock_callback,
            mock_state,
            user,
            mock_db,
            mock_redis,
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )
        mock_callback.answer.assert_called()
        assert "уже выполняется" in mock_callback.answer.call_args.args[0]

    async def test_e18_expired_preview_cas_fails(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={"preview_id": 100, "connection_id": 5})
        mock_redis.set = AsyncMock(return_value="OK")  # Lock acquired
        with patch(f"{_MODULE}.PreviewsRepository") as repo_cls:
            repo_cls.return_value.atomic_mark_published = AsyncMock(return_value=None)  # CAS fail
            await publish_article(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_redis,
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )
        mock_callback.answer.assert_called()
        assert "устарело" in mock_callback.answer.call_args.args[0]

    async def test_successful_publish_creates_log(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        preview = _make_preview()
        mock_state.get_data = AsyncMock(return_value={"preview_id": 100, "connection_id": 5})
        mock_redis.set = AsyncMock(return_value="OK")

        publish_result = MagicMock()
        publish_result.post_url = "https://blog.example.com/my-article"

        token_patch, _ = _patch_token_svc(balance=1180)
        with (
            patch(f"{_MODULE}.PreviewsRepository") as previews_cls,
            patch(f"{_MODULE}.ConnectionService") as conn_cls,
            patch(f"{_MODULE}.PreviewService") as svc_cls,
            patch(f"{_MODULE}.PublicationsRepository") as pub_cls,
            _patch_settings(),
            token_patch,
        ):
            previews_cls.return_value.atomic_mark_published = AsyncMock(return_value=preview)
            conn_cls.return_value.get_by_id = AsyncMock(return_value=make_connection())
            svc_cls.return_value.publish_to_wordpress = AsyncMock(return_value=publish_result)
            pub_cls.return_value.create_log = AsyncMock()

            await publish_article(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_redis,
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )

        pub_cls.return_value.create_log.assert_called_once()
        mock_state.set_state.assert_any_call(ArticlePipelineFSM.result)

    async def test_missing_data_shows_alert(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={})
        await publish_article(
            mock_callback,
            mock_state,
            user,
            mock_db,
            mock_redis,
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )
        mock_callback.answer.assert_called()
        assert "устарели" in mock_callback.answer.call_args.args[0]


# ---------------------------------------------------------------------------
# Step 7: regenerate_article (E10, G2, G8)
# ---------------------------------------------------------------------------


class TestRegenerateArticle:
    """regenerate_article handles free and paid regenerations."""

    async def test_free_regen_no_charge(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """First 2 regenerations are free (reuse tokens_charged)."""
        preview = _make_preview(regeneration_count=0)
        mock_state.get_data = AsyncMock(return_value={"preview_id": 100, "connection_id": 5})

        token_patch, token_mock = _patch_token_svc()
        with (
            patch(f"{_MODULE}.PreviewsRepository") as repo_cls,
            _patch_settings(),
            token_patch,
            patch(f"{_MODULE}._run_generation", new_callable=AsyncMock),
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=preview)
            repo_cls.return_value.increment_regeneration = AsyncMock(return_value=1)
            await regenerate_article(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_redis,
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )
        # Should NOT charge for free regen
        token_mock.charge.assert_not_called()

    async def test_paid_regen_after_free_limit(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Regeneration 3+ charges tokens (E10)."""
        preview = _make_preview(regeneration_count=2, tokens_charged=320)
        mock_state.get_data = AsyncMock(return_value={"preview_id": 100, "connection_id": 5})

        token_patch, token_mock = _patch_token_svc()
        with (
            patch(f"{_MODULE}.PreviewsRepository") as repo_cls,
            _patch_settings(),
            token_patch,
            patch(f"{_MODULE}._run_generation", new_callable=AsyncMock),
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=preview)
            repo_cls.return_value.increment_regeneration = AsyncMock(return_value=3)
            await regenerate_article(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_redis,
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )
        token_mock.charge.assert_called_once()

    async def test_e10_insufficient_balance_on_paid_regen(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        preview = _make_preview(regeneration_count=2, tokens_charged=320)
        mock_state.get_data = AsyncMock(return_value={"preview_id": 100})

        token_patch, _ = _patch_token_svc(balance=100, has_balance=False)
        with patch(f"{_MODULE}.PreviewsRepository") as repo_cls, _patch_settings(), token_patch:
            repo_cls.return_value.get_by_id = AsyncMock(return_value=preview)
            await regenerate_article(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_redis,
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )
        mock_callback.answer.assert_called()
        assert "Недостаточно" in mock_callback.answer.call_args.args[0]

    async def test_sets_regenerating_state(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """G8: preview -> regenerating -> preview."""
        preview = _make_preview(regeneration_count=0)
        mock_state.get_data = AsyncMock(return_value={"preview_id": 100, "connection_id": 5})

        with (
            patch(f"{_MODULE}.PreviewsRepository") as repo_cls,
            _patch_settings(),
            patch(f"{_MODULE}.TokenService"),
            patch(f"{_MODULE}._run_generation", new_callable=AsyncMock),
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=preview)
            repo_cls.return_value.increment_regeneration = AsyncMock(return_value=1)
            await regenerate_article(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_redis,
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.regenerating)

    async def test_expired_preview_shows_alert(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        preview = _make_preview(status="expired")
        mock_state.get_data = AsyncMock(return_value={"preview_id": 100})

        with patch(f"{_MODULE}.PreviewsRepository") as repo_cls, _patch_settings():
            repo_cls.return_value.get_by_id = AsyncMock(return_value=preview)
            await regenerate_article(
                mock_callback,
                mock_state,
                user,
                mock_db,
                mock_redis,
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )
        mock_callback.answer.assert_called()
        assert "устарело" in mock_callback.answer.call_args.args[0].lower()

    async def test_max_regenerations_free_value(self) -> None:
        assert MAX_REGENERATIONS_FREE == 2


# ---------------------------------------------------------------------------
# Step 7: cancel_refund
# ---------------------------------------------------------------------------


class TestCancelRefund:
    """cancel_refund marks preview cancelled and refunds tokens."""

    async def test_refunds_and_clears_fsm(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        preview = _make_preview(tokens_charged=320)
        mock_state.get_data = AsyncMock(return_value={"preview_id": 100})

        with (
            patch(f"{_MODULE}.PreviewsRepository") as repo_cls,
            _patch_settings(),
            patch(f"{_MODULE}._try_refund", new_callable=AsyncMock) as refund_mock,
        ):
            repo_cls.return_value.get_by_id = AsyncMock(return_value=preview)
            repo_cls.return_value.update = AsyncMock()
            await cancel_refund(mock_callback, mock_state, user, mock_db, mock_redis)

        mock_state.clear.assert_called_once()
        refund_mock.assert_called_once()
        mock_callback.message.edit_text.assert_called_once()
        assert "отменена" in mock_callback.message.edit_text.call_args.args[0].lower()


# ---------------------------------------------------------------------------
# Step 7: copy_html
# ---------------------------------------------------------------------------


class TestCopyHtml:
    """copy_html sends HTML as document."""

    async def test_sends_document(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_db: MagicMock,
    ) -> None:
        preview = _make_preview(content_html="<h1>Test</h1>", keyword="seo tips")
        mock_state.get_data = AsyncMock(return_value={"preview_id": 100})
        mock_callback.message.answer_document = AsyncMock()

        with patch(f"{_MODULE}.PreviewsRepository") as repo_cls:
            repo_cls.return_value.get_by_id = AsyncMock(return_value=preview)
            await copy_html(mock_callback, mock_state, mock_db)

        mock_callback.message.answer_document.assert_called_once()

    async def test_no_content_shows_alert(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_db: MagicMock,
    ) -> None:
        preview = _make_preview(content_html=None)
        mock_state.get_data = AsyncMock(return_value={"preview_id": 100})

        with patch(f"{_MODULE}.PreviewsRepository") as repo_cls:
            repo_cls.return_value.get_by_id = AsyncMock(return_value=preview)
            await copy_html(mock_callback, mock_state, mock_db)

        mock_callback.answer.assert_called()
        assert "недоступен" in mock_callback.answer.call_args.args[0].lower()


# ---------------------------------------------------------------------------
# Step 7: connect_wp_publish (G1, Variant B)
# ---------------------------------------------------------------------------


class TestConnectWpPublish:
    """connect_wp_publish starts WP connection sub-flow."""

    async def test_sets_connect_wp_url_state(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        await connect_wp_publish(mock_callback, mock_state)
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.connect_wp_url)


# ---------------------------------------------------------------------------
# Step 8: more_articles (G5)
# ---------------------------------------------------------------------------


class TestMoreArticles:
    """more_articles jumps to step 3 (category), keeping project."""

    async def test_clears_preview_data(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value=_make_fsm_data(preview_id=100))
        with (
            patch(f"{_MODULE}.CategoriesRepository") as cats_cls,
            patch(f"{_MODULE}.save_checkpoint", new_callable=AsyncMock),
        ):
            cats_cls.return_value.get_by_project = AsyncMock(
                return_value=[
                    make_category(id=10),
                    make_category(id=11),
                ]
            )
            await more_articles(mock_callback, mock_state, user, mock_db, mock_redis)

        # Should clear preview-specific data
        update_call = mock_state.update_data.call_args
        assert update_call.kwargs.get("preview_id") is None
        assert update_call.kwargs.get("keyword") is None

    async def test_single_category_auto_selects(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value=_make_fsm_data(preview_id=100))
        with (
            patch(f"{_MODULE}.CategoriesRepository") as cats_cls,
            patch(f"{_MODULE}.save_checkpoint", new_callable=AsyncMock),
            patch("routers.publishing.pipeline.readiness.show_readiness_check", new_callable=AsyncMock) as show_mock,
        ):
            cats_cls.return_value.get_by_project = AsyncMock(return_value=[make_category()])
            await more_articles(mock_callback, mock_state, user, mock_db, mock_redis)
        show_mock.assert_called_once()

    async def test_no_project_shows_alert(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={})
        await more_articles(mock_callback, mock_state, user, mock_db, mock_redis)
        mock_callback.answer.assert_called()
        assert "устарели" in mock_callback.answer.call_args.args[0]


# ---------------------------------------------------------------------------
# _build_preview_text
# ---------------------------------------------------------------------------


class TestBuildPreviewText:
    """_build_preview_text formats text correctly."""

    def test_with_telegraph_url(self) -> None:
        content = ArticleContent(
            title="Test Article",
            content_html="<p>Test</p>",
            word_count=2000,
            images_count=4,
        )
        text = _build_preview_text(content, "seo tips", 320, "https://telegra.ph/test")
        assert "Test Article" in text
        assert "seo tips" in text
        assert "2000" in text
        assert "320" in text
        assert "Превью недоступно" not in text

    def test_e05_no_telegraph(self) -> None:
        content = ArticleContent(
            title="Test Article",
            content_html="<p>Some content here</p>",
            word_count=2000,
            images_count=4,
        )
        text = _build_preview_text(content, "seo tips", 320, None)
        assert "Превью недоступно" in text
