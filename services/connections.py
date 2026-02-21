"""Connection service — platform validation and CRUD.

Extracts HTTP validation logic (WP REST, TG Bot API, VK API) from routers
into a Telegram-independent service. Zero Aiogram/Bot dependencies.

Source of truth: UX_TOOLBOX.md §5, ARCHITECTURE.md §2 ("services = business logic").
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from bot.config import get_settings
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import PlatformConnection, PlatformConnectionCreate
from db.repositories.connections import ConnectionsRepository

log = structlog.get_logger()


class ConnectionService:
    """Validates platform credentials and manages connections.

    All HTTP calls are isolated here so routers stay thin.
    """

    def __init__(self, db: SupabaseClient, http_client: httpx.AsyncClient) -> None:
        settings = get_settings()
        cm = CredentialManager(settings.encryption_key.get_secret_value())
        self._repo = ConnectionsRepository(db, cm)
        self._http = http_client

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    async def validate_wordpress(
        self,
        url: str,
        login: str,
        password: str,
    ) -> str | None:
        """Validate WP REST API credentials.

        Returns error message string on failure, None on success.
        """
        api_url = f"{url}/wp-json/wp/v2/posts"
        try:
            resp = await self._http.head(
                api_url,
                auth=httpx.BasicAuth(login, password),
                timeout=10.0,
            )
            if resp.status_code == 401:
                return "Неверный логин или пароль. Попробуйте ещё раз."
            if resp.status_code >= 400:
                return f"Сайт вернул ошибку ({resp.status_code}). Проверьте URL и данные."
        except httpx.TimeoutException:
            return "Сайт не отвечает. Проверьте URL."
        except httpx.RequestError:
            return "Не удалось подключиться к сайту. Проверьте URL."
        return None

    async def validate_vk_token(self, token: str) -> tuple[str | None, list[dict[str, Any]]]:
        """Validate VK token and fetch user's admin/editor groups.

        Returns (error_msg, groups). error_msg is None on success.
        """
        # Step 1: validate token via users.get
        try:
            resp = await self._http.get(
                "https://api.vk.com/method/users.get",
                params={"access_token": token, "v": "5.199"},
                timeout=10.0,
            )
            data = resp.json()
            if "error" in data:
                return "Недействительный токен. Попробуйте ещё раз.", []
        except Exception:
            return "Ошибка проверки токена. Попробуйте позже.", []

        # Step 2: get user's groups
        try:
            resp = await self._http.get(
                "https://api.vk.com/method/groups.get",
                params={
                    "access_token": token,
                    "v": "5.199",
                    "filter": "admin,editor",
                    "extended": "1",
                    "count": "50",
                },
                timeout=10.0,
            )
            groups_data = resp.json()
            groups: list[dict[str, Any]] = groups_data.get("response", {}).get("items", [])
        except Exception:
            return "Ошибка получения списка групп.", []

        if not groups:
            return "У вас нет групп VK, в которых вы администратор или редактор.", []

        return None, groups

    # ------------------------------------------------------------------
    # CRUD (delegate to repository)
    # ------------------------------------------------------------------

    async def get_by_id(self, connection_id: int) -> PlatformConnection | None:
        """Get connection by ID."""
        return await self._repo.get_by_id(connection_id)

    async def get_by_project(self, project_id: int) -> list[PlatformConnection]:
        """Get all connections for a project."""
        return await self._repo.get_by_project(project_id)

    async def get_by_project_and_platform(
        self,
        project_id: int,
        platform_type: str,
    ) -> list[PlatformConnection]:
        """Get connections filtered by project + platform."""
        return await self._repo.get_by_project_and_platform(project_id, platform_type)

    async def get_by_identifier_global(
        self,
        identifier: str,
        platform_type: str,
    ) -> PlatformConnection | None:
        """Find connection by identifier+platform across ALL users (E41)."""
        return await self._repo.get_by_identifier_global(identifier, platform_type)

    async def get_platform_types_by_project(self, project_id: int) -> list[str]:
        """Get distinct active platform types for a project."""
        return await self._repo.get_platform_types_by_project(project_id)

    async def get_social_connections(self, project_id: int) -> list[PlatformConnection]:
        """Get active social platform connections (TG/VK/Pinterest) for a project."""
        all_conns = await self._repo.get_by_project(project_id)
        social_types = {"telegram", "vk", "pinterest"}
        return [c for c in all_conns if c.platform_type in social_types and c.status == "active"]

    async def create(
        self,
        data: PlatformConnectionCreate,
        raw_credentials: dict[str, Any],
    ) -> PlatformConnection:
        """Create connection with encrypted credentials."""
        return await self._repo.create(data, raw_credentials)

    async def delete(self, connection_id: int) -> bool:
        """Delete connection."""
        return await self._repo.delete(connection_id)
