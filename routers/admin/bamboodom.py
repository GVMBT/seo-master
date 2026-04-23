"""Admin panel — Bamboodom.ru section.

Scope (Sessions 1 + 2A):
    - Entry screen with status + timestamps
    - Smoke-test (blog_key_test) with compact endpoint list
    - Context viewer (blog_context) with Redis-backed 1h cache + manual refresh
    - Codes viewer (blog_article_codes) with Redis-backed 1h cache + manual refresh
    - Settings screen (stub — Session 4 will populate with AI/scheduler)

Dependencies pattern follows `routers/admin/dashboard.py`:
    - `user: User` injected by AuthMiddleware (role-based admin guard)
    - `redis: RedisClient` injected by DBSessionMiddleware
    - `http_client: httpx.AsyncClient` shared client (re-used across calls)
"""

from __future__ import annotations

import datetime as dt
import json

import httpx
import sentry_sdk
import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.config import get_settings
from bot.helpers import safe_edit_text, safe_message
from bot.texts import bamboodom as TXT
from bot.texts import strings as S
from bot.texts.emoji import E
from bot.texts.screens import Screen
from cache.client import RedisClient
from db.models import User
from integrations.bamboodom import (
    ArticleCodesResponse,
    BamboodomAPIError,
    BamboodomAuthError,
    BamboodomClient,
    BamboodomRateLimitError,
    ContextResponse,
    KeyTestResponse,
)
from keyboards.bamboodom import (
    bamboodom_codes_kb,
    bamboodom_context_kb,
    bamboodom_entry_kb,
    bamboodom_settings_kb,
    bamboodom_smoke_result_kb,
)

log = structlog.get_logger()
router = Router()

# Redis keys for smoke-test history (TTL ensures auto-cleanup)
_LAST_OK_KEY = "bamboodom:smoke_test:last_ok"
_LAST_FAIL_KEY = "bamboodom:smoke_test:last_fail"
_HISTORY_TTL = 7 * 24 * 3600  # 7 days

_FORBIDDEN_CLAIMS_PREVIEW = 4  # show first N forbidden claims in UI (rest: +M more)
_TYPICAL_CONTEXTS_PREVIEW = 5
_SMOKE_ENDPOINTS_VISIBLE = 6


# ---------------------------------------------------------------------------
# Admin guard (mirrors routers/admin/dashboard.py)
# ---------------------------------------------------------------------------


def _is_admin(user: User) -> bool:
    return user.role == "admin"


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def _fmt_moscow(iso: str | None) -> str:
    """Render stored UTC/TZ timestamp in Europe/Moscow."""
    if not iso:
        return TXT.BAMBOODOM_LAST_OK_NONE
    try:
        ts = dt.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    # If naive — treat as UTC. Otherwise convert to MSK (+03:00 no DST).
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.UTC)
    local = ts.astimezone(dt.timezone(dt.timedelta(hours=3)))
    return local.strftime("%Y-%m-%d %H:%M МСК")


def _age_from_iso(iso: str | None) -> str:
    """Human-readable age: '5 мин', '2 ч', '3 дн'. Returns '—' on parse error."""
    if not iso:
        return "—"
    try:
        ts = dt.datetime.fromisoformat(iso)
    except ValueError:
        return "—"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.UTC)
    delta = dt.datetime.now(dt.UTC) - ts
    total_seconds = max(int(delta.total_seconds()), 0)
    if total_seconds < 60:
        return f"{total_seconds} сек"
    if total_seconds < 3600:
        return f"{total_seconds // 60} мин"
    if total_seconds < 86400:
        return f"{total_seconds // 3600} ч"
    return f"{total_seconds // 86400} дн"


async def _record_ok(redis: RedisClient) -> None:
    try:
        await redis.set(_LAST_OK_KEY, _now_iso(), ex=_HISTORY_TTL)
    except Exception:
        log.warning("bamboodom_record_ok_failed", exc_info=True)


