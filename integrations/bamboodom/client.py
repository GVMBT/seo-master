"""Async HTTP client for bamboodom.ru blog API (v1.1).

Session 1 surface: `key_test()` — smoke-test endpoint.
Session 2A adds: `get_context()`, `get_article_codes()` with Redis caching.
Other endpoints (blog_publish, blog_upload_image, blog_article_info) — Sessions 3+.

Design notes:
- Stateless HTTP calls via shared/one-off httpx.AsyncClient.
- Caching for context / codes is done here (mirrors `services/external/serper.py`).
- Exceptions map to user-facing screen messages; logs are structured.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from bot.config import get_settings
from cache.keys import BAMBOODOM_CODES_TTL, BAMBOODOM_CONTEXT_TTL
from integrations.bamboodom.exceptions import (
    BamboodomAPIError,
    BamboodomAuthError,
    BamboodomRateLimitError,
)
from integrations.bamboodom.models import (
    ArticleCodesResponse,
    ContextResponse,
    KeyTestResponse,
    PublishResponse,
)

log = structlog.get_logger()

_DEFAULT_TIMEOUT = 10.0
_MAX_ERROR_BODY = 500

# Redis key namespaces (see cache/keys.py for TTLs)
_CTX_CACHE_KEY = "bamboodom:context:data"
_CODES_CACHE_KEY = "bamboodom:codes:data"


@dataclass
class BamboodomClient:
    """Thin async wrapper over bamboodom.ru blog API with optional Redis caching.

    Parameters are optional — defaults fall back to `Settings` singleton.
    Pass explicit values in tests. `redis` is optional: if absent, cache is
    bypassed (every fetch hits the API).
    """

    api_base: str = ""
    api_key: str = ""
    http_client: httpx.AsyncClient | None = None
    redis: Any = None  # RedisClient; typed as Any to avoid circular import
    timeout: float = _DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        if not self.api_base or not self.api_key:
            settings = get_settings()
            self.api_base = self.api_base or settings.bamboodom_api_base
            self.api_key = self.api_key or settings.bamboodom_blog_key.get_secret_value()

    # ---- internals ----------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise BamboodomAuthError("BAMBOODOM_BLOG_KEY not configured")
        return {
            "X-Blog-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        action: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        headers = self._headers()  # raises BamboodomAuthError if key missing
        query: dict[str, Any] = {"action": action, **(params or {})}
        effective_timeout = timeout if timeout is not None else self.timeout

        async def _send(client: httpx.AsyncClient) -> httpx.Response:
            return await client.request(
                method,
                self.api_base,
                params=query,
                headers=headers,
                json=json_body,
                timeout=effective_timeout,
            )

        try:
            if self.http_client is not None:
                resp = await _send(self.http_client)
            else:
                async with httpx.AsyncClient(timeout=effective_timeout) as client:
                    resp = await _send(client)
        except httpx.TimeoutException as exc:
            raise BamboodomAPIError(f"Timeout on {action}: {exc}") from exc
        except httpx.RequestError as exc:
            raise BamboodomAPIError(f"Network error on {action}: {exc}") from exc

        return self._handle_response(action, resp)

    @staticmethod
    def _handle_response(action: str, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 401:
            raise BamboodomAuthError("Invalid X-Blog-Key (HTTP 401)")
        if resp.status_code == 429:
            retry_after_raw = resp.headers.get("Retry-After", "60")
            try:
                retry_after = int(retry_after_raw)
            except ValueError:
                retry_after = 60
            raise BamboodomRateLimitError(retry_after)
        if resp.status_code >= 500:
            raise BamboodomAPIError(f"Server error {resp.status_code} on {action}: {resp.text[:_MAX_ERROR_BODY]}")
        if resp.status_code >= 400:
            raise BamboodomAPIError(f"Client error {resp.status_code} on {action}: {resp.text[:_MAX_ERROR_BODY]}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise BamboodomAPIError(f"Non-JSON response on {action}: {resp.text[:_MAX_ERROR_BODY]}") from exc

        if not isinstance(data, dict):
            raise BamboodomAPIError(f"Unexpected JSON shape on {action}: {type(data).__name__}")

        if not data.get("ok"):
            raise BamboodomAPIError(f"API returned ok=false on {action}: {str(data)[:_MAX_ERROR_BODY]}")
        return data

    # ---- cache helpers ------------------------------------------------

    async def _cache_get(self, key: str) -> dict[str, Any] | None:
        if self.redis is None:
            return None
        try:
            raw = await self.redis.get(key)
        except Exception:
            log.warning("bamboodom_cache_read_failed", key=key, exc_info=True)
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            log.warning("bamboodom_cache_bad_json", key=key)
            return None

    async def _cache_set(self, key: str, data: dict[str, Any], ttl: int) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.set(key, json.dumps(data, ensure_ascii=False), ex=ttl)
        except Exception:
            log.warning("bamboodom_cache_write_failed", key=key, exc_info=True)

    # ---- public API ---------------------------------------------------

    async def key_test(self) -> KeyTestResponse:
        """GET blog_key_test — smoke-test endpoint (no rate limit, no sandbox needed)."""
        data = await self._request("GET", "blog_key_test", timeout=_DEFAULT_TIMEOUT)
        return KeyTestResponse.model_validate(data)

    async def get_context(
        self,
        *,
        force_refresh: bool = False,
    ) -> tuple[ContextResponse, bool]:
        """GET blog_context with Redis-backed caching.

        Returns (response, was_fresh_fetch). `was_fresh_fetch=False` means data
        came from cache; `True` means we hit the network.

        TTL: BAMBOODOM_CONTEXT_TTL (1h). Pass `force_refresh=True` to bypass
        cache but still write result back.
        """
        if not force_refresh:
            cached = await self._cache_get(_CTX_CACHE_KEY)
            if cached is not None:
                return ContextResponse.model_validate(cached), False

        data = await self._request("GET", "blog_context", timeout=_DEFAULT_TIMEOUT)
        await self._cache_set(_CTX_CACHE_KEY, data, BAMBOODOM_CONTEXT_TTL)
        return ContextResponse.model_validate(data), True

    async def get_article_codes(
        self,
        *,
        force_refresh: bool = False,
    ) -> tuple[ArticleCodesResponse, bool]:
        """GET blog_article_codes with Redis-backed caching.

        Returns (response, was_fresh_fetch).
        TTL: BAMBOODOM_CODES_TTL (1h).
        """
        if not force_refresh:
            cached = await self._cache_get(_CODES_CACHE_KEY)
            if cached is not None:
                return ArticleCodesResponse.model_validate(cached), False

        data = await self._request("GET", "blog_article_codes", timeout=_DEFAULT_TIMEOUT)
        await self._cache_set(_CODES_CACHE_KEY, data, BAMBOODOM_CODES_TTL)
        return ArticleCodesResponse.model_validate(data), True

    async def peek_cached_context(self) -> ContextResponse | None:
        """Read blog_context from Redis without hitting API. Returns None if no cache."""
        cached = await self._cache_get(_CTX_CACHE_KEY)
        return ContextResponse.model_validate(cached) if cached else None

    async def peek_cached_codes(self) -> ArticleCodesResponse | None:
        """Read blog_article_codes from Redis without hitting API. Returns None if no cache."""
        cached = await self._cache_get(_CODES_CACHE_KEY)
        return ArticleCodesResponse.model_validate(cached) if cached else None

    async def publish(
        self,
        payload: dict[str, Any],
        *,
        sandbox: bool = True,
    ) -> PublishResponse:
        """POST blog_publish — submit article blocks to bamboodom.ru.

        Parameters
        ----------
        payload : dict
            Article body. Must contain at minimum ``title`` and ``blocks``.
            Optional: ``excerpt``, ``draft``, ``slug`` (auto-generated from title if absent),
            ``published_at``. Server generates slug from title if not provided.
        sandbox : bool, default True
            When True → ``?sandbox=1``, writes to isolated blog_sandbox.json (auto-expires 7d).
            When False → production, visible to side B moderators.

        Returns
        -------
        PublishResponse
            Always contains ``ok``, ``slug``, ``url`` (client should display as-is — URL
            already embeds ``&sandbox=1`` when applicable).

        Timeout set to 30s — publish is heavier than smoke-test, especially with many
        product-blocks (server validates each article code against article_index.json).

        Rate-limited server-side: 1 request per 3 seconds. Callers SHOULD hold a client-side
        lock to avoid 429 from quick double-clicks.
        """
        params = {"sandbox": "1"} if sandbox else {}
        data = await self._request(
            "POST",
            "blog_publish",
            params=params,
            json_body=payload,
            timeout=30.0,
        )
        return PublishResponse.model_validate(data)

    async def regenerate_sitemap(self) -> dict[str, Any]:
        """POST blog_regenerate_sitemap (4E) — попросить сервер пересобрать sitemap_blog.xml.

        Сторона B сама вызывает этот helper после каждой production-публикации, так что
        отдельный явный вызов нужен только если оператор подозревает что sitemap отстал.
        Endpoint идемпотентен: повторный вызов в течение 60 секунд возвращает кэш.

        Возвращаемый dict (ключи как в спеке):
            ok: bool
            count: int            — сколько статей попало в sitemap
            generated_at: ISO ts
            sandbox_excluded: bool
            file: str             — имя файла на сервере ('sitemap_blog.xml')
            url: str              — публичный URL sitemap'а
            cached: bool          — True если сервер вернул кэш (повторный вызов)
        """
        return await self._request(
            "POST",
            "blog_regenerate_sitemap",
            timeout=15.0,
        )

    async def regenerate_sitemap_full(self) -> dict[str, Any]:
        """POST blog_regenerate_sitemap_full (4E_full) — пересборка ОБЩЕГО sitemap.xml.

        В отличие от `regenerate_sitemap` (который трогает только sitemap_blog.xml),
        этот endpoint пересобирает `sitemap.xml` со всеми разделами сайта:
        статические страницы, WPC-текстуры, flex-керамика, reiki, profiles,
        lighting, статьи блога, верификация. Используется для того чтобы
        новые товары/текстуры попадали в очередь Я.Вебмастера через cron B.

        Cache 60 секунд, идемпотентен. Триггер — кнопка в админке нашего бота.
        Сторона B также использует этот endpoint в их cabinet.html.

        Возвращаемый dict:
            ok: bool
            count: int                        — всего URL в sitemap.xml
            breakdown: dict[str, int]         — по разделам (static_pages, wpc_textures,
                                                 flex_textures, reiki, profiles, lighting,
                                                 blog_articles, verification)
            generated_at: ISO ts
            sandbox_excluded: bool
            file: str                         — 'sitemap.xml'
            url: str                          — публичный URL
            cached: bool                      — True если вернулся кэш
        """
        return await self._request(
            "POST",
            "blog_regenerate_sitemap_full",
            timeout=20.0,
        )

    async def upload_image(
        self,
        source_url: str,
        alt: str = "",
    ) -> dict[str, Any]:
        """POST blog_upload_image (4B.5 / 4K) — JSON-mode (legacy).

        Сторона B принимает:
        - `source_url` — публичный URL (whitelist *.railway.app, *.bamboodom.ru, ...).
          B сама скачивает, конвертит в WebP, ресайз <2000px, max 10MB.
        - `alt` — описание для SEO (опционально).

        Возвращает: {ok, url, slug, size_kb, ... }.
        Rate-limit: 1/сек.
        """
        return await self._request(
            "POST",
            "blog_upload_image",
            json_body={"source_url": source_url, "alt": alt or ""},
            timeout=30.0,
        )

    async def upload_image_multipart(
        self,
        *,
        slug: str,
        slot: str,
        image_bytes: bytes,
        content_type: str = "image/webp",
        alt: str = "",
    ) -> dict[str, Any]:
        """POST blog_upload_image multipart (BLOG_UPLOAD_MULTIPART_V1, 2026-04-27).

        Используется для прямой заливки сгенерированных AI-картинок в B-storage.
        Side B сохраняет файл по схеме /img/blog/[slug]/[slot]-[N].jpg или .webp,
        возвращает финальный публичный URL.

        Параметры (multipart fields):
        - slug: slug статьи (для папки)
        - slot: один из 10 slot-имён (hero, wide-1, ..., portrait-2)
        - image: binary content
        - alt: описание для SEO (опционально)

        Возвращает: {ok, src, slug, slot, size_kb, ...}.
        Rate-limit: 1/сек как обычный upload_image.
        """
        headers = self._headers()
        query = {"action": "blog_upload_image"}

        ext = "webp" if "webp" in content_type else ("jpg" if "jpeg" in content_type else "png")
        files = {
            "image": (f"{slot}.{ext}", image_bytes, content_type),
        }
        data = {
            "slug": slug,
            "slot": slot,
            "alt": alt or "",
        }

        async def _send(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(
                self.api_base,
                params=query,
                headers=headers,
                files=files,
                data=data,
                timeout=30.0,
            )

        try:
            if self.http_client is not None:
                resp = await _send(self.http_client)
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await _send(client)
        except httpx.TimeoutException as exc:
            raise BamboodomAPIError(f"Timeout on blog_upload_image multipart: {exc}") from exc
        except httpx.RequestError as exc:
            raise BamboodomAPIError(f"Network error on blog_upload_image multipart: {exc}") from exc

        return self._handle_response("blog_upload_image", resp)

    async def update_article(
        self,
        slug: str,
        fields: dict[str, Any],
        *,
        sandbox: bool = False,
    ) -> dict[str, Any]:
        """POST blog_update_article (4P, 2026-04-26).

        Updates only fields present in `fields` (array_key_exists на стороне B).
        Used for late image-attach flow: publish article first with empty
        src on img-blocks, then run image pipeline in background, then call
        update_article(slug, {"blocks": new_blocks}) to attach real URLs.

        Args:
            slug: статья по slug.
            fields: dict с полями для обновления — blocks, tags, cover,
                template_id, category, и т.д.
            sandbox: если True, добавляется ?sandbox=1.
        """
        params = {"sandbox": "1"} if sandbox else None
        body = {"slug": slug, **fields}
        return await self._request(
            "POST",
            "blog_update_article",
            params=params,
            json_body=body,
            timeout=30.0,
        )

    async def promote_from_sandbox(self, slug: str) -> dict[str, Any]:
        """POST blog_promote_from_sandbox (PROMOTE-V1) — переносит sandbox-статью в production.

        Сторона B сделала endpoint 2026-04-26: читает sandbox-статью по slug,
        проверяет через STRICT-ARTICLES-V1 и если ОК — переносит в blog.json
        (production), убирает из blog_sandbox.json.

        Идемпотентен: если статья с таким slug уже в production — вернёт ok=false
        с маркером {"already_in_production": true}.

        Ответ:
            {ok: bool, slug, url, action_type: 'promoted', warnings: [...], ...}
        Если STRICT-ARTICLES-V1 заблокировал → ok=false, error содержит причину.
        """
        return await self._request(
            "POST",
            "blog_promote_from_sandbox",
            json_body={"slug": slug},
            timeout=20.0,
        )
