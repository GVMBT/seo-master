"""Service factory functions for DI via dp.workflow_data (S6).

Services that depend on per-request `db` cannot be singletons.
Factory callables accept `db` and return the configured service instance.
This eliminates repeated `TokenService(db=db, admin_ids=settings.admin_ids)` boilerplate.

Usage in handlers:
    token_service = token_service_factory(db)
    conn_service = connection_service_factory(db, http_client)
"""

from __future__ import annotations

import httpx

from db.client import SupabaseClient
from services.connections import ConnectionService
from services.tokens import TokenService


def create_token_service_factory(admin_ids: list[int]) -> TokenServiceFactory:
    """Create a factory that produces TokenService instances with bound admin_ids.

    Registered once in dp.workflow_data["token_service_factory"].
    Called per-handler: `token_svc = token_service_factory(db)`
    """
    return TokenServiceFactory(admin_ids)


def create_connection_service_factory() -> ConnectionServiceFactory:
    """Create a factory that produces ConnectionService instances.

    Registered once in dp.workflow_data["connection_service_factory"].
    Called per-handler: `conn_svc = connection_service_factory(db, http_client)`
    """
    return ConnectionServiceFactory()


class TokenServiceFactory:
    """Callable factory for TokenService — binds admin_ids at setup time."""

    def __init__(self, admin_ids: list[int]) -> None:
        self._admin_ids = admin_ids

    def __call__(self, db: SupabaseClient) -> TokenService:
        return TokenService(db=db, admin_ids=self._admin_ids)


class ConnectionServiceFactory:
    """Callable factory for ConnectionService."""

    def __call__(self, db: SupabaseClient, http_client: httpx.AsyncClient) -> ConnectionService:
        return ConnectionService(db=db, http_client=http_client)