async def _record_fail(redis: RedisClient, detail: str) -> None:
    try:
        payload = json.dumps({"ts": _now_iso(), "detail": detail[:200]}, ensure_ascii=False)
        await redis.set(_LAST_FAIL_KEY, payload, ex=_HISTORY_TTL)
    except Exception:
        log.warning("bamboodom_record_fail_failed", exc_info=True)


async def _read_history(redis: RedisClient) -> tuple[str, str]:
    """Return formatted (last_ok, last_fail) strings for display."""
    try:
        raw_ok = await redis.get(_LAST_OK_KEY)
        raw_fail = await redis.get(_LAST_FAIL_KEY)
    except Exception:
        log.warning("bamboodom_read_history_failed", exc_info=True)
        return TXT.BAMBOODOM_LAST_OK_NONE, TXT.BAMBOODOM_LAST_FAIL_NONE

    last_ok = _fmt_moscow(raw_ok)
    if raw_fail:
        try:
            data = json.loads(raw_fail)
            last_fail = f"{_fmt_moscow(data.get('ts'))} — {data.get('detail', '')}"
        except ValueError, TypeError:
            last_fail = raw_fail
    else:
        last_fail = TXT.BAMBOODOM_LAST_FAIL_NONE

    return last_ok, last_fail


# ---------------------------------------------------------------------------
# Endpoint rendering helpers
# ---------------------------------------------------------------------------


def _ordered_endpoints(all_endpoints: list[str]) -> tuple[list[str], int]:
    """Return (visible, remaining_count) with priority ordering.

    Priority endpoints (BAMBOODOM_SMOKE_PRIORITY_ENDPOINTS) are placed first
    in the order they appear in the tuple; everything else — after, in the
    order returned by the API.
    """
    priority = list(TXT.BAMBOODOM_SMOKE_PRIORITY_ENDPOINTS)
    present = set(all_endpoints)
    ordered = [ep for ep in priority if ep in present]
    ordered.extend(ep for ep in all_endpoints if ep not in priority)
    visible = ordered[:_SMOKE_ENDPOINTS_VISIBLE]
    remaining = max(len(ordered) - len(visible), 0)
    return visible, remaining


# ---------------------------------------------------------------------------
# Screen builders
# ---------------------------------------------------------------------------


def _status_label(*, enabled: bool, key_present: bool) -> str:
    if not enabled:
        return TXT.BAMBOODOM_STATUS_DISABLED
    if not key_present:
        return TXT.BAMBOODOM_STATUS_KEY_MISSING
    return TXT.BAMBOODOM_STATUS_ENABLED


def _build_entry_text(
    *,
    enabled: bool,
    api_base: str,
    key_present: bool,
    last_ok: str,
    last_fail: str,
) -> str:
    return (
        Screen(E.LEAF, TXT.BAMBOODOM_TITLE)
        .blank()
        .line(TXT.BAMBOODOM_ENTRY_NAME)
        .blank()
        .field(E.INFO, TXT.BAMBOODOM_LABEL_STATUS, _status_label(enabled=enabled, key_present=key_present))
        .field(E.LINK, TXT.BAMBOODOM_LABEL_API_BASE, api_base)
        .field(E.CHECK, TXT.BAMBOODOM_LABEL_LAST_OK, last_ok)
        .field(E.CLOSE, TXT.BAMBOODOM_LABEL_LAST_FAIL, last_fail)
        .hint(TXT.BAMBOODOM_ENTRY_HINT)
        .build()
    )


