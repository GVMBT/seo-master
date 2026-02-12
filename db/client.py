"""Async Supabase PostgREST client wrapper."""

from typing import Any

from postgrest import AsyncPostgrestClient, AsyncRequestBuilder


class SupabaseClient:
    """Thin wrapper around AsyncPostgrestClient with Supabase auth headers."""

    def __init__(self, url: str, key: str) -> None:
        rest_url = f"{url}/rest/v1"
        headers = {"apikey": key, "Authorization": f"Bearer {key}"}
        self._client = AsyncPostgrestClient(rest_url, headers=headers)

    def table(self, name: str) -> AsyncRequestBuilder:
        """Return a request builder for the given table."""
        return self._client.table(name)

    async def rpc(self, fn_name: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Call a Supabase RPC (PostgreSQL function).

        Returns list of rows from the function result.
        Raises exception if function doesn't exist.
        """
        resp = await self._client.rpc(fn_name, params or {}).execute()
        return resp.data or []  # type: ignore[return-value]

    async def close(self) -> None:
        """Close the underlying HTTP connections."""
        await self._client.aclose()
