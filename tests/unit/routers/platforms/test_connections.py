"""Tests for routers/platforms/connections.py — connection CRUD, FSM validation, helpers.

Covers: cb_connection_list, cb_connection_card, cb_connection_delete + confirm,
regex validation patterns, _format_connection_card, _connection_list_kb.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from db.models import PlatformConnection, Project, User
from routers.platforms.connections import (
    _BOT_TOKEN_RE,
    _TG_CHANNEL_RE,
    _URL_RE,
    _VK_TOKEN_RE,
    _WP_APP_PASSWORD_RE,
    ConnectPinterestFSM,
    ConnectTelegramFSM,
    ConnectVKFSM,
    ConnectWordPressFSM,
    _connection_list_kb,
    _format_connection_card,
    cb_connection_card,
    cb_connection_delete,
    cb_connection_delete_confirm,
    cb_connection_list,
)

# ---------------------------------------------------------------------------
# Regex validation patterns
# ---------------------------------------------------------------------------


class TestUrlRegex:
    def test_https_valid(self) -> None:
        assert _URL_RE.match("https://example.com") is not None

    def test_http_valid(self) -> None:
        assert _URL_RE.match("http://example.com") is not None

    def test_no_protocol_invalid(self) -> None:
        assert _URL_RE.match("example.com") is None

    def test_ftp_invalid(self) -> None:
        assert _URL_RE.match("ftp://example.com") is None

    def test_with_path(self) -> None:
        assert _URL_RE.match("https://example.com/blog/post") is not None

    def test_with_port(self) -> None:
        assert _URL_RE.match("https://example.com:8080") is not None

    def test_spaces_invalid(self) -> None:
        assert _URL_RE.match("https://example .com") is None


class TestTgChannelRegex:
    def test_at_channel(self) -> None:
        assert _TG_CHANNEL_RE.match("@my_channel") is not None

    def test_at_channel_min_length(self) -> None:
        assert _TG_CHANNEL_RE.match("@abcde") is not None

    def test_at_channel_too_short(self) -> None:
        assert _TG_CHANNEL_RE.match("@abcd") is None

    def test_tme_link(self) -> None:
        assert _TG_CHANNEL_RE.match("https://t.me/my_channel") is not None

    def test_http_tme_link(self) -> None:
        assert _TG_CHANNEL_RE.match("http://t.me/my_channel") is not None

    def test_numeric_id(self) -> None:
        assert _TG_CHANNEL_RE.match("-1001234567890") is not None

    def test_short_numeric_id(self) -> None:
        assert _TG_CHANNEL_RE.match("-1001234567") is None

    def test_plain_text_invalid(self) -> None:
        assert _TG_CHANNEL_RE.match("my_channel") is None


class TestBotTokenRegex:
    def test_valid_token(self) -> None:
        assert _BOT_TOKEN_RE.match("12345678:ABC" + "x" * 32) is not None

    def test_short_id_invalid(self) -> None:
        assert _BOT_TOKEN_RE.match("1234:ABCdefGHI_1234567890123456789012345") is None

    def test_no_colon_invalid(self) -> None:
        assert _BOT_TOKEN_RE.match("1234567890ABCdefGHI") is None

    def test_short_hash_invalid(self) -> None:
        assert _BOT_TOKEN_RE.match("1234567890:ABC") is None


class TestVkTokenRegex:
    def test_valid_token(self) -> None:
        assert _VK_TOKEN_RE.match("vk1.a.some_long_token_string_here") is not None

    def test_without_prefix_invalid(self) -> None:
        assert _VK_TOKEN_RE.match("some_token") is None

    def test_partial_prefix_invalid(self) -> None:
        assert _VK_TOKEN_RE.match("vk1.token") is None

    def test_empty_after_prefix_invalid(self) -> None:
        """vk1.a. without any token chars after -> invalid."""
        assert _VK_TOKEN_RE.match("vk1.a.") is None


class TestWpAppPasswordRegex:
    def test_valid_password(self) -> None:
        assert _WP_APP_PASSWORD_RE.match("abcd efgh ijkl mnop qrst uvwx") is not None

    def test_valid_alphanumeric(self) -> None:
        assert _WP_APP_PASSWORD_RE.match("Ab1C De2F Gh3I Jk4L Mn5O Pq6R") is not None

    def test_wrong_group_count(self) -> None:
        assert _WP_APP_PASSWORD_RE.match("abcd efgh ijkl") is None

    def test_wrong_group_length(self) -> None:
        assert _WP_APP_PASSWORD_RE.match("abc efgh ijkl mnop qrst uvwx") is None

    def test_no_spaces_invalid(self) -> None:
        assert _WP_APP_PASSWORD_RE.match("abcdefghijklmnopqrstuvwx") is None


# ---------------------------------------------------------------------------
# _format_connection_card
# ---------------------------------------------------------------------------


class TestFormatConnectionCard:
    def test_active_wordpress(self) -> None:
        conn = PlatformConnection(
            id=1,
            project_id=1,
            platform_type="wordpress",
            identifier="example.com",
            status="active",
            credentials={},
        )
        card = _format_connection_card(conn)
        assert "WordPress" in card
        assert "example.com" in card
        assert "Активно" in card

    def test_error_status(self) -> None:
        conn = PlatformConnection(
            id=2,
            project_id=1,
            platform_type="telegram",
            identifier="@my_channel",
            status="error",
            credentials={},
        )
        card = _format_connection_card(conn)
        assert "Telegram" in card
        assert "Ошибка" in card

    def test_disconnected_status(self) -> None:
        conn = PlatformConnection(
            id=3,
            project_id=1,
            platform_type="vk",
            identifier="My Group",
            status="disconnected",
            credentials={},
        )
        card = _format_connection_card(conn)
        assert "VK" in card
        assert "Отключено" in card

    def test_unknown_status_shows_raw(self) -> None:
        conn = PlatformConnection(
            id=4,
            project_id=1,
            platform_type="pinterest",
            identifier="Board",
            status="pending",
            credentials={},
        )
        card = _format_connection_card(conn)
        assert "pending" in card

    def test_html_bold_platform_name(self) -> None:
        conn = PlatformConnection(
            id=1,
            project_id=1,
            platform_type="wordpress",
            identifier="x",
            credentials={},
        )
        card = _format_connection_card(conn)
        assert "<b>WordPress</b>" in card


# ---------------------------------------------------------------------------
# _connection_list_kb
# ---------------------------------------------------------------------------


class TestConnectionListKb:
    def test_empty_list_has_add_buttons_only(self) -> None:
        kb = _connection_list_kb([], project_id=1)
        markup = kb.as_markup()
        # Should have 4 "add" buttons + 1 "back" button
        all_buttons = [btn for row in markup.inline_keyboard for btn in row]
        assert len(all_buttons) == 5
        add_buttons = [b for b in all_buttons if "Добавить" in b.text]
        assert len(add_buttons) == 4

    def test_connections_shown_as_buttons(self) -> None:
        conns = [
            PlatformConnection(
                id=10, project_id=1, platform_type="wordpress",
                identifier="site.com", credentials={},
            ),
            PlatformConnection(
                id=11, project_id=1, platform_type="telegram",
                identifier="@chan", credentials={},
            ),
        ]
        kb = _connection_list_kb(conns, project_id=1)
        markup = kb.as_markup()
        all_buttons = [btn for row in markup.inline_keyboard for btn in row]
        # 2 connections + 4 add + 1 back = 7
        assert len(all_buttons) == 7
        # Verify callback_data format
        assert all_buttons[0].callback_data == "conn:10:card"
        assert all_buttons[1].callback_data == "conn:11:card"

    def test_error_status_shows_indicator(self) -> None:
        conns = [
            PlatformConnection(
                id=10, project_id=1, platform_type="wordpress",
                identifier="site.com", status="error", credentials={},
            ),
        ]
        kb = _connection_list_kb(conns, project_id=1)
        markup = kb.as_markup()
        button_text = markup.inline_keyboard[0][0].text
        assert "[!]" in button_text

    def test_long_name_truncated(self) -> None:
        conns = [
            PlatformConnection(
                id=10, project_id=1, platform_type="wordpress",
                identifier="a" * 100, credentials={},
            ),
        ]
        kb = _connection_list_kb(conns, project_id=1)
        markup = kb.as_markup()
        button_text = markup.inline_keyboard[0][0].text
        assert len(button_text) <= 60
        assert button_text.endswith("...")

    def test_back_button_links_to_project(self) -> None:
        kb = _connection_list_kb([], project_id=42)
        markup = kb.as_markup()
        all_buttons = [btn for row in markup.inline_keyboard for btn in row]
        back_btn = all_buttons[-1]
        assert back_btn.callback_data == "project:42:card"


# ---------------------------------------------------------------------------
# cb_connection_list
# ---------------------------------------------------------------------------


class TestCbConnectionList:
    async def test_empty_connections(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_callback.data = "project:1:connections"
        mock_project = Project(id=1, user_id=user.id, name="P", company_name="C", specialization="S")

        with (
            patch("routers.platforms.connections.guard_callback_message", return_value=mock_callback.message),
            patch("routers.platforms.connections._get_connections_repo") as mock_repo_fn,
            patch("routers.platforms.connections.ProjectsRepository") as mock_proj_cls,
        ):
            mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=mock_project)
            mock_repo_fn.return_value.get_by_project = AsyncMock(return_value=[])

            await cb_connection_list(mock_callback, user, mock_db)

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "Нет подключенных" in text

    async def test_with_connections(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_callback.data = "project:1:connections"
        mock_project = Project(id=1, user_id=user.id, name="P", company_name="C", specialization="S")
        conns = [
            PlatformConnection(id=10, project_id=1, platform_type="wordpress", identifier="x", credentials={}),
        ]

        with (
            patch("routers.platforms.connections.guard_callback_message", return_value=mock_callback.message),
            patch("routers.platforms.connections._get_connections_repo") as mock_repo_fn,
            patch("routers.platforms.connections.ProjectsRepository") as mock_proj_cls,
        ):
            mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=mock_project)
            mock_repo_fn.return_value.get_by_project = AsyncMock(return_value=conns)

            await cb_connection_list(mock_callback, user, mock_db)

        text = mock_callback.message.edit_text.call_args.args[0]
        assert "(1)" in text

    async def test_wrong_owner_blocked(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        """Ownership check: user cannot view another user's project connections."""
        mock_callback.data = "project:1:connections"
        other_project = Project(id=1, user_id=999, name="P", company_name="C", specialization="S")

        with (
            patch("routers.platforms.connections.guard_callback_message", return_value=mock_callback.message),
            patch("routers.platforms.connections.ProjectsRepository") as mock_proj_cls,
        ):
            mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=other_project)

            await cb_connection_list(mock_callback, user, mock_db)

        mock_callback.answer.assert_awaited_once()
        assert "не найден" in mock_callback.answer.call_args.args[0]