def _build_smoke_ok_text(resp: KeyTestResponse) -> str:
    writable_ok = bool(resp.writable)
    images_ok = bool(resp.image_dir_writable)
    visible, remaining = _ordered_endpoints(resp.endpoints)

    screen = (
        Screen(E.PULSE, TXT.BAMBOODOM_SMOKE_TITLE)
        .blank()
        .line(f"{E.CHECK} {TXT.BAMBOODOM_SMOKE_OK}")
        .section(E.INFO, "API")
        .field(E.INFO, TXT.BAMBOODOM_LABEL_VERSION, resp.version or "—")
        .field(E.DOC, f"{TXT.BAMBOODOM_LABEL_ENDPOINTS} ({len(resp.endpoints)})", "")
    )
    for ep in visible:
        screen = screen.line(f"  — {ep}")
    if remaining > 0:
        screen = screen.line(f"  {TXT.BAMBOODOM_SMOKE_ENDPOINTS_MORE.format(count=remaining)}")

    return (
        screen.section(E.LOCK, "Доступы")
        .check(TXT.BAMBOODOM_LABEL_WRITABLE, ok=writable_ok)
        .check(TXT.BAMBOODOM_LABEL_IMAGE_DIR, ok=images_ok)
        .hint(TXT.BAMBOODOM_SMOKE_HINT)
        .build()
    )


def _build_smoke_error_text(message: str) -> str:
    return (
        Screen(E.WARNING, TXT.BAMBOODOM_SMOKE_TITLE)
        .blank()
        .line(f"{E.CLOSE} {message}")
        .hint(TXT.BAMBOODOM_SMOKE_HINT)
        .build()
    )


def _build_context_text(ctx: ContextResponse, *, stale_banner: str | None = None) -> str:
    screen = Screen(E.LEAF, TXT.BAMBOODOM_CONTEXT_TITLE)
    if stale_banner:
        screen = screen.blank().line(f"{E.WARNING} {stale_banner}")

    # Company section
    company = ctx.company
    screen = screen.section(E.INFO, TXT.BAMBOODOM_CONTEXT_SECTION_COMPANY)
    if company.name:
        screen = screen.field(E.USER, "Название", company.name)
    if company.domain:
        screen = screen.field(E.LINK, TXT.BAMBOODOM_LABEL_DOMAIN, company.domain)
    if company.tagline:
        screen = screen.field_if(E.PEN, TXT.BAMBOODOM_LABEL_TAGLINE, company.tagline)
    if company.location:
        screen = screen.field_if(E.FOLDER, TXT.BAMBOODOM_LABEL_LOCATION, company.location)

    # Materials section
    if ctx.materials:
        screen = screen.section(E.IMAGE, TXT.BAMBOODOM_CONTEXT_SECTION_MATERIALS)
        for m in ctx.materials:
            parts = [m.name]
            if m.articles_count is not None:
                parts.append(f"{m.articles_count} артикулов")
            if m.series_count is not None:
                parts.append(f"{m.series_count} серий")
            screen = screen.line(f"  — {', '.join(parts)}")

    # Typical contexts section
    if ctx.typical_contexts:
        screen = screen.section(E.DOC, TXT.BAMBOODOM_CONTEXT_SECTION_CONTEXTS)
        preview = ctx.typical_contexts[:_TYPICAL_CONTEXTS_PREVIEW]
        extra = len(ctx.typical_contexts) - len(preview)
        suffix = f", …ещё {extra}" if extra > 0 else ""
        screen = screen.line(f"  {', '.join(preview)}{suffix}")

    # Forbidden claims
    if ctx.forbidden_claims:
        screen = screen.section(
            E.LOCK,
            f"{TXT.BAMBOODOM_CONTEXT_SECTION_FORBIDDEN} ({len(ctx.forbidden_claims)})",
        )
        preview = ctx.forbidden_claims[:_FORBIDDEN_CLAIMS_PREVIEW]
        for claim in preview:
            screen = screen.line(f"  — {claim}")
        extra = len(ctx.forbidden_claims) - len(preview)
        if extra > 0:
            screen = screen.line(f"  …ещё {extra}")

    # Footer
    screen = screen.separator()
    screen = screen.field(E.SCHEDULE, TXT.BAMBOODOM_LABEL_UPDATED_AT, _fmt_moscow(ctx.updated_at))
    if ctx.cache_key:
        screen = screen.field(E.KEY, TXT.BAMBOODOM_LABEL_CACHE_KEY, ctx.cache_key)
    screen = screen.hint(TXT.BAMBOODOM_CONTEXT_HINT)
    return screen.build()


