"""Tests for routers/publishing/pipeline/social/connection.py handlers (F6.2).

Covers step 2 of the Social Pipeline:
- _show_connection_step: 0/1/>1 connections
- pipeline_select_connection: select from list
- pipeline_add_connection: platform picker with exclude_types (P1-3)
- TG inline connect: channel validation, token, verify (3 states)
- VK inline connect: token validation, group selection (2 states)
- Pinterest OAuth entry
- Edge cases: E41, security (token deletion), limits
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from routers.publishing.pipeline._common import SocialPipelineFSM
from routers.publishing.pipeline.social.connection import (
    _normalize_tg_channel,
    _show_connection_step,
    pipeline_add_connection,
    pipeline_connect_tg_channel,
    pipeline_connect_tg_token,
    pipeline_connect_tg_verify,
    pipeline_connect_vk_token,
    pipeline_select_connection,
    pipeline_select_vk_group,
    pipeline_start_connect_pinterest,
    pipeline_start_connect_tg,
    pipeline_start_connect_vk,
)
from tests.unit.routers.conftest import make_connection

_MODULE = "routers.publishing.pipeline.social.connection"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_social_conn(
    *,
    id: int = 5,
    project_id: int = 1,
    platform_type: str = "telegram",
    identifier: str = "@testchannel",
    metadata: dict[str, Any] | None = None,
) -> Any:
    return make_connection(
        id=id,
        project_id=project_id,
        platform_type=platform_type,
        identifier=identifier,
        metadata=metadata or {},
    )


def _mock_conn_svc(
    *,
    social_conns: list | None = None,
    conn: Any = None,
    by_project_platform: list | None = None,
    by_identifier_global: Any = None,
    platform_types: list[str] | None = None,
    validate_vk_result: tuple[str | None, list] = (None, []),
    created_conn: Any = None,
) -> tuple[MagicMock, Any]:
    """Create a mock ConnectionService and its patch."""
    svc = MagicMock()
    svc.get_social_connections = AsyncMock(return_value=social_conns or [])
    svc.get_by_id = AsyncMock(return_value=conn)
    svc.get_by_project_and_platform = AsyncMock(return_value=by_project_platform or [])
    svc.get_by_identifier_global = AsyncMock(return_value=by_identifier_global)
    svc.get_platform_types_by_project = AsyncMock(return_value=platform_types or [])
    svc.validate_vk_token = AsyncMock(return_value=validate_vk_result)
    svc.create = AsyncMock(return_value=created_conn or _make_social_conn())
    p = patch(f"{_MODULE}.ConnectionService", return_value=svc)
    return svc, p


def _patch_http_client() -> Any:
    return patch(f"{_MODULE}._get_http_client", return_value=MagicMock())


def _patch_http_client_msg() -> Any:
    return patch(f"{_MODULE}._get_http_client_from_msg", return_value=MagicMock())


def _patch_category_step() -> Any:
    return patch(
        "routers.publishing.pipeline.social.social._show_category_step",
        new_callable=AsyncMock,
    )


def _patch_category_step_msg() -> Any:
    return patch(
        "routers.publishing.pipeline.social.social._show_category_step_msg",
        new_callable=AsyncMock,
    )


# ---------------------------------------------------------------------------
# _show_connection_step
# ---------------------------------------------------------------------------


class TestShowConnectionStep:
    async def test_zero_connections_shows_platform_picker(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        _, svc_patch = _mock_conn_svc(social_conns=[])
        with svc_patch, _patch_http_client():
            await _show_connection_step(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
                1,
                "Test",
            )

        mock_state.set_state.assert_awaited_once_with(SocialPipelineFSM.select_connection)
        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Подключите соцсеть" in text

    async def test_one_connection_auto_selects(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        conn = _make_social_conn(id=5, platform_type="telegram")
        _, svc_patch = _mock_conn_svc(social_conns=[conn])
        with svc_patch, _patch_http_client(), _patch_category_step() as cat_mock:
            await _show_connection_step(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
                1,
                "Test",
            )

        mock_state.update_data.assert_any_await(connection_id=5, platform_type="telegram")
        cat_mock.assert_awaited_once()

    async def test_multiple_connections_shows_list(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        c1 = _make_social_conn(id=5, platform_type="telegram", identifier="@ch1")
        c2 = _make_social_conn(id=6, platform_type="vk", identifier="club123")
        _, svc_patch = _mock_conn_svc(social_conns=[c1, c2])
        with svc_patch, _patch_http_client():
            await _show_connection_step(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
                1,
                "Test",
            )

        mock_state.set_state.assert_awaited_once_with(SocialPipelineFSM.select_connection)
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Куда публикуем" in text


# ---------------------------------------------------------------------------
# pipeline_select_connection
# ---------------------------------------------------------------------------


class TestSelectConnection:
    async def test_valid_connection_selected(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        conn = _make_social_conn(id=7, project_id=1, platform_type="telegram")
        mock_callback.data = "pipeline:social:1:conn:7"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1, "project_name": "Test"})
        _, svc_patch = _mock_conn_svc(conn=conn)
        with svc_patch, _patch_http_client(), _patch_category_step() as cat_mock:
            await pipeline_select_connection(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
            )

        mock_state.update_data.assert_any_await(connection_id=7, platform_type="telegram")
        cat_mock.assert_awaited_once()

    async def test_wrong_project_shows_alert(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        mock_callback.data = "pipeline:social:1:conn:7"
        mock_state.get_data = AsyncMock(return_value={"project_id": 2, "project_name": "Other"})
        await pipeline_select_connection(
            mock_callback,
            mock_state,
            user,
            MagicMock(),
            mock_redis,
        )
        mock_callback.answer.assert_awaited()
        assert "не совпадает" in mock_callback.answer.call_args[0][0]

    async def test_connection_not_found(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        mock_callback.data = "pipeline:social:1:conn:999"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1, "project_name": "Test"})
        _, svc_patch = _mock_conn_svc(conn=None)
        with svc_patch, _patch_http_client():
            await pipeline_select_connection(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
            )
        mock_callback.answer.assert_awaited()
        assert "не найдено" in mock_callback.answer.call_args[0][0]


# ---------------------------------------------------------------------------
# pipeline_add_connection (P1-3 fix)
# ---------------------------------------------------------------------------


class TestAddConnection:
    async def test_hides_already_connected_types(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={"project_id": 1})
        _, svc_patch = _mock_conn_svc(platform_types=["telegram"])
        with svc_patch, _patch_http_client():
            await pipeline_add_connection(mock_callback, mock_state, user, MagicMock())

        mock_callback.message.edit_text.assert_awaited_once()
        # Verify the keyboard was built with exclude_types
        kb = mock_callback.message.edit_text.call_args[1]["reply_markup"]
        button_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "Подключить Телеграм" not in button_texts
        assert "Подключить ВКонтакте" in button_texts

    async def test_all_platforms_connected_shows_alert(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        user: Any,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={"project_id": 1})
        _, svc_patch = _mock_conn_svc(platform_types=["telegram", "vk", "pinterest"])
        with svc_patch, _patch_http_client():
            await pipeline_add_connection(mock_callback, mock_state, user, MagicMock())

        mock_callback.answer.assert_awaited()
        assert "Все платформы" in mock_callback.answer.call_args[0][0]


# ---------------------------------------------------------------------------
# TG inline connect — channel (state 1)
# ---------------------------------------------------------------------------


class TestTGInlineChannel:
    async def test_start_sets_state(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        await pipeline_start_connect_tg(mock_callback, mock_state)
        mock_state.set_state.assert_awaited_once_with(SocialPipelineFSM.connect_tg_channel)

    async def test_invalid_channel_format(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
    ) -> None:
        mock_message.text = "not-a-channel"
        await pipeline_connect_tg_channel(mock_message, mock_state, user, MagicMock())
        mock_message.answer.assert_awaited_once()
        assert "Неверный формат" in mock_message.answer.call_args[0][0]

    async def test_valid_channel_proceeds(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
    ) -> None:
        mock_message.text = "@testchannel"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1})
        _, svc_patch = _mock_conn_svc(by_project_platform=[], by_identifier_global=None)
        with svc_patch, _patch_http_client_msg():
            await pipeline_connect_tg_channel(mock_message, mock_state, user, MagicMock())

        mock_state.update_data.assert_any_await(tg_channel="@testchannel")
        mock_state.set_state.assert_awaited_once_with(SocialPipelineFSM.connect_tg_token)

    async def test_duplicate_tg_per_project(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
    ) -> None:
        mock_message.text = "@testchannel"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1})
        existing_conn = _make_social_conn()
        _, svc_patch = _mock_conn_svc(by_project_platform=[existing_conn])
        with svc_patch, _patch_http_client_msg():
            await pipeline_connect_tg_channel(mock_message, mock_state, user, MagicMock())

        mock_message.answer.assert_awaited_once()
        assert "уже есть" in mock_message.answer.call_args[0][0]

    async def test_e41_global_uniqueness(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: Any,
    ) -> None:
        mock_message.text = "@testchannel"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1})
        dup = _make_social_conn()
        _, svc_patch = _mock_conn_svc(by_project_platform=[], by_identifier_global=dup)
        with svc_patch, _patch_http_client_msg():
            await pipeline_connect_tg_channel(mock_message, mock_state, user, MagicMock())

        mock_message.answer.assert_awaited_once()
        assert "другим пользователем" in mock_message.answer.call_args[0][0]


# ---------------------------------------------------------------------------
# TG inline connect — token (state 2)
# ---------------------------------------------------------------------------


class TestTGInlineToken:
    async def test_invalid_token_format(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "short"
        mock_message.delete = AsyncMock()
        await pipeline_connect_tg_token(mock_message, mock_state)
        mock_message.answer.assert_awaited_once()
        assert "Неверный формат токена" in mock_message.answer.call_args[0][0]

    async def test_valid_token_proceeds(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "123456789:AABBccddEEFFgghhIIjjKKllMMnn"
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(return_value={"tg_channel": "@test"})
        await pipeline_connect_tg_token(mock_message, mock_state)

        mock_message.delete.assert_awaited_once()  # Security: delete token
        mock_state.update_data.assert_any_await(
            tg_token="123456789:AABBccddEEFFgghhIIjjKKllMMnn",
        )
        mock_state.set_state.assert_awaited_once_with(SocialPipelineFSM.connect_tg_verify)

    async def test_token_message_deleted(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "123456789:AABBccddEEFFgghhIIjjKKllMMnn"
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(return_value={"tg_channel": "@test"})
        await pipeline_connect_tg_token(mock_message, mock_state)
        mock_message.delete.assert_awaited_once()


# ---------------------------------------------------------------------------
# TG inline connect — verify (state 3, P0 fix)
# ---------------------------------------------------------------------------


class TestTGInlineVerify:
    async def test_successful_verify(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        mock_state.get_data = AsyncMock(
            return_value={
                "tg_token": "123:AAA",
                "tg_channel": "@test",
                "project_id": 1,
                "project_name": "Test",
            }
        )

        # Mock Bot
        mock_bot = MagicMock()
        mock_bot_info = MagicMock()
        mock_bot_info.id = 999
        mock_bot_info.username = "testbot"
        mock_bot.get_me = AsyncMock(return_value=mock_bot_info)

        admin = MagicMock()
        admin.user = MagicMock()
        admin.user.id = 999
        admin.can_post_messages = True
        mock_bot.get_chat_administrators = AsyncMock(return_value=[admin])
        mock_bot.session = MagicMock()
        mock_bot.session.close = AsyncMock()

        created = _make_social_conn(id=10, platform_type="telegram")
        _, svc_patch = _mock_conn_svc(created_conn=created)

        with (
            patch(f"{_MODULE}.Bot", return_value=mock_bot),
            svc_patch,
            _patch_http_client(),
            _patch_category_step_msg(),
        ):
            await pipeline_connect_tg_verify(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
            )

        mock_state.update_data.assert_any_await(connection_id=10, platform_type="telegram")
        mock_bot.session.close.assert_awaited_once()

    async def test_bot_not_admin(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        mock_state.get_data = AsyncMock(
            return_value={
                "tg_token": "123:AAA",
                "tg_channel": "@test",
                "project_id": 1,
                "project_name": "Test",
            }
        )

        mock_bot = MagicMock()
        mock_bot_info = MagicMock()
        mock_bot_info.id = 999
        mock_bot.get_me = AsyncMock(return_value=mock_bot_info)
        # Admin list doesn't contain our bot
        mock_bot.get_chat_administrators = AsyncMock(return_value=[])
        mock_bot.session = MagicMock()
        mock_bot.session.close = AsyncMock()

        with patch(f"{_MODULE}.Bot", return_value=mock_bot):
            await pipeline_connect_tg_verify(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
            )

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "не является администратором" in text
        mock_bot.session.close.assert_awaited_once()

    async def test_invalid_token_shows_error(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        mock_state.get_data = AsyncMock(
            return_value={
                "tg_token": "badtoken",
                "tg_channel": "@test",
                "project_id": 1,
                "project_name": "Test",
            }
        )

        mock_bot = MagicMock()
        mock_bot.get_me = AsyncMock(side_effect=Exception("Invalid token"))
        mock_bot.session = MagicMock()
        mock_bot.session.close = AsyncMock()

        with patch(f"{_MODULE}.Bot", return_value=mock_bot):
            await pipeline_connect_tg_verify(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
            )

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Не удалось подключиться" in text
        mock_bot.session.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# VK inline connect
# ---------------------------------------------------------------------------


class TestVKInlineConnect:
    async def test_start_sets_state(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        await pipeline_start_connect_vk(mock_callback, mock_state)
        mock_state.set_state.assert_awaited_once_with(SocialPipelineFSM.connect_vk_token)

    async def test_short_token_rejected(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        mock_message.text = "short"
        mock_message.delete = AsyncMock()
        await pipeline_connect_vk_token(
            mock_message,
            mock_state,
            user,
            MagicMock(),
            mock_redis,
        )
        mock_message.answer.assert_awaited_once()
        assert "короткий" in mock_message.answer.call_args[0][0]

    async def test_invalid_vk_token(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        mock_message.text = "a" * 30
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(return_value={"project_id": 1, "project_name": "T"})
        _, svc_patch = _mock_conn_svc(
            validate_vk_result=("Недействительный токен.", []),
            by_project_platform=[],
        )
        with svc_patch, _patch_http_client_msg():
            await pipeline_connect_vk_token(
                mock_message,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
            )
        # Error message shown
        mock_message.answer.assert_awaited()
        calls = mock_message.answer.call_args_list
        assert any("Недействительный" in str(c) for c in calls)

    async def test_single_group_auto_creates(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        mock_message.text = "a" * 30
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(return_value={"project_id": 1, "project_name": "T"})
        groups = [{"id": 100, "name": "My Group"}]
        created = _make_social_conn(id=20, platform_type="vk", identifier="club100")
        _, svc_patch = _mock_conn_svc(
            validate_vk_result=(None, groups),
            by_project_platform=[],
            created_conn=created,
        )
        with svc_patch, _patch_http_client_msg(), _patch_category_step_msg():
            await pipeline_connect_vk_token(
                mock_message,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
            )

        mock_state.update_data.assert_any_await(connection_id=20, platform_type="vk")

    async def test_multiple_groups_shows_picker(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        mock_message.text = "a" * 30
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(return_value={"project_id": 1, "project_name": "T"})
        groups = [{"id": 100, "name": "G1"}, {"id": 200, "name": "G2"}]
        _, svc_patch = _mock_conn_svc(
            validate_vk_result=(None, groups),
            by_project_platform=[],
        )
        with svc_patch, _patch_http_client_msg():
            await pipeline_connect_vk_token(
                mock_message,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
            )

        mock_state.set_state.assert_awaited_once_with(SocialPipelineFSM.connect_vk_group)

    async def test_vk_token_message_deleted(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        mock_message.text = "a" * 30
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(return_value={"project_id": 1, "project_name": "T"})
        _, svc_patch = _mock_conn_svc(
            validate_vk_result=("err", []),
            by_project_platform=[],
        )
        with svc_patch, _patch_http_client_msg():
            await pipeline_connect_vk_token(
                mock_message,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
            )
        mock_message.delete.assert_awaited_once()

    async def test_duplicate_vk_per_project(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        mock_message.text = "a" * 30
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(return_value={"project_id": 1, "project_name": "T"})
        existing = _make_social_conn(platform_type="vk")
        _, svc_patch = _mock_conn_svc(by_project_platform=[existing])
        with svc_patch, _patch_http_client_msg():
            await pipeline_connect_vk_token(
                mock_message,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
            )
        mock_message.answer.assert_awaited()
        calls = mock_message.answer.call_args_list
        assert any("уже есть" in str(c) for c in calls)


class TestVKGroupSelect:
    async def test_select_group_creates_connection(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        mock_callback.data = "pipeline:social:vk_group:100"
        groups = [{"id": 100, "name": "My Group"}]
        created = _make_social_conn(id=25, platform_type="vk")
        mock_state.get_data = AsyncMock(
            return_value={
                "vk_groups": groups,
                "vk_token": "tok",
                "project_id": 1,
                "project_name": "T",
            }
        )
        _, svc_patch = _mock_conn_svc(created_conn=created)
        with svc_patch, _patch_http_client(), _patch_category_step_msg():
            await pipeline_select_vk_group(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
            )

        mock_state.update_data.assert_any_await(connection_id=25, platform_type="vk")


# ---------------------------------------------------------------------------
# Pinterest OAuth entry
# ---------------------------------------------------------------------------


class TestPinterestOAuth:
    async def test_generates_nonce_and_shows_url(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={"project_id": 1})
        with patch("bot.config.get_settings") as settings_mock:
            settings_mock.return_value = MagicMock(railway_public_url="https://bot.example.com")
            await pipeline_start_connect_pinterest(
                mock_callback,
                mock_state,
                user,
                mock_redis,
            )

        mock_state.set_state.assert_awaited_once_with(SocialPipelineFSM.connect_pinterest_oauth)
        mock_redis.set.assert_awaited_once()
        # Check nonce stored in Redis
        redis_key = mock_redis.set.call_args[0][0]
        assert "pinterest_oauth:" in redis_key


# ---------------------------------------------------------------------------
# Normalize TG channel helper
# ---------------------------------------------------------------------------


class TestNormalizeTGChannel:
    async def test_at_format(self) -> None:
        assert _normalize_tg_channel("@mychannel") == "@mychannel"

    async def test_tme_link(self) -> None:
        assert _normalize_tg_channel("https://t.me/mychannel") == "@mychannel"

    async def test_tme_no_scheme(self) -> None:
        assert _normalize_tg_channel("t.me/mychannel") == "@mychannel"

    async def test_numeric_id(self) -> None:
        assert _normalize_tg_channel("-1001234567890") == "-1001234567890"

    async def test_bare_name(self) -> None:
        assert _normalize_tg_channel("mychannel") == "@mychannel"
