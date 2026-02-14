"""Tests for routers/publishing/social.py — SocialPostPublishFSM flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from db.models import Category, PlatformConnection, Project, User
from routers.publishing.social import (
    SocialPostPublishFSM,
    _select_keyword,
    cb_social_cancel,
    cb_social_confirm,
    cb_social_publish,
    cb_social_publishing_guard,
    cb_social_regen,
    cb_social_start,
)

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _user(balance: int = 1500) -> User:
    return User(id=1, balance=balance)


def _project() -> Project:
    return Project(id=1, user_id=1, name="Test", company_name="Co", specialization="SEO")


def _other_project() -> Project:
    return Project(id=2, user_id=999, name="Other", company_name="Other", specialization="Other")


def _category(keywords: list[dict[str, object]] | None = None) -> Category:
    kw = keywords if keywords is not None else [{"phrase": "test keyword", "volume": 100}]
    return Category(id=10, project_id=1, name="Test Category", keywords=kw)


def _category_no_keywords() -> Category:
    return Category(id=10, project_id=1, name="Test Category", keywords=[])


def _connection(platform: str = "telegram") -> PlatformConnection:
    return PlatformConnection(
        id=5, project_id=1, platform_type=platform,
        status="active", credentials={}, identifier="@test_channel",
    )


def _callback(data: str) -> MagicMock:
    """Create mock CallbackQuery."""
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock(id=1)
    cb.answer = AsyncMock()
    msg = MagicMock()
    msg.edit_text = AsyncMock()
    msg.edit_reply_markup = AsyncMock()
    msg.answer = AsyncMock()
    cb.message = msg
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
    return rl


def _settings_mock() -> MagicMock:
    settings = MagicMock()
    settings.encryption_key = MagicMock(get_secret_value=MagicMock(return_value="k"))
    settings.admin_id = 999
    return settings


# ---------------------------------------------------------------------------
# _select_keyword helper
# ---------------------------------------------------------------------------


def test_select_keyword_cluster_format() -> None:
    """Cluster format: returns main_phrase."""
    kw = [{"cluster_name": "Test", "main_phrase": "best shoes", "phrases": []}]
    assert _select_keyword(kw) == "best shoes"


def test_select_keyword_legacy_format() -> None:
    """Legacy flat format: returns phrase."""
    kw = [{"phrase": "red shoes", "volume": 100}]
    assert _select_keyword(kw) == "red shoes"


def test_select_keyword_empty_list() -> None:
    """Empty keywords: returns None."""
    assert _select_keyword([]) is None


def test_select_keyword_missing_fields() -> None:
    """No recognized fields: returns None."""
    kw = [{"something_else": "value"}]
    assert _select_keyword(kw) is None


# ---------------------------------------------------------------------------
# cb_social_start — happy path
# ---------------------------------------------------------------------------


@patch("routers.publishing.social.ensure_no_active_fsm", new_callable=AsyncMock, return_value=None)
@patch("routers.publishing.social.TokenService")
@patch("routers.publishing.social.get_settings")
@patch("routers.publishing.social.CredentialManager")
@patch("routers.publishing.social.ConnectionsRepository")
@patch("routers.publishing.social.ProjectsRepository")
@patch("routers.publishing.social.CategoriesRepository")
@patch("routers.publishing.social.guard_callback_message")
async def test_social_start_happy_path(
    mock_guard: MagicMock,
    mock_cat_cls: MagicMock,
    mock_proj_cls: MagicMock,
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
    mock_token_cls: MagicMock,
    mock_ensure: MagicMock,
) -> None:
    """Happy path: enters confirm_cost state, shows cost confirmation."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock(), answer=AsyncMock())
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_settings.return_value = _settings_mock()
    mock_conn_cls.return_value.get_by_id = AsyncMock(return_value=_connection())
    mock_token_cls.return_value.check_balance = AsyncMock(return_value=True)

    state = _state()
    cb = _callback("category:10:publish:tg:5")
    await cb_social_start(cb, state, _user(), MagicMock())

    state.set_state.assert_called_with(SocialPostPublishFSM.confirm_cost)
    mock_guard.return_value.edit_text.assert_called_once()
    call_text = mock_guard.return_value.edit_text.call_args[0][0]
    assert "Telegram" in call_text
    assert "Test Category" in call_text


