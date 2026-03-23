"""Project-level content settings with per-platform tabs.

Entry: project:{pid}:content_settings -> main screen with platform tabs.
Callback format: psettings:{pid}:{target}:{action}
  target = "d" (default) | "wordpress" | "telegram" | "vk" | "pinterest"
"""

from typing import Any

import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.helpers import safe_callback_data, safe_edit_text, safe_message
from bot.service_factory import ProjectServiceFactory
from bot.texts import strings as S
from bot.texts.content_options import (
    ANGLES,
    ASPECT_RATIOS,
    CAMERAS,
    HTML_STYLES,
    IMAGE_STYLES,
    QUALITY,
    TEXT_ON_IMAGE,
    TEXT_STYLES,
    TONES,
    WORD_COUNTS,
)
from bot.texts.emoji import E
from bot.texts.screens import Screen
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import Project, User
from db.repositories.connections import ConnectionsRepository
from keyboards.inline import (
    project_angle_kb,
    project_article_format_kb,
    project_camera_kb,
    project_content_settings_kb,
    project_html_style_kb,
    project_image_count_kb,
    project_image_menu_kb,
    project_image_style_kb,
    project_platform_card_kb,
    project_preview_format_kb,
    project_quality_kb,
    project_text_menu_kb,
    project_text_on_image_kb,
    project_text_style_kb,
    project_tone_kb,
    project_word_count_kb,
)

log = structlog.get_logger()
router = Router()

_PLAT_ICONS: dict[str, str] = {
    "wordpress": E.WORDPRESS,
    "telegram": E.TELEGRAM,
    "vk": E.VK,
    "pinterest": E.PINTEREST,
}

_PLAT_NAMES = {k: v.upper() for k, v in S.PLATFORM_DISPLAY.items()}

# Regex for target: "d" or platform names
_PT_RE = r"(d|wordpress|telegram|vk|pinterest)"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt(items: list[str], fb: str = "не выбран") -> str:
    return ", ".join(items) if items else fb


def _settings_text(ts: dict[str, Any], is_: dict[str, Any]) -> str:
    """Build settings display text from ts/is dicts."""
    na = "не выбран"
    df = "по умолчанию"

    wc = ts.get("word_count")
    wc_line = f"{wc} слов" if wc else df
    styles_line = _fmt(ts.get("styles", []))
    html_line = ts.get("html_style") or na

    pf_line = is_.get("preview_format") or na
    af_line = _fmt(is_.get("article_formats", []), "не выбраны")
    is_line = _fmt(is_.get("styles", []))
    cnt = is_.get("count")
    cnt_line = str(cnt) if cnt else df

    return (
        f"{E.PEN} <b>Текст</b>\n"
        f"  Стиль: {styles_line}\n"
        f"  HTML: {html_line}\n"
        f"  Длина: {wc_line}\n"
        "\n"
        f"{E.IMAGE} <b>Изображения</b>\n"
        f"  Превью: {pf_line}\n"
        f"  Форматы: {af_line}\n"
        f"  Стиль: {is_line}\n"
        f"  Количество: {cnt_line}"
    )


def _main_screen_text() -> str:
    return (
        Screen(E.SLIDERS, S.CONTENT_SETTINGS_TITLE)
        .blank()
        .line(S.CONTENT_SETTINGS_DESC)
        .hint(S.CONTENT_SETTINGS_HINT)
        .build()
    )


def _platform_card_text(
    pt: str, ts: dict[str, Any], is_: dict[str, Any],
) -> str:
    icon = _PLAT_ICONS.get(pt, "")
    name = _PLAT_NAMES.get(pt, pt.upper())
    body = _settings_text(ts, is_)
    return (
        Screen(icon, name)
        .blank()
        .line(body)
        .hint(S.CONTENT_PLATFORM_HINT)
        .build()
    )


def _default_card_text(ts: dict[str, Any], is_: dict[str, Any]) -> str:
    body = _settings_text(ts, is_)
    return (
        Screen(E.SLIDERS, S.CONTENT_DEFAULT_TITLE)
        .blank()
        .line(body)
        .hint(S.CONTENT_DEFAULT_HINT)
        .build()
    )


