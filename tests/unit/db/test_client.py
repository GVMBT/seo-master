"""Tests for db/client.py — Supabase PostgREST client."""

from unittest.mock import AsyncMock, MagicMock, patch

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

    @pytest.mark.asyncio
    async def test_rpc_returns_data(self) -> None:
        client = SupabaseClient(url="https://test.supabase.co", key="test-key")
        mock_resp = MagicMock()
        mock_resp.data = [{"id": 1, "balance": 2000}]
        mock_builder = AsyncMock()
        mock_builder.execute = AsyncMock(return_value=mock_resp)
        with patch.object(client._client, "rpc", return_value=mock_builder) as mock_rpc:
            result = await client.rpc("adjust_balance", {"uid": 1, "delta": 500})
            mock_rpc.assert_called_once_with("adjust_balance", {"uid": 1, "delta": 500})
            assert result == [{"id": 1, "balance": 2000}]

    @pytest.mark.asyncio
    async def test_rpc_returns_empty_on_none(self) -> None:
        client = SupabaseClient(url="https://test.supabase.co", key="test-key")
        mock_resp = MagicMock()
        mock_resp.data = None
        mock_builder = AsyncMock()
        mock_builder.execute = AsyncMock(return_value=mock_resp)
        with patch.object(client._client, "rpc", return_value=mock_builder):
            result = await client.rpc("some_function")
            assert result == []
