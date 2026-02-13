"""Telegraph API client for article preview pages.

Spec: docs/API_CONTRACTS.md section 8.5
Edge case E05: Telegraph down -> return None, caller handles fallback.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog

log = structlog.get_logger()

TELEGRAPH_API_BASE = "https://api.telegra.ph"


@dataclass(frozen=True, slots=True)
class TelegraphPage:
    """Result of a Telegraph page creation."""

    url: str  # https://telegra.ph/Article-Title-02-11
    path: str  # Article-Title-02-11 (used for deletion)


class TelegraphClient:
    """Client for Telegraph API (telegra.ph).

    Uses shared httpx.AsyncClient (never creates its own).
    Lazily creates a Telegraph account on first call.
    All public methods return None on failure (E05).
    """

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http = http_client
        self._access_token: str | None = None

    async def _ensure_account(self) -> str | None:
        """Lazily create a Telegraph account and cache the access_token.

        Returns the access_token or None on failure.
        """
        if self._access_token is not None:
            return self._access_token

        try:
            resp = await self._http.post(
                f"{TELEGRAPH_API_BASE}/createAccount",
                data={"short_name": "SEO Master Bot"},
            )
            resp.raise_for_status()
            body = resp.json()
            if not body.get("ok"):
                log.error("telegraph.create_account_failed", error=body.get("error"))
                return None
            self._access_token = body["result"]["access_token"]
            log.info("telegraph.account_created")
            return self._access_token
        except (httpx.HTTPError, KeyError) as exc:
            log.exception("telegraph.create_account_error", error=str(exc))
            return None

    async def create_page(
        self,
        title: str,
        html: str,
        author: str = "SEO Master Bot",
    ) -> TelegraphPage | None:
        """Create a Telegraph page with the given HTML content.

        Args:
            title: Page title.
            html: HTML content for the page body.
            author: Author name displayed on the page.

        Returns:
            TelegraphPage on success, None on any failure (E05).
        """
        token = await self._ensure_account()
        if token is None:
            return None

        try:
            resp = await self._http.post(
                f"{TELEGRAPH_API_BASE}/createPage",
                data={
                    "access_token": token,
                    "title": title,
                    "author_name": author,
                    "content": html,
                    "return_content": "false",
                },
            )
            resp.raise_for_status()
            body = resp.json()
            if not body.get("ok"):
                log.error("telegraph.create_page_failed", error=body.get("error"))
                return None
            result = body["result"]
            page = TelegraphPage(url=result["url"], path=result["path"])
            log.info("telegraph.page_created", path=page.path)
            return page
        except (httpx.HTTPError, KeyError) as exc:
            log.exception("telegraph.create_page_error", error=str(exc))
            return None

    async def delete_page(self, path: str) -> bool:
        """Delete a Telegraph page by setting its content to empty.

        Telegraph API has no real delete; we overwrite with minimal content.

        Args:
            path: The page path (e.g. "Article-Title-02-11").

        Returns:
            True if the page was cleared, False on failure.
        """
        token = await self._ensure_account()
        if token is None:
            return False

        try:
            resp = await self._http.post(
                f"{TELEGRAPH_API_BASE}/editPage",
                data={
                    "access_token": token,
                    "path": path,
                    "title": "deleted",
                    "content": '[{"tag":"p","children":[""]}]',
                },
            )
            resp.raise_for_status()
            body = resp.json()
            if not body.get("ok"):
                log.error("telegraph.delete_page_failed", path=path, error=body.get("error"))
                return False
            log.info("telegraph.page_deleted", path=path)
            return True
        except (httpx.HTTPError, KeyError) as exc:
            log.exception("telegraph.delete_page_error", path=path, error=str(exc))
            return False
