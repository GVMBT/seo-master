"""Tests for routers/publishing/preview.py — ArticlePublishFSM flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import Message

from db.models import (
    ArticlePreview,
    Category,
    PlatformConnection,
    Project,
    User,
)
from routers.publishing.preview import (
    ArticlePublishFSM,
    _format_preview_text,
    _get_article_clusters,
    cb_article_cancel,
    cb_article_confirm,
    cb_article_publish,
    cb_article_publishing_guard,
    cb_article_regen,
    cb_article_regen_guard,
    cb_article_start,
    cb_article_start_with_conn,
)

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _user(balance: int = 1500) -> User:
    return User(id=1, balance=balance)


def _project(user_id: int = 1) -> Project:
    return Project(id=1, user_id=user_id, name="Test", company_name="Co", specialization="SEO")


def _category(keywords: list | None = None) -> Category:
    kw = keywords if keywords is not None else [
        {
            "cluster_name": "Test cluster",
            "cluster_type": "article",
            "main_phrase": "test phrase",
            "total_volume": 1000,
            "avg_difficulty": 30,
            "phrases": [{"phrase": "test phrase", "volume": 1000}],
        },
    ]
    return Category(id=10, project_id=1, name="Test Category", keywords=kw)


def _connection(conn_id: int = 5, platform: str = "wordpress") -> PlatformConnection:
    return PlatformConnection(
        id=conn_id, project_id=1, platform_type=platform,
        status="active", credentials={}, identifier="test.com",
    )


def _preview(
    preview_id: int = 1,
    regen_count: int = 0,
    status: str = "draft",
    telegraph_url: str | None = "https://telegra.ph/test",
) -> ArticlePreview:
    return ArticlePreview(
        id=preview_id,
        user_id=1,
        project_id=1,
        category_id=10,
        connection_id=5,
        title="Test Article",
        keyword="test phrase",
        word_count=2000,
        images_count=4,
        tokens_charged=320,
        regeneration_count=regen_count,
        status=status,
        telegraph_url=telegraph_url,
        content_html="<h1>Test</h1><p>Content</p>",
    )


def _callback(data: str) -> MagicMock:
    """Create mock CallbackQuery with proper Message spec."""
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock(id=1)
    cb.answer = AsyncMock()
    msg = MagicMock(spec=Message)
    msg.edit_text = AsyncMock()
    msg.edit_reply_markup = AsyncMock()
    msg.answer = AsyncMock()
    cb.message = msg
    cb.bot = MagicMock()
    cb.bot.session = MagicMock()
    cb.bot.session._session = MagicMock()
    return cb


def _state(**data: object) -> MagicMock:
    """Create mock FSMContext."""
    state = MagicMock()
    state.get_data = AsyncMock(return_value=dict(data))
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    state.get_state = AsyncMock(return_value=None)
    return state


def _rl() -> MagicMock:
    """Create mock RateLimiter."""
    rl = MagicMock()
    rl.check = AsyncMock()
    rl.check_batch = AsyncMock()
    return rl


def _ai_deps() -> tuple[MagicMock, MagicMock, MagicMock]:
    """Dummy AI pipeline deps: (ai_orchestrator, image_storage, http_client)."""
    return MagicMock(), MagicMock(), MagicMock()


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


def test_get_article_clusters_empty():
    assert _get_article_clusters([]) == []


def test_get_article_clusters_cluster_format():
    kw = [
        {"cluster_name": "c1", "cluster_type": "article", "main_phrase": "a"},
        {"cluster_name": "c2", "cluster_type": "product_page", "main_phrase": "b"},
    ]
    result = _get_article_clusters(kw)
    assert len(result) == 1
    assert result[0]["main_phrase"] == "a"


def test_get_article_clusters_legacy_format():
    kw = [{"phrase": "test", "volume": 100}]
    result = _get_article_clusters(kw)
    assert len(result) == 1


def test_format_preview_text_with_telegraph():
    preview = _preview()
    text = _format_preview_text(preview, 320)
    assert "Test Article" in text
    assert "test phrase" in text
    assert "telegra.ph" in text
    assert "320" in text


def test_format_preview_text_without_telegraph_e05():
    preview = _preview(telegraph_url=None)
    text = _format_preview_text(preview, 320)
    assert "Test Article" in text
    assert "Content" in text  # fallback snippet


def test_format_preview_text_no_content():
    preview = ArticlePreview(
        id=1, user_id=1, project_id=1, category_id=10,
        title=None, keyword=None, telegraph_url=None, content_html=None,
    )
    text = _format_preview_text(preview, 100)
    assert "100" in text


# ---------------------------------------------------------------------------
# cb_article_start
# ---------------------------------------------------------------------------


@patch("routers.publishing.preview.quick_wp_choice_kb")
@patch("routers.publishing.preview.ConnectionsRepository")
@patch("routers.publishing.preview.CategoriesRepository")
@patch("routers.publishing.preview.ProjectsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_start_ownership_check(
    mock_guard, mock_proj_cls, mock_cat_cls, mock_conn_cls, mock_wp_kb,
):
    """cb_article_start rejects if project.user_id != user.id."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project(user_id=999))

    cb = _callback("category:10:publish:wp")
    await cb_article_start(cb, _user(), MagicMock(), _state())

    cb.answer.assert_awaited_once_with("Категория не найдена.", show_alert=True)


