"""Admin panel — Bamboodom.ru: новый root-экран + раздел «Администрирование».

Сессия 4D: разделение раздела Bamboodom на два подраздела:
- Статьи (старый entry-экран, callback теперь `bamboodom:articles`)
- Администрирование (новый раздел, начинаем с переобхода в Я.Вебмастер)

Этот файл регистрирует:
    bamboodom:entry              → root-экран (3 кнопки)
    bamboodom:admin              → подменю администрирования
    bamboodom:admin:recrawl      → краулим сайт, показываем что нашли
    bamboodom:admin:recrawl:run  → шлём найденные URL'ы в Я.Вебмастер

ВАЖНО: после применения 4D в существующем `routers/admin/bamboodom.py`
старый декоратор `@router.callback_query(F.data == "bamboodom:entry")`
ОБЯЗАТЕЛЬНО переименован в `"bamboodom:articles"` (см. README_DEPLOY.md).
Если этого не сделать — оба обработчика отстреляют на один callback и
aiogram возьмёт тот, что зарегистрирован первым.
"""

from __future__ import annotations

import asyncio
import contextlib

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
from integrations.yandex_webmaster import (
    YandexWebmasterAuthError,
    YandexWebmasterClient,
    YandexWebmasterError,
    YandexWebmasterHostNotFoundError,
    YandexWebmasterQuotaExceededError,
    YandexWebmasterRateLimitError,
    add_urls_with_rate_limit,
)
from keyboards.bamboodom import (
    bamboodom_admin_kb,
    bamboodom_recrawl_preview_kb,
    bamboodom_recrawl_progress_kb,
    bamboodom_recrawl_result_kb,
    bamboodom_root_kb,
)
from services.site_crawler import (
    crawl_bamboodom,
    save_snapshot,
)

log = structlog.get_logger()
router = Router()

_RECRAWL_LOCK_KEY = "bamboodom:admin:recrawl_lock:{user_id}"
_RECRAWL_LOCK_TTL = 600  # 10 минут — пока идёт отправка
_RECRAWL_PREVIEW_KEY = "bamboodom:admin:recrawl_preview:{user_id}"
_RECRAWL_PREVIEW_TTL = 900  # 15 минут — между «нашли» и «отправить»

_PREVIEW_URL_LIMIT = 8  # сколько URL'ов показывать на превью
_FAIL_LINE_LIMIT = 5  # сколько ошибок показывать в финальном экране


def _is_admin(user: User) -> bool:
    return user.role == "admin"


# ---------------------------------------------------------------------------
# bamboodom:entry — root-экран (3 кнопки)
# ---------------------------------------------------------------------------


def _build_root_text() -> str:
    return (
        Screen(E.LEAF, TXT.BAMBOODOM_ROOT_TITLE)
        .blank()
        .line(TXT.BAMBOODOM_ROOT_SUBTITLE)
        .blank()
        .hint(TXT.BAMBOODOM_ROOT_HINT)
        .build()
    )


@router.callback_query(F.data == "bamboodom:entry")
async def bamboodom_entry_root(callback: CallbackQuery, user: User) -> None:
    """Корневой экран Bamboodom — 3 кнопки."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    await safe_edit_text(msg, _build_root_text(), reply_markup=bamboodom_root_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# bamboodom:admin — подменю администрирования
# ---------------------------------------------------------------------------


def _build_admin_text() -> str:
    return (
        Screen(E.GEAR, TXT.BAMBOODOM_ADMIN_TITLE)
        .blank()
        .line(TXT.BAMBOODOM_ADMIN_SUBTITLE)
        .blank()
        .hint(TXT.BAMBOODOM_ADMIN_HINT)
        .build()
    )


@router.callback_query(F.data == "bamboodom:admin")
async def bamboodom_admin(callback: CallbackQuery, user: User) -> None:
    """Подменю «Администрирование»."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    await safe_edit_text(msg, _build_admin_text(), reply_markup=bamboodom_admin_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# bamboodom:admin:recrawl — запустить краул и показать что нашли
# ---------------------------------------------------------------------------


def _settings_check() -> str | None:
    """Возвращает текст ошибки если конфиг неполный, иначе None."""
    s = get_settings()
    token = s.yandex_webmaster_token.get_secret_value() if s.yandex_webmaster_token else ""
    if not token:
        return TXT.BAMBOODOM_RECRAWL_NO_AUTH
    return None