@patch("routers.publishing.social.ensure_no_active_fsm", new_callable=AsyncMock, return_value=None)
@patch("routers.publishing.social.TokenService")
@patch("routers.publishing.social.get_settings")
@patch("routers.publishing.social.CredentialManager")
@patch("routers.publishing.social.ConnectionsRepository")
@patch("routers.publishing.social.ProjectsRepository")
@patch("routers.publishing.social.CategoriesRepository")
@patch("routers.publishing.social.guard_callback_message")
async def test_social_start_vk_platform(
    mock_guard: MagicMock,
    mock_cat_cls: MagicMock,
    mock_proj_cls: MagicMock,
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
    mock_token_cls: MagicMock,
    mock_ensure: MagicMock,
) -> None:
    """VK platform is correctly mapped and displayed."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock(), answer=AsyncMock())
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_settings.return_value = _settings_mock()
    mock_conn_cls.return_value.get_by_id = AsyncMock(return_value=_connection("vk"))
    mock_token_cls.return_value.check_balance = AsyncMock(return_value=True)

    state = _state()
    cb = _callback("category:10:publish:vk:5")
    await cb_social_start(cb, state, _user(), MagicMock())

    call_text = mock_guard.return_value.edit_text.call_args[0][0]
    assert "VK" in call_text


@patch("routers.publishing.social.ensure_no_active_fsm", new_callable=AsyncMock, return_value=None)
@patch("routers.publishing.social.TokenService")
@patch("routers.publishing.social.get_settings")
@patch("routers.publishing.social.CredentialManager")
@patch("routers.publishing.social.ConnectionsRepository")
@patch("routers.publishing.social.ProjectsRepository")
@patch("routers.publishing.social.CategoriesRepository")
@patch("routers.publishing.social.guard_callback_message")
async def test_social_start_pinterest_platform(
    mock_guard: MagicMock,
    mock_cat_cls: MagicMock,
    mock_proj_cls: MagicMock,
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
    mock_token_cls: MagicMock,
    mock_ensure: MagicMock,
) -> None:
    """Pinterest platform is correctly mapped and displayed."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock(), answer=AsyncMock())
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_settings.return_value = _settings_mock()
    mock_conn_cls.return_value.get_by_id = AsyncMock(return_value=_connection("pinterest"))
    mock_token_cls.return_value.check_balance = AsyncMock(return_value=True)

    state = _state()
    cb = _callback("category:10:publish:pin:5")
    await cb_social_start(cb, state, _user(), MagicMock())

    call_text = mock_guard.return_value.edit_text.call_args[0][0]
    assert "Pinterest" in call_text


# ---------------------------------------------------------------------------
# cb_social_start — ownership checks
# ---------------------------------------------------------------------------


@patch("routers.publishing.social.CategoriesRepository")
@patch("routers.publishing.social.guard_callback_message")
async def test_social_start_category_not_found(
    mock_guard: MagicMock, mock_cat_cls: MagicMock,
) -> None:
    """Category not found: show alert."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=None)

    cb = _callback("category:99:publish:tg:5")
    await cb_social_start(cb, _state(), _user(), MagicMock())

    cb.answer.assert_called_with("Категория не найдена.", show_alert=True)


@patch("routers.publishing.social.ProjectsRepository")
@patch("routers.publishing.social.CategoriesRepository")
@patch("routers.publishing.social.guard_callback_message")
async def test_social_start_wrong_owner(
    mock_guard: MagicMock, mock_cat_cls: MagicMock, mock_proj_cls: MagicMock,
) -> None:
    """Category belongs to different user: show alert."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_other_project())

    cb = _callback("category:10:publish:tg:5")
    await cb_social_start(cb, _state(), _user(), MagicMock())

    cb.answer.assert_called_with("Категория не найдена.", show_alert=True)


# ---------------------------------------------------------------------------
# cb_social_start — E16: no keywords
# ---------------------------------------------------------------------------


