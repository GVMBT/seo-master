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
from typing import Any

import httpx
import sentry_sdk
import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_edit_text, safe_message
from bot.texts import bamboodom as TXT
from bot.texts import strings as S
from bot.texts.emoji import E
from bot.texts.screens import Screen
from cache.client import RedisClient
from cache.keys import BAMBOODOM_PUBLISH_HISTORY_TTL, BAMBOODOM_PUBLISH_LOCK_TTL
from db.models import User
from integrations.bamboodom import (
    ArticleCodesResponse,
    BamboodomAPIError,
    BamboodomAuthError,
    BamboodomClient,
    BamboodomRateLimitError,
    ContextResponse,
    KeyTestResponse,
    PublishResponse,
)
from keyboards.bamboodom import (
    bamboodom_ai_keyword_kb,
    bamboodom_ai_material_kb,
    bamboodom_ai_preview_kb,
    bamboodom_ai_result_kb,
    bamboodom_codes_kb,
    bamboodom_context_kb,
    bamboodom_entry_kb,
    bamboodom_history_kb,
    bamboodom_publish_confirm_kb,
    bamboodom_publish_input_kb,
    bamboodom_publish_result_kb,
    bamboodom_settings_kb,
    bamboodom_smoke_result_kb,
)
from services.ai.bamboodom import (
    BamboodomArticleService,
    BamboodomGenerationError,
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


# FSM for manual publishing (Session 3A)
class PublishFSM(StatesGroup):
    input_json = State()
    confirm = State()


# Redis keys for publish lock + history
_PUBLISH_LOCK_KEY = "bamboodom:publish_lock:{user_id}"
_PUBLISH_HISTORY_KEY = "bamboodom:publish_history"
_HISTORY_MAX_ENTRIES = 10
_MAX_JSON_FILE_BYTES = 100_000
_MAX_INLINE_JSON_CHARS = 4000
_REQUIRED_PUBLISH_FIELDS = ("title", "blocks")


def _normalize_smart_quotes(text: str) -> str:
    """Replace iOS/macOS smart quotes with ASCII variants.

    Telegram auto-formatting on some clients breaks JSON parse. Side B specifically
    requested this normalization in SESSION_3A_ANSWERS.md §А2.
    """
    return (
        text.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u00ab", '"')
        .replace("\u00bb", '"')
    )


def _validate_payload_shape(payload: dict) -> list[str]:
    """Return list of missing required fields in a publish payload."""
    missing = []
    if not isinstance(payload, dict):
        return ["payload must be a JSON object"]
    for field in _REQUIRED_PUBLISH_FIELDS:
        if field not in payload or not payload[field]:
            missing.append(field)
    if "blocks" in payload and not isinstance(payload["blocks"], list):
        missing.append("blocks (must be a list)")
    return missing


async def _try_acquire_publish_lock(redis: RedisClient, user_id: int) -> bool:
    """Try to acquire a 3-second lock to prevent double-publishes.

    Returns True if acquired (caller may proceed), False if another publish is in flight.
    """
    key = _PUBLISH_LOCK_KEY.format(user_id=user_id)
    try:
        result = await redis.set(key, "1", ex=BAMBOODOM_PUBLISH_LOCK_TTL, nx=True)
    except Exception:
        log.warning("bamboodom_publish_lock_error", exc_info=True)
        return True  # fail-open: degraded without lock rather than block user
    return bool(result)


def _deep_json_decode(raw, *, max_depth: int = 4) -> object:
    """Decode a value that might be multi-layer JSON-encoded (Upstash quirks).

    Handles three cases observed empirically:
    1. Plain JSON string → `json.loads()` once yields native Python value.
    2. Double-encoded string → two iterations of `json.loads()` required.
    3. A LIST whose elements are themselves JSON-strings → unwrap each element.

    Iterates up to `max_depth` times; stops on the first shape that is neither
    a string nor a list-of-strings.
    """
    value = raw
    for _ in range(max_depth):
        if isinstance(value, str):
            try:
                value = json.loads(value)
                continue
            except ValueError, TypeError:
                break
        if isinstance(value, list) and value and all(isinstance(e, str) for e in value):
            try:
                value = [json.loads(e) for e in value]
                continue
            except ValueError, TypeError:
                break
        break
    return value


async def _append_history(redis: RedisClient, entry: dict) -> None:
    """Prepend an entry to the publish history list (max _HISTORY_MAX_ENTRIES, TTL 7 days)."""
    try:
        raw = await redis.get(_PUBLISH_HISTORY_KEY)
    except Exception:
        log.warning("bamboodom_history_read_error", exc_info=True)
        raw = None

    decoded = _deep_json_decode(raw) if raw is not None else []
    if not isinstance(decoded, list):
        decoded = []
    # Defensive: drop any non-dict leftovers from previous buggy writes.
    history: list[dict] = [e for e in decoded if isinstance(e, dict)]

    history.insert(0, entry)
    history = history[:_HISTORY_MAX_ENTRIES]

    try:
        await redis.set(
            _PUBLISH_HISTORY_KEY,
            json.dumps(history, ensure_ascii=False),
            ex=BAMBOODOM_PUBLISH_HISTORY_TTL,
        )
    except Exception:
        log.warning("bamboodom_history_write_error", exc_info=True)


async def _read_history(redis: RedisClient) -> list[dict]:
    """Read publish history. Tolerates plain JSON-arrays, Upstash double-encoding,
    and lists where every element was stored as a JSON-string separately.
    """
    try:
        raw = await redis.get(_PUBLISH_HISTORY_KEY)
    except Exception:
        log.warning("bamboodom_history_read_error", exc_info=True)
        return []
    if raw is None:
        return []
    decoded = _deep_json_decode(raw)
    # Diagnostic — one line per read, helps confirm the Upstash storage shape.
    log.info(
        "bamboodom_history_read",
        raw_type=type(raw).__name__,
        raw_preview=str(raw)[:150],
        decoded_type=type(decoded).__name__,
        decoded_len=len(decoded) if hasattr(decoded, "__len__") else None,
    )
    if not isinstance(decoded, list):
        log.warning("bamboodom_history_unexpected_shape", shape=type(decoded).__name__)
        return []
    return [e for e in decoded if isinstance(e, dict)]


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


# ---------------------------------------------------------------------------
# Handlers: manual sandbox publish (Session 3A)
# ---------------------------------------------------------------------------


def _build_publish_entry_text() -> str:
    return (
        Screen(E.UPLOAD, TXT.BAMBOODOM_PUBLISH_ENTRY_TITLE)
        .blank()
        .line(TXT.BAMBOODOM_PUBLISH_SANDBOX_NOTE)
        .blank()
        .line(TXT.BAMBOODOM_PUBLISH_ENTRY_HINT)
        .build()
    )


def _build_publish_confirm_text(payload: dict) -> str:
    title = str(payload.get("title") or "—")
    excerpt = str(payload.get("excerpt") or "—")
    blocks = payload.get("blocks") or []
    return (
        Screen(E.PEN, TXT.BAMBOODOM_PUBLISH_CONFIRM_TITLE)
        .blank()
        .line(
            TXT.BAMBOODOM_PUBLISH_CONFIRM_TEXT.format(
                title=title[:120],
                excerpt=excerpt[:200],
                blocks_count=len(blocks) if isinstance(blocks, list) else "?",
                mode=TXT.BAMBOODOM_PUBLISH_MODE_SANDBOX,
            )
        )
        .build()
    )


def _build_publish_result_text(
    resp: PublishResponse,
    *,
    submitted_title: str,
) -> str:
    action_label = (
        TXT.BAMBOODOM_PUBLISH_ACTION_CREATED if resp.action_type == "created" else TXT.BAMBOODOM_PUBLISH_ACTION_UPDATED
    )
    screen = (
        Screen(E.CHECK, TXT.BAMBOODOM_PUBLISH_RESULT_TITLE)
        .blank()
        .line(f"{E.CHECK} {TXT.BAMBOODOM_PUBLISH_SUCCESS}")
        .blank()
        .line(f"<i>{TXT.BAMBOODOM_PUBLISH_BADGE_SANDBOX}</i>")
        .section(E.INFO, "Детали")
        .field(E.PEN, "Заголовок", submitted_title[:120])
        .field(E.DOC, "Slug", resp.slug or "—")
        .field(E.SYNC, "Действие", action_label)
        .field(E.CHART, "Блоков принято", resp.blocks_parsed if resp.blocks_parsed is not None else "—")
    )

    if resp.blocks_dropped:
        screen = screen.blank().line(
            f"{E.WARNING} {TXT.BAMBOODOM_PUBLISH_BLOCKS_DROPPED.format(count=len(resp.blocks_dropped))}"
        )
        for drop in resp.blocks_dropped[:5]:
            parts = [f"#{drop.index}" if drop.index is not None else "#?"]
            if drop.type:
                parts.append(drop.type)
            if drop.reason:
                parts.append(drop.reason)
            if drop.article:
                parts.append(drop.article)
            elif drop.raw_type:
                parts.append(f"raw={drop.raw_type}")
            screen = screen.line(f"  — {' '.join(parts)}")
        if len(resp.blocks_dropped) > 5:
            screen = screen.line(f"  …ещё {len(resp.blocks_dropped) - 5}")

    screen = screen.hint(TXT.BAMBOODOM_PUBLISH_HINT)
    return screen.build()


def _resolve_article_url(resp: PublishResponse) -> str | None:
    """Convert server-provided relative URL to full HTTP link for inline button."""
    if not resp.url:
        return None
    url = resp.url
    if url.startswith(("http://", "https://")):
        return url
    # relative — prepend host
    host = TXT.BAMBOODOM_URL_HOST.rstrip("/")
    return f"{host}{url if url.startswith('/') else '/' + url}"


@router.callback_query(F.data == "bamboodom:publish")
async def bamboodom_publish_entry(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    """Open publish FSM — prompt for JSON input."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    settings = get_settings()
    if not settings.bamboodom_blog_key.get_secret_value():
        await safe_edit_text(
            msg,
            _build_simple_error_text(TXT.BAMBOODOM_PUBLISH_ENTRY_TITLE, TXT.BAMBOODOM_SMOKE_KEY_MISSING),
            reply_markup=bamboodom_publish_input_kb(),
        )
        await callback.answer()
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        log.info("bamboodom_publish_interrupted_other_fsm", previous=interrupted)

    await state.set_state(PublishFSM.input_json)
    await safe_edit_text(msg, _build_publish_entry_text(), reply_markup=bamboodom_publish_input_kb())
    await callback.answer()


@router.callback_query(F.data == "bamboodom:publish:example")
async def bamboodom_publish_example(callback: CallbackQuery, user: User) -> None:
    """Send the example JSON as a separate message so the user can copy it easily."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    # Send raw JSON inside a code-block for easy copy.
    bot = callback.bot
    if bot is not None and callback.from_user is not None:
        await bot.send_message(
            callback.from_user.id,
            f"<pre>{TXT.BAMBOODOM_PUBLISH_EXAMPLE_JSON}</pre>",
        )
    await callback.answer("Пример отправлен — скопируйте, поправьте, пришлите в чат")


@router.message(PublishFSM.input_json, F.text)
async def bamboodom_publish_input_text(
    message: Message,
    user: User,
    state: FSMContext,
) -> None:
    """Parse JSON from a text message."""
    if not _is_admin(user):
        return
    text = message.text or ""
    if len(text) > _MAX_INLINE_JSON_CHARS:
        await message.answer(
            TXT.BAMBOODOM_PUBLISH_TEXT_TOO_LONG.format(length=len(text)),
            reply_markup=bamboodom_publish_input_kb(),
        )
        return
    await _handle_publish_input(message, state, text)


@router.message(PublishFSM.input_json, F.document)
async def bamboodom_publish_input_document(
    message: Message,
    user: User,
    state: FSMContext,
) -> None:
    """Parse JSON from an uploaded .json document (fallback for long payloads)."""
    if not _is_admin(user):
        return
    doc = message.document
    if doc is None:
        return
    if doc.file_size and doc.file_size > _MAX_JSON_FILE_BYTES:
        await message.answer(
            TXT.BAMBOODOM_PUBLISH_FILE_TOO_LARGE.format(size=doc.file_size),
            reply_markup=bamboodom_publish_input_kb(),
        )
        return

    bot = message.bot
    if bot is None:
        return
    try:
        file_obj = await bot.get_file(doc.file_id)
        binary = await bot.download_file(file_obj.file_path) if file_obj.file_path else None
        if binary is None:
            raise ValueError("empty file")
        raw = binary.read() if hasattr(binary, "read") else bytes(binary)
        text = raw.decode("utf-8")
    except Exception as exc:
        log.warning("bamboodom_publish_file_read_failed", exc_info=True)
        await message.answer(
            TXT.BAMBOODOM_PUBLISH_FILE_READ_ERROR.format(detail=str(exc)[:200]),
            reply_markup=bamboodom_publish_input_kb(),
        )
        return

    await _handle_publish_input(message, state, text)


async def _handle_publish_input(message: Message, state: FSMContext, text: str) -> None:
    """Common JSON parse + shape validation + transition to confirm state."""
    normalized = _normalize_smart_quotes(text)
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError as exc:
        await message.answer(
            TXT.BAMBOODOM_PUBLISH_JSON_PARSE_ERROR.format(detail=str(exc)),
            reply_markup=bamboodom_publish_input_kb(),
        )
        return

    missing = _validate_payload_shape(payload)
    if missing:
        await message.answer(
            TXT.BAMBOODOM_PUBLISH_MISSING_FIELDS.format(fields=", ".join(missing)),
            reply_markup=bamboodom_publish_input_kb(),
        )
        return

    await state.update_data(publish_payload=payload)
    await state.set_state(PublishFSM.confirm)
    await message.answer(
        _build_publish_confirm_text(payload),
        reply_markup=bamboodom_publish_confirm_kb(),
    )


@router.callback_query(F.data == "bamboodom:publish:submit", PublishFSM.confirm)
async def bamboodom_publish_submit(
    callback: CallbackQuery,
    user: User,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    state: FSMContext,
) -> None:
    """Send the pre-approved payload to blog_publish?sandbox=1."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    # Rate-limit guard (1 publish / 3 sec server-side).
    acquired = await _try_acquire_publish_lock(redis, user.id)
    if not acquired:
        await callback.answer(TXT.BAMBOODOM_PUBLISH_LOCKED, show_alert=True)
        return

    data = await state.get_data()
    payload = data.get("publish_payload")
    if not isinstance(payload, dict):
        log.warning("bamboodom_publish_no_payload_in_state")
        await state.clear()
        await safe_edit_text(
            msg,
            _build_simple_error_text(
                TXT.BAMBOODOM_PUBLISH_RESULT_TITLE,
                TXT.BAMBOODOM_PUBLISH_JSON_PARSE_ERROR.format(detail="no payload"),
            ),
            reply_markup=bamboodom_publish_result_kb(None),
        )
        await callback.answer()
        return

    await callback.answer(TXT.BAMBOODOM_PUBLISH_PROGRESS)
    client = BamboodomClient(http_client=http_client, redis=redis)

    try:
        resp = await client.publish(payload, sandbox=True)
    except BamboodomAuthError:
        log.info("bamboodom_publish_failed", reason="auth")
        await state.clear()
        await safe_edit_text(
            msg,
            _build_simple_error_text(TXT.BAMBOODOM_PUBLISH_RESULT_TITLE, TXT.BAMBOODOM_SMOKE_KEY_INVALID),
            reply_markup=bamboodom_publish_result_kb(None),
        )
        return
    except BamboodomRateLimitError as exc:
        log.info("bamboodom_publish_failed", reason="rate_limit", retry_after=exc.retry_after)
        await safe_edit_text(
            msg,
            _build_simple_error_text(
                TXT.BAMBOODOM_PUBLISH_RESULT_TITLE,
                TXT.BAMBOODOM_SMOKE_RATE_LIMIT.format(retry_after=exc.retry_after),
            ),
            reply_markup=bamboodom_publish_confirm_kb(),
        )
        return
    except BamboodomAPIError as exc:
        message_text, is_transient = _classify_api_error(exc)
        log.warning("bamboodom_publish_failed", reason="server" if is_transient else "api", detail=str(exc))
        if is_transient:
            sentry_sdk.capture_exception(exc)
        await safe_edit_text(
            msg,
            _build_simple_error_text(TXT.BAMBOODOM_PUBLISH_RESULT_TITLE, message_text),
            reply_markup=bamboodom_publish_confirm_kb(),
        )
        return
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        log.exception("bamboodom_publish_unexpected")
        await safe_edit_text(
            msg,
            _build_simple_error_text(
                TXT.BAMBOODOM_PUBLISH_RESULT_TITLE,
                TXT.BAMBOODOM_SMOKE_UNEXPECTED.format(detail=str(exc)[:200]),
            ),
            reply_markup=bamboodom_publish_confirm_kb(),
        )
        return

    # Success path.
    submitted_title = str(payload.get("title") or "")
    article_url = _resolve_article_url(resp)
    log.info(
        "bamboodom_publish_ok",
        slug=resp.slug,
        action_type=resp.action_type,
        blocks_parsed=resp.blocks_parsed,
        blocks_dropped_count=len(resp.blocks_dropped),
    )

    history_entry = {
        "slug": resp.slug,
        "title": submitted_title[:200],
        "action_type": resp.action_type,
        "url": article_url,
        "created_at": _now_iso(),
    }
    await _append_history(redis, history_entry)

    await state.clear()
    await safe_edit_text(
        msg,
        _build_publish_result_text(resp, submitted_title=submitted_title),
        reply_markup=bamboodom_publish_result_kb(article_url),
    )


# ---------------------------------------------------------------------------
# Handlers: history
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "bamboodom:history")
async def bamboodom_history(
    callback: CallbackQuery,
    user: User,
    redis: RedisClient,
) -> None:
    """Show recent publish history (last 10, TTL 7 days)."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    history = await _read_history(redis)

    screen = Screen(E.SCHEDULE, TXT.BAMBOODOM_HISTORY_TITLE).blank()
    rendered = 0
    for entry in history:
        if not isinstance(entry, dict):
            continue
        ts = _fmt_moscow(entry.get("created_at")) if entry.get("created_at") else "—"
        title = (entry.get("title") or "—")[:80]
        action = entry.get("action_type") or "—"
        slug = entry.get("slug") or "—"
        screen = screen.line(f"— <b>{title}</b>")
        screen = screen.line(f"  {ts} · {action} · <code>{slug}</code>")
        rendered += 1
    if rendered == 0:
        screen = screen.line(TXT.BAMBOODOM_HISTORY_EMPTY)
    screen = screen.hint(TXT.BAMBOODOM_HISTORY_HINT)

    await safe_edit_text(msg, screen.build(), reply_markup=bamboodom_history_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# AI publish FSM (Session 4A) — generate article via Claude, publish to sandbox
# ---------------------------------------------------------------------------


class AIPublishFSM(StatesGroup):
    choose_material = State()
    enter_keyword = State()
    preview = State()


_MATERIAL_LABELS: dict[str, str] = {
    "wpc": TXT.BAMBOODOM_AI_MATERIAL_WPC,
    "flex": TXT.BAMBOODOM_AI_MATERIAL_FLEX,
    "reiki": TXT.BAMBOODOM_AI_MATERIAL_REIKI,
    "profiles": TXT.BAMBOODOM_AI_MATERIAL_PROFILES,
}

_MAX_KEYWORD_LENGTH = 300
_PREVIEW_PARAGRAPHS = 2


def _build_ai_entry_text() -> str:
    return (
        Screen(E.AI_BRAIN, TXT.BAMBOODOM_AI_TITLE)
        .blank()
        .line(TXT.BAMBOODOM_AI_CHOOSE_MATERIAL_HINT)
        .blank()
        .line(f"<i>{TXT.BAMBOODOM_AI_SANDBOX_NOTE}</i>")
        .build()
    )


def _build_ai_keyword_text(material: str) -> str:
    label = _MATERIAL_LABELS.get(material, material)
    return (
        Screen(E.PEN, TXT.BAMBOODOM_AI_KEYWORD_TITLE)
        .blank()
        .field(E.FOLDER, "Категория", label)
        .blank()
        .line(TXT.BAMBOODOM_AI_KEYWORD_PROMPT)
        .build()
    )


def _build_ai_generating_text(material: str, keyword: str) -> str:
    label = _MATERIAL_LABELS.get(material, material)
    return (
        Screen(E.AI_BRAIN, TXT.BAMBOODOM_AI_GENERATING_TITLE)
        .blank()
        .field(E.FOLDER, "Категория", label)
        .field(E.PEN, "Тема", keyword[:120])
        .blank()
        .line(TXT.BAMBOODOM_AI_GENERATING_HINT)
        .build()
    )


def _extract_first_paragraphs(blocks: list[dict], limit: int) -> str:
    """Pull first `limit` paragraph blocks' text for preview display."""
    paragraphs = []
    for block in blocks:
        if block.get("type") == "p" and isinstance(block.get("text"), str):
            paragraphs.append(block["text"])
            if len(paragraphs) >= limit:
                break
    return "\n\n".join(p[:400] for p in paragraphs)


def _build_ai_preview_text(
    *,
    material: str,
    draft,
    validation_issues: list[str],
) -> str:
    label = _MATERIAL_LABELS.get(material, material)
    summary = TXT.BAMBOODOM_AI_PREVIEW_SUMMARY.format(
        title=draft.title[:120],
        excerpt=draft.excerpt[:200],
        blocks_count=len(draft.blocks),
        material=label,
    )
    paragraphs = _extract_first_paragraphs(draft.blocks, _PREVIEW_PARAGRAPHS)
    screen = Screen(E.EDIT_DOC, TXT.BAMBOODOM_AI_PREVIEW_TITLE).blank().line(summary)
    if paragraphs:
        screen = screen.line(TXT.BAMBOODOM_AI_PREVIEW_FIRST_PARAGRAPHS.format(paragraphs=paragraphs))
    if validation_issues:
        screen = screen.line(TXT.BAMBOODOM_AI_PREVIEW_VALIDATION_WARN.format(count=len(validation_issues)))
        for issue in validation_issues[:4]:
            screen = screen.line(f"  — {issue[:180]}")
        if len(validation_issues) > 4:
            screen = screen.line(f"  …ещё {len(validation_issues) - 4}")
    return screen.build()


def _build_ai_result_text(submitted_title: str, resp) -> str:
    action_label = (
        TXT.BAMBOODOM_PUBLISH_ACTION_CREATED if resp.action_type == "created" else TXT.BAMBOODOM_PUBLISH_ACTION_UPDATED
    )
    screen = (
        Screen(E.CHECK, TXT.BAMBOODOM_AI_RESULT_TITLE)
        .blank()
        .line(f"{E.CHECK} {TXT.BAMBOODOM_AI_RESULT_SUCCESS}")
        .blank()
        .line(f"<i>{TXT.BAMBOODOM_PUBLISH_BADGE_SANDBOX}</i>")
        .section(E.INFO, "Детали")
        .field(E.PEN, "Заголовок", submitted_title[:120])
        .field(E.DOC, "Slug", resp.slug or "—")
        .field(E.SYNC, "Действие", action_label)
        .field(E.CHART, "Блоков принято", resp.blocks_parsed if resp.blocks_parsed is not None else "—")
    )
    if resp.blocks_dropped:
        screen = screen.blank().line(
            f"{E.WARNING} {TXT.BAMBOODOM_PUBLISH_BLOCKS_DROPPED.format(count=len(resp.blocks_dropped))}"
        )
    screen = screen.hint(TXT.BAMBOODOM_PUBLISH_HINT)
    return screen.build()


# --- Entry / material selection ----------------------------------------


@router.callback_query(F.data == "bamboodom:ai:start")
async def ai_start(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    settings = get_settings()
    if not settings.bamboodom_blog_key.get_secret_value():
        await safe_edit_text(
            msg,
            _build_simple_error_text(TXT.BAMBOODOM_AI_TITLE, TXT.BAMBOODOM_SMOKE_KEY_MISSING),
            reply_markup=bamboodom_entry_kb(),
        )
        await callback.answer()
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        log.info("bamboodom_ai_interrupted_other_fsm", previous=interrupted)

    await state.set_state(AIPublishFSM.choose_material)
    await safe_edit_text(msg, _build_ai_entry_text(), reply_markup=bamboodom_ai_material_kb())
    await callback.answer()


@router.callback_query(
    F.data.regexp(r"^bamboodom:ai:mat:(wpc|flex|reiki|profiles)$"),
    AIPublishFSM.choose_material,
)
async def ai_choose_material(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cb_data = callback.data or ""
    material = cb_data.split(":")[-1]
    await state.update_data(ai_material=material)
    await state.set_state(AIPublishFSM.enter_keyword)
    await safe_edit_text(msg, _build_ai_keyword_text(material), reply_markup=bamboodom_ai_keyword_kb())
    await callback.answer()


# --- Keyword entry -----------------------------------------------------


@router.message(AIPublishFSM.enter_keyword, F.text)
async def ai_receive_keyword(
    message: Message,
    user: User,
    state: FSMContext,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
) -> None:
    if not _is_admin(user):
        return
    keyword = (message.text or "").strip()
    if not keyword:
        await message.answer(TXT.BAMBOODOM_AI_KEYWORD_EMPTY, reply_markup=bamboodom_ai_keyword_kb())
        return
    if len(keyword) > _MAX_KEYWORD_LENGTH:
        await message.answer(TXT.BAMBOODOM_AI_KEYWORD_TOO_LONG, reply_markup=bamboodom_ai_keyword_kb())
        return

    data = await state.get_data()
    material = data.get("ai_material", "wpc")

    # Show "generating" screen immediately so operator sees progress
    progress_msg = await message.answer(_build_ai_generating_text(material, keyword))
    await _run_ai_generation(
        bot_msg=progress_msg,
        state=state,
        user_id=user.id,
        material=material,
        keyword=keyword,
        redis=redis,
        http_client=http_client,
    )


async def _run_ai_generation(
    *,
    bot_msg,
    state: FSMContext,
    user_id: int,
    material: str,
    keyword: str,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
) -> None:
    """Shared: call BamboodomArticleService, render preview or error."""
    settings = get_settings()
    bamboodom_client = BamboodomClient(http_client=http_client, redis=redis)
    ai_service = BamboodomArticleService(
        http_client=http_client,
        openrouter_api_key=settings.openrouter_api_key.get_secret_value(),
        bamboodom_client=bamboodom_client,
    )

    current_date_iso = _now_iso()

    try:
        draft, validation = await ai_service.generate_and_validate(
            material=material,
            keyword=keyword,
            current_date_iso=current_date_iso,
        )
    except BamboodomGenerationError as exc:
        log.warning("bamboodom_ai_generation_error", detail=str(exc))
        sentry_sdk.capture_exception(exc)
        await safe_edit_text(
            bot_msg,
            _build_simple_error_text(
                TXT.BAMBOODOM_AI_TITLE,
                TXT.BAMBOODOM_AI_GENERATION_FAILED.format(detail=str(exc)[:250]),
            ),
            reply_markup=bamboodom_entry_kb(),
        )
        await state.clear()
        return
    except Exception as exc:
        log.exception("bamboodom_ai_generation_unexpected")
        sentry_sdk.capture_exception(exc)
        await safe_edit_text(
            bot_msg,
            _build_simple_error_text(
                TXT.BAMBOODOM_AI_TITLE,
                TXT.BAMBOODOM_AI_GENERATION_FAILED.format(detail=str(exc)[:250]),
            ),
            reply_markup=bamboodom_entry_kb(),
        )
        await state.clear()
        return

    # Stash draft in FSM for the publish step
    await state.update_data(
        ai_material=material,
        ai_keyword=keyword,
        ai_draft_title=draft.title,
        ai_draft_excerpt=draft.excerpt,
        ai_draft_blocks=draft.blocks,
        ai_draft_seo=draft.seo,
    )
    await state.set_state(AIPublishFSM.preview)

    issues_text = [i.detail for i in validation.issues]
    await safe_edit_text(
        bot_msg,
        _build_ai_preview_text(material=material, draft=draft, validation_issues=issues_text),
        reply_markup=bamboodom_ai_preview_kb(),
    )
    _ = user_id  # reserved for future rate-limit logging


@router.callback_query(F.data == "bamboodom:ai:regenerate", AIPublishFSM.preview)
async def ai_regenerate(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
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

    data = await state.get_data()
    material = data.get("ai_material", "wpc")
    keyword = data.get("ai_keyword", "")

    await callback.answer(TXT.BAMBOODOM_AI_GENERATING_PROGRESS)
    await safe_edit_text(msg, _build_ai_generating_text(material, keyword))
    await _run_ai_generation(
        bot_msg=msg,
        state=state,
        user_id=user.id,
        material=material,
        keyword=keyword,
        redis=redis,
        http_client=http_client,
    )


@router.callback_query(F.data == "bamboodom:ai:publish", AIPublishFSM.preview)
async def ai_publish_submit(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
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

    # Rate-limit guard (shared with manual publish: bamboodom:publish_lock)
    acquired = await _try_acquire_publish_lock(redis, user.id)
    if not acquired:
        await callback.answer(TXT.BAMBOODOM_PUBLISH_LOCKED, show_alert=True)
        return

    data = await state.get_data()
    title = data.get("ai_draft_title")
    excerpt = data.get("ai_draft_excerpt")
    blocks = data.get("ai_draft_blocks")
    seo = data.get("ai_draft_seo") or {}
    if not title or not blocks or not isinstance(blocks, list):
        await callback.answer(TXT.BAMBOODOM_AI_GENERATION_FAILED.format(detail="state lost"), show_alert=True)
        await state.clear()
        return

    await callback.answer(TXT.BAMBOODOM_AI_PUBLISHING_PROGRESS)
    payload: dict[str, Any] = {
        "title": title,
        "excerpt": excerpt or "",
        "draft": False,
        "blocks": blocks,
    }
    if isinstance(seo, dict) and seo:
        payload["seo"] = seo

    client = BamboodomClient(http_client=http_client, redis=redis)
    try:
        resp = await client.publish(payload, sandbox=True)
    except BamboodomAuthError:
        await safe_edit_text(
            msg,
            _build_simple_error_text(TXT.BAMBOODOM_AI_RESULT_TITLE, TXT.BAMBOODOM_SMOKE_KEY_INVALID),
            reply_markup=bamboodom_ai_result_kb(None),
        )
        await state.clear()
        return
    except BamboodomRateLimitError as exc:
        await safe_edit_text(
            msg,
            _build_simple_error_text(
                TXT.BAMBOODOM_AI_RESULT_TITLE,
                TXT.BAMBOODOM_SMOKE_RATE_LIMIT.format(retry_after=exc.retry_after),
            ),
            reply_markup=bamboodom_ai_preview_kb(),
        )
        return
    except BamboodomAPIError as exc:
        message_text, is_transient = _classify_api_error(exc)
        if is_transient:
            sentry_sdk.capture_exception(exc)
        await safe_edit_text(
            msg,
            _build_simple_error_text(TXT.BAMBOODOM_AI_RESULT_TITLE, message_text),
            reply_markup=bamboodom_ai_preview_kb(),
        )
        return
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        log.exception("bamboodom_ai_publish_unexpected")
        await safe_edit_text(
            msg,
            _build_simple_error_text(
                TXT.BAMBOODOM_AI_RESULT_TITLE,
                TXT.BAMBOODOM_SMOKE_UNEXPECTED.format(detail=str(exc)[:200]),
            ),
            reply_markup=bamboodom_ai_preview_kb(),
        )
        return

    # Success
    log.info(
        "bamboodom_ai_publish_ok",
        slug=resp.slug,
        action_type=resp.action_type,
        blocks_parsed=resp.blocks_parsed,
        blocks_dropped_count=len(resp.blocks_dropped),
    )

    article_url = _resolve_article_url(resp)
    # Record in history with AI-marker
    history_entry = {
        "slug": resp.slug,
        "title": title[:200],
        "action_type": resp.action_type,
        "url": article_url,
        "source": "ai",
        "created_at": _now_iso(),
    }
    await _append_history(redis, history_entry)

    await state.clear()
    await safe_edit_text(
        msg,
        _build_ai_result_text(title, resp),
        reply_markup=bamboodom_ai_result_kb(article_url),
    )
