"""Tests for OAuth pipeline return in start.py.

Verifies P0 fix: after VK/Pinterest OAuth deep-link, user returns
to social pipeline instead of Dashboard (FSM_SPEC.md:419-423).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.fernet import Fernet

from routers.start import (
    _handle_pinterest_deep_link,
    _handle_vk_deep_link,
    _return_to_pipeline,
    vk_group_select_deeplink,
)
from tests.unit.routers.conftest import make_project, make_user

_FERNET_KEY = Fernet.generate_key().decode()

_MODULE = "routers.start"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_http_client() -> MagicMock:
    return MagicMock()


def _make_state() -> MagicMock:
    state = MagicMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    state.get_state = AsyncMock(return_value=None)
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    return state


def _make_redis(
    *,
    auth_tokens: dict[str, Any] | None = None,
    meta: dict[str, Any] | str | None = None,
) -> MagicMock:
    redis = MagicMock()
    redis.delete = AsyncMock(return_value=1)

    async def _get(key: str) -> str | None:
        if "pinterest_auth:" in key and auth_tokens:
            return json.dumps(auth_tokens)
        if "pinterest_oauth:" in key and meta is not None:
            return json.dumps(meta) if isinstance(meta, dict) else str(meta)
        return None

    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock(return_value="OK")
    return redis


def _make_message() -> MagicMock:
    msg = MagicMock()
    msg.answer = AsyncMock()
    msg.answer_photo = AsyncMock()
    msg.edit_text = AsyncMock()
    msg.delete = AsyncMock()
    msg.text = "/start pinterest_auth_abc123"
    return msg


# ---------------------------------------------------------------------------
# _return_to_pipeline
# ---------------------------------------------------------------------------


class TestReturnToPipeline:
    async def test_calls_show_connection_step_msg(self) -> None:
        msg = _make_message()
        state = _make_state()
        user = make_user()
        redis = MagicMock()
        redis.set = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        db = MagicMock()
        http = _mock_http_client()
        project = make_project(id=5, name="My Project")

        with patch(
            "routers.publishing.pipeline.social.connection._show_connection_step_msg",
            new_callable=AsyncMock,
        ) as mock_show:
            await _return_to_pipeline(msg, state, user, db, redis, http, project)

        state.update_data.assert_any_await(project_id=5, project_name="My Project")
        mock_show.assert_awaited_once()


# ---------------------------------------------------------------------------
# _handle_pinterest_deep_link — from_pipeline
# ---------------------------------------------------------------------------


class TestPinterestDeepLinkPipeline:
    async def test_from_pipeline_true_calls_return(self) -> None:
        msg = _make_message()
        state = _make_state()
        user = make_user()
        db = MagicMock()
        http = _mock_http_client()
        project = make_project(id=1, name="Test")

        tokens = {"access_token": "tok", "refresh_token": "ref", "expires_in": 2592000}
        meta = {"project_id": 1, "from_pipeline": True}
        redis = _make_redis(auth_tokens=tokens, meta=meta)

        with (
            patch(f"{_MODULE}.ProjectsRepository") as projects_cls,
            patch(f"{_MODULE}.ConnectionsRepository") as conn_cls,
            patch(f"{_MODULE}._return_to_pipeline", new_callable=AsyncMock) as ret_mock,
            patch(f"{_MODULE}.get_settings") as settings_mock,
        ):
            mock_encryption_key = MagicMock()
            mock_encryption_key.get_secret_value.return_value = _FERNET_KEY
            settings_mock.return_value = MagicMock(encryption_key=mock_encryption_key)

            projects_cls.return_value.get_by_id = AsyncMock(return_value=project)
            conn_cls.return_value.create = AsyncMock(return_value=MagicMock(id=99))

            await _handle_pinterest_deep_link(msg, state, user, db, redis, http, "abc123")

        ret_mock.assert_awaited_once()

    async def test_from_pipeline_false_no_return(self) -> None:
        msg = _make_message()
        state = _make_state()
        user = make_user()
        db = MagicMock()
        http = _mock_http_client()
        project = make_project(id=1, name="Test")

        tokens = {"access_token": "tok", "refresh_token": "ref"}
        meta = {"project_id": 1}  # no from_pipeline
        redis = _make_redis(auth_tokens=tokens, meta=meta)

        with (
            patch(f"{_MODULE}.ProjectsRepository") as projects_cls,
            patch(f"{_MODULE}.ConnectionsRepository") as conn_cls,
            patch(f"{_MODULE}._return_to_pipeline", new_callable=AsyncMock) as ret_mock,
            patch(f"{_MODULE}.get_settings") as settings_mock,
        ):
            mock_encryption_key = MagicMock()
            mock_encryption_key.get_secret_value.return_value = _FERNET_KEY
            settings_mock.return_value = MagicMock(encryption_key=mock_encryption_key)

            projects_cls.return_value.get_by_id = AsyncMock(return_value=project)
            conn_cls.return_value.create = AsyncMock(return_value=MagicMock(id=99))

            await _handle_pinterest_deep_link(msg, state, user, db, redis, http, "abc123")

        ret_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# _handle_vk_deep_link — from_pipeline (single group)
# ---------------------------------------------------------------------------


class TestVKDeepLinkPipeline:
    async def test_single_group_from_pipeline_calls_return(self) -> None:
        from services.oauth.vk import VKDeepLinkResult

        msg = _make_message()
        state = _make_state()
        user = make_user()
        db = MagicMock()
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        redis.delete = AsyncMock()
        http = _mock_http_client()
        project = make_project(id=1, name="Test")

        dl = VKDeepLinkResult(
            groups=[{"id": 100, "name": "Group"}],
            project_id=1,
            access_token="tok",
            refresh_token="ref",
            expires_at="2026-12-31T00:00:00",
            device_id="dev",
            raw_result={},
            from_pipeline=True,
        )

        with (
            patch(f"{_MODULE}._build_vk_oauth_service") as vk_svc_mock,
            patch(f"{_MODULE}.ProjectsRepository") as projects_cls,
            patch(f"{_MODULE}._create_vk_connection", new_callable=AsyncMock),
            patch(f"{_MODULE}._return_to_pipeline", new_callable=AsyncMock) as ret_mock,
        ):
            svc = MagicMock()
            svc.process_deep_link = AsyncMock(return_value=dl)
            svc.cleanup_meta = AsyncMock()
            vk_svc_mock.return_value = svc
            projects_cls.return_value.get_by_id = AsyncMock(return_value=project)

            await _handle_vk_deep_link(msg, state, user, db, redis, http, "nonce1")

        ret_mock.assert_awaited_once()

    async def test_single_group_no_pipeline_no_return(self) -> None:
        from services.oauth.vk import VKDeepLinkResult

        msg = _make_message()
        state = _make_state()
        user = make_user()
        db = MagicMock()
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        redis.delete = AsyncMock()
        http = _mock_http_client()
        project = make_project(id=1, name="Test")

        dl = VKDeepLinkResult(
            groups=[{"id": 100, "name": "Group"}],
            project_id=1,
            access_token="tok",
            refresh_token="ref",
            expires_at="2026-12-31T00:00:00",
            device_id="dev",
            raw_result={},
            from_pipeline=False,
        )

        with (
            patch(f"{_MODULE}._build_vk_oauth_service") as vk_svc_mock,
            patch(f"{_MODULE}.ProjectsRepository") as projects_cls,
            patch(f"{_MODULE}._create_vk_connection", new_callable=AsyncMock),
            patch(f"{_MODULE}._return_to_pipeline", new_callable=AsyncMock) as ret_mock,
        ):
            svc = MagicMock()
            svc.process_deep_link = AsyncMock(return_value=dl)
            svc.cleanup_meta = AsyncMock()
            vk_svc_mock.return_value = svc
            projects_cls.return_value.get_by_id = AsyncMock(return_value=project)

            await _handle_vk_deep_link(msg, state, user, db, redis, http, "nonce1")

        ret_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# vk_group_select_deeplink — from_pipeline
# ---------------------------------------------------------------------------


class TestVKGroupSelectPipeline:
    async def test_group_select_from_pipeline_calls_return(self) -> None:
        callback = MagicMock()
        callback.data = "vk_auth:nonce1:100"
        callback.answer = AsyncMock()
        callback.message = _make_message()
        state = _make_state()
        user = make_user()
        db = MagicMock()
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        redis.delete = AsyncMock()
        http = _mock_http_client()
        project = make_project(id=1, name="Test")

        stored_result = {
            "groups": [{"id": 100, "name": "Group"}],
            "access_token": "tok",
            "refresh_token": "ref",
            "expires_in": 3600,
            "device_id": "dev",
        }
        meta = {"project_id": 1, "from_pipeline": True}

        with (
            patch(f"{_MODULE}._build_vk_oauth_service") as vk_svc_mock,
            patch(f"{_MODULE}.ProjectsRepository") as projects_cls,
            patch(f"{_MODULE}.ConnectionService") as conn_svc_cls,
            patch(f"{_MODULE}._return_to_pipeline", new_callable=AsyncMock) as ret_mock,
        ):
            svc = MagicMock()
            svc.get_stored_result = AsyncMock(return_value=stored_result)
            svc.get_meta = AsyncMock(return_value=meta)
            svc.cleanup = AsyncMock()
            vk_svc_mock.return_value = svc

            projects_cls.return_value.get_by_id = AsyncMock(return_value=project)
            conn_svc_cls.return_value.create_vk_from_oauth = AsyncMock(
                return_value=MagicMock(id=99)
            )

            await vk_group_select_deeplink(callback, state, user, db, redis, http)

        ret_mock.assert_awaited_once()