# ---------------------------------------------------------------------------
# cb_connection_card
# ---------------------------------------------------------------------------


class TestCbConnectionCard:
    async def test_found_shows_card(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock, connection: PlatformConnection
    ) -> None:
        mock_callback.data = f"conn:{connection.id}:card"
        mock_project = Project(id=1, user_id=user.id, name="P", company_name="C", specialization="S")

        with (
            patch("routers.platforms.connections.guard_callback_message", return_value=mock_callback.message),
            patch("routers.platforms.connections._get_connections_repo") as mock_repo_fn,
            patch("routers.platforms.connections.ProjectsRepository") as mock_proj_cls,
        ):
            mock_repo_fn.return_value.get_by_id = AsyncMock(return_value=connection)
            mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=mock_project)

            await cb_connection_card(mock_callback, user, mock_db)

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "WordPress" in text

    async def test_not_found_shows_alert(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_callback.data = "conn:999:card"

        with (
            patch("routers.platforms.connections.guard_callback_message", return_value=mock_callback.message),
            patch("routers.platforms.connections._get_connections_repo") as mock_repo_fn,
        ):
            mock_repo_fn.return_value.get_by_id = AsyncMock(return_value=None)

            await cb_connection_card(mock_callback, user, mock_db)

        mock_callback.answer.assert_awaited_once()
        assert "не найдено" in mock_callback.answer.call_args.args[0]

    async def test_wrong_owner_shows_alert(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock, connection: PlatformConnection
    ) -> None:
        """Ownership check: connection belongs to another user's project."""
        mock_callback.data = f"conn:{connection.id}:card"
        other_project = Project(id=1, user_id=999, name="P", company_name="C", specialization="S")

        with (
            patch("routers.platforms.connections.guard_callback_message", return_value=mock_callback.message),
            patch("routers.platforms.connections._get_connections_repo") as mock_repo_fn,
            patch("routers.platforms.connections.ProjectsRepository") as mock_proj_cls,
        ):
            mock_repo_fn.return_value.get_by_id = AsyncMock(return_value=connection)
            mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=other_project)

            await cb_connection_card(mock_callback, user, mock_db)

        mock_callback.answer.assert_awaited_once()
        assert "не найдено" in mock_callback.answer.call_args.args[0]


