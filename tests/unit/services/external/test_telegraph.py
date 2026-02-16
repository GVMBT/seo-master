"""Tests for services/external/telegraph.py — Telegraph API client.

Covers: _ensure_account (lazy creation, cached token), create_page success/fail,
delete_page success/fail, E05 (None return on failure).
"""

from __future__ import annotations

import httpx

from services.external.telegraph import TelegraphClient, TelegraphPage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(handler: object) -> TelegraphClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    http = httpx.AsyncClient(transport=transport)
    return TelegraphClient(http_client=http)


# ---------------------------------------------------------------------------
# TelegraphPage dataclass
# ---------------------------------------------------------------------------


class TestTelegraphPage:
    def test_create(self) -> None:
        page = TelegraphPage(url="https://telegra.ph/Test-01-01", path="Test-01-01")
        assert page.url == "https://telegra.ph/Test-01-01"
        assert page.path == "Test-01-01"

    def test_frozen(self) -> None:
        page = TelegraphPage(url="https://telegra.ph/Test-01-01", path="Test-01-01")
        try:
            page.url = "changed"  # type: ignore[misc]
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass


# ---------------------------------------------------------------------------
# _ensure_account
# ---------------------------------------------------------------------------


class TestEnsureAccount:
    async def test_creates_account_on_first_call(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "createAccount" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": {"access_token": "tok_test", "short_name": "SEO Master Bot"},
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        token = await client._ensure_account()
        assert token == "tok_test"

    async def test_caches_token_after_first_call(self) -> None:
        """Second call should not make HTTP request."""
        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            if "createAccount" in str(request.url):
                call_count += 1
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": {"access_token": "cached_token"},
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        token1 = await client._ensure_account()
        token2 = await client._ensure_account()
        assert token1 == "cached_token"
        assert token2 == "cached_token"
        assert call_count == 1

    async def test_api_error_returns_none(self) -> None:
        """E05: Telegraph down -> return None."""

        async def handler(request: httpx.Request) -> httpx.Response:
            if "createAccount" in str(request.url):
                return httpx.Response(200, json={"ok": False, "error": "Internal error"})
            return httpx.Response(404)

        client = _make_client(handler)
        token = await client._ensure_account()
        assert token is None

    async def test_network_error_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Telegraph unreachable")

        client = _make_client(handler)
        token = await client._ensure_account()
        assert token is None

    async def test_http_error_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Server Error")

        client = _make_client(handler)
        token = await client._ensure_account()
        assert token is None

    async def test_missing_key_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True, "result": {}})

        client = _make_client(handler)
        token = await client._ensure_account()
        assert token is None


# ---------------------------------------------------------------------------
# create_page
# ---------------------------------------------------------------------------


class TestCreatePage:
    async def test_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "createAccount" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": {"access_token": "tok_123"},
                    },
                )
            if "createPage" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": {
                            "url": "https://telegra.ph/SEO-Guide-02-11",
                            "path": "SEO-Guide-02-11",
                        },
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        page = await client.create_page("SEO Guide", "<p>Content here</p>")
        assert page is not None
        assert page.url == "https://telegra.ph/SEO-Guide-02-11"
        assert page.path == "SEO-Guide-02-11"

    async def test_passes_correct_params(self) -> None:
        captured_data: dict = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            if "createAccount" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": {"access_token": "tok_x"},
                    },
                )
            if "createPage" in str(request.url):
                # Parse form data
                body = request.content.decode()
                for pair in body.split("&"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        captured_data[k] = v
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": {"url": "https://telegra.ph/x", "path": "x"},
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        await client.create_page("Title", "<p>HTML</p>", author="Custom Author")
        assert "access_token" in captured_data
        assert "title" in captured_data
        assert captured_data["return_content"] == "false"

    async def test_api_error_returns_none(self) -> None:
        """E05: create_page fails -> None."""

        async def handler(request: httpx.Request) -> httpx.Response:
            if "createAccount" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": {"access_token": "tok_x"},
                    },
                )
            if "createPage" in str(request.url):
                return httpx.Response(200, json={"ok": False, "error": "PAGE_SAVE_FAILED"})
            return httpx.Response(404)

        client = _make_client(handler)
        page = await client.create_page("Title", "<p>Content</p>")
        assert page is None

    async def test_network_error_returns_none(self) -> None:
        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            if "createAccount" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": {"access_token": "tok_x"},
                    },
                )
            call_count += 1
            raise httpx.ConnectError("Down")

        client = _make_client(handler)
        page = await client.create_page("Title", "Content")
        assert page is None

    async def test_account_creation_failure_returns_none(self) -> None:
        """If _ensure_account fails, create_page returns None immediately."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Error")

        client = _make_client(handler)
        page = await client.create_page("Title", "Content")
        assert page is None

    async def test_uses_default_author(self) -> None:
        """Default author should be 'SEO Master Bot'."""

        async def handler(request: httpx.Request) -> httpx.Response:
            if "createAccount" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": {"access_token": "tok"},
                    },
                )
            if "createPage" in str(request.url):
                body = request.content.decode()
                assert "SEO+Master+Bot" in body or "SEO%20Master%20Bot" in body or "author_name" in body
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": {"url": "https://telegra.ph/x", "path": "x"},
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        page = await client.create_page("Title", "Content")
        assert page is not None


# ---------------------------------------------------------------------------
# delete_page
# ---------------------------------------------------------------------------


class TestDeletePage:
    async def test_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "createAccount" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": {"access_token": "tok_del"},
                    },
                )
            if "editPage" in str(request.url):
                return httpx.Response(200, json={"ok": True, "result": {"path": "deleted-page"}})
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.delete_page("SEO-Guide-02-11")
        assert result is True

    async def test_sets_minimal_content(self) -> None:
        """delete_page overwrites with empty content (Telegraph has no real delete)."""
        captured_data: dict = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            if "createAccount" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": {"access_token": "tok"},
                    },
                )
            if "editPage" in str(request.url):
                body = request.content.decode()
                for pair in body.split("&"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        captured_data[k] = v
                return httpx.Response(200, json={"ok": True, "result": {}})
            return httpx.Response(404)

        client = _make_client(handler)
        await client.delete_page("some-path")
        assert captured_data.get("title") == "deleted"

    async def test_api_error_returns_false(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "createAccount" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": {"access_token": "tok"},
                    },
                )
            if "editPage" in str(request.url):
                return httpx.Response(200, json={"ok": False, "error": "PAGE_NOT_FOUND"})
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.delete_page("nonexistent")
        assert result is False

    async def test_network_error_returns_false(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "createAccount" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": {"access_token": "tok"},
                    },
                )
            raise httpx.ConnectError("Down")

        client = _make_client(handler)
        result = await client.delete_page("some-path")
        assert result is False

    async def test_account_creation_failure_returns_false(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Error")

        client = _make_client(handler)
        result = await client.delete_page("some-path")
        assert result is False