@patch("routers.publishing.social.ProjectsRepository")
@patch("routers.publishing.social.CategoriesRepository")
@patch("routers.publishing.social.guard_callback_message")
async def test_social_start_no_keywords_e16(
    mock_guard: MagicMock, mock_cat_cls: MagicMock, mock_proj_cls: MagicMock,
) -> None:
    """E16: Category has no keywords — block publish."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category_no_keywords())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())

    cb = _callback("category:10:publish:tg:5")
    await cb_social_start(cb, _state(), _user(), MagicMock())

    call_text = mock_guard.return_value.edit_text.call_args[0][0]
    assert "нет ключевых фраз" in call_text


# ---------------------------------------------------------------------------
# cb_social_start — connection not found
# ---------------------------------------------------------------------------


@patch("routers.publishing.social.TokenService")
@patch("routers.publishing.social.get_settings")
@patch("routers.publishing.social.CredentialManager")
@patch("routers.publishing.social.ConnectionsRepository")
@patch("routers.publishing.social.ProjectsRepository")
@patch("routers.publishing.social.CategoriesRepository")
@patch("routers.publishing.social.guard_callback_message")
async def test_social_start_connection_not_found(
    mock_guard: MagicMock,
    mock_cat_cls: MagicMock,
    mock_proj_cls: MagicMock,
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
    mock_token_cls: MagicMock,
) -> None:
    """Connection not found: show alert."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_settings.return_value = _settings_mock()
    mock_conn_cls.return_value.get_by_id = AsyncMock(return_value=None)

    cb = _callback("category:10:publish:tg:5")
    await cb_social_start(cb, _state(), _user(), MagicMock())

    cb.answer.assert_called_with("Подключение не найдено.", show_alert=True)


# ---------------------------------------------------------------------------
# cb_social_start — insufficient balance
# ---------------------------------------------------------------------------


@patch("routers.publishing.social.TokenService")
@patch("routers.publishing.social.get_settings")
@patch("routers.publishing.social.CredentialManager")
@patch("routers.publishing.social.ConnectionsRepository")
@patch("routers.publishing.social.ProjectsRepository")
@patch("routers.publishing.social.CategoriesRepository")
@patch("routers.publishing.social.guard_callback_message")
async def test_social_start_insufficient_balance(
    mock_guard: MagicMock,
    mock_cat_cls: MagicMock,
    mock_proj_cls: MagicMock,
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
    mock_token_cls: MagicMock,
) -> None:
    """Insufficient balance: show topup prompt."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_settings.return_value = _settings_mock()
    mock_conn_cls.return_value.get_by_id = AsyncMock(return_value=_connection())
    mock_token_cls.return_value.check_balance = AsyncMock(return_value=False)
    mock_token_cls.return_value.get_balance = AsyncMock(return_value=10)
    mock_token_cls.return_value.format_insufficient_msg = MagicMock(
        return_value="Недостаточно токенов. Нужно 40, у вас 10."
    )

    cb = _callback("category:10:publish:tg:5")
    await cb_social_start(cb, _state(), _user(balance=10), MagicMock())

    call_text = mock_guard.return_value.edit_text.call_args[0][0]
    assert "Недостаточно" in call_text


# ---------------------------------------------------------------------------
# cb_social_start — inaccessible message
# ---------------------------------------------------------------------------


@patch("routers.publishing.social.guard_callback_message", new_callable=AsyncMock, return_value=None)
async def test_social_start_inaccessible_message(mock_guard: MagicMock) -> None:
    """Inaccessible message: returns early."""
    cb = _callback("category:10:publish:tg:5")
    await cb_social_start(cb, _state(), _user(), MagicMock())
    # No crash, guard returned None


# ---------------------------------------------------------------------------
# cb_social_start — ensure_no_active_fsm interrupted
# ---------------------------------------------------------------------------


@patch("routers.publishing.social.ensure_no_active_fsm", new_callable=AsyncMock, return_value="создание проекта")
@patch("routers.publishing.social.TokenService")
@patch("routers.publishing.social.get_settings")
@patch("routers.publishing.social.CredentialManager")
@patch("routers.publishing.social.ConnectionsRepository")
@patch("routers.publishing.social.ProjectsRepository")
@patch("routers.publishing.social.CategoriesRepository")
@patch("routers.publishing.social.guard_callback_message")
async def test_social_start_interrupts_active_fsm(
    mock_guard: MagicMock,
    mock_cat_cls: MagicMock,
    mock_proj_cls: MagicMock,
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
    mock_token_cls: MagicMock,
    mock_ensure: MagicMock,
) -> None:
    """Active FSM is interrupted and user is notified."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock(), answer=AsyncMock())
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_settings.return_value = _settings_mock()
    mock_conn_cls.return_value.get_by_id = AsyncMock(return_value=_connection())
    mock_token_cls.return_value.check_balance = AsyncMock(return_value=True)

    state = _state()
    cb = _callback("category:10:publish:tg:5")
    await cb_social_start(cb, state, _user(), MagicMock())

    mock_guard.return_value.answer.assert_called_once()
    answer_text = mock_guard.return_value.answer.call_args[0][0]
    assert "создание проекта" in answer_text
    assert "прерван" in answer_text