def _build_recrawl_intro_text() -> str:
    return (
        Screen(E.SYNC, TXT.BAMBOODOM_RECRAWL_TITLE)
        .blank()
        .line(TXT.BAMBOODOM_RECRAWL_INTRO)
        .blank()
        .hint(TXT.BAMBOODOM_RECRAWL_PROGRESS_CRAWL)
        .build()
    )


def _build_recrawl_preview_text(total: int, new_urls: list[str], first_run: bool) -> str:
    screen = (
        Screen(E.SYNC, TXT.BAMBOODOM_RECRAWL_TITLE)
        .blank()
        .line(TXT.BAMBOODOM_RECRAWL_FOUND.format(total=total, new=len(new_urls)))
    )
    if first_run:
        screen = screen.blank().line(f"{E.INFO} {TXT.BAMBOODOM_RECRAWL_FIRST_RUN.format(total=total)}")
        return screen.build()
    if not new_urls:
        screen = screen.blank().line(f"{E.CHECK} {TXT.BAMBOODOM_RECRAWL_NOTHING_NEW}")
        return screen.build()
    screen = screen.blank().line("Новые URL'ы:")
    for u in new_urls[:_PREVIEW_URL_LIMIT]:
        screen = screen.line(TXT.BAMBOODOM_RECRAWL_PREVIEW_URL_LINE.format(url=u))
    if len(new_urls) > _PREVIEW_URL_LIMIT:
        screen = screen.line(TXT.BAMBOODOM_RECRAWL_PREVIEW_URL_MORE.format(count=len(new_urls) - _PREVIEW_URL_LIMIT))
    screen = screen.blank().hint(TXT.BAMBOODOM_RECRAWL_PREVIEW_HINT)
    return screen.build()


async def _save_preview(redis: RedisClient, user_id: int, new_urls: list[str], all_urls: list[str]) -> None:
    import json

    data = {"new_urls": new_urls, "all_urls": all_urls}
    try:
        await redis.set(
            _RECRAWL_PREVIEW_KEY.format(user_id=user_id),
            json.dumps(data, ensure_ascii=False),
            ex=_RECRAWL_PREVIEW_TTL,
        )
    except Exception:
        log.warning("yw_preview_save_failed", exc_info=True)


async def _read_preview(redis: RedisClient, user_id: int) -> tuple[list[str], list[str]] | None:
    import json

    try:
        raw = await redis.get(_RECRAWL_PREVIEW_KEY.format(user_id=user_id))
    except Exception:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    new_urls = [str(u) for u in (data.get("new_urls") or []) if u]
    all_urls = [str(u) for u in (data.get("all_urls") or []) if u]
    return new_urls, all_urls