def _build_codes_text(codes: ArticleCodesResponse, *, stale_banner: str | None = None) -> str:
    screen = Screen(E.DOC, TXT.BAMBOODOM_CODES_TITLE)
    if stale_banner:
        screen = screen.blank().line(f"{E.WARNING} {stale_banner}")

    screen = screen.blank()
    for category, count in codes.categories().items():
        screen = screen.line(f"  — {category}: {count}")

    total = codes.total if codes.total is not None else sum(codes.categories().values())
    screen = screen.separator().field(E.CHART, TXT.BAMBOODOM_LABEL_TOTAL, total)

    screen = screen.field(E.SCHEDULE, TXT.BAMBOODOM_LABEL_UPDATED_AT, _fmt_moscow(codes.updated_at))
    if codes.cache_key:
        screen = screen.field(E.KEY, TXT.BAMBOODOM_LABEL_CACHE_KEY, codes.cache_key)
    screen = screen.hint(TXT.BAMBOODOM_CODES_HINT)
    return screen.build()


def _build_simple_error_text(title: str, message: str) -> str:
    return Screen(E.WARNING, title).blank().line(f"{E.CLOSE} {message}").build()


# ---------------------------------------------------------------------------
# Error classification helpers
# ---------------------------------------------------------------------------


def _classify_api_error(exc: BamboodomAPIError) -> tuple[str, bool]:
    """Return (human_message, is_transient_server_error)."""
    detail = str(exc)
    if "Timeout" in detail or "Network error" in detail:
        return TXT.BAMBOODOM_SMOKE_NETWORK.format(detail=detail[:200]), True
    if "Server error" in detail:
        return TXT.BAMBOODOM_SMOKE_SERVER.format(detail=detail[:200]), True
    return TXT.BAMBOODOM_SMOKE_UNEXPECTED.format(detail=detail[:200]), False