# ---------------------------------------------------------------------------
# cb_social_confirm — happy path
# ---------------------------------------------------------------------------


@patch("routers.publishing.social.CategoriesRepository")
@patch("routers.publishing.social.TokenService")
@patch("routers.publishing.social.get_settings")
@patch("routers.publishing.social.guard_callback_message")
async def test_social_confirm_charges_and_generates(
    mock_guard: MagicMock,
    mock_settings: MagicMock,
    mock_token_cls: MagicMock,
    mock_cat_cls: MagicMock,
) -> None:
    """Confirm: charges tokens, generates content, transitions to review."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_settings.return_value = _settings_mock()
    mock_token_cls.return_value.charge = AsyncMock(return_value=1460)
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())

    state = _state(cost=40, category_id=10, platform="telegram")
    cb = _callback("pub:social:confirm")
    await cb_social_confirm(cb, state, _user(), MagicMock(), _rl())

    mock_token_cls.return_value.charge.assert_called_once()
    state.set_state.assert_any_call(SocialPostPublishFSM.generating)
    state.set_state.assert_any_call(SocialPostPublishFSM.review)
    state.update_data.assert_called_once()
    # Verify content is shown
    final_call = mock_guard.return_value.edit_text.call_args_list[-1]
    assert "Готово" in final_call[0][0]


@patch("routers.publishing.social.TokenService")
@patch("routers.publishing.social.get_settings")
@patch("routers.publishing.social.guard_callback_message")
async def test_social_confirm_charge_failure(
    mock_guard: MagicMock,
    mock_settings: MagicMock,
    mock_token_cls: MagicMock,
) -> None:
    """Charge failure: show error, clear FSM."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_settings.return_value = _settings_mock()
    mock_token_cls.return_value.charge = AsyncMock(side_effect=Exception("charge error"))

    state = _state(cost=40, category_id=10, platform="telegram")
    cb = _callback("pub:social:confirm")
    await cb_social_confirm(cb, state, _user(), MagicMock(), _rl())

    state.clear.assert_called_once()
    call_text = mock_guard.return_value.edit_text.call_args[0][0]
    assert "Ошибка" in call_text


# ---------------------------------------------------------------------------
# cb_social_publish — happy path
# ---------------------------------------------------------------------------


@patch("routers.publishing.social.PublicationsRepository")
@patch("routers.publishing.social.guard_callback_message")
async def test_social_publish_success(
    mock_guard: MagicMock, mock_pub_cls: MagicMock,
) -> None:
    """Publish: transitions to publishing, creates log, shows success."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_pub_cls.return_value.create_log = AsyncMock(return_value=MagicMock(id=1))

    state = _state(
        category_id=10, project_id=1, connection_id=5,
        platform="telegram", keyword="test keyword",
        generated_content="Hello world", cost=40,
    )
    cb = _callback("pub:social:publish")
    await cb_social_publish(cb, state, _user(), MagicMock())

    state.set_state.assert_called_with(SocialPostPublishFSM.publishing)
    state.clear.assert_called_once()
    mock_pub_cls.return_value.create_log.assert_called_once()
    call_text = mock_guard.return_value.edit_text.call_args_list[-1][0][0]
    assert "Telegram" in call_text
    assert "опубликован" in call_text


@patch("routers.publishing.social.PublicationsRepository")
@patch("routers.publishing.social.guard_callback_message")
async def test_social_publish_log_failure_still_succeeds(
    mock_guard: MagicMock, mock_pub_cls: MagicMock,
) -> None:
    """Publication log failure: still completes (post is published, log is non-critical)."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_pub_cls.return_value.create_log = AsyncMock(side_effect=Exception("log error"))

    state = _state(
        category_id=10, project_id=1, connection_id=5,
        platform="vk", keyword="test", generated_content="VK post", cost=40,
    )
    cb = _callback("pub:social:publish")
    await cb_social_publish(cb, state, _user(), MagicMock())

    state.clear.assert_called_once()
    call_text = mock_guard.return_value.edit_text.call_args_list[-1][0][0]
    assert "VK" in call_text