# ---------------------------------------------------------------------------
# cb_connection_delete
# ---------------------------------------------------------------------------


class TestCbConnectionDelete:
    async def test_shows_confirmation(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock, connection: PlatformConnection
    ) -> None:
        mock_callback.data = f"conn:{connection.id}:delete"
        mock_project = Project(id=1, user_id=user.id, name="P", company_name="C", specialization="S")

        with (
            patch("routers.platforms.connections.guard_callback_message", return_value=mock_callback.message),
            patch("routers.platforms.connections._get_connections_repo") as mock_repo_fn,
            patch("routers.platforms.connections.ProjectsRepository") as mock_proj_cls,
        ):
            mock_repo_fn.return_value.get_by_id = AsyncMock(return_value=connection)
            mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=mock_project)

            await cb_connection_delete(mock_callback, user, mock_db)

        text = mock_callback.message.edit_text.call_args.args[0]
        assert "Удалить" in text
        assert "расписания" in text

    async def test_not_found_shows_alert(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_callback.data = "conn:999:delete"

        with (
            patch("routers.platforms.connections.guard_callback_message", return_value=mock_callback.message),
            patch("routers.platforms.connections._get_connections_repo") as mock_repo_fn,
        ):
            mock_repo_fn.return_value.get_by_id = AsyncMock(return_value=None)

            await cb_connection_delete(mock_callback, user, mock_db)

        mock_callback.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# cb_connection_delete_confirm
# ---------------------------------------------------------------------------


class TestCbConnectionDeleteConfirm:
    async def test_deletes_and_shows_updated_list(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock, connection: PlatformConnection
    ) -> None:
        mock_callback.data = f"conn:{connection.id}:delete:confirm"
        mock_project = Project(id=1, user_id=user.id, name="P", company_name="C", specialization="S")

        with (
            patch("routers.platforms.connections.guard_callback_message", return_value=mock_callback.message),
            patch("routers.platforms.connections._get_connections_repo") as mock_repo_fn,
            patch("routers.platforms.connections.ProjectsRepository") as mock_proj_cls,
        ):
            repo = mock_repo_fn.return_value
            repo.get_by_id = AsyncMock(return_value=connection)
            repo.delete = AsyncMock()
            repo.get_by_project = AsyncMock(return_value=[])
            mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=mock_project)

            await cb_connection_delete_confirm(mock_callback, user, mock_db)

        repo.delete.assert_awaited_once_with(connection.id)
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "удалено" in text.lower()

    async def test_not_found_shows_alert(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_callback.data = "conn:999:delete:confirm"

        with (
            patch("routers.platforms.connections.guard_callback_message", return_value=mock_callback.message),
            patch("routers.platforms.connections._get_connections_repo") as mock_repo_fn,
        ):
            mock_repo_fn.return_value.get_by_id = AsyncMock(return_value=None)

            await cb_connection_delete_confirm(mock_callback, user, mock_db)

        mock_callback.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# FSM StatesGroup definitions
# ---------------------------------------------------------------------------


class TestFSMDefinitions:
    def test_wordpress_fsm_has_3_states(self) -> None:
        states = ConnectWordPressFSM.__all_states__
        assert len(states) == 3

    def test_telegram_fsm_has_2_states(self) -> None:
        states = ConnectTelegramFSM.__all_states__
        assert len(states) == 2

    def test_vk_fsm_has_2_states(self) -> None:
        states = ConnectVKFSM.__all_states__
        assert len(states) == 2

    def test_pinterest_fsm_has_2_states(self) -> None:
        states = ConnectPinterestFSM.__all_states__
        assert len(states) == 2
