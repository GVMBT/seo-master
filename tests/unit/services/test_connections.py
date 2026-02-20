"""Tests for services/connections.py — ConnectionService.

Covers: WP validation, VK validation, CRUD delegation, error paths.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from services.connections import ConnectionService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MODULE = "services.connections"


def _make_service(
    *,
    http_responses: list[httpx.Response] | None = None,
    http_error: Exception | None = None,
) -> tuple[ConnectionService, AsyncMock]:
    """Create a ConnectionService with mocked DB and HTTP client."""
    mock_db = MagicMock()
    mock_repo = AsyncMock()

    if http_error:
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.head = AsyncMock(side_effect=http_error)
        mock_http.get = AsyncMock(side_effect=http_error)
    elif http_responses:
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.head = AsyncMock(return_value=http_responses[0])
        if len(http_responses) > 1:
            mock_http.get = AsyncMock(side_effect=http_responses[1:])
        else:
            mock_http.get = AsyncMock(return_value=http_responses[0])
    else:
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.head = AsyncMock(return_value=httpx.Response(200))
        mock_http.get = AsyncMock(return_value=httpx.Response(200, json={"response": [{}]}))

    with (
        patch(f"{_MODULE}.get_settings") as mock_settings,
        patch(f"{_MODULE}.CredentialManager"),
        patch(f"{_MODULE}.ConnectionsRepository", return_value=mock_repo),
    ):
        mock_settings.return_value.encryption_key.get_secret_value.return_value = "fake-key"
        svc = ConnectionService(mock_db, mock_http)

    # Replace repo with our mock for assertion access
    svc._repo = mock_repo
    return svc, mock_repo


# ---------------------------------------------------------------------------
# WordPress validation
# ---------------------------------------------------------------------------


class TestValidateWordpress:
    async def test_success_returns_none(self) -> None:
        svc, _ = _make_service(http_responses=[httpx.Response(200)])
        result = await svc.validate_wordpress("https://example.com", "admin", "pass123")
        assert result is None

    async def test_401_returns_auth_error(self) -> None:
        svc, _ = _make_service(http_responses=[httpx.Response(401)])
        result = await svc.validate_wordpress("https://example.com", "admin", "wrong")
        assert result is not None
        assert "логин" in result.lower() or "пароль" in result.lower()

    async def test_500_returns_server_error(self) -> None:
        svc, _ = _make_service(http_responses=[httpx.Response(500)])
        result = await svc.validate_wordpress("https://example.com", "admin", "pass")
        assert result is not None
        assert "500" in result

    async def test_403_returns_error(self) -> None:
        svc, _ = _make_service(http_responses=[httpx.Response(403)])
        result = await svc.validate_wordpress("https://example.com", "admin", "pass")
        assert result is not None
        assert "403" in result

    async def test_timeout_returns_error(self) -> None:
        svc, _ = _make_service(http_error=httpx.TimeoutException("timed out"))
        result = await svc.validate_wordpress("https://slow.com", "admin", "pass")
        assert result is not None
        assert "не отвечает" in result.lower()

    async def test_connection_error_returns_error(self) -> None:
        svc, _ = _make_service(http_error=httpx.ConnectError("refused"))
        result = await svc.validate_wordpress("https://down.com", "admin", "pass")
        assert result is not None
        assert "подключиться" in result.lower()

    async def test_uses_correct_url(self) -> None:
        svc, _ = _make_service(http_responses=[httpx.Response(200)])
        await svc.validate_wordpress("https://blog.example.com", "admin", "pass")
        call_args = svc._http.head.call_args
        assert "/wp-json/wp/v2/posts" in call_args[0][0]


# ---------------------------------------------------------------------------
# VK validation
# ---------------------------------------------------------------------------


class TestValidateVkToken:
    async def test_valid_token_with_groups(self) -> None:
        users_resp = httpx.Response(200, json={"response": [{"id": 1}]})
        groups_resp = httpx.Response(
            200,
            json={
                "response": {
                    "count": 2,
                    "items": [
                        {"id": 100, "name": "Group 1"},
                        {"id": 200, "name": "Group 2"},
                    ],
                },
            },
        )
        svc, _ = _make_service(http_responses=[users_resp, users_resp, groups_resp])
        # Override get to return side_effect sequence
        svc._http.get = AsyncMock(side_effect=[users_resp, groups_resp])

        error, groups = await svc.validate_vk_token("valid_token")
        assert error is None
        assert len(groups) == 2

    async def test_invalid_token_returns_error(self) -> None:
        error_resp = httpx.Response(200, json={"error": {"error_code": 5}})
        svc, _ = _make_service(http_responses=[error_resp])
        svc._http.get = AsyncMock(return_value=error_resp)

        error, groups = await svc.validate_vk_token("bad_token")
        assert error is not None
        assert "токен" in error.lower()
        assert groups == []

    async def test_no_groups_returns_error(self) -> None:
        users_resp = httpx.Response(200, json={"response": [{"id": 1}]})
        groups_resp = httpx.Response(200, json={"response": {"count": 0, "items": []}})
        svc, _ = _make_service()
        svc._http.get = AsyncMock(side_effect=[users_resp, groups_resp])

        error, groups = await svc.validate_vk_token("token_no_groups")
        assert error is not None
        assert "нет групп" in error.lower()
        assert groups == []

    async def test_network_error_on_users_get(self) -> None:
        svc, _ = _make_service(http_error=httpx.ConnectError("refused"))

        error, groups = await svc.validate_vk_token("token")
        assert error is not None
        assert groups == []

    async def test_network_error_on_groups_get(self) -> None:
        users_resp = httpx.Response(200, json={"response": [{"id": 1}]})
        svc, _ = _make_service()
        svc._http.get = AsyncMock(side_effect=[users_resp, httpx.ConnectError("refused")])

        error, groups = await svc.validate_vk_token("token")
        assert error is not None
        assert "групп" in error.lower()
        assert groups == []


# ---------------------------------------------------------------------------
# CRUD delegation
# ---------------------------------------------------------------------------


class TestCrudDelegation:
    async def test_get_by_id_delegates(self) -> None:
        svc, repo = _make_service()
        repo.get_by_id.return_value = MagicMock(id=1)
        result = await svc.get_by_id(1)
        repo.get_by_id.assert_awaited_once_with(1)
        assert result.id == 1

    async def test_get_by_project_delegates(self) -> None:
        svc, repo = _make_service()
        repo.get_by_project.return_value = [MagicMock(), MagicMock()]
        result = await svc.get_by_project(42)
        repo.get_by_project.assert_awaited_once_with(42)
        assert len(result) == 2

    async def test_get_by_project_and_platform_delegates(self) -> None:
        svc, repo = _make_service()
        repo.get_by_project_and_platform.return_value = [MagicMock()]
        result = await svc.get_by_project_and_platform(42, "wordpress")
        repo.get_by_project_and_platform.assert_awaited_once_with(42, "wordpress")
        assert len(result) == 1

    async def test_get_by_identifier_global_delegates(self) -> None:
        svc, repo = _make_service()
        repo.get_by_identifier_global.return_value = None
        result = await svc.get_by_identifier_global("@channel", "telegram")
        repo.get_by_identifier_global.assert_awaited_once_with("@channel", "telegram")
        assert result is None

    async def test_get_platform_types_by_project_delegates(self) -> None:
        svc, repo = _make_service()
        repo.get_platform_types_by_project.return_value = ["wordpress", "telegram"]
        result = await svc.get_platform_types_by_project(42)
        assert result == ["wordpress", "telegram"]

    async def test_create_delegates(self) -> None:
        svc, repo = _make_service()
        mock_conn = MagicMock(id=5)
        repo.create.return_value = mock_conn
        data = MagicMock()
        creds = {"login": "admin", "password": "secret"}
        result = await svc.create(data, creds)
        repo.create.assert_awaited_once_with(data, creds)
        assert result.id == 5

    async def test_delete_delegates(self) -> None:
        svc, repo = _make_service()
        repo.delete.return_value = True
        result = await svc.delete(99)
        repo.delete.assert_awaited_once_with(99)
        assert result is True
