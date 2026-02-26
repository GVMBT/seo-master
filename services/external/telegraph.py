"""Telegraph API client for article preview pages.

Spec: docs/API_CONTRACTS.md section 8.5
Edge case E05: Telegraph down -> return None, caller handles fallback.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

TELEGRAPH_API_BASE = "https://api.telegra.ph"

# Telegraph API content field limit (~64KB). Use 60KB as safe threshold.
_MAX_CONTENT_BYTES = 60_000

# Tags that Telegraph API accepts (all others are stripped, children kept).
_ALLOWED_TAGS = frozenset(
    {
        "a",
        "aside",
        "b",
        "blockquote",
        "br",
        "code",
        "em",
        "figcaption",
        "figure",
        "h3",
        "h4",
        "hr",
        "i",
        "img",
        "li",
        "ol",
        "p",
        "pre",
        "s",
        "strong",
        "u",
        "ul",
    }
)

# HTML heading tags to remap to Telegraph-supported h3/h4.
_HEADING_MAP: dict[str, str] = {
    "h1": "h3",
    "h2": "h3",
    "h3": "h3",
    "h4": "h4",
    "h5": "h4",
    "h6": "h4",
}


class _TelegraphNodeBuilder(HTMLParser):
    """Convert HTML to Telegraph Node Array (JSON-serializable list)."""

    def __init__(self) -> None:
        super().__init__()
        self._stack: list[dict[str, Any]] = []  # open elements
        self._root: list[Any] = []  # top-level nodes

    def _current(self) -> list[Any]:
        if self._stack:
            children: list[Any] = self._stack[-1].setdefault("children", [])
            return children
        return self._root

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Remap headings
        tag = _HEADING_MAP.get(tag, tag)

        # Self-closing tags
        if tag in ("br", "hr", "img"):
            node: dict[str, Any] = {"tag": tag}
            if attrs:
                node["attrs"] = {k: v or "" for k, v in attrs if k in ("src", "href", "alt")}
            self._current().append(node)
            return

        if tag not in _ALLOWED_TAGS:
            # Skip unsupported tag, but keep processing children
            return

        node = {"tag": tag}
        attr_dict = {k: v or "" for k, v in attrs if k in ("href", "src", "alt")}
        if attr_dict:
            node["attrs"] = attr_dict
        self._current().append(node)
        self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = _HEADING_MAP.get(tag, tag)
        if tag not in _ALLOWED_TAGS or tag in ("br", "hr", "img"):
            return
        # Pop matching tag from stack
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i]["tag"] == tag:
                self._stack.pop(i)
                break

    def handle_data(self, data: str) -> None:
        text = data
        if text:
            self._current().append(text)

    def get_nodes(self) -> list[Any]:
        # Ensure at least one node (Telegraph requires non-empty content)
        if not self._root:
            return [{"tag": "p", "children": [" "]}]
        return self._root


def html_to_telegraph_nodes(html: str) -> str:
    """Convert HTML string to Telegraph Node Array JSON string."""
    parser = _TelegraphNodeBuilder()
    parser.feed(html)
    return json.dumps(parser.get_nodes(), ensure_ascii=False)


def _truncate_telegraph_content(content_json: str) -> str:
    """Truncate Telegraph node array to fit within API size limit.

    Removes nodes from the end until the JSON fits in _MAX_CONTENT_BYTES,
    then appends a continuation notice.
    """
    nodes: list[Any] = json.loads(content_json)
    continuation = {"tag": "p", "children": ["[...продолжение в полной статье]"]}

    # Remove nodes from the end until we fit
    while len(json.dumps(nodes + [continuation], ensure_ascii=False).encode()) > _MAX_CONTENT_BYTES and len(nodes) > 1:
        nodes.pop()

    nodes.append(continuation)
    return json.dumps(nodes, ensure_ascii=False)


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
            content_json = html_to_telegraph_nodes(html)
            if len(content_json.encode()) > _MAX_CONTENT_BYTES:
                log.warning("telegraph.content_truncated", original_bytes=len(content_json.encode()))
                content_json = _truncate_telegraph_content(content_json)
            resp = await self._http.post(
                f"{TELEGRAPH_API_BASE}/createPage",
                data={
                    "access_token": token,
                    "title": title,
                    "author_name": author,
                    "content": content_json,
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