# ---------------------------------------------------------------------------
# Handlers: entry
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "bamboodom:entry")
async def bamboodom_entry(
    callback: CallbackQuery,
    user: User,
    redis: RedisClient,
) -> None:
    """Entry screen for the Bamboodom admin section."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    settings = get_settings()
    key_present = bool(settings.bamboodom_blog_key.get_secret_value())
    last_ok, last_fail = await _read_history(redis)

    text = _build_entry_text(
        enabled=settings.bamboodom_enabled,
        api_base=settings.bamboodom_api_base,
        key_present=key_present,
        last_ok=last_ok,
        last_fail=last_fail,
    )

    await safe_edit_text(msg, text, reply_markup=bamboodom_entry_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# Handlers: smoke-test
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "bamboodom:smoke")
async def bamboodom_smoke(
    callback: CallbackQuery,
    user: User,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
) -> None:
    """Execute `blog_key_test` and render result screen."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    await callback.answer(TXT.BAMBOODOM_SMOKE_PROGRESS)

    settings = get_settings()
    if not settings.bamboodom_blog_key.get_secret_value():
        text = _build_smoke_error_text(TXT.BAMBOODOM_SMOKE_KEY_MISSING)
        await _record_fail(redis, "key_missing")
        await safe_edit_text(msg, text, reply_markup=bamboodom_smoke_result_kb())
        return

    client = BamboodomClient(http_client=http_client, redis=redis)

    try:
        resp = await client.key_test()
    except BamboodomAuthError:
        log.info("bamboodom_smoke_test_failed", reason="auth")
        await _record_fail(redis, "auth")
        text = _build_smoke_error_text(TXT.BAMBOODOM_SMOKE_KEY_INVALID)
        await safe_edit_text(msg, text, reply_markup=bamboodom_smoke_result_kb())
        return
    except BamboodomRateLimitError as exc:
        log.info("bamboodom_smoke_test_failed", reason="rate_limit", retry_after=exc.retry_after)
        await _record_fail(redis, f"rate_limit retry={exc.retry_after}")
        text = _build_smoke_error_text(TXT.BAMBOODOM_SMOKE_RATE_LIMIT.format(retry_after=exc.retry_after))
        await safe_edit_text(msg, text, reply_markup=bamboodom_smoke_result_kb())
        return
    except BamboodomAPIError as exc:
        message, is_transient = _classify_api_error(exc)
        log.warning("bamboodom_smoke_test_failed", reason="server" if is_transient else "api", detail=str(exc))
        if is_transient:
            sentry_sdk.capture_exception(exc)
        await _record_fail(redis, str(exc)[:200])
        await safe_edit_text(msg, _build_smoke_error_text(message), reply_markup=bamboodom_smoke_result_kb())
        return
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        log.exception("bamboodom_smoke_test_unexpected")
        await _record_fail(redis, f"unexpected: {exc}"[:200])
        text = _build_smoke_error_text(TXT.BAMBOODOM_SMOKE_UNEXPECTED.format(detail=str(exc)[:200]))
        await safe_edit_text(msg, text, reply_markup=bamboodom_smoke_result_kb())
        return

    log.info(
        "bamboodom_smoke_test_ok",
        version=resp.version,
        endpoints=resp.endpoints,
        writable=resp.writable,
        image_dir_writable=resp.image_dir_writable,
    )
    await _record_ok(redis)
    await safe_edit_text(msg, _build_smoke_ok_text(resp), reply_markup=bamboodom_smoke_result_kb())


# ---------------------------------------------------------------------------
# Handlers: context / codes
# ---------------------------------------------------------------------------


async def _render_context_screen(
    msg,
    callback: CallbackQuery,
    *,
    client: BamboodomClient,
    force_refresh: bool,
    previous_cache_key: str | None = None,
) -> None:
    """Shared rendering for bamboodom:context + bamboodom:context:refresh."""
    try:
        resp, was_fresh = await client.get_context(force_refresh=force_refresh)
    except BamboodomAuthError:
        cached = await client.peek_cached_context()
        await _serve_with_fallback(msg, callback, cached, TXT.BAMBOODOM_SMOKE_KEY_INVALID, which="context")
        return
    except BamboodomRateLimitError as exc:
        cached = await client.peek_cached_context()
        banner = TXT.BAMBOODOM_SMOKE_RATE_LIMIT.format(retry_after=exc.retry_after)
        await _serve_with_fallback(msg, callback, cached, banner, which="context")
        return
    except BamboodomAPIError as exc:
        message, is_transient = _classify_api_error(exc)
        if is_transient:
            sentry_sdk.capture_exception(exc)
        cached = await client.peek_cached_context()
        await _serve_with_fallback(msg, callback, cached, message, which="context")
        return
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        log.exception("bamboodom_context_unexpected")
        cached = await client.peek_cached_context()
        await _serve_with_fallback(
            msg, callback, cached, TXT.BAMBOODOM_SMOKE_UNEXPECTED.format(detail=str(exc)[:200]), which="context"
        )
        return

    if force_refresh and not was_fresh:
        # force_refresh always hits API — if was_fresh=False something weird happened.
        log.warning("bamboodom_force_refresh_hit_cache", which="context")

    unchanged = (
        force_refresh
        and previous_cache_key is not None
        and resp.cache_key is not None
        and resp.cache_key == previous_cache_key
    )

    log.info("bamboodom_context_ok", cache_key=resp.cache_key, was_fresh=was_fresh, unchanged=unchanged)
    alert = None
    if force_refresh:
        alert = TXT.BAMBOODOM_CONTEXT_REFRESH_UNCHANGED if unchanged else TXT.BAMBOODOM_CONTEXT_REFRESH_DONE
    await safe_edit_text(msg, _build_context_text(resp), reply_markup=bamboodom_context_kb())
    if alert:
        await callback.answer(alert)
    else:
        await callback.answer()