@patch("routers.publishing.preview.ConnectionsRepository")
@patch("routers.publishing.preview.CategoriesRepository")
@patch("routers.publishing.preview.ProjectsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_start_no_keywords_e16(
    mock_guard, mock_proj_cls, mock_cat_cls, mock_conn_cls,
):
    """E16: category with no keywords blocks publish."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category(keywords=[]))
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())

    cb = _callback("category:10:publish:wp")
    await cb_article_start(cb, _user(), MagicMock(), _state())

    cb.answer.assert_awaited_once()
    args = cb.answer.call_args
    assert "нет ключевых фраз" in args[0][0].lower() or "нет ключевых фраз" in str(args)


@patch("routers.publishing.preview.ConnectionsRepository")
@patch("routers.publishing.preview.CategoriesRepository")
@patch("routers.publishing.preview.ProjectsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_start_no_article_clusters_e40(
    mock_guard, mock_proj_cls, mock_cat_cls, mock_conn_cls,
):
    """E40: category with only product_page clusters blocks publish."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    kw = [{"cluster_name": "c1", "cluster_type": "product_page", "main_phrase": "buy"}]
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category(keywords=kw))
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())

    cb = _callback("category:10:publish:wp")
    await cb_article_start(cb, _user(), MagicMock(), _state())

    cb.answer.assert_awaited_once()
    assert "кластер" in cb.answer.call_args[0][0].lower()