@router.callback_query(F.data == "bamboodom:admin:recrawl")
async def bamboodom_admin_recrawl_preview(
    callback: CallbackQuery,
    user: User,
    redis: RedisClient,
) -> None:
    """Сканируем сайт, показываем что нашли, ждём подтверждения."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cfg_err = _settings_check()
    if cfg_err:
        await safe_edit_text(
            msg,
            Screen(E.WARNING, TXT.BAMBOODOM_RECRAWL_TITLE).blank().line(f"{E.CLOSE} {cfg_err}").build(),
            reply_markup=bamboodom_admin_kb(),
        )
        await callback.answer()
        return

    # Промежуточный экран «сканирую…»
    await safe_edit_text(msg, _build_recrawl_intro_text(), reply_markup=bamboodom_recrawl_progress_kb())
    await callback.answer()

    try:
        result = await crawl_bamboodom(redis)
    except Exception as exc:
        log.warning("bamboodom_recrawl_crawl_failed", exc_info=True)
        await safe_edit_text(
            msg,
            Screen(E.WARNING, TXT.BAMBOODOM_RECRAWL_TITLE)
            .blank()
            .line(TXT.BAMBOODOM_RECRAWL_CRAWL_FAIL.format(detail=str(exc)[:200]))
            .build(),
            reply_markup=bamboodom_admin_kb(),
        )
        return

    is_first_run = (
        len(result.all_urls) > 0 and len(result.new_urls) == 0
        # snapshot был пустой → diff_against_snapshot вернул []
        # отличаем от «новых нет, snapshot был» — для этого читаем snapshot ещё раз
    )
    # Аккуратное определение: если в Redis ещё нет ключа — это первый запуск
    snapshot_exists = False
    try:
        existed = await redis.get("yandex_recrawl:bamboodom:known_urls")
        snapshot_exists = bool(existed)
    except Exception:
        snapshot_exists = False
    is_first_run = (not snapshot_exists) and len(result.all_urls) > 0

    if is_first_run:
        # Сохраняем стартовый snapshot и ничего не шлём
        await save_snapshot(redis, result.all_urls)
        await safe_edit_text(
            msg,
            _build_recrawl_preview_text(len(result.all_urls), [], first_run=True),
            reply_markup=bamboodom_admin_kb(),
        )
        return

    # Сохраняем preview в Redis (на случай, если юзер нажмёт «Отправить» позже)
    await _save_preview(redis, user.id, result.new_urls, result.all_urls)

    if not result.new_urls:
        await safe_edit_text(
            msg,
            _build_recrawl_preview_text(len(result.all_urls), [], first_run=False),
            reply_markup=bamboodom_admin_kb(),
        )
        return

    await safe_edit_text(
        msg,
        _build_recrawl_preview_text(len(result.all_urls), result.new_urls, first_run=False),
        reply_markup=bamboodom_recrawl_preview_kb(),
    )


# ---------------------------------------------------------------------------
# bamboodom:admin:recrawl:run — отправить новые URL'ы в Я.Вебмастер
# ---------------------------------------------------------------------------


def _build_progress_text(i: int, total: int) -> str:
    return (
        Screen(E.SYNC, TXT.BAMBOODOM_RECRAWL_TITLE)
        .blank()
        .line(TXT.BAMBOODOM_RECRAWL_PROGRESS_SEND.format(i=i, total=total))
        .build()
    )


def _build_result_text(sent: list[str], failed: list[tuple[str, str]]) -> str:
    screen = (
        Screen(E.CHECK, TXT.BAMBOODOM_RECRAWL_RESULT_TITLE)
        .blank()
        .line(TXT.BAMBOODOM_RECRAWL_RESULT_LINE_OK.format(count=len(sent)))
    )
    if failed:
        screen = screen.line(TXT.BAMBOODOM_RECRAWL_RESULT_LINE_FAIL.format(count=len(failed)))
        screen = screen.blank().line(TXT.BAMBOODOM_RECRAWL_RESULT_FAIL_HEADER)
        for url, err in failed[:_FAIL_LINE_LIMIT]:
            screen = screen.line(TXT.BAMBOODOM_RECRAWL_RESULT_FAIL_LINE.format(url=url, err=str(err)[:120]))
        if len(failed) > _FAIL_LINE_LIMIT:
            screen = screen.line(TXT.BAMBOODOM_RECRAWL_RESULT_FAIL_MORE.format(count=len(failed) - _FAIL_LINE_LIMIT))
    return screen.build()


@router.callback_query(F.data == "bamboodom:admin:recrawl:run")
async def bamboodom_admin_recrawl_run(
    callback: CallbackQuery,
    user: User,
    redis: RedisClient,
) -> None:
    """Отправить новые URL'ы (из preview в Redis) в Я.Вебмастер."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cfg_err = _settings_check()
    if cfg_err:
        await safe_edit_text(
            msg,
            Screen(E.WARNING, TXT.BAMBOODOM_RECRAWL_TITLE).blank().line(f"{E.CLOSE} {cfg_err}").build(),
            reply_markup=bamboodom_admin_kb(),
        )
        await callback.answer()
        return

    # Анти-двойной-клик
    lock_key = _RECRAWL_LOCK_KEY.format(user_id=user.id)
    try:
        acquired = await redis.set(lock_key, "1", ex=_RECRAWL_LOCK_TTL, nx=True)
    except Exception:
        acquired = True
    if not acquired:
        await callback.answer("Уже запущено, подождите…", show_alert=True)
        return

    try:
        preview = await _read_preview(redis, user.id)
        if preview is None:
            await safe_edit_text(
                msg,
                Screen(E.WARNING, TXT.BAMBOODOM_RECRAWL_TITLE)
                .blank()
                .line("Сначала нажмите «Перепроверить» — данные превью устарели.")
                .build(),
                reply_markup=bamboodom_admin_kb(),
            )
            await callback.answer()
            return

        new_urls, all_urls = preview
        if not new_urls:
            await safe_edit_text(
                msg,
                _build_recrawl_preview_text(len(all_urls), [], first_run=False),
                reply_markup=bamboodom_admin_kb(),
            )
            await callback.answer()
            return

        # Превращаем callback в «выполняется»
        await safe_edit_text(msg, _build_progress_text(0, len(new_urls)), reply_markup=bamboodom_recrawl_progress_kb())
        await callback.answer()

        client = YandexWebmasterClient()

        # Прогрессовый колбэк — обновляем сообщение раз в 3 URL'а или каждые 5 секунд
        last_edit = {"i": 0, "ts": 0.0}

        async def _on_progress(i: int, total: int, _url: str, _ok: bool) -> None:
            now = asyncio.get_event_loop().time()
            if i == total or i - last_edit["i"] >= 3 or now - last_edit["ts"] >= 5:
                last_edit["i"] = i
                last_edit["ts"] = now
                with contextlib.suppress(Exception):
                    await safe_edit_text(
                        msg,
                        _build_progress_text(i, total),
                        reply_markup=bamboodom_recrawl_progress_kb(),
                    )

        try:
            sent, failed = await add_urls_with_rate_limit(client, new_urls, delay_sec=1.1, on_progress=_on_progress)
        except YandexWebmasterAuthError:
            await safe_edit_text(
                msg,
                Screen(E.WARNING, TXT.BAMBOODOM_RECRAWL_TITLE)
                .blank()
                .line(f"{E.CLOSE} {TXT.BAMBOODOM_RECRAWL_AUTH_FAIL}")
                .build(),
                reply_markup=bamboodom_admin_kb(),
            )
            return
        except YandexWebmasterHostNotFoundError:
            await safe_edit_text(
                msg,
                Screen(E.WARNING, TXT.BAMBOODOM_RECRAWL_TITLE)
                .blank()
                .line(f"{E.CLOSE} {TXT.BAMBOODOM_RECRAWL_HOST_NOT_FOUND}")
                .build(),
                reply_markup=bamboodom_admin_kb(),
            )
            return
        except YandexWebmasterQuotaExceededError:
            await safe_edit_text(
                msg,
                Screen(E.WARNING, TXT.BAMBOODOM_RECRAWL_TITLE)
                .blank()
                .line(f"{E.CLOSE} {TXT.BAMBOODOM_RECRAWL_QUOTA_FAIL}")
                .build(),
                reply_markup=bamboodom_admin_kb(),
            )
            return
        except YandexWebmasterRateLimitError as exc:
            await safe_edit_text(
                msg,
                Screen(E.WARNING, TXT.BAMBOODOM_RECRAWL_TITLE)
                .blank()
                .line(f"{E.CLOSE} Я.Вебмастер просит подождать {exc.retry_after} сек. Попробуйте ещё раз чуть позже.")
                .build(),
                reply_markup=bamboodom_admin_kb(),
            )
            return
        except YandexWebmasterError as exc:
            await safe_edit_text(
                msg,
                Screen(E.WARNING, TXT.BAMBOODOM_RECRAWL_TITLE)
                .blank()
                .line(f"{E.CLOSE} {TXT.BAMBOODOM_RECRAWL_NETWORK_FAIL.format(detail=str(exc)[:200])}")
                .build(),
                reply_markup=bamboodom_admin_kb(),
            )
            return

        # Снимаем превью и обновляем snapshot всем тем что нашли в обходе.
        # Если что-то не отправилось — оно всё равно зафиксировано в snapshot,
        # чтобы на следующем запуске не пытаться слать заново. Юзер видит ошибки в UI.
        with contextlib.suppress(Exception):
            await redis.delete(_RECRAWL_PREVIEW_KEY.format(user_id=user.id))
        await save_snapshot(redis, all_urls)

        await safe_edit_text(
            msg,
            _build_result_text(sent, failed),
            reply_markup=bamboodom_recrawl_result_kb(),
        )
    finally:
        with contextlib.suppress(Exception):
            await redis.delete(lock_key)
