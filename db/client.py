"""Async Supabase PostgREST client wrapper."""

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

    async def close(self) -> None:
        """Close the underlying HTTP connections."""
        await self._client.aclose()
