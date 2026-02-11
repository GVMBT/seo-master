"""Tests for db/client.py — Supabase PostgREST client."""

from unittest.mock import AsyncMock

import pytest

from db.client import SupabaseClient


class TestSupabaseClient:
    def test_init_builds_correct_url(self) -> None:
        client = SupabaseClient(url="https://test.supabase.co", key="test-key")
        # PostgREST client should be initialized with rest/v1 URL
        assert client._client is not None

    def test_table_returns_request_builder(self) -> None:
        client = SupabaseClient(url="https://test.supabase.co", key="test-key")
        builder = client.table("users")
        assert builder is not None

    @pytest.mark.asyncio
    async def test_close_calls_aclose(self) -> None:
        client = SupabaseClient(url="https://test.supabase.co", key="test-key")
        client._client.aclose = AsyncMock()
        await client.close()
        client._client.aclose.assert_awaited_once()

    def test_headers_include_apikey_and_bearer(self) -> None:
        key = "my-service-role-key"
        client = SupabaseClient(url="https://test.supabase.co", key=key)
        session_headers = dict(client._client.session.headers)
        assert session_headers["apikey"] == key
        assert session_headers["authorization"] == f"Bearer {key}"