@patch("routers.publishing.preview._show_article_confirm", new_callable=AsyncMock)
@patch("routers.publishing.preview.ConnectionsRepository")
@patch("routers.publishing.preview.CategoriesRepository")
@patch("routers.publishing.preview.ProjectsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_start_no_wp_connections(
    mock_guard, mock_proj_cls, mock_cat_cls, mock_conn_cls, mock_confirm,
):
    """No active WP connections -> alert."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_conn_cls.return_value.get_by_project_and_platform = AsyncMock(return_value=[])

    cb = _callback("category:10:publish:wp")
    await cb_article_start(cb, _user(), MagicMock(), _state())

    cb.answer.assert_awaited()
    assert "WordPress" in cb.answer.call_args[0][0]


@patch("routers.publishing.preview._show_article_confirm", new_callable=AsyncMock)
@patch("routers.publishing.preview.ConnectionsRepository")
@patch("routers.publishing.preview.CategoriesRepository")
@patch("routers.publishing.preview.ProjectsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_start_multiple_wp_e28(
    mock_guard, mock_proj_cls, mock_cat_cls, mock_conn_cls, mock_confirm,
):
    """E28: >1 WP connections shows choice keyboard."""
    msg = MagicMock(spec=Message, edit_text=AsyncMock())
    mock_guard.return_value = msg
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_conn_cls.return_value.get_by_project_and_platform = AsyncMock(
        return_value=[_connection(conn_id=5), _connection(conn_id=6)],
    )

    cb = _callback("category:10:publish:wp")
    await cb_article_start(cb, _user(), MagicMock(), _state())

    msg.edit_text.assert_awaited_once()
    assert "подключение" in msg.edit_text.call_args[0][0].lower()
    mock_confirm.assert_not_awaited()


@patch("routers.publishing.preview._show_article_confirm", new_callable=AsyncMock)
@patch("routers.publishing.preview.ConnectionsRepository")
@patch("routers.publishing.preview.CategoriesRepository")
@patch("routers.publishing.preview.ProjectsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_start_single_wp_happy(
    mock_guard, mock_proj_cls, mock_cat_cls, mock_conn_cls, mock_confirm,
):
    """Single WP connection goes straight to confirmation."""
    msg = MagicMock(spec=Message, edit_text=AsyncMock())
    mock_guard.return_value = msg
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_conn_cls.return_value.get_by_project_and_platform = AsyncMock(
        return_value=[_connection()],
    )

    cb = _callback("category:10:publish:wp")
    st = _state()
    await cb_article_start(cb, _user(), MagicMock(), st)

    mock_confirm.assert_awaited_once()


@patch("routers.publishing.preview.TokenService")
@patch("routers.publishing.preview.ConnectionsRepository")
@patch("routers.publishing.preview.CategoriesRepository")
@patch("routers.publishing.preview.ProjectsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_start_insufficient_balance(
    mock_guard, mock_proj_cls, mock_cat_cls, mock_conn_cls, mock_token_cls,
):
    """Insufficient balance shows topup keyboard."""
    msg = MagicMock(spec=Message, edit_text=AsyncMock(), answer=AsyncMock())
    mock_guard.return_value = msg
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_conn_cls.return_value.get_by_project_and_platform = AsyncMock(
        return_value=[_connection()],
    )
    mock_token_cls.return_value.check_balance = AsyncMock(return_value=False)
    mock_token_cls.return_value.get_balance = AsyncMock(return_value=10)
    mock_token_cls.return_value.format_insufficient_msg = MagicMock(return_value="Недостаточно токенов.")

    cb = _callback("category:10:publish:wp")
    st = _state()
    await cb_article_start(cb, _user(balance=10), MagicMock(), st)

    msg.edit_text.assert_awaited_once()
    assert "Недостаточно" in msg.edit_text.call_args[0][0]


# ---------------------------------------------------------------------------
# cb_article_start_with_conn
# ---------------------------------------------------------------------------


@patch("routers.publishing.preview._show_article_confirm", new_callable=AsyncMock)
@patch("routers.publishing.preview.ConnectionsRepository")
@patch("routers.publishing.preview.CategoriesRepository")
@patch("routers.publishing.preview.ProjectsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_start_with_conn_happy(
    mock_guard, mock_proj_cls, mock_cat_cls, mock_conn_cls, mock_confirm,
):
    """cb_article_start_with_conn with valid connection proceeds."""
    msg = MagicMock(spec=Message, edit_text=AsyncMock())
    mock_guard.return_value = msg
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_conn_cls.return_value.get_by_id = AsyncMock(return_value=_connection())

    cb = _callback("category:10:publish:wp:5")
    await cb_article_start_with_conn(cb, _user(), MagicMock(), _state())

    mock_confirm.assert_awaited_once()


@patch("routers.publishing.preview.ConnectionsRepository")
@patch("routers.publishing.preview.CategoriesRepository")
@patch("routers.publishing.preview.ProjectsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_start_with_conn_bad_connection(
    mock_guard, mock_proj_cls, mock_cat_cls, mock_conn_cls,
):
    """Connection not found -> alert."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_conn_cls.return_value.get_by_id = AsyncMock(return_value=None)

    cb = _callback("category:10:publish:wp:99")
    await cb_article_start_with_conn(cb, _user(), MagicMock(), _state())

    cb.answer.assert_awaited_once_with("Подключение не найдено.", show_alert=True)


