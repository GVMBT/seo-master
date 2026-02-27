"""Tests for routers/publishing/pipeline/readiness.py handlers.

Covers Readiness Check (step 4) sub-flows:
- Checklist display (show_readiness_check, _build_checklist_text)
- Keywords sub-flow: menu, auto/configure/upload, city select, geo/qty/confirm/cancel,
  generation pipeline (_run_pipeline_keyword_generation)
- Description sub-flow: menu, AI generation (charge tokens), manual input
- Prices sub-flow: menu, text input, Excel upload
- Images sub-flow: menu, count selection
- Navigation: back, done (keywords blocker), step 5
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from routers.publishing.pipeline._common import ArticlePipelineFSM
from routers.publishing.pipeline.readiness import (
    _article_readiness_config,
    _build_checklist_text,
    _handle_configure_products,
    _run_pipeline_keyword_generation,
    readiness_back,
    readiness_description_ai,
    readiness_description_manual_input,
    readiness_description_manual_start,
    readiness_description_menu,
    readiness_done,
    readiness_images_menu,
    readiness_images_select,
    readiness_keywords_auto,
    readiness_keywords_cancel,
    readiness_keywords_city_select,
    readiness_keywords_configure,
    readiness_keywords_confirm,
    readiness_keywords_geo_input,
    readiness_keywords_menu,
    readiness_keywords_qty_select,
    readiness_keywords_text_input,
    readiness_keywords_upload_file,
    readiness_keywords_upload_start,
    readiness_prices_excel_file,
    readiness_prices_excel_start,
    readiness_prices_menu,
    readiness_prices_text_input,
    readiness_prices_text_start,
    show_readiness_check,
    show_readiness_check_msg,
)
from services.readiness import ReadinessReport

_MODULE = "routers.publishing.pipeline.readiness"
_COMMON = "routers.publishing.pipeline._readiness_common"

# Config object for closure-based handler testing.
# Closures capture cfg (the ReadinessConfig instance), so patching module-level
# names like show_readiness_check won't intercept calls from inside closures.
# Use _mock_cfg_show_check() / _mock_cfg_show_check_msg() helpers instead.
_CFG = _article_readiness_config


def _mock_cfg_show_check() -> tuple[AsyncMock, Any]:
    """Replace _CFG.show_check with AsyncMock; return (mock, original).

    Closures call cfg.show_check(...) on each invocation, so replacing
    the attribute on the frozen dataclass intercepts the call.
    """
    orig = _CFG.show_check
    mock = AsyncMock()
    object.__setattr__(_CFG, "show_check", mock)
    return mock, orig


def _mock_cfg_show_check_msg() -> tuple[AsyncMock, Any]:
    """Replace _CFG.show_check_msg with AsyncMock; return (mock, original)."""
    orig = _CFG.show_check_msg
    mock = AsyncMock()
    object.__setattr__(_CFG, "show_check_msg", mock)
    return mock, orig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_report(**overrides: Any) -> ReadinessReport:
    """Create a ReadinessReport with sensible defaults."""
    defaults: dict[str, Any] = {
        "has_keywords": True,
        "keyword_count": 50,
        "cluster_count": 5,
        "has_description": True,
        "has_prices": False,
        "image_count": 4,
        "estimated_cost": 320,
        "user_balance": 1500,
        "is_sufficient_balance": True,
        "publication_count": 0,
        "missing_items": [],
    }
    defaults.update(overrides)
    return ReadinessReport(**defaults)


def _patch_readiness(report: ReadinessReport | None = None):
    """Patch ReadinessService.check to return a given report."""
    r = report or _make_report()
    svc_mock = MagicMock()
    svc_mock.check = AsyncMock(return_value=r)
    return patch(f"{_MODULE}.ReadinessService", return_value=svc_mock), svc_mock


def _make_token_mock(balance: int = 1500, *, has_balance: bool = True) -> MagicMock:
    """Create TokenService mock."""
    token_mock = MagicMock()
    token_mock.get_balance = AsyncMock(return_value=balance)
    token_mock.check_balance = AsyncMock(return_value=has_balance)
    token_mock.charge = AsyncMock()
    token_mock.refund = AsyncMock(return_value=balance)
    token_mock.format_insufficient_msg = MagicMock(return_value="Недостаточно токенов")
    return token_mock


def _patch_token_svc(
    balance: int = 1500, *, has_balance: bool = True, module: str = _MODULE,
):
    """Patch TokenService for balance checks."""
    token_mock = _make_token_mock(balance, has_balance=has_balance)
    return patch(f"{module}.TokenService", return_value=token_mock), token_mock


def _patch_cats_repo(category: Any = None, module: str = _MODULE):
    """Patch CategoriesRepository."""
    cat_mock = MagicMock()
    cat_mock.update = AsyncMock()
    cat_mock.update_keywords = AsyncMock()
    cat_mock.get_by_id = AsyncMock(return_value=category)
    return patch(f"{module}.CategoriesRepository", return_value=cat_mock), cat_mock


def _patch_settings(module: str = _MODULE):
    """Patch get_settings to return mock config."""
    settings = MagicMock()
    settings.admin_ids = [999]
    return patch(f"{module}.get_settings", return_value=settings)


def _patch_projects_repo(project: Any = None, module: str = _MODULE):
    """Patch ProjectsRepository."""
    proj_mock = MagicMock()
    proj_mock.get_by_id = AsyncMock(return_value=project)
    proj_mock.update = AsyncMock()
    return patch(f"{module}.ProjectsRepository", return_value=proj_mock), proj_mock


def _make_state_data(**overrides: Any) -> dict[str, Any]:
    """Create FSM state data dict with defaults."""
    data: dict[str, Any] = {
        "project_id": 1,
        "project_name": "Test Project",
        "category_id": 10,
        "category_name": "Test Category",
        "image_count": 4,
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Checklist display
# ---------------------------------------------------------------------------


class TestBuildChecklistText:
    """_build_checklist_text builds correct display text."""

    async def test_all_filled(self) -> None:
        report = _make_report(has_keywords=True, has_description=True, has_prices=True)
        data = _make_state_data()
        text = _build_checklist_text(report, data)
        assert "Test Project" in text
        assert "Test Category" in text
        assert "5 кластеров (50 фраз)" in text
        assert "заполнено" in text

    async def test_keywords_missing(self) -> None:
        report = _make_report(
            has_keywords=False,
            keyword_count=0,
            cluster_count=0,
            missing_items=["keywords"],
        )
        text = _build_checklist_text(report, _make_state_data())
        assert "не заполнены (обязательно)" in text

    async def test_description_missing(self) -> None:
        report = _make_report(has_description=False, missing_items=["description"])
        text = _build_checklist_text(report, _make_state_data())
        assert "Описание — не заполнено" in text

    async def test_prices_missing_shown(self) -> None:
        report = _make_report(has_prices=False, missing_items=["prices"])
        text = _build_checklist_text(report, _make_state_data())
        assert "Цены — не заполнены" in text

    async def test_image_count_in_text(self) -> None:
        report = _make_report(image_count=6)
        text = _build_checklist_text(report, _make_state_data())
        assert "6 шт. в статье" in text

    async def test_zero_images_in_text(self) -> None:
        report = _make_report(image_count=0)
        text = _build_checklist_text(report, _make_state_data())
        assert "без изображений" in text

    async def test_html_escaping(self) -> None:
        data = _make_state_data(project_name="<script>", category_name="&test")
        report = _make_report()
        text = _build_checklist_text(report, data)
        assert "&lt;script&gt;" in text
        assert "&amp;test" in text


class TestShowReadinessCheck:
    """show_readiness_check renders checklist or skips to step 5."""

    async def test_renders_checklist_when_items_missing(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Missing keywords -> show checklist, set FSM to readiness_check."""
        report = _make_report(has_keywords=False, missing_items=["keywords"])
        mock_state.get_data = AsyncMock(return_value=_make_state_data())

        p_readiness, _ = _patch_readiness(report)
        p_token, _ = _patch_token_svc()
        p_settings = _patch_settings()
        p_save = patch(f"{_MODULE}.save_checkpoint", new_callable=AsyncMock)

        with p_readiness, p_token, p_settings, p_save:
            await show_readiness_check(mock_callback, mock_state, user, mock_db, mock_redis)

        mock_callback.message.edit_text.assert_called_once()
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.readiness_check)

    async def test_skips_to_step5_when_all_filled(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """All filled + no missing_items -> skip to step 5 stub."""
        report = _make_report(has_keywords=True, has_description=True, missing_items=[])
        mock_state.get_data = AsyncMock(return_value=_make_state_data())

        p_readiness, _ = _patch_readiness(report)
        p_token, _ = _patch_token_svc()
        p_settings = _patch_settings()
        p_confirm = patch(
            "routers.publishing.pipeline.generation.show_confirm",
            new_callable=AsyncMock,
        )

        with p_readiness, p_token, p_settings, p_confirm as mock_confirm:
            await show_readiness_check(mock_callback, mock_state, user, mock_db, mock_redis)

        mock_confirm.assert_called_once()

    async def test_no_category_clears_state(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """No category_id in state -> error, clear state."""
        mock_state.get_data = AsyncMock(return_value={"project_id": 1})
        p_clear = patch(f"{_MODULE}.clear_checkpoint", new_callable=AsyncMock)

        with p_clear:
            await show_readiness_check(mock_callback, mock_state, user, mock_db, mock_redis)

        mock_callback.message.edit_text.assert_called_once()
        assert "не выбрана" in mock_callback.message.edit_text.call_args[0][0]
        mock_state.clear.assert_called_once()

    async def test_inaccessible_message_returns_early(
        self,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """InaccessibleMessage -> return without action."""
        from aiogram.types import InaccessibleMessage as IM

        callback = MagicMock()
        callback.message = MagicMock(spec=IM)
        callback.answer = AsyncMock()

        await show_readiness_check(callback, mock_state, user, mock_db, mock_redis)
        mock_state.set_state.assert_not_called()


class TestShowReadinessCheckMsg:
    """show_readiness_check_msg for message context (after text/file input)."""

    async def test_renders_checklist_via_answer(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        report = _make_report(has_keywords=False, missing_items=["keywords"])
        mock_state.get_data = AsyncMock(return_value=_make_state_data())

        p_readiness, _ = _patch_readiness(report)
        p_token, _ = _patch_token_svc()
        p_settings = _patch_settings()
        p_save = patch(f"{_MODULE}.save_checkpoint", new_callable=AsyncMock)

        with p_readiness, p_token, p_settings, p_save:
            await show_readiness_check_msg(mock_message, mock_state, user, mock_db, mock_redis)

        mock_message.answer.assert_called_once()
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.readiness_check)


# ---------------------------------------------------------------------------
# Keywords sub-flow
# ---------------------------------------------------------------------------


class TestKeywordsSubFlow:
    """Keywords menu, stubs, upload (file + text)."""

    async def test_menu_shows_options(self, mock_callback: MagicMock) -> None:
        """Keywords menu shows keyword options keyboard."""
        await readiness_keywords_menu(mock_callback)
        mock_callback.message.edit_text.assert_called_once()
        assert "Ключевые фразы" in mock_callback.message.edit_text.call_args[0][0]
        mock_callback.answer.assert_called_once()

    async def test_auto_shows_confirm(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
    ) -> None:
        """Auto keyword generation loads category/project and shows confirm."""
        mock_state.get_data = AsyncMock(return_value=_make_state_data())

        cat_obj = MagicMock()
        cat_obj.name = "Test Category"
        p_cats, _ = _patch_cats_repo(category=cat_obj, module=_COMMON)
        p_projects = patch(
            f"{_COMMON}.ProjectsRepository",
            return_value=MagicMock(
                get_by_id=AsyncMock(
                    return_value=MagicMock(company_city="Москва"),
                ),
            ),
        )
        p_settings = patch(f"{_COMMON}.get_settings", return_value=MagicMock(admin_ids=[]))
        p_token = patch(
            f"{_COMMON}.TokenService",
            return_value=MagicMock(
                get_balance=AsyncMock(return_value=500),
            ),
        )

        with p_cats, p_projects, p_settings, p_token:
            await readiness_keywords_auto(
                mock_callback,
                mock_state,
                user,
                mock_db,
            )

        mock_state.set_state.assert_called_with(ArticlePipelineFSM.readiness_keywords_qty)
        mock_state.update_data.assert_called_once()
        update_kwargs = mock_state.update_data.call_args.kwargs
        assert update_kwargs["kw_quantity"] == 100
        assert update_kwargs["kw_products"] == "Test Category"
        assert update_kwargs["kw_geography"] == "Москва"
        mock_callback.message.edit_text.assert_called_once()
        assert "Автоподбор" in mock_callback.message.edit_text.call_args[0][0]

    async def test_auto_no_city_shows_city_kb(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
    ) -> None:
        """Auto shows city selection when project has no company_city (UX_PIPELINE SS4a)."""
        mock_state.get_data = AsyncMock(return_value=_make_state_data())

        cat_obj = MagicMock()
        cat_obj.name = "Test Category"
        p_cats, _ = _patch_cats_repo(category=cat_obj, module=_COMMON)
        p_projects = patch(
            f"{_COMMON}.ProjectsRepository",
            return_value=MagicMock(
                get_by_id=AsyncMock(
                    return_value=MagicMock(company_city=None),
                ),
            ),
        )

        with p_cats, p_projects:
            await readiness_keywords_auto(
                mock_callback,
                mock_state,
                user,
                mock_db,
            )

        # Should transition to geo state with kw_mode="auto"
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.readiness_keywords_geo)
        update_kwargs = mock_state.update_data.call_args.kwargs
        assert update_kwargs["kw_mode"] == "auto"
        assert update_kwargs["kw_products"] == "Test Category"
        # Should show city selection, not directly confirm
        edit_text = mock_callback.message.edit_text.call_args[0][0]
        assert "город" in edit_text.lower()

    async def test_configure_shows_products_prompt(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        """Configure keyword generation shows products input prompt."""
        await readiness_keywords_configure(mock_callback, mock_state)
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.readiness_keywords_products)
        mock_state.update_data.assert_called_with(kw_mode="configure")
        mock_callback.message.edit_text.assert_called_once()
        assert "товары" in mock_callback.message.edit_text.call_args[0][0].lower()

    async def test_upload_start_sets_state(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        """Upload start sets FSM to readiness_keywords_products."""
        await readiness_keywords_upload_start(mock_callback, mock_state)
        mock_callback.message.edit_text.assert_called_once()
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.readiness_keywords_products)

    async def test_upload_file_valid_txt(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Valid TXT file -> saves keywords, returns to checklist."""
        from io import BytesIO

        content = "ключевое слово 1\nключевое слово 2\nключевое слово 3"
        file_obj = BytesIO(content.encode("utf-8"))

        mock_message.document = MagicMock()
        mock_message.document.file_name = "keywords.txt"
        mock_message.document.file_size = 100
        mock_message.bot = MagicMock()
        mock_message.bot.download = AsyncMock(return_value=file_obj)

        mock_state.get_data = AsyncMock(return_value=_make_state_data())

        p_cats, cat_mock = _patch_cats_repo(module=_COMMON)
        mock_show, orig = _mock_cfg_show_check_msg()

        try:
            with p_cats:
                await readiness_keywords_upload_file(
                    mock_message, mock_state, user, mock_db, mock_redis,
                )
        finally:
            object.__setattr__(_CFG, "show_check_msg", orig)

        cat_mock.update_keywords.assert_called_once()
        keywords_arg = cat_mock.update_keywords.call_args[0][1]
        assert len(keywords_arg) == 3
        assert keywords_arg[0]["phrase"] == "ключевое слово 1"
        mock_show.assert_called_once()

    async def test_upload_file_wrong_extension(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Non-TXT file -> error message."""
        mock_message.document = MagicMock()
        mock_message.document.file_name = "keywords.xlsx"
        mock_message.document.file_size = 100

        await readiness_keywords_upload_file(
            mock_message, mock_state, user, mock_db, mock_redis,
        )

        mock_message.answer.assert_called_once()
        assert ".txt" in mock_message.answer.call_args[0][0]

    async def test_upload_file_too_large(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """File > 1 MB -> error message."""
        mock_message.document = MagicMock()
        mock_message.document.file_name = "keywords.txt"
        mock_message.document.file_size = 2 * 1024 * 1024  # 2 MB

        await readiness_keywords_upload_file(
            mock_message, mock_state, user, mock_db, mock_redis,
        )

        mock_message.answer.assert_called_once()
        assert "1 МБ" in mock_message.answer.call_args[0][0]

    async def test_upload_file_too_many_phrases(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """More than 500 phrases -> error message."""
        from io import BytesIO

        lines = "\n".join(f"phrase {i}" for i in range(501))
        file_obj = BytesIO(lines.encode("utf-8"))

        mock_message.document = MagicMock()
        mock_message.document.file_name = "keywords.txt"
        mock_message.document.file_size = 5000
        mock_message.bot = MagicMock()
        mock_message.bot.download = AsyncMock(return_value=file_obj)

        mock_state.get_data = AsyncMock(return_value=_make_state_data())

        await readiness_keywords_upload_file(
            mock_message, mock_state, user, mock_db, mock_redis,
        )

        mock_message.answer.assert_called_once()
        assert "500" in mock_message.answer.call_args[0][0]

    async def test_upload_file_empty(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Empty TXT file -> error message."""
        from io import BytesIO

        file_obj = BytesIO(b"")

        mock_message.document = MagicMock()
        mock_message.document.file_name = "keywords.txt"
        mock_message.document.file_size = 0
        mock_message.bot = MagicMock()
        mock_message.bot.download = AsyncMock(return_value=file_obj)

        await readiness_keywords_upload_file(
            mock_message, mock_state, user, mock_db, mock_redis,
        )

        mock_message.answer.assert_called_once()
        assert "пустой" in mock_message.answer.call_args[0][0].lower()

    async def test_upload_text_valid(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Text input with phrases -> saves keywords."""
        mock_message.text = "фраза один\nфраза два\nфраза три"
        mock_state.get_data = AsyncMock(return_value=_make_state_data())

        p_cats, cat_mock = _patch_cats_repo(module=_COMMON)
        mock_show, orig = _mock_cfg_show_check_msg()

        try:
            with p_cats:
                await readiness_keywords_text_input(
                    mock_message, mock_state, user, mock_db, mock_redis,
                )
        finally:
            object.__setattr__(_CFG, "show_check_msg", orig)

        cat_mock.update_keywords.assert_called_once()
        assert len(cat_mock.update_keywords.call_args[0][1]) == 3
        mock_show.assert_called_once()

    async def test_upload_text_empty(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Empty text -> error."""
        mock_message.text = ""

        await readiness_keywords_text_input(
            mock_message, mock_state, user, mock_db, mock_redis,
        )

        mock_message.answer.assert_called_once()

    async def test_upload_text_no_category(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """No category_id in state -> error."""
        mock_message.text = "фраза один"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1})

        await readiness_keywords_text_input(
            mock_message, mock_state, user, mock_db, mock_redis,
        )

        mock_message.answer.assert_called_once()
        assert "не найдена" in mock_message.answer.call_args[0][0].lower()


# ---------------------------------------------------------------------------
# Description sub-flow
# ---------------------------------------------------------------------------


class TestDescriptionSubFlow:
    """Description menu, AI stub, manual input."""

    async def test_menu_shows_options(self, mock_callback: MagicMock) -> None:
        await readiness_description_menu(mock_callback)
        mock_callback.message.edit_text.assert_called_once()
        assert "Описание" in mock_callback.message.edit_text.call_args[0][0]

    async def test_ai_generates_and_charges(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """AI description: checks balance, charges tokens, saves to category."""
        mock_state.get_data = AsyncMock(return_value=_make_state_data())

        # Patches target _COMMON (generate_description_ai lives in _readiness_common)
        token_mock = MagicMock()
        token_mock.get_balance = AsyncMock(return_value=1500)
        token_mock.check_balance = AsyncMock(return_value=True)
        token_mock.charge = AsyncMock()
        token_mock.refund = AsyncMock(return_value=1500)
        token_mock.format_insufficient_msg = MagicMock(return_value="Недостаточно токенов")
        p_token = patch(f"{_COMMON}.TokenService", return_value=token_mock)
        cat_mock = MagicMock()
        cat_mock.update = AsyncMock()
        p_cats = patch(f"{_COMMON}.CategoriesRepository", return_value=cat_mock)
        settings_mock = MagicMock()
        settings_mock.admin_ids = [999]
        p_settings = patch(f"{_COMMON}.get_settings", return_value=settings_mock)
        # Mock show_check on the config (closure calls cfg.show_check)
        mock_show, orig = _mock_cfg_show_check()
        p_desc = patch(f"{_COMMON}.DescriptionService")
        mock_orchestrator = MagicMock()

        try:
            with p_token, p_cats, p_settings, p_desc as desc_cls:
                desc_cls.return_value.generate = AsyncMock(
                    return_value=MagicMock(content="Generated description"),
                )
                await readiness_description_ai(
                    mock_callback, mock_state, user, mock_db, mock_redis,
                    mock_orchestrator,
                )
        finally:
            object.__setattr__(_CFG, "show_check", orig)

        token_mock.check_balance.assert_called_once()
        token_mock.charge.assert_called_once()
        cat_mock.update.assert_called_once()
        mock_show.assert_called_once()

    async def test_ai_insufficient_balance(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """AI description with insufficient balance -> show_alert."""
        mock_state.get_data = AsyncMock(return_value=_make_state_data())

        # Patches target _COMMON
        token_mock = MagicMock()
        token_mock.get_balance = AsyncMock(return_value=5)
        token_mock.check_balance = AsyncMock(return_value=False)
        token_mock.format_insufficient_msg = MagicMock(return_value="Недостаточно токенов")
        p_token = patch(f"{_COMMON}.TokenService", return_value=token_mock)
        settings_mock = MagicMock()
        settings_mock.admin_ids = [999]
        p_settings = patch(f"{_COMMON}.get_settings", return_value=settings_mock)
        mock_orchestrator = MagicMock()

        with p_token, p_settings:
            await readiness_description_ai(
                mock_callback, mock_state, user, mock_db, mock_redis,
                mock_orchestrator,
            )

        mock_callback.answer.assert_called_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True

    async def test_ai_save_fails_refunds(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """If category update returns None, tokens are refunded (debit-first)."""
        mock_state.get_data = AsyncMock(return_value=_make_state_data())

        # Patches target _COMMON
        token_mock = MagicMock()
        token_mock.get_balance = AsyncMock(return_value=1500)
        token_mock.check_balance = AsyncMock(return_value=True)
        token_mock.charge = AsyncMock()
        token_mock.refund = AsyncMock(return_value=1500)
        token_mock.format_insufficient_msg = MagicMock(return_value="Недостаточно токенов")
        p_token = patch(f"{_COMMON}.TokenService", return_value=token_mock)
        cat_mock = MagicMock()
        cat_mock.update = AsyncMock(return_value=None)
        p_cats = patch(f"{_COMMON}.CategoriesRepository", return_value=cat_mock)
        settings_mock = MagicMock()
        settings_mock.admin_ids = [999]
        p_settings = patch(f"{_COMMON}.get_settings", return_value=settings_mock)
        p_desc = patch(f"{_COMMON}.DescriptionService")
        mock_orchestrator = MagicMock()

        with p_token, p_cats, p_settings, p_desc as desc_cls:
            desc_cls.return_value.generate = AsyncMock(
                return_value=MagicMock(content="Generated description"),
            )
            await readiness_description_ai(
                mock_callback, mock_state, user, mock_db, mock_redis,
                mock_orchestrator,
            )

        # Debit-first: charge called, then refund on save failure
        token_mock.charge.assert_called_once()
        token_mock.refund.assert_called_once()
        # Error message shown via edit_text (answer() called early without text)
        mock_callback.message.edit_text.assert_called()
        last_edit = mock_callback.message.edit_text.call_args[0][0]
        assert "возвращены" in last_edit

    async def test_manual_start_sets_state(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        await readiness_description_manual_start(mock_callback, mock_state)
        mock_callback.message.edit_text.assert_called_once()
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.readiness_description)

    async def test_manual_input_saves(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Valid manual description -> saves to category."""
        mock_message.text = "A" * 50  # 50 chars, valid
        mock_state.get_data = AsyncMock(return_value=_make_state_data())

        p_cats, cat_mock = _patch_cats_repo(module=_COMMON)
        mock_show, orig = _mock_cfg_show_check_msg()

        try:
            with p_cats:
                await readiness_description_manual_input(
                    mock_message, mock_state, user, mock_db, mock_redis,
                )
        finally:
            object.__setattr__(_CFG, "show_check_msg", orig)

        cat_mock.update.assert_called_once()
        # Check the description was passed
        update_arg = cat_mock.update.call_args[0][1]
        assert update_arg.description == "A" * 50
        mock_show.assert_called_once()

    async def test_manual_input_too_short(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Description < 10 chars -> validation error."""
        mock_message.text = "Short"

        await readiness_description_manual_input(
            mock_message, mock_state, user, mock_db, mock_redis,
        )

        mock_message.answer.assert_called_once()
        assert "10" in mock_message.answer.call_args[0][0]

    async def test_manual_input_too_long(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Description > 2000 chars -> validation error."""
        mock_message.text = "A" * 2001

        await readiness_description_manual_input(
            mock_message, mock_state, user, mock_db, mock_redis,
        )

        mock_message.answer.assert_called_once()
        assert "2000" in mock_message.answer.call_args[0][0]


# ---------------------------------------------------------------------------
# Prices sub-flow
# ---------------------------------------------------------------------------


class TestPricesSubFlow:
    """Prices menu, text input, Excel upload."""

    async def test_menu_shows_options(self, mock_callback: MagicMock) -> None:
        await readiness_prices_menu(mock_callback)
        mock_callback.message.edit_text.assert_called_once()
        assert "прайс" in mock_callback.message.edit_text.call_args[0][0].lower()

    async def test_text_start_sets_state(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        await readiness_prices_text_start(mock_callback, mock_state)
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.readiness_prices)

    async def test_text_input_saves(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Valid price text -> saves to category."""
        mock_message.text = "Кухня Прага — 120 000 руб.\nШкаф-купе — 45 000 руб."
        mock_state.get_data = AsyncMock(return_value=_make_state_data())

        # Prices handler is in readiness.py, calls show_readiness_check_msg directly
        p_cats, cat_mock = _patch_cats_repo()
        p_show = patch(f"{_MODULE}.show_readiness_check_msg", new_callable=AsyncMock)

        with p_cats, p_show as mock_show:
            await readiness_prices_text_input(
                mock_message, mock_state, user, mock_db, mock_redis,
            )

        cat_mock.update.assert_called_once()
        update_arg = cat_mock.update.call_args[0][1]
        assert "Кухня Прага" in update_arg.prices
        mock_show.assert_called_once()

    async def test_text_input_empty(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Empty text -> error."""
        mock_message.text = ""

        await readiness_prices_text_input(
            mock_message, mock_state, user, mock_db, mock_redis,
        )

        mock_message.answer.assert_called_once()

    async def test_text_input_too_long(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Text > 50000 chars -> error."""
        mock_message.text = "A" * 50_001

        await readiness_prices_text_input(
            mock_message, mock_state, user, mock_db, mock_redis,
        )

        mock_message.answer.assert_called_once()
        assert "50 000" in mock_message.answer.call_args[0][0]

    async def test_text_input_too_many_rows(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """More than 1000 rows -> error."""
        mock_message.text = "\n".join(f"Item {i} — {i} руб." for i in range(1001))

        await readiness_prices_text_input(
            mock_message, mock_state, user, mock_db, mock_redis,
        )

        mock_message.answer.assert_called_once()
        assert "1000" in mock_message.answer.call_args[0][0]

    async def test_excel_start_sets_state(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        await readiness_prices_excel_start(mock_callback, mock_state)
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.readiness_prices)

    async def test_excel_wrong_extension(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Non-xlsx file -> error."""
        mock_message.document = MagicMock()
        mock_message.document.file_name = "prices.csv"
        mock_message.document.file_size = 100

        await readiness_prices_excel_file(
            mock_message, mock_state, user, mock_db, mock_redis,
        )

        mock_message.answer.assert_called_once()
        assert ".xlsx" in mock_message.answer.call_args[0][0]

    async def test_excel_too_large(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Excel > 5 MB -> error."""
        mock_message.document = MagicMock()
        mock_message.document.file_name = "prices.xlsx"
        mock_message.document.file_size = 6 * 1024 * 1024

        await readiness_prices_excel_file(
            mock_message, mock_state, user, mock_db, mock_redis,
        )

        mock_message.answer.assert_called_once()
        assert "5 МБ" in mock_message.answer.call_args[0][0]

    async def test_excel_valid_parsed(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Valid Excel -> parses and saves prices."""
        from io import BytesIO

        mock_message.document = MagicMock()
        mock_message.document.file_name = "prices.xlsx"
        mock_message.document.file_size = 1000
        mock_message.bot = MagicMock()
        mock_message.bot.download = AsyncMock(return_value=BytesIO(b"fake"))

        mock_state.get_data = AsyncMock(return_value=_make_state_data())

        parsed_rows = ["Кухня — 120000", "Шкаф — 45000"]
        p_parse = patch(
            "routers.categories.prices.parse_excel_rows",
            return_value=parsed_rows,
        )
        # Prices handler is in readiness.py
        p_cats, cat_mock = _patch_cats_repo()
        p_show = patch(f"{_MODULE}.show_readiness_check_msg", new_callable=AsyncMock)

        with p_parse, p_cats, p_show as mock_show:
            await readiness_prices_excel_file(
                mock_message, mock_state, user, mock_db, mock_redis,
            )

        cat_mock.update.assert_called_once()
        update_arg = cat_mock.update.call_args[0][1]
        assert "Кухня" in update_arg.prices
        mock_show.assert_called_once()

    async def test_excel_parse_error(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Excel parse returns error string -> show error."""
        from io import BytesIO

        mock_message.document = MagicMock()
        mock_message.document.file_name = "prices.xlsx"
        mock_message.document.file_size = 1000
        mock_message.bot = MagicMock()
        mock_message.bot.download = AsyncMock(return_value=BytesIO(b"fake"))

        p_parse = patch(
            "routers.categories.prices.parse_excel_rows",
            return_value="empty",
        )

        with p_parse:
            await readiness_prices_excel_file(
                mock_message, mock_state, user, mock_db, mock_redis,
            )

        mock_message.answer.assert_called_once()


# ---------------------------------------------------------------------------
# Images sub-flow
# ---------------------------------------------------------------------------


class TestImagesSubFlow:
    """Image count selection."""

    async def test_menu_shows_current_count(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={"image_count": 6})
        await readiness_images_menu(mock_callback, mock_state)
        mock_callback.message.edit_text.assert_called_once()
        assert "6" in mock_callback.message.edit_text.call_args[0][0]

    async def test_menu_default_count(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        """Default image count is 4."""
        mock_state.get_data = AsyncMock(return_value={})
        await readiness_images_menu(mock_callback, mock_state)
        assert "4" in mock_callback.message.edit_text.call_args[0][0]

    async def test_select_updates_state(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Selecting image count updates state and returns to checklist."""
        mock_callback.data = "pipeline:readiness:images:6"
        mock_state.get_data = AsyncMock(return_value=_make_state_data())

        # Images handler is in readiness.py, calls show_readiness_check directly
        p_show = patch(f"{_MODULE}.show_readiness_check", new_callable=AsyncMock)

        with p_show as mock_show:
            await readiness_images_select(
                mock_callback, mock_state, user, mock_db, mock_redis,
            )

        mock_state.update_data.assert_called_with(image_count=6)
        mock_show.assert_called_once()

    async def test_select_zero_images(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """0 images is a valid selection."""
        mock_callback.data = "pipeline:readiness:images:0"

        p_show = patch(f"{_MODULE}.show_readiness_check", new_callable=AsyncMock)

        with p_show:
            await readiness_images_select(
                mock_callback, mock_state, user, mock_db, mock_redis,
            )

        mock_state.update_data.assert_called_with(image_count=0)

    async def test_select_invalid_count_rejected(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Invalid image count (e.g. 99) is rejected with show_alert."""
        mock_callback.data = "pipeline:readiness:images:99"

        await readiness_images_select(
            mock_callback, mock_state, user, mock_db, mock_redis,
        )

        mock_state.update_data.assert_not_called()
        mock_callback.answer.assert_called_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# Navigation: back, done
# ---------------------------------------------------------------------------


class TestNavigation:
    """Back to checklist, done (keywords blocker)."""

    async def test_back_returns_to_checklist(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        # Closure calls cfg.show_check -- mock it on the config
        mock_show, orig = _mock_cfg_show_check()
        try:
            await readiness_back(mock_callback, mock_state, user, mock_db, mock_redis)
        finally:
            object.__setattr__(_CFG, "show_check", orig)

        mock_show.assert_called_once()
        mock_callback.answer.assert_called_once()

    async def test_done_with_keywords_proceeds(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Keywords present -> proceed to step 5."""
        report = _make_report(has_keywords=True)
        mock_state.get_data = AsyncMock(return_value=_make_state_data())

        p_readiness, _ = _patch_readiness(report)
        p_token, _ = _patch_token_svc()
        p_settings = _patch_settings()
        p_confirm = patch(
            "routers.publishing.pipeline.generation.show_confirm",
            new_callable=AsyncMock,
        )

        with p_readiness, p_token, p_settings, p_confirm as mock_confirm:
            await readiness_done(mock_callback, mock_state, user, mock_db, mock_redis)

        mock_confirm.assert_called_once()

    async def test_done_without_keywords_blocks(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """No keywords -> show_alert, do NOT proceed."""
        report = _make_report(has_keywords=False)
        mock_state.get_data = AsyncMock(return_value=_make_state_data())

        p_readiness, _ = _patch_readiness(report)
        p_token, _ = _patch_token_svc()
        p_settings = _patch_settings()

        with p_readiness, p_token, p_settings:
            await readiness_done(mock_callback, mock_state, user, mock_db, mock_redis)

        mock_callback.answer.assert_called()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True
        assert "ключевые фразы" in mock_callback.answer.call_args[0][0].lower()

    async def test_done_no_category(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """No category_id -> show_alert error."""
        mock_state.get_data = AsyncMock(return_value={"project_id": 1})

        await readiness_done(mock_callback, mock_state, user, mock_db, mock_redis)

        mock_callback.answer.assert_called_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# Keywords: configure products validation
# ---------------------------------------------------------------------------


class TestConfigureProductsValidation:
    """_handle_configure_products validates 3-1000 chars, routes to geo state."""

    async def test_products_too_short(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        """Text < 3 chars -> validation error."""
        mock_message.text = "ab"
        await _handle_configure_products(mock_message, mock_state)
        mock_message.answer.assert_called_once()
        assert "3" in mock_message.answer.call_args[0][0]
        mock_state.set_state.assert_not_called()

    async def test_products_too_long(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        """Text > 1000 chars -> validation error."""
        mock_message.text = "x" * 1001
        await _handle_configure_products(mock_message, mock_state)
        mock_message.answer.assert_called_once()
        assert "1000" in mock_message.answer.call_args[0][0]
        mock_state.set_state.assert_not_called()

    async def test_products_valid_transitions_to_geo(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        """Valid products (3-1000 chars) -> state to readiness_keywords_geo."""
        mock_message.text = "кухни на заказ, шкафы-купе"
        await _handle_configure_products(mock_message, mock_state)
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.readiness_keywords_geo)
        mock_state.update_data.assert_called_with(kw_products="кухни на заказ, шкафы-купе")
        mock_message.answer.assert_called_once()
        assert "географи" in mock_message.answer.call_args[0][0].lower()

    async def test_products_boundary_3_chars(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        """Exactly 3 chars is valid."""
        mock_message.text = "SEO"
        await _handle_configure_products(mock_message, mock_state)
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.readiness_keywords_geo)

    async def test_configure_text_routes_to_products(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """kw_mode='configure' in text_input routes to _handle_configure_products."""
        mock_message.text = "кухни на заказ"
        mock_state.get_data = AsyncMock(
            return_value=_make_state_data(kw_mode="configure"),
        )
        # _handle_configure_products is called internally, verify its effect
        await readiness_keywords_text_input(
            mock_message, mock_state, user, mock_db, mock_redis,
        )
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.readiness_keywords_geo)


# ---------------------------------------------------------------------------
# Keywords: geo input validation
# ---------------------------------------------------------------------------


class TestGeoInputValidation:
    """readiness_keywords_geo_input validates 2-200 chars."""

    async def test_geo_too_short(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        """Geo < 2 chars -> validation error."""
        mock_message.text = "М"
        await readiness_keywords_geo_input(mock_message, mock_state)
        mock_message.answer.assert_called_once()
        assert "2" in mock_message.answer.call_args[0][0]
        mock_state.set_state.assert_not_called()

    async def test_geo_too_long(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        """Geo > 200 chars -> validation error."""
        mock_message.text = "А" * 201
        await readiness_keywords_geo_input(mock_message, mock_state)
        mock_message.answer.assert_called_once()
        mock_state.set_state.assert_not_called()

    async def test_geo_valid_transitions_to_qty(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        """Valid geo -> state to readiness_keywords_qty, shows qty keyboard."""
        mock_message.text = "Москва"
        await readiness_keywords_geo_input(mock_message, mock_state)
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.readiness_keywords_qty)
        mock_state.update_data.assert_called_with(kw_geography="Москва")
        mock_message.answer.assert_called_once()
        assert "фраз" in mock_message.answer.call_args[0][0].lower()


# ---------------------------------------------------------------------------
# Keywords: city select handler
# ---------------------------------------------------------------------------


class TestCitySelectHandler:
    """readiness_keywords_city_select: quick city buttons for auto/configure paths."""

    async def test_auto_city_goes_to_confirm(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
    ) -> None:
        """Auto mode + city selected -> shows confirm (100 phrases)."""
        mock_callback.data = "pipeline:readiness:keywords:city:Москва"
        mock_state.get_data = AsyncMock(
            return_value=_make_state_data(kw_mode="auto", kw_products="Мебель"),
        )
        p_projects, proj_mock = _patch_projects_repo(module=_COMMON)
        p_settings = _patch_settings(module=_COMMON)
        p_token, _ = _patch_token_svc(balance=500, module=_COMMON)

        with p_projects, p_settings, p_token:
            await readiness_keywords_city_select(mock_callback, mock_state, user, mock_db)

        mock_state.set_state.assert_called_with(ArticlePipelineFSM.readiness_keywords_qty)
        update_kwargs = mock_state.update_data.call_args.kwargs
        assert update_kwargs["kw_geography"] == "Москва"
        assert update_kwargs["kw_quantity"] == 100
        # Should save city to project
        proj_mock.update.assert_called_once()
        # Confirm text shown
        edit_text = mock_callback.message.edit_text.call_args[0][0]
        assert "Автоподбор" in edit_text

    async def test_configure_city_goes_to_qty(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
    ) -> None:
        """Configure mode + city selected -> shows qty selection."""
        mock_callback.data = "pipeline:readiness:keywords:city:СПб"
        mock_state.get_data = AsyncMock(
            return_value=_make_state_data(kw_mode="configure", kw_products="Мебель"),
        )
        p_projects, _ = _patch_projects_repo(module=_COMMON)

        with p_projects:
            await readiness_keywords_city_select(mock_callback, mock_state, user, mock_db)

        mock_state.set_state.assert_called_with(ArticlePipelineFSM.readiness_keywords_qty)
        mock_state.update_data.assert_called_with(kw_geography="СПб")
        edit_text = mock_callback.message.edit_text.call_args[0][0]
        assert "фраз" in edit_text.lower()


# ---------------------------------------------------------------------------
# Keywords: qty select handler
# ---------------------------------------------------------------------------


class TestQtySelectHandler:
    """readiness_keywords_qty_select: parse quantity, compute cost, show confirm."""

    async def test_qty_50_shows_confirm(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
    ) -> None:
        """Select 50 phrases -> compute cost=50, show confirm."""
        mock_callback.data = "pipeline:readiness:keywords:qty_50"
        mock_state.get_data = AsyncMock(
            return_value=_make_state_data(kw_products="Мебель", kw_geography="Москва"),
        )
        p_settings = _patch_settings(module=_COMMON)
        p_token, _ = _patch_token_svc(balance=500, module=_COMMON)

        with p_settings, p_token:
            await readiness_keywords_qty_select(mock_callback, mock_state, user, mock_db)

        update_kwargs = mock_state.update_data.call_args.kwargs
        assert update_kwargs["kw_quantity"] == 50
        assert update_kwargs["kw_cost"] == 50
        edit_text = mock_callback.message.edit_text.call_args[0][0]
        assert "50" in edit_text
        assert "Мебель" in edit_text

    async def test_qty_200_shows_confirm(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
    ) -> None:
        """Select 200 phrases -> cost=200."""
        mock_callback.data = "pipeline:readiness:keywords:qty_200"
        mock_state.get_data = AsyncMock(
            return_value=_make_state_data(kw_products="SEO", kw_geography="Россия"),
        )
        p_settings = _patch_settings(module=_COMMON)
        p_token, _ = _patch_token_svc(balance=1000, module=_COMMON)

        with p_settings, p_token:
            await readiness_keywords_qty_select(mock_callback, mock_state, user, mock_db)

        assert mock_state.update_data.call_args.kwargs["kw_quantity"] == 200

    async def test_qty_invalid_rejected(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
    ) -> None:
        """Invalid quantity (e.g. 999) -> show_alert error."""
        mock_callback.data = "pipeline:readiness:keywords:qty_999"
        await readiness_keywords_qty_select(mock_callback, mock_state, user, mock_db)
        mock_callback.answer.assert_called_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True
        mock_state.update_data.assert_not_called()


# ---------------------------------------------------------------------------
# Keywords: confirm handler (E01 balance check + charge)
# ---------------------------------------------------------------------------


class TestConfirmHandler:
    """readiness_keywords_confirm: E01 balance check, charge, run generation."""

    async def test_confirm_insufficient_balance_e01(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """E01: insufficient balance -> show_alert, no charge."""
        mock_state.get_data = AsyncMock(
            return_value=_make_state_data(
                kw_cost=100, kw_quantity=100, kw_products="Test", kw_geography="Москва",
            ),
        )
        p_settings = _patch_settings(module=_COMMON)
        p_token, token_mock = _patch_token_svc(balance=50, has_balance=False, module=_COMMON)

        with p_settings, p_token:
            await readiness_keywords_confirm(
                mock_callback, mock_state, user, mock_db, mock_redis,
                ai_orchestrator=AsyncMock(), dataforseo_client=AsyncMock(),
            )

        token_mock.charge.assert_not_called()
        mock_callback.answer.assert_called_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True

    async def test_confirm_charges_and_starts_generation(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Sufficient balance -> charge tokens, set generating state, call pipeline."""
        mock_state.get_data = AsyncMock(
            return_value=_make_state_data(
                kw_cost=100, kw_quantity=100, kw_products="Test", kw_geography="Москва",
            ),
        )
        p_settings = _patch_settings(module=_COMMON)
        p_token, token_mock = _patch_token_svc(balance=500, has_balance=True, module=_COMMON)
        # Patch run_keyword_generation in _readiness_common (called by the closure)
        p_pipeline = patch(f"{_COMMON}.run_keyword_generation", new_callable=AsyncMock)

        with p_settings, p_token, p_pipeline as mock_pipeline:
            await readiness_keywords_confirm(
                mock_callback, mock_state, user, mock_db, mock_redis,
                ai_orchestrator=AsyncMock(), dataforseo_client=AsyncMock(),
            )

        token_mock.charge.assert_called_once()
        charge_kwargs = token_mock.charge.call_args.kwargs
        assert charge_kwargs["amount"] == 100
        assert charge_kwargs["operation_type"] == "keywords"
        mock_state.set_state.assert_called_with(
            ArticlePipelineFSM.readiness_keywords_generating,
        )
        mock_pipeline.assert_awaited_once()

    async def test_confirm_missing_data_shows_alert(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Missing category_id or cost -> show_alert error."""
        mock_state.get_data = AsyncMock(return_value={"project_id": 1})
        await readiness_keywords_confirm(
            mock_callback, mock_state, user, mock_db, mock_redis,
            ai_orchestrator=AsyncMock(), dataforseo_client=AsyncMock(),
        )
        mock_callback.answer.assert_called_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# Keywords: cancel handler
# ---------------------------------------------------------------------------


class TestCancelHandler:
    """readiness_keywords_cancel returns to checklist."""

    async def test_cancel_returns_to_checklist(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        # Closure calls cfg.show_check -- mock it on the config
        mock_show, orig = _mock_cfg_show_check()
        try:
            await readiness_keywords_cancel(
                mock_callback, mock_state, user, mock_db, mock_redis,
            )
        finally:
            object.__setattr__(_CFG, "show_check", orig)
        mock_show.assert_called_once()
        mock_callback.answer.assert_called_once()


# ---------------------------------------------------------------------------
# Keywords: generation pipeline
# ---------------------------------------------------------------------------


class TestRunPipelineKeywordGeneration:
    """_run_pipeline_keyword_generation: fetch->cluster->enrich->save, refund on error."""

    _SENTINEL = object()

    def _make_kw_service_mock(
        self,
        raw_phrases: list[str] | None | object = _SENTINEL,
        clusters: list[dict[str, Any]] | None = None,
        enriched: list[dict[str, Any]] | None = None,
    ) -> MagicMock:
        """Create a mock KeywordService with configurable return values."""
        kw_mock = MagicMock()
        kw_mock.fetch_raw_phrases = AsyncMock(
            return_value=(
                ["фраза 1", "фраза 2"] if raw_phrases is self._SENTINEL else raw_phrases
            ),
        )
        kw_mock.cluster_phrases = AsyncMock(
            return_value=clusters or [
                {"cluster_name": "C1", "main_phrase": "фраза 1",
                 "phrases": [{"phrase": "фраза 1"}]},
            ],
        )
        kw_mock.generate_clusters_direct = AsyncMock(
            return_value=clusters or [
                {"cluster_name": "C1", "main_phrase": "фраза 1",
                 "phrases": [{"phrase": "фраза 1"}]},
            ],
        )
        kw_mock.enrich_clusters = AsyncMock(
            return_value=enriched or [
                {"cluster_name": "C1", "main_phrase": "фраза 1",
                 "phrases": [{"phrase": "фраза 1", "volume": 100}],
                 "total_volume": 100},
            ],
        )
        kw_mock.filter_low_quality = MagicMock(side_effect=lambda x: x)
        return kw_mock

    async def test_success_saves_keywords_and_returns_to_checklist(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Successful generation: fetch->cluster->enrich->save->checklist."""
        kw_mock = self._make_kw_service_mock()
        cat_obj = MagicMock()
        cat_obj.keywords = []
        p_kw = patch(f"{_COMMON}.KeywordService", return_value=kw_mock)
        cat_repo_mock = MagicMock()
        cat_repo_mock.get_by_id = AsyncMock(return_value=cat_obj)
        cat_repo_mock.update_keywords = AsyncMock()
        p_cats = patch(f"{_COMMON}.CategoriesRepository", return_value=cat_repo_mock)
        mock_show = AsyncMock()
        token_mock = MagicMock()
        token_mock.refund = AsyncMock()
        # Mock msg.bot.send_message
        mock_callback.message.bot = MagicMock()
        mock_callback.message.bot.send_message = AsyncMock()
        mock_callback.message.delete = AsyncMock()

        with p_kw, p_cats:
            await _run_pipeline_keyword_generation(
                callback=mock_callback, state=mock_state, user=user,
                db=mock_db, redis=mock_redis,
                category_id=10, project_id=1,
                products="мебель", geography="Москва",
                quantity=100, cost=100,
                token_service=token_mock,
                ai_orchestrator=AsyncMock(), dataforseo_client=AsyncMock(),
                log_prefix="pipeline.readiness",
                readiness_state=ArticlePipelineFSM.readiness_check,
                on_success=mock_show,
            )

        kw_mock.fetch_raw_phrases.assert_awaited_once()
        kw_mock.cluster_phrases.assert_awaited_once()
        kw_mock.enrich_clusters.assert_awaited_once()
        cat_repo_mock.update_keywords.assert_called_once()
        # Tokens NOT refunded on success
        token_mock.refund.assert_not_called()
        # Checklist shown
        mock_show.assert_awaited_once()

    async def test_dataforseo_empty_falls_back_to_direct(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """DataForSEO returns empty -> generate_clusters_direct called instead."""
        kw_mock = self._make_kw_service_mock(raw_phrases=[])
        cat_obj = MagicMock()
        cat_obj.keywords = []
        p_kw = patch(f"{_COMMON}.KeywordService", return_value=kw_mock)
        cat_repo_mock = MagicMock()
        cat_repo_mock.get_by_id = AsyncMock(return_value=cat_obj)
        cat_repo_mock.update_keywords = AsyncMock()
        p_cats = patch(f"{_COMMON}.CategoriesRepository", return_value=cat_repo_mock)
        mock_callback.message.bot = MagicMock()
        mock_callback.message.bot.send_message = AsyncMock()
        mock_callback.message.delete = AsyncMock()

        with p_kw, p_cats:
            await _run_pipeline_keyword_generation(
                callback=mock_callback, state=mock_state, user=user,
                db=mock_db, redis=mock_redis,
                category_id=10, project_id=1,
                products="мебель", geography="Москва",
                quantity=100, cost=100,
                token_service=MagicMock(refund=AsyncMock()),
                ai_orchestrator=AsyncMock(), dataforseo_client=AsyncMock(),
                log_prefix="pipeline.readiness",
                readiness_state=ArticlePipelineFSM.readiness_check,
                on_success=AsyncMock(),
            )

        kw_mock.cluster_phrases.assert_not_awaited()
        kw_mock.generate_clusters_direct.assert_awaited_once()

    async def test_error_refunds_tokens(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Generation error -> refund tokens, show error, return to readiness_check."""
        kw_mock = MagicMock()
        kw_mock.fetch_raw_phrases = AsyncMock(side_effect=RuntimeError("API down"))
        p_kw = patch(f"{_COMMON}.KeywordService", return_value=kw_mock)
        token_mock = MagicMock()
        token_mock.refund = AsyncMock()
        mock_callback.message.bot = MagicMock()
        mock_callback.message.bot.send_message = AsyncMock()
        mock_callback.message.delete = AsyncMock()

        with p_kw:
            await _run_pipeline_keyword_generation(
                callback=mock_callback, state=mock_state, user=user,
                db=mock_db, redis=mock_redis,
                category_id=10, project_id=1,
                products="мебель", geography="Москва",
                quantity=100, cost=100,
                token_service=token_mock,
                ai_orchestrator=AsyncMock(), dataforseo_client=AsyncMock(),
                log_prefix="pipeline.readiness",
                readiness_state=ArticlePipelineFSM.readiness_check,
                on_success=AsyncMock(),
            )

        token_mock.refund.assert_awaited_once()
        refund_kwargs = token_mock.refund.call_args.kwargs
        assert refund_kwargs["user_id"] == user.id
        assert refund_kwargs["amount"] == 100
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.readiness_check)

    async def test_merges_with_existing_keywords(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Existing keywords in category are preserved (MERGE, not overwrite)."""
        existing_kw = [
            {"cluster_name": "Old", "main_phrase": "old phrase",
             "phrases": [{"phrase": "old"}]},
        ]
        new_enriched = [
            {"cluster_name": "New", "main_phrase": "new phrase",
             "phrases": [{"phrase": "new", "volume": 50}], "total_volume": 50},
        ]
        kw_mock = self._make_kw_service_mock(enriched=new_enriched)
        cat_obj = MagicMock()
        cat_obj.keywords = existing_kw
        p_kw = patch(f"{_COMMON}.KeywordService", return_value=kw_mock)
        cat_repo_mock = MagicMock()
        cat_repo_mock.get_by_id = AsyncMock(return_value=cat_obj)
        cat_repo_mock.update_keywords = AsyncMock()
        p_cats = patch(f"{_COMMON}.CategoriesRepository", return_value=cat_repo_mock)
        mock_callback.message.bot = MagicMock()
        mock_callback.message.bot.send_message = AsyncMock()
        mock_callback.message.delete = AsyncMock()

        with p_kw, p_cats:
            await _run_pipeline_keyword_generation(
                callback=mock_callback, state=mock_state, user=user,
                db=mock_db, redis=mock_redis,
                category_id=10, project_id=1,
                products="мебель", geography="Москва",
                quantity=100, cost=100,
                token_service=MagicMock(refund=AsyncMock()),
                ai_orchestrator=AsyncMock(), dataforseo_client=AsyncMock(),
                log_prefix="pipeline.readiness",
                readiness_state=ArticlePipelineFSM.readiness_check,
                on_success=AsyncMock(),
            )

        # update_keywords called with merged list: existing + new
        merged = cat_repo_mock.update_keywords.call_args[0][1]
        assert len(merged) == 2
        assert merged[0]["cluster_name"] == "Old"
        assert merged[1]["cluster_name"] == "New"