async def _load_project(
    callback: CallbackQuery,
    pid: int,
    user: User,
    db: SupabaseClient,
    psf: ProjectServiceFactory,
) -> Project | None:
    proj_svc = psf(db)
    project = await proj_svc.get_owned_project(pid, user.id)
    if not project:
        await callback.answer(S.PROJECT_NOT_FOUND, show_alert=True)
    return project


async def _get_platforms(
    db: SupabaseClient, key: str, pid: int,
) -> list[str]:
    cm = CredentialManager(key)
    return await ConnectionsRepository(db, cm).get_platform_types_by_project(pid)


async def _load_settings(
    db: SupabaseClient,
    project: Project,
    target: str,
    psf: ProjectServiceFactory,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if target == "d":
        ts = dict(project.text_settings) if project.text_settings else {}
        is_ = dict(project.image_settings) if project.image_settings else {}
        return ts, is_
    return await psf(db).resolve_effective_settings(project.id, target)


async def _save_ts(
    db: SupabaseClient, pid: int, uid: int, target: str,
    ts: dict[str, Any], psf: ProjectServiceFactory,
) -> None:
    svc = psf(db)
    if target == "d":
        await svc.update_text_settings(pid, uid, ts)
    else:
        await svc.upsert_platform_settings(pid, uid, target, text_settings=ts)


async def _save_is(
    db: SupabaseClient, pid: int, uid: int, target: str,
    is_: dict[str, Any], psf: ProjectServiceFactory,
) -> None:
    svc = psf(db)
    if target == "d":
        await svc.update_image_settings(pid, uid, is_)
    else:
        await svc.upsert_platform_settings(
            pid, uid, target, image_settings=is_,
        )


async def _load_ts(
    db: SupabaseClient, p: Project, t: str, psf: ProjectServiceFactory,
) -> dict[str, Any]:
    ts, _ = await _load_settings(db, p, t, psf)
    return ts


async def _load_is(
    db: SupabaseClient, p: Project, t: str, psf: ProjectServiceFactory,
) -> dict[str, Any]:
    _, is_ = await _load_settings(db, p, t, psf)
    return is_


# ---------------------------------------------------------------------------
# 1. Main settings screen
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:\d+:content_settings$"))
async def show_settings(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    pid = int(cb_data.split(":")[1])
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    svc = project_service_factory(db)
    platforms = await _get_platforms(db, svc.encryption_key, pid)
    await safe_edit_text(
        msg, _main_screen_text(),
        reply_markup=project_content_settings_kb(pid, platforms),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^psettings:\d+:back$"))
async def back_to_settings(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    pid = int(cb_data.split(":")[1])
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    svc = project_service_factory(db)
    platforms = await _get_platforms(db, svc.encryption_key, pid)
    await safe_edit_text(
        msg, _main_screen_text(),
        reply_markup=project_content_settings_kb(pid, platforms),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 2. Platform / Default card
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:card$"))
async def show_platform_card(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target = int(parts[1]), parts[2]
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    ts, is_ = await _load_settings(
        db, project, target, project_service_factory,
    )
    text = _default_card_text(ts, is_) if target == "d" else _platform_card_text(target, ts, is_)
    await safe_edit_text(
        msg, text, reply_markup=project_platform_card_kb(pid, target),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 3. Reset platform override
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:reset$"))
async def reset_platform(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target = int(parts[1]), parts[2]
    if target == "d":
        await callback.answer()
        return
    svc = project_service_factory(db)
    project = await svc.get_owned_project(pid, user.id)
    if not project:
        await callback.answer(S.PROJECT_NOT_FOUND, show_alert=True)
        return
    await svc.delete_platform_settings(pid, user.id, target)
    log.info("platform_settings_reset", project_id=pid, platform=target)
    ts = dict(project.text_settings) if project.text_settings else {}
    is_ = dict(project.image_settings) if project.image_settings else {}
    await safe_edit_text(
        msg, _platform_card_text(target, ts, is_),
        reply_markup=project_platform_card_kb(pid, target),
    )
    await callback.answer(S.CONTENT_RESET_DONE)


# ---------------------------------------------------------------------------
# 4. Text sub-menu
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:text$"))
async def show_text_menu(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target = int(parts[1]), parts[2]
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    text = (
        Screen(E.PEN, S.CONTENT_TEXT_TITLE)
        .blank()
        .line(S.CONTENT_TEXT_PROMPT)
        .hint(S.CONTENT_TEXT_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_text_menu_kb(pid, target),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 5. Word count
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:words$"))
async def show_word_count(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target = int(parts[1]), parts[2]
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    ts = await _load_ts(db, project, target, project_service_factory)
    text = (
        Screen(E.PEN, S.CONTENT_WORD_COUNT_TITLE)
        .blank()
        .line(S.CONTENT_WORD_COUNT_PROMPT)
        .hint(S.CONTENT_WORD_COUNT_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_word_count_kb(pid, ts.get("word_count"), target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:wc:\d+$"))
async def select_word_count(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target, wc = int(parts[1]), parts[2], int(parts[4])
    if wc not in WORD_COUNTS:
        await callback.answer(S.CONTENT_INVALID_VALUE, show_alert=True)
        return
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    ts = await _load_ts(db, project, target, project_service_factory)
    ts["word_count"] = wc
    await _save_ts(db, pid, user.id, target, ts, project_service_factory)
    log.info("word_count_updated", project_id=pid, target=target, wc=wc)
    await safe_edit_text(
        msg, f"{E.CHECK} Длина статьи: <b>{wc} слов</b>",
        reply_markup=project_word_count_kb(pid, wc, target),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 6. HTML style
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:html$"))
async def show_html_style(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target = int(parts[1]), parts[2]
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    ts = await _load_ts(db, project, target, project_service_factory)
    text = (
        Screen(E.DOC, S.CONTENT_HTML_TITLE)
        .blank()
        .line(S.CONTENT_HTML_DESC)
        .line(S.CONTENT_TEXT_STYLE_MULTI)
        .hint(S.CONTENT_HTML_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_html_style_kb(pid, ts.get("html_style"), target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:hs:\d+$"))
async def select_html_style(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target, idx = int(parts[1]), parts[2], int(parts[4])
    if idx < 0 or idx >= len(HTML_STYLES):
        await callback.answer(S.CONTENT_UNKNOWN_STYLE, show_alert=True)
        return
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    style = HTML_STYLES[idx]
    ts = await _load_ts(db, project, target, project_service_factory)
    ts["html_style"] = style
    await _save_ts(db, pid, user.id, target, ts, project_service_factory)
    log.info("html_style_updated", project_id=pid, target=target, style=style)
    await safe_edit_text(
        msg, f"{E.CHECK} HTML-верстка: <b>{style}</b>",
        reply_markup=project_html_style_kb(pid, style, target),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 7. Text styles (multi-select)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:tstyle$"))
async def show_text_styles(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target = int(parts[1]), parts[2]
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    ts = await _load_ts(db, project, target, project_service_factory)
    selected = set(ts.get("styles", []))
    text = (
        Screen(E.PEN, S.CONTENT_TEXT_STYLE_TITLE)
        .blank()
        .line(S.CONTENT_TEXT_STYLE_DESC)
        .line(S.CONTENT_TEXT_STYLE_MULTI)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_text_style_kb(pid, selected, target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:ts:\d+$"))
async def toggle_text_style(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target, idx = int(parts[1]), parts[2], int(parts[4])
    if idx < 0 or idx >= len(TEXT_STYLES):
        await callback.answer(S.CONTENT_UNKNOWN_STYLE, show_alert=True)
        return
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    style = TEXT_STYLES[idx]
    ts = await _load_ts(db, project, target, project_service_factory)
    styles: list[str] = list(ts.get("styles", []))
    if style in styles:
        styles.remove(style)
    else:
        styles.append(style)
    ts["styles"] = styles
    await _save_ts(db, pid, user.id, target, ts, project_service_factory)
    text = (
        Screen(E.PEN, S.CONTENT_TEXT_STYLE_TITLE)
        .blank()
        .line(S.CONTENT_TEXT_STYLE_DESC)
        .line(S.CONTENT_TEXT_STYLE_MULTI)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_text_style_kb(pid, set(styles), target),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 8. Image sub-menu
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:images$"))
async def show_image_menu(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target = int(parts[1]), parts[2]
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    text = (
        Screen(E.IMAGE, S.CONTENT_IMAGE_TITLE)
        .blank()
        .line(S.CONTENT_IMAGE_PROMPT)
        .hint(S.CONTENT_IMAGE_MENU_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_image_menu_kb(pid, target),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 9-17. Image setting handlers (generated pattern)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:pfmt$"))
async def show_preview_format(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target = int(parts[1]), parts[2]
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    is_ = await _load_is(db, project, target, project_service_factory)
    text = (
        Screen(E.IMAGE, S.CONTENT_PREVIEW_TITLE)
        .blank()
        .line(S.CONTENT_PREVIEW_DESC)
        .hint(S.CONTENT_PREVIEW_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_preview_format_kb(
            pid, is_.get("preview_format"), target,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:pf:\d+$"))
async def select_preview_format(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target, idx = int(parts[1]), parts[2], int(parts[4])
    if idx < 0 or idx >= len(ASPECT_RATIOS):
        await callback.answer("Неизвестный формат", show_alert=True)
        return
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    fmt = ASPECT_RATIOS[idx]
    is_ = await _load_is(db, project, target, project_service_factory)
    is_["preview_format"] = fmt
    await _save_is(db, pid, user.id, target, is_, project_service_factory)
    log.info("preview_format_updated", project_id=pid, target=target, fmt=fmt)
    await safe_edit_text(
        msg, f"{E.CHECK} Формат превью: <b>{fmt}</b>",
        reply_markup=project_preview_format_kb(pid, fmt, target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:afmts$"))
async def show_article_formats(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target = int(parts[1]), parts[2]
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    is_ = await _load_is(db, project, target, project_service_factory)
    selected = set(is_.get("article_formats", []))
    text = (
        Screen(E.IMAGE, S.CONTENT_ARTICLE_FMT_TITLE)
        .blank()
        .line(S.CONTENT_ARTICLE_FMT_DESC)
        .line(S.CONTENT_TEXT_STYLE_MULTI)
        .hint(S.CONTENT_ARTICLE_FMT_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_article_format_kb(pid, selected, target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:af:\d+$"))
async def toggle_article_format(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target, idx = int(parts[1]), parts[2], int(parts[4])
    if idx < 0 or idx >= len(ASPECT_RATIOS):
        await callback.answer("Неизвестный формат", show_alert=True)
        return
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    fmt = ASPECT_RATIOS[idx]
    is_ = await _load_is(db, project, target, project_service_factory)
    formats: list[str] = list(is_.get("article_formats", []))
    if fmt in formats:
        formats.remove(fmt)
    else:
        formats.append(fmt)
    is_["article_formats"] = formats
    await _save_is(db, pid, user.id, target, is_, project_service_factory)
    text = (
        Screen(E.IMAGE, S.CONTENT_ARTICLE_FMT_TITLE)
        .blank()
        .line(S.CONTENT_ARTICLE_FMT_DESC)
        .line(S.CONTENT_TEXT_STYLE_MULTI)
        .hint(S.CONTENT_ARTICLE_FMT_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_article_format_kb(pid, set(formats), target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:istyle$"))
async def show_image_styles(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target = int(parts[1]), parts[2]
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    is_ = await _load_is(db, project, target, project_service_factory)
    selected = set(is_.get("styles", []))
    text = (
        Screen(E.IMAGE, S.CONTENT_IMAGE_STYLE_TITLE)
        .blank()
        .line(S.CONTENT_TEXT_STYLE_MULTI)
        .hint(S.CONTENT_IMAGE_STYLE_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_image_style_kb(pid, selected, target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:is:\d+$"))
async def toggle_image_style(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target, idx = int(parts[1]), parts[2], int(parts[4])
    if idx < 0 or idx >= len(IMAGE_STYLES):
        await callback.answer(S.CONTENT_UNKNOWN_STYLE, show_alert=True)
        return
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    style = IMAGE_STYLES[idx]
    is_ = await _load_is(db, project, target, project_service_factory)
    styles: list[str] = list(is_.get("styles", []))
    if style in styles:
        styles.remove(style)
    else:
        styles.append(style)
    is_["styles"] = styles
    await _save_is(db, pid, user.id, target, is_, project_service_factory)
    text = (
        Screen(E.IMAGE, S.CONTENT_IMAGE_STYLE_TITLE)
        .blank()
        .line(S.CONTENT_TEXT_STYLE_MULTI)
        .hint(S.CONTENT_IMAGE_STYLE_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_image_style_kb(pid, set(styles), target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:icount$"))
async def show_image_count(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target = int(parts[1]), parts[2]
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    is_ = await _load_is(db, project, target, project_service_factory)
    text = (
        Screen(E.IMAGE, S.CONTENT_IMAGE_COUNT_TITLE)
        .blank()
        .line(S.CONTENT_IMAGE_COUNT_DESC)
        .hint(S.CONTENT_IMAGE_COUNT_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_image_count_kb(pid, is_.get("count"), target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:ic:\d+$"))
async def select_image_count(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target, count = int(parts[1]), parts[2], int(parts[4])
    if count < 0 or count > 10:
        await callback.answer("Допустимо: 0-10", show_alert=True)
        return
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    is_ = await _load_is(db, project, target, project_service_factory)
    is_["count"] = count
    await _save_is(db, pid, user.id, target, is_, project_service_factory)
    log.info("image_count_updated", project_id=pid, target=target, count=count)
    await safe_edit_text(
        msg, f"{E.CHECK} Количество изображений: <b>{count}</b>",
        reply_markup=project_image_count_kb(pid, count, target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:tximg$"))
async def show_text_on_image(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target = int(parts[1]), parts[2]
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    is_ = await _load_is(db, project, target, project_service_factory)
    text = (
        Screen(E.IMAGE, S.CONTENT_TEXT_ON_IMAGE_TITLE)
        .blank()
        .line(S.CONTENT_TEXT_ON_IMAGE_DESC)
        .hint(S.CONTENT_TEXT_ON_IMAGE_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_text_on_image_kb(
            pid, is_.get("text_on_image"), target,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:to:\d+$"))
async def select_text_on_image(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target, pct = int(parts[1]), parts[2], int(parts[4])
    if pct not in TEXT_ON_IMAGE:
        await callback.answer(S.CONTENT_INVALID_VALUE, show_alert=True)
        return
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    is_ = await _load_is(db, project, target, project_service_factory)
    is_["text_on_image"] = pct
    await _save_is(db, pid, user.id, target, is_, project_service_factory)
    log.info("text_on_image_updated", project_id=pid, target=target, pct=pct)
    await safe_edit_text(
        msg, f"{E.CHECK} Текст на изображении: <b>{pct}%</b>",
        reply_markup=project_text_on_image_kb(pid, pct, target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:camera$"))
async def show_cameras(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target = int(parts[1]), parts[2]
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    is_ = await _load_is(db, project, target, project_service_factory)
    selected = set(is_.get("cameras", []))
    text = (
        Screen(E.IMAGE, S.CONTENT_CAMERA_TITLE)
        .blank()
        .line(S.CONTENT_CAMERA_DESC)
        .hint(S.CONTENT_CAMERA_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_camera_kb(pid, selected, target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:cm:\d+$"))
async def toggle_camera(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target, idx = int(parts[1]), parts[2], int(parts[4])
    if idx < 0 or idx >= len(CAMERAS):
        await callback.answer("Неизвестная камера", show_alert=True)
        return
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    cam = CAMERAS[idx]
    is_ = await _load_is(db, project, target, project_service_factory)
    cams: list[str] = list(is_.get("cameras", []))
    if cam in cams:
        cams.remove(cam)
    else:
        cams.append(cam)
    is_["cameras"] = cams
    await _save_is(db, pid, user.id, target, is_, project_service_factory)
    text = (
        Screen(E.IMAGE, S.CONTENT_CAMERA_TITLE)
        .blank()
        .line(S.CONTENT_CAMERA_DESC)
        .hint(S.CONTENT_CAMERA_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_camera_kb(pid, set(cams), target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:angle$"))
async def show_angles(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target = int(parts[1]), parts[2]
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    is_ = await _load_is(db, project, target, project_service_factory)
    selected = set(is_.get("angles", []))
    text = (
        Screen(E.IMAGE, S.CONTENT_ANGLE_TITLE)
        .blank()
        .line(S.CONTENT_ANGLE_DESC)
        .hint(S.CONTENT_ANGLE_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_angle_kb(pid, selected, target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:an:\d+$"))
async def toggle_angle(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target, idx = int(parts[1]), parts[2], int(parts[4])
    if idx < 0 or idx >= len(ANGLES):
        await callback.answer("Неизвестный ракурс", show_alert=True)
        return
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    angle = ANGLES[idx]
    is_ = await _load_is(db, project, target, project_service_factory)
    angles: list[str] = list(is_.get("angles", []))
    if angle in angles:
        angles.remove(angle)
    else:
        angles.append(angle)
    is_["angles"] = angles
    await _save_is(db, pid, user.id, target, is_, project_service_factory)
    text = (
        Screen(E.IMAGE, S.CONTENT_ANGLE_TITLE)
        .blank()
        .line(S.CONTENT_ANGLE_DESC)
        .hint(S.CONTENT_ANGLE_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_angle_kb(pid, set(angles), target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:quality$"))
async def show_quality(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target = int(parts[1]), parts[2]
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    is_ = await _load_is(db, project, target, project_service_factory)
    selected = set(is_.get("quality", []))
    text = (
        Screen(E.IMAGE, S.CONTENT_QUALITY_TITLE)
        .blank()
        .line(S.CONTENT_QUALITY_DESC)
        .hint(S.CONTENT_QUALITY_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_quality_kb(pid, selected, target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:ql:\d+$"))
async def toggle_quality(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target, idx = int(parts[1]), parts[2], int(parts[4])
    if idx < 0 or idx >= len(QUALITY):
        await callback.answer("Неизвестное значение", show_alert=True)
        return
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    q = QUALITY[idx]
    is_ = await _load_is(db, project, target, project_service_factory)
    quals: list[str] = list(is_.get("quality", []))
    if q in quals:
        quals.remove(q)
    else:
        quals.append(q)
    is_["quality"] = quals
    await _save_is(db, pid, user.id, target, is_, project_service_factory)
    text = (
        Screen(E.IMAGE, S.CONTENT_QUALITY_TITLE)
        .blank()
        .line(S.CONTENT_QUALITY_DESC)
        .hint(S.CONTENT_QUALITY_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_quality_kb(pid, set(quals), target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:tone$"))
async def show_tones(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target = int(parts[1]), parts[2]
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    is_ = await _load_is(db, project, target, project_service_factory)
    selected = set(is_.get("tones", []))
    text = (
        Screen(E.IMAGE, S.CONTENT_TONE_TITLE)
        .blank()
        .line(S.CONTENT_TONE_DESC)
        .hint(S.CONTENT_TONE_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_tone_kb(pid, selected, target),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:tn:\d+$"))
async def toggle_tone(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, target, idx = int(parts[1]), parts[2], int(parts[4])
    if idx < 0 or idx >= len(TONES):
        await callback.answer("Неизвестная тональность", show_alert=True)
        return
    project = await _load_project(
        callback, pid, user, db, project_service_factory,
    )
    if not project:
        return
    tone = TONES[idx]
    is_ = await _load_is(db, project, target, project_service_factory)
    tones: list[str] = list(is_.get("tones", []))
    if tone in tones:
        tones.remove(tone)
    else:
        tones.append(tone)
    is_["tones"] = tones
    await _save_is(db, pid, user.id, target, is_, project_service_factory)
    text = (
        Screen(E.IMAGE, S.CONTENT_TONE_TITLE)
        .blank()
        .line(S.CONTENT_TONE_DESC)
        .hint(S.CONTENT_TONE_HINT)
        .build()
    )
    await safe_edit_text(
        msg, text,
        reply_markup=project_tone_kb(pid, set(tones), target),
    )
    await callback.answer()