async def _render_codes_screen(
    msg,
    callback: CallbackQuery,
    *,
    client: BamboodomClient,
    force_refresh: bool,
    previous_cache_key: str | None = None,
) -> None:
    """Shared rendering for bamboodom:codes + bamboodom:codes:refresh."""
    try:
        resp, was_fresh = await client.get_article_codes(force_refresh=force_refresh)
    except BamboodomAuthError:
        cached = await client.peek_cached_codes()
        await _serve_with_fallback(msg, callback, cached, TXT.BAMBOODOM_SMOKE_KEY_INVALID, which="codes")
        return
    except BamboodomRateLimitError as exc:
        cached = await client.peek_cached_codes()
        banner = TXT.BAMBOODOM_SMOKE_RATE_LIMIT.format(retry_after=exc.retry_after)
        await _serve_with_fallback(msg, callback, cached, banner, which="codes")
        return
    except BamboodomAPIError as exc:
        message, is_transient = _classify_api_error(exc)
        if is_transient:
            sentry_sdk.capture_exception(exc)
        cached = await client.peek_cached_codes()
        await _serve_with_fallback(msg, callback, cached, message, which="codes")
        return
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        log.exception("bamboodom_codes_unexpected")
        cached = await client.peek_cached_codes()
        await _serve_with_fallback(
            msg, callback, cached, TXT.BAMBOODOM_SMOKE_UNEXPECTED.format(detail=str(exc)[:200]), which="codes"
        )
        return

    unchanged = (
        force_refresh
        and previous_cache_key is not None
        and resp.cache_key is not None
        and resp.cache_key == previous_cache_key
    )

    log.info("bamboodom_codes_ok", cache_key=resp.cache_key, was_fresh=was_fresh, total=resp.total, unchanged=unchanged)
    alert = None
    if force_refresh:
        alert = TXT.BAMBOODOM_CONTEXT_REFRESH_UNCHANGED if unchanged else TXT.BAMBOODOM_CONTEXT_REFRESH_DONE
    await safe_edit_text(msg, _build_codes_text(resp), reply_markup=bamboodom_codes_kb())
    if alert:
        await callback.answer(alert)
    else:
        await callback.answer()


async def _serve_with_fallback(
    msg,
    callback: CallbackQuery,
    cached: ContextResponse | ArticleCodesResponse | None,
    error_detail: str,
    *,
    which: str,
) -> None:
    """When a fresh fetch fails: serve cached data with a banner, else show error."""
    if cached is not None:
        age = _age_from_iso(cached.updated_at) if cached.updated_at else "—"
        banner = TXT.BAMBOODOM_CONTEXT_STALE_BANNER.format(detail=error_detail, age=age)
        log.warning("bamboodom_served_stale_cache", which=which, detail=error_detail[:200])
        if which == "context":
            text = _build_context_text(cached, stale_banner=banner)
            markup = bamboodom_context_kb()
        else:
            text = _build_codes_text(cached, stale_banner=banner)
            markup = bamboodom_codes_kb()
        await safe_edit_text(msg, text, reply_markup=markup)
        await callback.answer()
        return

    # No cache at all — show plain error with retry button.
    log.info("bamboodom_no_cache_on_error", which=which, detail=error_detail[:200])
    if which == "context":
        title = TXT.BAMBOODOM_CONTEXT_TITLE
        fallback_text = TXT.BAMBOODOM_CONTEXT_NO_DATA
        markup = bamboodom_context_kb()
    else:
        title = TXT.BAMBOODOM_CODES_TITLE
        fallback_text = TXT.BAMBOODOM_CODES_NO_DATA
        markup = bamboodom_codes_kb()
    await safe_edit_text(
        msg, _build_simple_error_text(title, f"{error_detail}\n\n{fallback_text}"), reply_markup=markup
    )
    await callback.answer()