@patch("routers.publishing.social.PublicationsRepository")
@patch("routers.publishing.social.guard_callback_message")
async def test_social_publish_creates_log_with_correct_data(
    mock_guard: MagicMock, mock_pub_cls: MagicMock,
) -> None:
    """Publication log has correct fields."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_pub_cls.return_value.create_log = AsyncMock(return_value=MagicMock(id=1))

    state = _state(
        category_id=10, project_id=1, connection_id=5,
        platform="pinterest", keyword="my keyword",
        generated_content="Pin content here", cost=40,
    )
    cb = _callback("pub:social:publish")
    await cb_social_publish(cb, state, _user(), MagicMock())

    log_call = mock_pub_cls.return_value.create_log.call_args[0][0]
    assert log_call.user_id == 1
    assert log_call.project_id == 1
    assert log_call.category_id == 10
    assert log_call.platform_type == "pinterest"
    assert log_call.keyword == "my keyword"
    assert log_call.content_type == "social_post"
    assert log_call.tokens_spent == 40
    assert log_call.status == "success"


# ---------------------------------------------------------------------------
# cb_social_regen — free regeneration
# ---------------------------------------------------------------------------


@patch("routers.publishing.social.guard_callback_message")
async def test_social_regen_free_first(mock_guard: MagicMock) -> None:
    """First regen (count=0): free, no charge."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())

    state = _state(
        regeneration_count=0, cost=40, platform="telegram", keyword="test",
    )
    cb = _callback("pub:social:regen")
    await cb_social_regen(cb, state, _user(), MagicMock())

    state.set_state.assert_any_call(SocialPostPublishFSM.regenerating)
    state.set_state.assert_any_call(SocialPostPublishFSM.review)
    state.update_data.assert_called_once()
    # Verify regeneration_count incremented
    update_kwargs = state.update_data.call_args[1]
    assert update_kwargs["regeneration_count"] == 1


@patch("routers.publishing.social.guard_callback_message")
async def test_social_regen_free_second(mock_guard: MagicMock) -> None:
    """Second regen (count=1): still free."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())

    state = _state(
        regeneration_count=1, cost=40, platform="telegram", keyword="test",
    )
    cb = _callback("pub:social:regen")
    await cb_social_regen(cb, state, _user(), MagicMock())

    state.set_state.assert_any_call(SocialPostPublishFSM.review)
    update_kwargs = state.update_data.call_args[1]
    assert update_kwargs["regeneration_count"] == 2


# ---------------------------------------------------------------------------
# cb_social_regen — paid regeneration (E10)
# ---------------------------------------------------------------------------


@patch("routers.publishing.social.TokenService")
@patch("routers.publishing.social.get_settings")
@patch("routers.publishing.social.guard_callback_message")
async def test_social_regen_paid_third(
    mock_guard: MagicMock, mock_settings: MagicMock, mock_token_cls: MagicMock,
) -> None:
    """Third regen (count=2): paid, charges tokens."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_settings.return_value = _settings_mock()
    mock_token_cls.return_value.check_balance = AsyncMock(return_value=True)
    mock_token_cls.return_value.charge = AsyncMock(return_value=1420)

    state = _state(
        regeneration_count=2, cost=40, platform="telegram", keyword="test",
    )
    cb = _callback("pub:social:regen")
    await cb_social_regen(cb, state, _user(), MagicMock())

    mock_token_cls.return_value.charge.assert_called_once()
    state.set_state.assert_any_call(SocialPostPublishFSM.review)
    update_kwargs = state.update_data.call_args[1]
    assert update_kwargs["regeneration_count"] == 3


