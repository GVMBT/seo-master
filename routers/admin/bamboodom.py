"""Admin panel — Bamboodom.ru section (Session 1 skeleton).

Scope:
    - Entry screen with status + timestamps
    - Smoke-test button -> calls `blog_key_test` via BamboodomClient
    - Settings screen (stub until Session 2)

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
    BamboodomAPIError,
    BamboodomAuthError,
    BamboodomClient,
    BamboodomRateLimitError,
    KeyTestResponse,
)
from keyboards.bamboodom import (
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


# ---------------------------------------------------------------------------
# Admin guard (mirrors routers/admin/dashboard.py)
# ---------------------------------------------------------------------------


def _is_admin(user: User) -> bool:
    return user.role == "admin"


# ---------------------------------------------------------------------------
# Timestamp persistence helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """UTC timestamp in ISO-8601 for Redis storage."""
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def _fmt_moscow(iso: str | None) -> str:
    """Render stored UTC timestamp in operator's timezone (Europe/Moscow → UTC+3)."""
    if not iso:
        return TXT.BAMBOODOM_LAST_OK_NONE
    try:
        ts = dt.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    # Storage is UTC; shift to Moscow (no DST since 2011).
    local = ts + dt.timedelta(hours=3)
    return local.strftime("%Y-%m-%d %H:%M МСК")


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
# Screen builders
# ---------------------------------------------------------------------------


def _status_label(*, enabled: bool, key_present: bool) -> str:
    if not enabled:
        return TXT.BAMBOODOM_STATUS_DISABLED
    if not key_present:
        return TXT.BAMBOODOM_STATUS_KEY_MISSING
    return TXT.BAMBOODOM_STATUS_ENABLED


def _build_entry_text(*, enabled: bool, api_base: str, key_present: bool, last_ok: str, last_fail: str) -> str:
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
    endpoints_str = ", ".join(resp.endpoints) if resp.endpoints else "—"
    screen = (
        Screen(E.PULSE, TXT.BAMBOODOM_SMOKE_TITLE)
        .blank()
        .line(f"{E.CHECK} {TXT.BAMBOODOM_SMOKE_OK}")
        .section(E.INFO, "API")
        .field(E.INFO, TXT.BAMBOODOM_LABEL_VERSION, resp.version or "—")
        .field(E.DOC, TXT.BAMBOODOM_LABEL_ENDPOINTS, endpoints_str)
        .section(E.LOCK, "Доступы")
        .check(TXT.BAMBOODOM_LABEL_WRITABLE, ok=writable_ok)
        .check(TXT.BAMBOODOM_LABEL_IMAGE_DIR, ok=images_ok)
        .hint(TXT.BAMBOODOM_SMOKE_HINT)
    )
    return screen.build()


def _build_smoke_error_text(message: str) -> str:
    return (
        Screen(E.WARNING, TXT.BAMBOODOM_SMOKE_TITLE)
        .blank()
        .line(f"{E.CLOSE} {message}")
        .hint(TXT.BAMBOODOM_SMOKE_HINT)
        .build()
    )


# ---------------------------------------------------------------------------
# Handlers
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

    # Quick feedback to the user while the request is in flight.
    await callback.answer(TXT.BAMBOODOM_SMOKE_PROGRESS)

    settings = get_settings()
    if not settings.bamboodom_blog_key.get_secret_value():
        text = _build_smoke_error_text(TXT.BAMBOODOM_SMOKE_KEY_MISSING)
        await _record_fail(redis, "key_missing")
        await safe_edit_text(msg, text, reply_markup=bamboodom_smoke_result_kb())
        return

    client = BamboodomClient(http_client=http_client)

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
        detail = str(exc)
        is_server = "Server error" in detail or "Timeout" in detail or "Network error" in detail
        log.warning(
            "bamboodom_smoke_test_failed",
            reason="server" if is_server else "api",
            detail=detail,
        )
        if is_server:
            sentry_sdk.capture_exception(exc)
            template = (
                TXT.BAMBOODOM_SMOKE_NETWORK
                if "Timeout" in detail or "Network error" in detail
                else TXT.BAMBOODOM_SMOKE_SERVER
            )
            text = _build_smoke_error_text(template.format(detail=detail[:200]))
        else:
            text = _build_smoke_error_text(TXT.BAMBOODOM_SMOKE_UNEXPECTED.format(detail=detail[:200]))
        await _record_fail(redis, detail[:200])
        await safe_edit_text(msg, text, reply_markup=bamboodom_smoke_result_kb())
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
        endpoints_count=len(resp.endpoints),
        writable=resp.writable,
        image_dir_writable=resp.image_dir_writable,
    )
    await _record_ok(redis)
    text = _build_smoke_ok_text(resp)
    await safe_edit_text(msg, text, reply_markup=bamboodom_smoke_result_kb())


@router.callback_query(F.data == "bamboodom:settings")
async def bamboodom_settings(
    callback: CallbackQuery,
    user: User,
) -> None:
    """Settings screen stub — Session 2 will populate."""
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
