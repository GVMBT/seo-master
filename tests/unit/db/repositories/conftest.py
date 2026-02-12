"""Shared mock fixtures for repository tests.

Uses a MockSupabaseClient that records calls and returns configurable responses.
The mock auto-handles maybe_single() semantics:
- dict data + maybe_single() → returns dict (single row)
- dict data + no maybe_single() → wraps in list (for update/insert)
- list data + maybe_single() → returns first element or None
- None/[] + maybe_single() → returns None
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from cryptography.fernet import Fernet

from db.credential_manager import CredentialManager

# ---------------------------------------------------------------------------
# Mock PostgREST chain
# ---------------------------------------------------------------------------

@dataclass
class MockResponse:
    """Simulated PostgREST response."""

    data: Any = None
    count: int | None = None


class MockRequestBuilder:
    """Chainable mock that records method calls and returns configurable response.

    Automatically handles maybe_single() semantics: when called,
    execute() returns a single row (dict) or None instead of a list.
    """

    def __init__(self, response: MockResponse | None = None) -> None:
        self._response = response or MockResponse()
        self._is_maybe_single = False

    def _chain(self, method: str, *args: Any, **kwargs: Any) -> MockRequestBuilder:
        return self

    def select(self, *args: Any, **kwargs: Any) -> MockRequestBuilder:
        return self._chain("select", *args, **kwargs)

    def insert(self, *args: Any, **kwargs: Any) -> MockRequestBuilder:
        return self._chain("insert", *args, **kwargs)

    def update(self, *args: Any, **kwargs: Any) -> MockRequestBuilder:
        return self._chain("update", *args, **kwargs)

    def upsert(self, *args: Any, **kwargs: Any) -> MockRequestBuilder:
        return self._chain("upsert", *args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> MockRequestBuilder:
        return self._chain("delete", *args, **kwargs)

    def eq(self, *args: Any, **kwargs: Any) -> MockRequestBuilder:
        return self._chain("eq", *args, **kwargs)

    def neq(self, *args: Any, **kwargs: Any) -> MockRequestBuilder:
        return self._chain("neq", *args, **kwargs)

    def gte(self, *args: Any, **kwargs: Any) -> MockRequestBuilder:
        return self._chain("gte", *args, **kwargs)

    def lte(self, *args: Any, **kwargs: Any) -> MockRequestBuilder:
        return self._chain("lte", *args, **kwargs)

    def gt(self, *args: Any, **kwargs: Any) -> MockRequestBuilder:
        return self._chain("gt", *args, **kwargs)

    def lt(self, *args: Any, **kwargs: Any) -> MockRequestBuilder:
        return self._chain("lt", *args, **kwargs)

    def order(self, *args: Any, **kwargs: Any) -> MockRequestBuilder:
        return self._chain("order", *args, **kwargs)

    def limit(self, *args: Any, **kwargs: Any) -> MockRequestBuilder:
        return self._chain("limit", *args, **kwargs)

    def range(self, *args: Any, **kwargs: Any) -> MockRequestBuilder:
        return self._chain("range", *args, **kwargs)

    def maybe_single(self) -> MockRequestBuilder:
        self._is_maybe_single = True
        return self

    def in_(self, *args: Any, **kwargs: Any) -> MockRequestBuilder:
        return self._chain("in_", *args, **kwargs)

    def is_(self, *args: Any, **kwargs: Any) -> MockRequestBuilder:
        return self._chain("is_", *args, **kwargs)

    @property
    def not_(self) -> MockRequestBuilder:
        """Support for .not_.is_(...) chain."""
        return self

    async def execute(self) -> MockResponse:
        """Return response with automatic maybe_single() handling.

        - maybe_single + list data → first element (dict) or None
        - maybe_single + dict data → as-is
        - maybe_single + None → None
        - no maybe_single + dict data → wrap in [dict]
        - no maybe_single + list data → as-is
        - no maybe_single + None → []
        """
        data = self._response.data
        count = self._response.count

        if self._is_maybe_single:
            resolved = (data[0] if data else None) if isinstance(data, list) else data
            return MockResponse(data=resolved, count=count)

        # Non-maybe_single: ensure list
        if data is None:
            return MockResponse(data=[], count=count)
        if isinstance(data, dict):
            return MockResponse(data=[data], count=count)
        return self._response


@dataclass
class MockSupabaseClient:
    """SupabaseClient mock that returns preconfigured responses per table.

    Creates a NEW MockRequestBuilder for each table() call so that
    maybe_single() state doesn't leak between different query chains.
    """

    _responses: dict[str, MockResponse] = field(default_factory=dict)
    _response_queues: dict[str, list[MockResponse]] = field(default_factory=dict)
    _rpc_responses: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def set_response(self, table: str, response: MockResponse) -> None:
        """Set the response for a given table name."""
        self._responses[table] = response

    def set_responses(self, table: str, responses: list[MockResponse]) -> None:
        """Set sequential responses for a table (consumed in order, then falls back to set_response)."""
        self._response_queues[table] = list(responses)

    def table(self, name: str) -> MockRequestBuilder:
        """Return a fresh MockRequestBuilder for the given table."""
        queue = self._response_queues.get(name)
        if queue:
            resp = queue.pop(0)
            if not queue:
                del self._response_queues[name]
            return MockRequestBuilder(resp)
        resp = self._responses.get(name, MockResponse())
        return MockRequestBuilder(resp)

    def set_rpc_response(self, fn_name: str, data: list[dict[str, Any]]) -> None:
        """Set response data for an RPC call."""
        self._rpc_responses[fn_name] = data

    async def rpc(self, fn_name: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Mock RPC call. Raises RuntimeError if no response configured (simulates missing function)."""
        if fn_name not in self._rpc_responses:
            msg = f"RPC function {fn_name} not found"
            raise RuntimeError(msg)
        return self._rpc_responses[fn_name]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_response() -> type[MockResponse]:
    """MockResponse class for direct use."""
    return MockResponse


@pytest.fixture
def mock_db() -> MockSupabaseClient:
    """MockSupabaseClient instance."""
    return MockSupabaseClient()


@pytest.fixture
def encryption_key() -> str:
    """Fresh Fernet key."""
    return Fernet.generate_key().decode()


@pytest.fixture
def credential_manager(encryption_key: str) -> CredentialManager:
    """CredentialManager with test key."""
    return CredentialManager(encryption_key)