@router.callback_query(F.data == "bamboodom:context")
async def bamboodom_context(
    callback: CallbackQuery,
    user: User,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    await callback.answer(TXT.BAMBOODOM_CONTEXT_PROGRESS)

    settings = get_settings()
    if not settings.bamboodom_blog_key.get_secret_value():
        await safe_edit_text(
            msg,
            _build_simple_error_text(TXT.BAMBOODOM_CONTEXT_TITLE, TXT.BAMBOODOM_SMOKE_KEY_MISSING),
            reply_markup=bamboodom_context_kb(),
        )
        return

    client = BamboodomClient(http_client=http_client, redis=redis)
    await _render_context_screen(msg, callback, client=client, force_refresh=False)


@router.callback_query(F.data == "bamboodom:context:refresh")
async def bamboodom_context_refresh(
    callback: CallbackQuery,
    user: User,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    await callback.answer(TXT.BAMBOODOM_CONTEXT_PROGRESS)

    settings = get_settings()
    if not settings.bamboodom_blog_key.get_secret_value():
        await safe_edit_text(
            msg,
            _build_simple_error_text(TXT.BAMBOODOM_CONTEXT_TITLE, TXT.BAMBOODOM_SMOKE_KEY_MISSING),
            reply_markup=bamboodom_context_kb(),
        )
        return

    client = BamboodomClient(http_client=http_client, redis=redis)
    cached = await client.peek_cached_context()
    previous_key = cached.cache_key if cached else None
    await _render_context_screen(msg, callback, client=client, force_refresh=True, previous_cache_key=previous_key)


@router.callback_query(F.data == "bamboodom:codes")
async def bamboodom_codes(
    callback: CallbackQuery,
    user: User,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    await callback.answer(TXT.BAMBOODOM_CODES_PROGRESS)

    settings = get_settings()
    if not settings.bamboodom_blog_key.get_secret_value():
        await safe_edit_text(
            msg,
            _build_simple_error_text(TXT.BAMBOODOM_CODES_TITLE, TXT.BAMBOODOM_SMOKE_KEY_MISSING),
            reply_markup=bamboodom_codes_kb(),
        )
        return

    client = BamboodomClient(http_client=http_client, redis=redis)
    await _render_codes_screen(msg, callback, client=client, force_refresh=False)


@router.callback_query(F.data == "bamboodom:codes:refresh")
async def bamboodom_codes_refresh(
    callback: CallbackQuery,
    user: User,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    await callback.answer(TXT.BAMBOODOM_CODES_PROGRESS)

    settings = get_settings()
    if not settings.bamboodom_blog_key.get_secret_value():
        await safe_edit_text(
            msg,
            _build_simple_error_text(TXT.BAMBOODOM_CODES_TITLE, TXT.BAMBOODOM_SMOKE_KEY_MISSING),
            reply_markup=bamboodom_codes_kb(),
        )
        return

    client = BamboodomClient(http_client=http_client, redis=redis)
    cached = await client.peek_cached_codes()
    previous_key = cached.cache_key if cached else None
    await _render_codes_screen(msg, callback, client=client, force_refresh=True, previous_cache_key=previous_key)


# ---------------------------------------------------------------------------
# Handlers: settings stub
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "bamboodom:settings")
async def bamboodom_settings(
    callback: CallbackQuery,
    user: User,
) -> None:
    """Settings stub — Session 4 will populate."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    text = Screen(E.GEAR, TXT.BAMBOODOM_SETTINGS_TITLE).blank().line(TXT.BAMBOODOM_SETTINGS_STUB).build()
    await safe_edit_text(msg, text, reply_markup=bamboodom_settings_kb())
    await callback.answer()
