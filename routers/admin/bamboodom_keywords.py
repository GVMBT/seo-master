"""Bamboodom keywords admin handlers (4Y, 2026-04-27).

Phase 1 UI — manual collection + manual single-keyword publish.

Flow:
- bamboodom:keywords → root with stats
- bamboodom:keywords:collect → choose material
- bamboodom:keywords:collect:<material|all> → run DataForSEO + cluster + save
- bamboodom:keywords:list → choose material
- bamboodom:keywords:list:<material> → show top-50 keywords with cluster labels
- bamboodom:keywords:publish_one → preview next keyword to publish (highest volume new)
- bamboodom:keywords:publish:<id> → invoke ai-publish flow for that keyword

Phase 2 (next session) will add cron-based auto-publishing with weighted distribution.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from cache.client import RedisClient

from bot.config import get_settings
from bot.helpers import safe_edit_text, safe_message
from bot.texts import strings as S
from bot.texts.emoji import E
from bot.texts.screens import Screen
from db.client import SupabaseClient
from db.models import User
from db.repositories import BamboodomKeywordsRepository
from db.repositories.bamboodom_keywords import CRIMEA_CITIES
from keyboards.bamboodom import (
    bamboodom_keywords_collect_kb,
    bamboodom_keywords_geo_kb,
    bamboodom_keywords_kb,
    bamboodom_keywords_list_kb,
    bamboodom_keywords_publish_one_kb,
)
from services.bamboodom_keywords import collect_for_material

log = structlog.get_logger()

router = Router(name="bamboodom_keywords")

_MATERIAL_LABELS = {
    "wpc": "WPC панели",
    "flex": "Гибкая керамика",
    "reiki": "Реечные панели",
    "profiles": "Алюминиевые профили",
}


# ---------------------------------------------------------------------------
# Local admin guard — duplicate of bamboodom.py:_is_admin to avoid import.
# ---------------------------------------------------------------------------


def _is_admin(user: User) -> bool:
    return user.role == "admin"


# ---------------------------------------------------------------------------
# Root screen
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "bamboodom:keywords")
async def keywords_root(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show stats + entry buttons for keyword pipeline."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    repo = BamboodomKeywordsRepository(db)
    stats = await repo.stats_summary()

    screen = Screen(E.HASHTAG, "Подбор ключевых слов").blank()
    if stats:
        screen = screen.line("База ключей по материалам:")
        for mat in ("wpc", "flex", "reiki", "profiles"):
            mat_stats = stats.get(mat, {})
            total = mat_stats.get("total", 0)
            if total == 0:
                continue
            new = mat_stats.get("new", 0)
            used = mat_stats.get("used", 0)
            failed = mat_stats.get("failed", 0)
            screen = screen.line(
                f"  • {_MATERIAL_LABELS.get(mat, mat)}: всего {total}, "
                f"свободно {new}, опубликовано {used}, ошибки {failed}"
            )
        screen = screen.blank()
    else:
        screen = screen.line("База пуста. Запустите подбор ключей.").blank()

    screen = screen.line(
        "🔍 Подобрать — DataForSEO Yandex + AI кластеризация (5-7 минут)\n"
        "📋 База ключей — просмотр собранного\n"
        "🎯 Опубликовать пробную — взять следующий ключ и сгенерировать AI-статью"
    )
    await safe_edit_text(msg, screen.build(), reply_markup=bamboodom_keywords_kb(stats))
    await callback.answer()


# ---------------------------------------------------------------------------
# Collection: choose material
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "bamboodom:keywords:collect")
async def keywords_collect_menu(callback: CallbackQuery, user: User) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    s = get_settings()
    if not s.dataforseo_login or not s.dataforseo_password.get_secret_value():
        await safe_edit_text(
            msg,
            "DataForSEO не настроен. Заполните DATAFORSEO_LOGIN и DATAFORSEO_PASSWORD в env.",
            reply_markup=bamboodom_keywords_kb(None),
        )
        await callback.answer()
        return

    if not s.openrouter_api_key.get_secret_value():
        await safe_edit_text(
            msg,
            "OPENROUTER_API_KEY не настроен — кластеризация невозможна.",
            reply_markup=bamboodom_keywords_kb(None),
        )
        await callback.answer()
        return

    text = (
        Screen(E.HASHTAG, "Подбор ключей — выбор материала")
        .blank()
        .line(
            "Сбор займёт 3-7 минут на материал:\n"
            "• 5-7 seed-ключей через keywords_for_keywords API\n"
            "• AI кластеризация по темам (выбор / монтаж / сравнение / use-case / общее)\n"
            "• Дедуп и сохранение в БД"
        )
        .blank()
        .line("Стоимость: ~$0.30 на 1 материал, ~$1.20 на все четыре.")
        .build()
    )
    await safe_edit_text(msg, text, reply_markup=bamboodom_keywords_collect_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# Collection: run for one material or all
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^bamboodom:keywords:collect:(wpc|flex|reiki|profiles|all)$"))
async def keywords_collect_run(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cb_data = callback.data or ""
    target = cb_data.rsplit(":", 1)[-1]
    materials = ("wpc", "flex", "reiki", "profiles") if target == "all" else (target,)

    s = get_settings()
    repo = BamboodomKeywordsRepository(db)

    await safe_edit_text(
        msg,
        Screen(E.SYNC, "Подбор ключей").blank().line(
            f"Запущен сбор для: {', '.join(_MATERIAL_LABELS.get(m, m) for m in materials)}.\n"
            f"Дождитесь завершения, не закрывайте чат."
        ).build(),
    )
    await callback.answer()

    total_stats = {"fetched": 0, "after_filter": 0, "saved_new": 0, "saved_updated": 0, "by_cluster": {}}
    errors: list[str] = []
    progress_lines: list[str] = []

    async def _progress(stage: str, mat: str) -> None:
        emoji = {"fetching": "📡", "clustering": "🤖", "saving": "💾"}.get(stage, "⏳")
        try:
            await safe_edit_text(
                msg,
                Screen(E.SYNC, "Подбор ключей").blank().line(
                    f"{emoji} {_MATERIAL_LABELS.get(mat, mat)} — {stage}..."
                ).line("\n".join(progress_lines) if progress_lines else "").build(),
            )
        except Exception:
            pass

    for mat in materials:
        try:
            stats = await collect_for_material(
                material=mat,
                repo=repo,
                openrouter_api_key=s.openrouter_api_key.get_secret_value(),
                http_client=http_client,
                progress_cb=lambda stage, m=mat: _progress(stage, m),
            )
            total_stats["fetched"] += stats["fetched"]
            total_stats["after_filter"] += stats["after_filter"]
            total_stats["saved_new"] += stats["saved_new"]
            total_stats["saved_updated"] += stats["saved_updated"]
            for lbl, n in (stats.get("by_cluster") or {}).items():
                total_stats["by_cluster"][lbl] = total_stats["by_cluster"].get(lbl, 0) + n
            progress_lines.append(
                f"✅ {_MATERIAL_LABELS.get(mat, mat)}: {stats['saved_new']} new, {stats['saved_updated']} upd"
            )
        except Exception as exc:
            log.warning("bbk_collect_material_failed", material=mat, error=str(exc)[:200])
            errors.append(f"{_MATERIAL_LABELS.get(mat, mat)}: {str(exc)[:120]}")
            progress_lines.append(f"❌ {_MATERIAL_LABELS.get(mat, mat)}: ошибка")

    # Final result
    fresh_stats = await repo.stats_summary()
    screen = Screen(E.HASHTAG, "Подбор ключей — готово").blank().line(
        f"Найдено фраз: {total_stats['fetched']}\n"
        f"После фильтра (volume по материалу): {total_stats['after_filter']}\n"
        f"Сохранено новых: {total_stats['saved_new']}\n"
        f"Обновлено существующих: {total_stats['saved_updated']}"
    )
    if total_stats["by_cluster"]:
        screen = screen.blank().line("По кластерам:")
        for lbl, n in sorted(total_stats["by_cluster"].items(), key=lambda x: -x[1]):
            screen = screen.line(f"  • {lbl}: {n}")
    if errors:
        screen = screen.blank().line("Ошибки:")
        for e in errors:
            screen = screen.line(f"  ⚠ {e}")

    await safe_edit_text(msg, screen.build(), reply_markup=bamboodom_keywords_kb(fresh_stats))


# ---------------------------------------------------------------------------
# List: choose material
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "bamboodom:keywords:list")
async def keywords_list_menu(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    repo = BamboodomKeywordsRepository(db)
    stats = await repo.stats_summary()
    materials_with_data = [m for m in ("wpc", "flex", "reiki", "profiles") if stats.get(m, {}).get("total", 0) > 0]

    if not materials_with_data:
        await safe_edit_text(
            msg,
            "База пуста. Запустите подбор ключей.",
            reply_markup=bamboodom_keywords_kb(stats),
        )
        await callback.answer()
        return

    text = (
        Screen(E.HASHTAG, "База ключей — выбор материала")
        .blank()
        .line("Выберите материал для просмотра топ-30 ключей.")
        .build()
    )
    await safe_edit_text(msg, text, reply_markup=bamboodom_keywords_list_kb(materials_with_data))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^bamboodom:keywords:list:(wpc|flex|reiki|profiles)$"))
async def keywords_list_show(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cb_data = callback.data or ""
    material = cb_data.rsplit(":", 1)[-1]

    repo = BamboodomKeywordsRepository(db)
    items = await repo.list_by_material(material, status=None, limit=30)

    if not items:
        await safe_edit_text(
            msg,
            f"По материалу {_MATERIAL_LABELS.get(material, material)} пока нет ключей.",
            reply_markup=bamboodom_keywords_kb(await repo.stats_summary()),
        )
        await callback.answer()
        return

    screen = Screen(E.HASHTAG, f"База — {_MATERIAL_LABELS.get(material, material)}").blank()
    screen = screen.line("Топ 30 по частотности (статус — кластер — частотность):")
    screen = screen.blank()
    for it in items:
        flag = {"new": "🆕", "used": "✅", "failed": "❌", "queued": "⏳", "skipped": "⏭"}.get(it.status, "•")
        cluster = it.cluster_label or "—"
        screen = screen.line(f"{flag} <code>{it.keyword}</code> ({cluster}) — {it.search_volume}")

    await safe_edit_text(msg, screen.build(), reply_markup=bamboodom_keywords_kb(await repo.stats_summary()))
    await callback.answer()


# ---------------------------------------------------------------------------
# Publish: pick next, run AI publication
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "bamboodom:keywords:publish_one")
async def keywords_publish_one_preview(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    repo = BamboodomKeywordsRepository(db)
    # Phase 1: pick from material with the largest backlog of new keywords.
    stats = await repo.stats_summary()
    candidates = sorted(
        ((m, s.get("new", 0)) for m, s in stats.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    candidates = [m for m, n in candidates if n > 0]
    if not candidates:
        await safe_edit_text(
            msg,
            "Нет новых ключей в базе. Запустите подбор.",
            reply_markup=bamboodom_keywords_kb(stats),
        )
        await callback.answer()
        return

    chosen = await repo.pick_for_publishing(candidates[0])
    if not chosen:
        await safe_edit_text(
            msg,
            "Не удалось выбрать ключ. Попробуйте позже.",
            reply_markup=bamboodom_keywords_kb(stats),
        )
        await callback.answer()
        return

    text = (
        Screen(E.HASHTAG, "Пробная публикация").blank().line(
            f"Материал: <b>{_MATERIAL_LABELS.get(chosen.material, chosen.material)}</b>\n"
            f"Ключ: <b>{chosen.keyword}</b>\n"
            f"Кластер: {chosen.cluster_label or '—'}\n"
            f"Частотность: {chosen.search_volume}/мес"
        ).blank().line(
            "Нажмите «Запустить» — бот сгенерирует AI-статью и опубликует на /blog.\n"
            "Это займёт 3-5 минут (текст + 5-7 фото)."
        ).build()
    )
    await safe_edit_text(msg, text, reply_markup=bamboodom_keywords_publish_one_kb(chosen.id))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^bamboodom:keywords:publish:(\d+)$"))
async def keywords_publish_run(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    db: SupabaseClient,
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

    cb_data = callback.data or ""
    kw_id = int(cb_data.rsplit(":", 1)[-1])

    repo = BamboodomKeywordsRepository(db)
    kw = await repo.get_by_id(kw_id)
    if not kw or kw.status != "new":
        await safe_edit_text(
            msg,
            f"Ключ #{kw_id} недоступен (status={kw.status if kw else 'NOT_FOUND'}).",
            reply_markup=bamboodom_keywords_kb(await repo.stats_summary()),
        )
        await callback.answer()
        return

    # Mark as queued so we don't double-pick if the user clicks again
    await repo.mark_status(kw_id, "queued")

    # Borrow the AI generation routine from bamboodom.py — reuse the live
    # progress + cancel + autopublish pipeline that already works.
    from routers.admin.bamboodom import _run_ai_generation

    # 5E (2026-04-27): if keyword has a city, expand to "<keyword> в <city>"
    # so the AI generates a geo-targeted title / slug / text.
    keyword_for_ai = kw.keyword
    if kw.city:
        keyword_for_ai = f"{kw.keyword} в {kw.city}"

    city_line = f"\nГород: {kw.city}" if kw.city else ""
    progress_msg = await msg.answer(
        Screen(E.SYNC, "Пробная публикация").blank().line(
            f"Материал: {_MATERIAL_LABELS.get(kw.material, kw.material)}\n"
            f"Ключ: {keyword_for_ai}{city_line}\n\n"
            f"Генерация запущена. Прогресс ниже."
        ).build()
    )
    await callback.answer("Запустил публикацию")

    # Set FSM state so cancel button (if shown) can find this run
    try:
        from routers.admin.bamboodom import AIPublishFSM
        await state.set_state(AIPublishFSM.enter_keyword)
        await state.update_data(ai_material=kw.material, kw_db_id=kw.id)
    except Exception:
        pass

    async def _run_and_track() -> None:
        try:
            await _run_ai_generation(
                bot_msg=progress_msg,
                state=state,
                user_id=user.id,
                material=kw.material,
                keyword=keyword_for_ai,
                redis=redis,
                http_client=http_client,
            )
            # Successful generation lands the article in preview state.
            # The actual publish happens via "Опубликовать" button in the AI
            # publish flow. Status will move to 'used' there. For now mark as
            # used optimistically so it doesn't get re-picked.
            data = await state.get_data()
            slug_hint = data.get("ai_published_slug") or data.get("preview_slug")
            await repo.mark_status(kw.id, "used", published_slug=slug_hint)
        except Exception as exc:
            log.warning("bbk_publish_failed", kw_id=kw.id, error=str(exc)[:200])
            await repo.mark_status(kw.id, "failed")

    # Detach so the user can keep navigating
    asyncio.create_task(_run_and_track(), name=f"bbk_publish_{kw.id}")


# ---------------------------------------------------------------------------
# 5E (2026-04-27): Гео-расширение по городам Крыма
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "bamboodom:keywords:geo")
async def keywords_geo_menu(callback: CallbackQuery, user: User) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cities_list = ", ".join(CRIMEA_CITIES)
    text = (
        Screen(E.HASHTAG, "Гео-расширение Крым").blank()
        .line(
            "Бот возьмёт top-N ключей по материалу и умножит каждый на список "
            "городов Крыма. Получатся ключи вида «keyword + город».\n\n"
            f"<b>Города ({len(CRIMEA_CITIES)}):</b>\n{cities_list}\n\n"
            "Дубликаты пропускаются. Ключи сохраняются со status=new и "
            "city=&lt;город&gt;. При публикации AI учтёт город в title, slug "
            "и тексте."
        )
        .build()
    )
    await safe_edit_text(msg, text, reply_markup=bamboodom_keywords_geo_kb())
    await callback.answer()


@router.callback_query(F.data.regexp(r"^bamboodom:keywords:geo:(wpc|flex|reiki|profiles|all)$"))
async def keywords_geo_run(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cb_data = callback.data or ""
    target = cb_data.rsplit(":", 1)[-1]
    materials = ["wpc", "flex", "reiki", "profiles"] if target == "all" else [target]
    top_n = 5 if target == "all" else 10

    repo = BamboodomKeywordsRepository(db)

    progress_msg = await msg.answer(
        Screen(E.SYNC, "Гео-расширение Крым").blank()
        .line(f"Обрабатываю {len(materials)} материал(ов), top-{top_n} × {len(CRIMEA_CITIES)} городов…")
        .build()
    )
    await callback.answer("Гео-расширение запущено")

    results: dict[str, dict] = {}
    for mat in materials:
        try:
            res = await repo.expand_to_cities(material=mat, cities=list(CRIMEA_CITIES), top_n=top_n)
            results[mat] = res
        except Exception as exc:
            log.warning("bbk_geo_expand_failed", material=mat, error=str(exc)[:200])
            results[mat] = {"new": 0, "skipped": 0, "total": 0, "error": str(exc)[:100]}

    summary_lines = []
    total_new = 0
    total_skipped = 0
    for mat in materials:
        r = results.get(mat, {})
        label = _MATERIAL_LABELS.get(mat, mat)
        if "error" in r:
            summary_lines.append(f"❌ {label}: {r['error']}")
        else:
            summary_lines.append(
                f"✅ {label}: новых {r.get('new', 0)}, дублей {r.get('skipped', 0)}, всего {r.get('total', 0)}"
            )
            total_new += r.get("new", 0)
            total_skipped += r.get("skipped", 0)

    final_text = (
        Screen(E.CHECK, "Гео-расширение Крым").blank()
        .line("\n".join(summary_lines))
        .blank()
        .line(f"<b>Итого:</b> добавлено {total_new}, дублей {total_skipped}.")
        .build()
    )
    await progress_msg.edit_text(final_text, reply_markup=bamboodom_keywords_kb(await repo.stats_summary()))