@patch("routers.publishing.preview.ConnectionsRepository")
@patch("routers.publishing.preview.CategoriesRepository")
@patch("routers.publishing.preview.ProjectsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_start_with_conn_ownership_check(
    mock_guard, mock_proj_cls, mock_cat_cls, mock_conn_cls,
):
    """cb_article_start_with_conn rejects wrong owner."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project(user_id=999))

    cb = _callback("category:10:publish:wp:5")
    await cb_article_start_with_conn(cb, _user(), MagicMock(), _state())

    cb.answer.assert_awaited_once_with("Категория не найдена.", show_alert=True)


# ---------------------------------------------------------------------------
# cb_article_confirm
# ---------------------------------------------------------------------------


@patch("routers.publishing.preview.PreviewService")
@patch("routers.publishing.preview.PreviewsRepository")
@patch("routers.publishing.preview.PublicationsRepository")
@patch("routers.publishing.preview.CategoriesRepository")
@patch("routers.publishing.preview.TokenService")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_confirm_happy(
    mock_guard, mock_token_cls, mock_cat_cls, mock_pub_cls, mock_prev_cls,
    mock_preview_svc_cls,
):
    """Confirm charges tokens and creates preview."""
    msg = MagicMock(spec=Message, edit_text=AsyncMock())
    mock_guard.return_value = msg
    mock_token_cls.return_value.charge = AsyncMock(return_value=1180)

    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_pub_cls.return_value.get_rotation_keyword = AsyncMock(return_value=("test phrase", False))

    # Mock PreviewService.generate_article_content
    mock_preview_svc_cls.return_value.generate_article_content = AsyncMock(
        return_value=MagicMock(
            title="Test Article", content_html="<p>Content</p>",
            word_count=2000, images_count=4, stored_images=[],
        ),
    )

    preview = _preview()
    mock_prev_cls.return_value.create = AsyncMock(return_value=preview)
    mock_prev_cls.return_value.get_by_id = AsyncMock(return_value=preview)
    mock_prev_cls.return_value.update = AsyncMock(return_value=preview)

    cb = _callback("pub:article:confirm")
    st = _state(category_id=10, project_id=1, connection_id=5, cost=320)

    with patch("services.external.telegraph.TelegraphClient") as mock_tg:
        mock_tg_inst = MagicMock()
        mock_tg.return_value = mock_tg_inst
        mock_tg_page = MagicMock()
        mock_tg_page.url = "https://telegra.ph/test"
        mock_tg_page.path = "test"
        mock_tg_inst.create_page = AsyncMock(return_value=mock_tg_page)

        await cb_article_confirm(cb, _user(), MagicMock(), st, _rl(), *_ai_deps())

    # Should charge tokens
    mock_token_cls.return_value.charge.assert_awaited_once()
    # Should set state to preview
    st.set_state.assert_any_call(ArticlePublishFSM.preview)
    # Should create preview
    mock_prev_cls.return_value.create.assert_awaited_once()


@patch("routers.publishing.preview.TokenService")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_confirm_insufficient_balance(mock_guard, mock_token_cls):
    """Confirm with insufficient balance shows topup."""
    from bot.exceptions import InsufficientBalanceError

    msg = MagicMock(spec=Message, edit_text=AsyncMock())
    mock_guard.return_value = msg
    mock_token_cls.return_value.charge = AsyncMock(side_effect=InsufficientBalanceError())
    mock_token_cls.return_value.get_balance = AsyncMock(return_value=10)
    mock_token_cls.return_value.format_insufficient_msg = MagicMock(return_value="Недостаточно токенов.")

    cb = _callback("pub:article:confirm")
    st = _state(category_id=10, project_id=1, connection_id=5, cost=320)

    await cb_article_confirm(cb, _user(balance=10), MagicMock(), st, _rl(), *_ai_deps())

    msg.edit_text.assert_awaited()
    st.clear.assert_awaited()


@patch("routers.publishing.preview.CategoriesRepository")
@patch("routers.publishing.preview.TokenService")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_confirm_no_keyword_refunds(
    mock_guard, mock_token_cls, mock_cat_cls,
):
    """If category not found during generation, refund tokens."""
    msg = MagicMock(spec=Message, edit_text=AsyncMock())
    mock_guard.return_value = msg
    mock_token_cls.return_value.charge = AsyncMock(return_value=1180)
    mock_token_cls.return_value.refund = AsyncMock(return_value=1500)
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=None)

    cb = _callback("pub:article:confirm")
    st = _state(category_id=10, project_id=1, connection_id=5, cost=320)

    await cb_article_confirm(cb, _user(), MagicMock(), st, _rl(), *_ai_deps())

    # Should refund
    mock_token_cls.return_value.refund.assert_awaited_once()
    st.clear.assert_awaited()


@patch("routers.publishing.preview.guard_callback_message")
async def test_article_confirm_session_lost(mock_guard):
    """Missing state data clears FSM and shows alert."""
    mock_guard.return_value = MagicMock(spec=Message, edit_text=AsyncMock())

    cb = _callback("pub:article:confirm")
    st = _state()  # empty state

    await cb_article_confirm(cb, _user(), MagicMock(), st, _rl(), *_ai_deps())

    st.clear.assert_awaited()
    cb.answer.assert_awaited_once()
    assert "потеряны" in cb.answer.call_args[0][0].lower()


# ---------------------------------------------------------------------------
# cb_article_publish
# ---------------------------------------------------------------------------


@patch("routers.publishing.preview.PreviewService")
@patch("routers.publishing.preview.CredentialManager")
@patch("routers.publishing.preview.ConnectionsRepository")
@patch("routers.publishing.preview.get_settings")
@patch("routers.publishing.preview.PublicationsRepository")
@patch("routers.publishing.preview.PreviewsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_publish_success(
    mock_guard, mock_prev_cls, mock_pub_cls, mock_settings,
    mock_conn_cls, mock_cm_cls, mock_preview_svc_cls,
):
    """Publish creates log and clears FSM."""
    msg = MagicMock(spec=Message, edit_text=AsyncMock())
    mock_guard.return_value = msg
    mock_settings.return_value = MagicMock(
        encryption_key=MagicMock(get_secret_value=MagicMock(return_value="testkey")),
    )

    preview = _preview()
    mock_prev_cls.return_value.get_by_id = AsyncMock(return_value=preview)
    mock_prev_cls.return_value.update = AsyncMock()
    mock_pub_cls.return_value.create_log = AsyncMock(return_value=MagicMock())
    mock_conn_cls.return_value.get_by_id = AsyncMock(return_value=_connection())
    mock_preview_svc_cls.return_value.publish_to_wordpress = AsyncMock(
        return_value=MagicMock(success=True, post_url="https://test.com/post-1"),
    )

    cb = _callback("pub:article:publish")
    st = _state(
        preview_id=1, connection_id=5, category_id=10, project_id=1,
        keyword="test phrase", cost=320,
    )

    await cb_article_publish(cb, _user(), MagicMock(), st, *_ai_deps())

    # Should transition to publishing state (E07 guard)
    st.set_state.assert_any_call(ArticlePublishFSM.publishing)
    # Should clear FSM on success
    st.clear.assert_awaited()
    # Should create pub log
    mock_pub_cls.return_value.create_log.assert_awaited_once()
    # Should update preview status
    mock_prev_cls.return_value.update.assert_awaited()
    # Should show success
    assert "успешна" in msg.edit_text.call_args_list[-1][0][0].lower()


@patch("routers.publishing.preview.PreviewsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_publish_expired_preview(mock_guard, mock_prev_cls):
    """Published preview (not draft) shows expiry message."""
    msg = MagicMock(spec=Message, edit_text=AsyncMock())
    mock_guard.return_value = msg

    mock_prev_cls.return_value.get_by_id = AsyncMock(
        return_value=_preview(status="published"),
    )

    cb = _callback("pub:article:publish")
    st = _state(preview_id=1, connection_id=5, category_id=10, project_id=1, cost=320)

    await cb_article_publish(cb, _user(), MagicMock(), st, *_ai_deps())

    st.clear.assert_awaited()
    assert "устарело" in msg.edit_text.call_args[0][0].lower()


@patch("routers.publishing.preview.PreviewsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_publish_missing_preview(mock_guard, mock_prev_cls):
    """No preview_id in state clears FSM."""
    msg = MagicMock(spec=Message, edit_text=AsyncMock())
    mock_guard.return_value = msg

    cb = _callback("pub:article:publish")
    st = _state()  # no preview_id

    await cb_article_publish(cb, _user(), MagicMock(), st, *_ai_deps())

    st.clear.assert_awaited()
    assert "не найдено" in msg.edit_text.call_args[0][0].lower()


# ---------------------------------------------------------------------------
# cb_article_regen
# ---------------------------------------------------------------------------


@patch("routers.publishing.preview.PreviewService")
@patch("routers.publishing.preview.PreviewsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_regen_free(mock_guard, mock_prev_cls, mock_svc_cls):
    """Free regeneration (count < 2) does not charge."""
    msg = MagicMock(spec=Message, edit_text=AsyncMock())
    mock_guard.return_value = msg

    preview = _preview(regen_count=0)
    updated = _preview(regen_count=1)
    mock_prev_cls.return_value.get_by_id = AsyncMock(side_effect=[preview, updated])
    mock_prev_cls.return_value.update = AsyncMock()
    mock_svc_cls.return_value.generate_article_content = AsyncMock(
        return_value=MagicMock(
            title="Regen", content_html="<p>New</p>",
            word_count=2000, images_count=4, stored_images=[],
        ),
    )

    cb = _callback("pub:article:regen")
    st = _state(preview_id=1, cost=320, keyword="test phrase")

    await cb_article_regen(cb, _user(), MagicMock(), st, *_ai_deps())

    # Should transition through regenerating -> preview
    st.set_state.assert_any_call(ArticlePublishFSM.regenerating)
    st.set_state.assert_any_call(ArticlePublishFSM.preview)
    # Should update preview
    mock_prev_cls.return_value.update.assert_awaited_once()


@patch("routers.publishing.preview.PreviewService")
@patch("routers.publishing.preview.TokenService")
@patch("routers.publishing.preview.PreviewsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_regen_paid_e10(mock_guard, mock_prev_cls, mock_token_cls, mock_svc_cls):
    """Paid regen (count >= 2) charges tokens (E10)."""
    msg = MagicMock(spec=Message, edit_text=AsyncMock())
    mock_guard.return_value = msg

    preview = _preview(regen_count=2)
    updated = _preview(regen_count=3)
    mock_prev_cls.return_value.get_by_id = AsyncMock(side_effect=[preview, updated])
    mock_prev_cls.return_value.update = AsyncMock()
    mock_token_cls.return_value.charge = AsyncMock(return_value=860)
    mock_svc_cls.return_value.generate_article_content = AsyncMock(
        return_value=MagicMock(
            title="Regen", content_html="<p>New</p>",
            word_count=2000, images_count=4, stored_images=[],
        ),
    )

    cb = _callback("pub:article:regen")
    st = _state(preview_id=1, cost=320, keyword="test phrase")

    await cb_article_regen(cb, _user(), MagicMock(), st, *_ai_deps())

    mock_token_cls.return_value.charge.assert_awaited_once()


@patch("routers.publishing.preview.TokenService")
@patch("routers.publishing.preview.PreviewsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_regen_paid_insufficient_e10(mock_guard, mock_prev_cls, mock_token_cls):
    """Paid regen with insufficient balance shows alert (E10)."""
    from bot.exceptions import InsufficientBalanceError

    mock_guard.return_value = MagicMock(spec=Message, edit_text=AsyncMock())

    preview = _preview(regen_count=2)
    mock_prev_cls.return_value.get_by_id = AsyncMock(return_value=preview)
    mock_token_cls.return_value.charge = AsyncMock(side_effect=InsufficientBalanceError())
    mock_token_cls.return_value.get_balance = AsyncMock(return_value=10)

    cb = _callback("pub:article:regen")
    st = _state(preview_id=1, cost=320)

    await cb_article_regen(cb, _user(balance=10), MagicMock(), st, *_ai_deps())

    cb.answer.assert_awaited()
    assert "320" in cb.answer.call_args[0][0]


@patch("routers.publishing.preview.PreviewsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_regen_missing_preview(mock_guard, mock_prev_cls):
    """Missing preview_id in state clears FSM."""
    mock_guard.return_value = MagicMock(spec=Message, edit_text=AsyncMock())

    cb = _callback("pub:article:regen")
    st = _state()  # no preview_id

    await cb_article_regen(cb, _user(), MagicMock(), st, *_ai_deps())

    st.clear.assert_awaited()
    cb.answer.assert_awaited_once()


@patch("routers.publishing.preview.PreviewsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_regen_preview_not_found(mock_guard, mock_prev_cls):
    """Preview not found in DB clears FSM."""
    mock_guard.return_value = MagicMock(spec=Message, edit_text=AsyncMock())
    mock_prev_cls.return_value.get_by_id = AsyncMock(return_value=None)

    cb = _callback("pub:article:regen")
    st = _state(preview_id=999)

    await cb_article_regen(cb, _user(), MagicMock(), st, *_ai_deps())

    st.clear.assert_awaited()
    cb.answer.assert_awaited()


# ---------------------------------------------------------------------------
# cb_article_cancel
# ---------------------------------------------------------------------------


@patch("routers.publishing.preview.guard_callback_message")
async def test_article_cancel(mock_guard):
    """Cancel clears state and shows cancel message."""
    msg = MagicMock(spec=Message, edit_text=AsyncMock())
    mock_guard.return_value = msg

    cb = _callback("pub:article:cancel")
    st = _state(category_id=10)

    await cb_article_cancel(cb, st)

    st.clear.assert_awaited()
    msg.edit_text.assert_awaited_once()
    assert "отменена" in msg.edit_text.call_args[0][0].lower()
    cb.answer.assert_awaited()


@patch("routers.publishing.preview.guard_callback_message")
async def test_article_cancel_no_category(mock_guard):
    """Cancel with no category_id falls back to menu:main."""
    msg = MagicMock(spec=Message, edit_text=AsyncMock())
    mock_guard.return_value = msg

    cb = _callback("pub:article:cancel")
    st = _state()

    await cb_article_cancel(cb, st)

    st.clear.assert_awaited()
    msg.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# Guards (E07)
# ---------------------------------------------------------------------------


async def test_publishing_guard_e07():
    """E07: all callbacks during publishing state return alert."""
    cb = _callback("pub:article:confirm")
    await cb_article_publishing_guard(cb)
    cb.answer.assert_awaited_once_with("Публикация в процессе.", show_alert=True)


async def test_regen_guard():
    """All callbacks during regenerating state return alert."""
    cb = _callback("pub:article:publish")
    await cb_article_regen_guard(cb)
    cb.answer.assert_awaited_once_with("Перегенерация в процессе.", show_alert=True)


# ---------------------------------------------------------------------------
# cb_article_confirm: keyword rotation and refund scenarios
# ---------------------------------------------------------------------------


@patch("routers.publishing.preview.PreviewsRepository")
@patch("routers.publishing.preview.PublicationsRepository")
@patch("routers.publishing.preview.CategoriesRepository")
@patch("routers.publishing.preview.TokenService")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_confirm_no_keywords_refunds(
    mock_guard, mock_token_cls, mock_cat_cls, mock_pub_cls, mock_prev_cls,
):
    """No available keywords after charge -> refund."""
    msg = MagicMock(spec=Message, edit_text=AsyncMock())
    mock_guard.return_value = msg
    mock_token_cls.return_value.charge = AsyncMock(return_value=1180)
    mock_token_cls.return_value.refund = AsyncMock(return_value=1500)

    cat = _category()
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=cat)
    mock_pub_cls.return_value.get_rotation_keyword = AsyncMock(return_value=(None, True))

    cb = _callback("pub:article:confirm")
    st = _state(category_id=10, project_id=1, connection_id=5, cost=320)

    await cb_article_confirm(cb, _user(), MagicMock(), st, _rl(), *_ai_deps())

    mock_token_cls.return_value.refund.assert_awaited_once()
    st.clear.assert_awaited()


@patch("routers.publishing.preview.PreviewService")
@patch("routers.publishing.preview.PreviewsRepository")
@patch("routers.publishing.preview.PublicationsRepository")
@patch("routers.publishing.preview.CategoriesRepository")
@patch("routers.publishing.preview.TokenService")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_confirm_preview_create_fails_refunds(
    mock_guard, mock_token_cls, mock_cat_cls, mock_pub_cls, mock_prev_cls,
    mock_preview_svc_cls,
):
    """Preview creation failure -> refund."""
    msg = MagicMock(spec=Message, edit_text=AsyncMock())
    mock_guard.return_value = msg
    mock_token_cls.return_value.charge = AsyncMock(return_value=1180)
    mock_token_cls.return_value.refund = AsyncMock(return_value=1500)

    cat = _category()
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=cat)
    mock_pub_cls.return_value.get_rotation_keyword = AsyncMock(return_value=("test phrase", False))
    mock_preview_svc_cls.return_value.generate_article_content = AsyncMock(
        return_value=MagicMock(
            title="Test", content_html="<p>T</p>",
            word_count=200, images_count=0, stored_images=[],
        ),
    )
    mock_prev_cls.return_value.create = AsyncMock(side_effect=Exception("DB error"))

    cb = _callback("pub:article:confirm")
    st = _state(category_id=10, project_id=1, connection_id=5, cost=320)

    await cb_article_confirm(cb, _user(), MagicMock(), st, _rl(), *_ai_deps())

    mock_token_cls.return_value.refund.assert_awaited_once()
    st.clear.assert_awaited()


# ---------------------------------------------------------------------------
# cb_article_publish: error recovery
# ---------------------------------------------------------------------------


@patch("routers.publishing.preview.CredentialManager")
@patch("routers.publishing.preview.get_settings")
@patch("routers.publishing.preview.PublicationsRepository")
@patch("routers.publishing.preview.PreviewsRepository")
@patch("routers.publishing.preview.guard_callback_message")
async def test_article_publish_error_returns_to_preview(
    mock_guard, mock_prev_cls, mock_pub_cls, mock_settings, mock_cm,
):
    """Publish error returns to preview state (connection lookup fails)."""
    msg = MagicMock(spec=Message, edit_text=AsyncMock())
    mock_guard.return_value = msg
    mock_settings.return_value = MagicMock(
        encryption_key=MagicMock(get_secret_value=MagicMock(return_value="k")),
    )

    preview = _preview()
    mock_prev_cls.return_value.get_by_id = AsyncMock(return_value=preview)
    mock_prev_cls.return_value.update = AsyncMock()

    cb = _callback("pub:article:publish")
    st = _state(
        preview_id=1, connection_id=5, category_id=10,
        project_id=1, keyword="test", cost=320,
    )

    # ConnectionsRepository(db, cm).get_by_id uses real code with MagicMock db
    # → await .execute() raises TypeError → handler recovers
    await cb_article_publish(cb, _user(), MagicMock(), st, *_ai_deps())

    # Should go back to preview state on error
    st.set_state.assert_any_call(ArticlePublishFSM.preview)


# ---------------------------------------------------------------------------
# Guard: inaccessible message
# ---------------------------------------------------------------------------


@patch("routers.publishing.preview.guard_callback_message", return_value=None)
async def test_article_start_inaccessible_message(mock_guard):
    """Inaccessible message -> early return."""
    cb = _callback("category:10:publish:wp")
    await cb_article_start(cb, _user(), MagicMock(), _state())
    # No crash, just returns


@patch("routers.publishing.preview.guard_callback_message", return_value=None)
async def test_article_confirm_inaccessible_message(mock_guard):
    """Inaccessible message -> early return."""
    cb = _callback("pub:article:confirm")
    await cb_article_confirm(cb, _user(), MagicMock(), _state(), _rl(), *_ai_deps())


@patch("routers.publishing.preview.guard_callback_message", return_value=None)
async def test_article_publish_inaccessible_message(mock_guard):
    """Inaccessible message -> early return."""
    cb = _callback("pub:article:publish")
    await cb_article_publish(cb, _user(), MagicMock(), _state(), *_ai_deps())


@patch("routers.publishing.preview.guard_callback_message", return_value=None)
async def test_article_regen_inaccessible_message(mock_guard):
    """Inaccessible message -> early return."""
    cb = _callback("pub:article:regen")
    await cb_article_regen(cb, _user(), MagicMock(), _state(), *_ai_deps())