@patch("routers.publishing.social.TokenService")
@patch("routers.publishing.social.get_settings")
@patch("routers.publishing.social.guard_callback_message")
async def test_social_regen_paid_insufficient_balance(
    mock_guard: MagicMock, mock_settings: MagicMock, mock_token_cls: MagicMock,
) -> None:
    """E10: Paid regen with insufficient balance shows alert."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_settings.return_value = _settings_mock()
    mock_token_cls.return_value.check_balance = AsyncMock(return_value=False)
    mock_token_cls.return_value.get_balance = AsyncMock(return_value=10)

    state = _state(
        regeneration_count=2, cost=40, platform="telegram", keyword="test",
    )
    cb = _callback("pub:social:regen")
    await cb_social_regen(cb, state, _user(balance=10), MagicMock())

    cb.answer.assert_called_once()
    answer_text = cb.answer.call_args[0][0]
    assert "40" in answer_text
    assert "10" in answer_text
    # Should NOT transition state
    state.set_state.assert_not_called()


@patch("routers.publishing.social.TokenService")
@patch("routers.publishing.social.get_settings")
@patch("routers.publishing.social.guard_callback_message")
async def test_social_regen_paid_charge_failure(
    mock_guard: MagicMock, mock_settings: MagicMock, mock_token_cls: MagicMock,
) -> None:
    """Paid regen charge failure: show alert, stay in review."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_settings.return_value = _settings_mock()
    mock_token_cls.return_value.check_balance = AsyncMock(return_value=True)
    mock_token_cls.return_value.charge = AsyncMock(side_effect=Exception("charge error"))

    state = _state(
        regeneration_count=2, cost=40, platform="telegram", keyword="test",
    )
    cb = _callback("pub:social:regen")
    await cb_social_regen(cb, state, _user(), MagicMock())

    cb.answer.assert_called_once()
    answer_text = cb.answer.call_args[0][0]
    assert "Ошибка" in answer_text
    state.set_state.assert_not_called()


# ---------------------------------------------------------------------------
# cb_social_cancel
# ---------------------------------------------------------------------------


@patch("routers.publishing.social.guard_callback_message")
async def test_social_cancel_clears_state(mock_guard: MagicMock) -> None:
    """Cancel: clears FSM, shows cancelled message."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())

    state = _state(category_id=10)
    cb = _callback("pub:social:cancel")
    await cb_social_cancel(cb, state)

    state.clear.assert_called_once()
    call_text = mock_guard.return_value.edit_text.call_args[0][0]
    assert "отменена" in call_text


@patch("routers.publishing.social.guard_callback_message")
async def test_social_cancel_no_refund(mock_guard: MagicMock) -> None:
    """E27: No refund on cancel for cheap social posts."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())

    state = _state(category_id=10, cost=40)
    cb = _callback("pub:social:cancel")
    await cb_social_cancel(cb, state)

    # Only clear is called, no refund service interaction
    state.clear.assert_called_once()


@patch("routers.publishing.social.guard_callback_message")
async def test_social_cancel_shows_category_button(mock_guard: MagicMock) -> None:
    """Cancel shows button to go back to category."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())

    state = _state(category_id=10)
    cb = _callback("pub:social:cancel")
    await cb_social_cancel(cb, state)

    call_kwargs = mock_guard.return_value.edit_text.call_args[1]
    markup = call_kwargs["reply_markup"]
    # Should have at least one button
    assert markup is not None


# ---------------------------------------------------------------------------
# cb_social_publishing_guard — E07
# ---------------------------------------------------------------------------


async def test_social_publishing_guard_e07() -> None:
    """E07: Publishing guard shows alert."""
    cb = MagicMock()
    cb.answer = AsyncMock()
    await cb_social_publishing_guard(cb)
    cb.answer.assert_called_with("Публикация в процессе.", show_alert=True)


# ---------------------------------------------------------------------------
# cb_social_start — inaccessible message guards in other handlers
# ---------------------------------------------------------------------------


@patch("routers.publishing.social.guard_callback_message", new_callable=AsyncMock, return_value=None)
async def test_social_confirm_inaccessible_message(mock_guard: MagicMock) -> None:
    """Confirm with inaccessible message: returns early."""
    cb = _callback("pub:social:confirm")
    await cb_social_confirm(cb, _state(), _user(), MagicMock(), _rl())


@patch("routers.publishing.social.guard_callback_message", new_callable=AsyncMock, return_value=None)
async def test_social_publish_inaccessible_message(mock_guard: MagicMock) -> None:
    """Publish with inaccessible message: returns early."""
    cb = _callback("pub:social:publish")
    await cb_social_publish(cb, _state(), _user(), MagicMock())


@patch("routers.publishing.social.guard_callback_message", new_callable=AsyncMock, return_value=None)
async def test_social_regen_inaccessible_message(mock_guard: MagicMock) -> None:
    """Regen with inaccessible message: returns early."""
    cb = _callback("pub:social:regen")
    await cb_social_regen(cb, _state(), _user(), MagicMock())


@patch("routers.publishing.social.guard_callback_message", new_callable=AsyncMock, return_value=None)
async def test_social_cancel_inaccessible_message(mock_guard: MagicMock) -> None:
    """Cancel with inaccessible message: returns early."""
    cb = _callback("pub:social:cancel")
    await cb_social_cancel(cb, _state())
