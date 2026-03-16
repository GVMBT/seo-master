"""Project-level content settings: text styles, word count, image options.

All interactions via callbacks (no FSM needed). Entry point: project:{pid}:content_settings.
Callback format: psettings:{pid}:{action}.
"""

from typing import Any

import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.helpers import safe_edit_text, safe_message
from bot.service_factory import ProjectServiceFactory
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
from db.client import SupabaseClient
from db.models import Project, User
from keyboards.inline import (
    project_angle_kb,
    project_article_format_kb,
    project_camera_kb,
    project_content_settings_kb,
    project_html_style_kb,
    project_image_count_kb,
    project_image_menu_kb,
    project_image_style_kb,
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

# Premium emoji for message texts
_SETTINGS_ICON = '<tg-emoji emoji-id="5305307637410206511">\u2699</tg-emoji>'
_TEXT_ICON = '<tg-emoji emoji-id="5305682317472208455">\u270f</tg-emoji>'
_IMAGE_ICON = '<tg-emoji emoji-id="5305545582893373314">\U0001f5bc</tg-emoji>'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_ts(project: Project) -> dict[str, Any]:
    """Get text_settings dict from project."""
    return dict(project.text_settings) if project.text_settings else {}


def _get_is(project: Project) -> dict[str, Any]:
    """Get image_settings dict from project."""
    return dict(project.image_settings) if project.image_settings else {}


def _main_text(ts: dict[str, Any], is_: dict[str, Any]) -> str:
    """Build main settings screen text."""
    lines = [f"{_SETTINGS_ICON} <b>НАСТРОЙКИ КОНТЕНТА</b>\n"]

    # Text section
    lines.append(f"{_TEXT_ICON} <b>Текст:</b>")
    styles = ts.get("styles", [])
    lines.append(f"  Стиль: {', '.join(styles) if styles else 'не выбран'}")
    html_style = ts.get("html_style")
    lines.append(f"  HTML: {html_style or 'не выбран'}")
    wc = ts.get("word_count")
    lines.append(f"  Длина: {wc} слов" if wc else "  Длина: по умолчанию")

    # Image section
    lines.append(f"\n{_IMAGE_ICON} <b>Изображения:</b>")
    img_styles = is_.get("styles", [])
    lines.append(f"  Стиль: {', '.join(img_styles) if img_styles else 'не выбран'}")
    preview_fmt = is_.get("preview_format")
    lines.append(f"  Превью: {preview_fmt or 'не выбран'}")
    art_fmts = is_.get("article_formats", [])
    lines.append(f"  Форматы: {', '.join(art_fmts) if art_fmts else 'не выбраны'}")
    count = is_.get("count")
    lines.append(f"  Количество: {count}" if count else "  Количество: по умолчанию")

    return "\n".join(lines)


async def _load_project(
    callback: CallbackQuery,
    pid: int,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> Project | None:
    """Load and verify project ownership. Answers callback on failure."""
    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(pid, user.id)
    if not project:
        await callback.answer("Проект не найден", show_alert=True)
    return project


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
    """Main content settings screen."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    pid = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _load_project(callback, pid, user, db, project_service_factory)
    if not project:
        return

    ts, is_ = _get_ts(project), _get_is(project)
    await safe_edit_text(
        msg,
        _main_text(ts, is_),
        reply_markup=project_content_settings_kb(pid),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^psettings:\d+:back$"))
async def back_to_settings(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Return to main settings screen."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    pid = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _load_project(callback, pid, user, db, project_service_factory)
    if not project:
        return

    ts, is_ = _get_ts(project), _get_is(project)
    await safe_edit_text(
        msg,
        _main_text(ts, is_),
        reply_markup=project_content_settings_kb(pid),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 2. Text sub-menu
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^psettings:\d+:text$"))
async def show_text_menu(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Text settings sub-menu."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    pid = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _load_project(callback, pid, user, db, project_service_factory)
    if not project:
        return

    await safe_edit_text(
        msg,
        f"{_TEXT_ICON} <b>Настройки текста</b>",
        reply_markup=project_text_menu_kb(pid),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 3. Word count (single-select from presets)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^psettings:\d+:words$"))
async def show_word_count(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show word count presets."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    pid = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _load_project(callback, pid, user, db, project_service_factory)
    if not project:
        return

    ts = _get_ts(project)
    current = ts.get("word_count")
    await safe_edit_text(
        msg,
        "Выберите длину статьи (в словах):",
        reply_markup=project_word_count_kb(pid, current),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^psettings:\d+:wc:\d+$"))
async def select_word_count(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Save selected word count."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    pid, wc = int(parts[1]), int(parts[3])

    if wc not in WORD_COUNTS:
        await callback.answer("Недопустимое значение", show_alert=True)
        return

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(pid, user.id)
    if not project:
        await callback.answer("Проект не найден", show_alert=True)
        return

    ts = _get_ts(project)
    ts["word_count"] = wc
    await proj_svc.update_text_settings(pid, user.id, ts)

    log.info("word_count_updated", project_id=pid, word_count=wc, user_id=user.id)
    await safe_edit_text(
        msg,
        f"Длина статьи: <b>{wc} слов</b>",
        reply_markup=project_word_count_kb(pid, wc),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 4. HTML style (single-select)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^psettings:\d+:html$"))
async def show_html_style(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show HTML style selection."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    pid = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _load_project(callback, pid, user, db, project_service_factory)
    if not project:
        return

    ts = _get_ts(project)
    current = ts.get("html_style")
    await safe_edit_text(
        msg,
        "Выберите стиль HTML-верстки:",
        reply_markup=project_html_style_kb(pid, current),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^psettings:\d+:hs:\d+$"))
async def select_html_style(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Save selected HTML style."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    pid, idx = int(parts[1]), int(parts[3])

    if idx < 0 or idx >= len(HTML_STYLES):
        await callback.answer("Неизвестный стиль", show_alert=True)
        return

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(pid, user.id)
    if not project:
        await callback.answer("Проект не найден", show_alert=True)
        return

    style = HTML_STYLES[idx]
    ts = _get_ts(project)
    ts["html_style"] = style
    await proj_svc.update_text_settings(pid, user.id, ts)

    log.info("html_style_updated", project_id=pid, style=style, user_id=user.id)
    await safe_edit_text(
        msg,
        f"HTML-верстка: <b>{style}</b>",
        reply_markup=project_html_style_kb(pid, style),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 5. Text styles (multi-select)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^psettings:\d+:tstyle$"))
async def show_text_styles(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show text style multi-select."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    pid = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _load_project(callback, pid, user, db, project_service_factory)
    if not project:
        return

    ts = _get_ts(project)
    selected = set(ts.get("styles", []))
    await safe_edit_text(
        msg,
        "Выберите стили текста (можно несколько):",
        reply_markup=project_text_style_kb(pid, selected),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^psettings:\d+:ts:\d+$"))
async def toggle_text_style(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Toggle a text style on/off."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    pid, idx = int(parts[1]), int(parts[3])

    if idx < 0 or idx >= len(TEXT_STYLES):
        await callback.answer("Неизвестный стиль", show_alert=True)
        return

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(pid, user.id)
    if not project:
        await callback.answer("Проект не найден", show_alert=True)
        return

    style = TEXT_STYLES[idx]
    ts = _get_ts(project)
    styles: list[str] = list(ts.get("styles", []))

    if style in styles:
        styles.remove(style)
    else:
        styles.append(style)

    ts["styles"] = styles
    await proj_svc.update_text_settings(pid, user.id, ts)

    await safe_edit_text(
        msg,
        "Выберите стили текста (можно несколько):",
        reply_markup=project_text_style_kb(pid, set(styles)),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 6. Image sub-menu
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^psettings:\d+:images$"))
async def show_image_menu(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Image settings sub-menu."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    pid = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _load_project(callback, pid, user, db, project_service_factory)
    if not project:
        return

    await safe_edit_text(
        msg,
        f"{_IMAGE_ICON} <b>Настройки изображений</b>",
        reply_markup=project_image_menu_kb(pid),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 7. Preview format (single-select)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^psettings:\d+:pfmt$"))
async def show_preview_format(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show preview format selection (single-select aspect ratio)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    pid = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _load_project(callback, pid, user, db, project_service_factory)
    if not project:
        return

    is_ = _get_is(project)
    current = is_.get("preview_format")
    await safe_edit_text(
        msg,
        "Выберите формат превью-изображения:",
        reply_markup=project_preview_format_kb(pid, current),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^psettings:\d+:pf:\d+$"))
async def select_preview_format(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Save selected preview format."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    pid, idx = int(parts[1]), int(parts[3])

    if idx < 0 or idx >= len(ASPECT_RATIOS):
        await callback.answer("Неизвестный формат", show_alert=True)
        return

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(pid, user.id)
    if not project:
        await callback.answer("Проект не найден", show_alert=True)
        return

    fmt = ASPECT_RATIOS[idx]
    is_ = _get_is(project)
    is_["preview_format"] = fmt
    await proj_svc.update_image_settings(pid, user.id, is_)

    log.info("preview_format_updated", project_id=pid, format=fmt, user_id=user.id)
    await safe_edit_text(
        msg,
        f"Формат превью: <b>{fmt}</b>",
        reply_markup=project_preview_format_kb(pid, fmt),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 8. Article formats (multi-select aspect ratios)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^psettings:\d+:afmts$"))
async def show_article_formats(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show article image format multi-select."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    pid = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _load_project(callback, pid, user, db, project_service_factory)
    if not project:
        return

    is_ = _get_is(project)
    selected = set(is_.get("article_formats", []))
    await safe_edit_text(
        msg,
        "Выберите форматы для изображений в статье (можно несколько):",
        reply_markup=project_article_format_kb(pid, selected),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^psettings:\d+:af:\d+$"))
async def toggle_article_format(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Toggle an article image format."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    pid, idx = int(parts[1]), int(parts[3])

    if idx < 0 or idx >= len(ASPECT_RATIOS):
        await callback.answer("Неизвестный формат", show_alert=True)
        return

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(pid, user.id)
    if not project:
        await callback.answer("Проект не найден", show_alert=True)
        return

    fmt = ASPECT_RATIOS[idx]
    is_ = _get_is(project)
    formats: list[str] = list(is_.get("article_formats", []))

    if fmt in formats:
        formats.remove(fmt)
    else:
        formats.append(fmt)

    is_["article_formats"] = formats
    await proj_svc.update_image_settings(pid, user.id, is_)

    await safe_edit_text(
        msg,
        "Выберите форматы для изображений в статье (можно несколько):",
        reply_markup=project_article_format_kb(pid, set(formats)),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 9. Image styles (multi-select)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^psettings:\d+:istyle$"))
async def show_image_styles(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show image style multi-select."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    pid = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _load_project(callback, pid, user, db, project_service_factory)
    if not project:
        return

    is_ = _get_is(project)
    selected = set(is_.get("styles", []))
    await safe_edit_text(
        msg,
        "Выберите стили изображений (можно несколько):",
        reply_markup=project_image_style_kb(pid, selected),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^psettings:\d+:is:\d+$"))
async def toggle_image_style(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Toggle an image style on/off."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    pid, idx = int(parts[1]), int(parts[3])

    if idx < 0 or idx >= len(IMAGE_STYLES):
        await callback.answer("Неизвестный стиль", show_alert=True)
        return

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(pid, user.id)
    if not project:
        await callback.answer("Проект не найден", show_alert=True)
        return

    style = IMAGE_STYLES[idx]
    is_ = _get_is(project)
    styles: list[str] = list(is_.get("styles", []))

    if style in styles:
        styles.remove(style)
    else:
        styles.append(style)

    is_["styles"] = styles
    await proj_svc.update_image_settings(pid, user.id, is_)

    await safe_edit_text(
        msg,
        "Выберите стили изображений (можно несколько):",
        reply_markup=project_image_style_kb(pid, set(styles)),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 10. Image count (single-select 1-10)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^psettings:\d+:icount$"))
async def show_image_count(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show image count selection."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    pid = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _load_project(callback, pid, user, db, project_service_factory)
    if not project:
        return

    is_ = _get_is(project)
    current = is_.get("count")
    await safe_edit_text(
        msg,
        "Выберите количество изображений на статью:",
        reply_markup=project_image_count_kb(pid, current),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^psettings:\d+:ic:\d+$"))
async def select_image_count(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Save selected image count."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    pid, count = int(parts[1]), int(parts[3])

    if count < 0 or count > 10:
        await callback.answer("Допустимо: 0-10", show_alert=True)
        return

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(pid, user.id)
    if not project:
        await callback.answer("Проект не найден", show_alert=True)
        return

    is_ = _get_is(project)
    is_["count"] = count
    await proj_svc.update_image_settings(pid, user.id, is_)

    log.info("image_count_updated", project_id=pid, count=count, user_id=user.id)
    await safe_edit_text(
        msg,
        f"Количество изображений: <b>{count}</b>",
        reply_markup=project_image_count_kb(pid, count),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 11. Text on image percentage (single-select)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^psettings:\d+:tximg$"))
async def show_text_on_image(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show text-on-image percentage selection."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    pid = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _load_project(callback, pid, user, db, project_service_factory)
    if not project:
        return

    is_ = _get_is(project)
    current = is_.get("text_on_image")
    await safe_edit_text(
        msg,
        "Процент текста на изображении:",
        reply_markup=project_text_on_image_kb(pid, current),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^psettings:\d+:to:\d+$"))
async def select_text_on_image(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Save selected text-on-image percentage."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    pid, pct = int(parts[1]), int(parts[3])

    if pct not in TEXT_ON_IMAGE:
        await callback.answer("Недопустимое значение", show_alert=True)
        return

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(pid, user.id)
    if not project:
        await callback.answer("Проект не найден", show_alert=True)
        return

    is_ = _get_is(project)
    is_["text_on_image"] = pct
    await proj_svc.update_image_settings(pid, user.id, is_)

    log.info("text_on_image_updated", project_id=pid, pct=pct, user_id=user.id)
    await safe_edit_text(
        msg,
        f"Текст на изображении: <b>{pct}%</b>",
        reply_markup=project_text_on_image_kb(pid, pct),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 12. Cameras (multi-select)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^psettings:\d+:camera$"))
async def show_cameras(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show camera multi-select."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    pid = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _load_project(callback, pid, user, db, project_service_factory)
    if not project:
        return

    is_ = _get_is(project)
    selected = set(is_.get("cameras", []))
    await safe_edit_text(
        msg,
        "Выберите камеры (можно несколько):",
        reply_markup=project_camera_kb(pid, selected),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^psettings:\d+:cm:\d+$"))
async def toggle_camera(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Toggle a camera on/off."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    pid, idx = int(parts[1]), int(parts[3])

    if idx < 0 or idx >= len(CAMERAS):
        await callback.answer("Неизвестная камера", show_alert=True)
        return

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(pid, user.id)
    if not project:
        await callback.answer("Проект не найден", show_alert=True)
        return

    cam = CAMERAS[idx]
    is_ = _get_is(project)
    cams: list[str] = list(is_.get("cameras", []))

    if cam in cams:
        cams.remove(cam)
    else:
        cams.append(cam)

    is_["cameras"] = cams
    await proj_svc.update_image_settings(pid, user.id, is_)

    await safe_edit_text(
        msg,
        "Выберите камеры (можно несколько):",
        reply_markup=project_camera_kb(pid, set(cams)),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 13. Angles (multi-select)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^psettings:\d+:angle$"))
async def show_angles(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show angle multi-select."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    pid = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _load_project(callback, pid, user, db, project_service_factory)
    if not project:
        return

    is_ = _get_is(project)
    selected = set(is_.get("angles", []))
    await safe_edit_text(
        msg,
        "Выберите ракурсы (можно несколько):",
        reply_markup=project_angle_kb(pid, selected),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^psettings:\d+:an:\d+$"))
async def toggle_angle(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Toggle an angle on/off."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    pid, idx = int(parts[1]), int(parts[3])

    if idx < 0 or idx >= len(ANGLES):
        await callback.answer("Неизвестный ракурс", show_alert=True)
        return

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(pid, user.id)
    if not project:
        await callback.answer("Проект не найден", show_alert=True)
        return

    angle = ANGLES[idx]
    is_ = _get_is(project)
    angles: list[str] = list(is_.get("angles", []))

    if angle in angles:
        angles.remove(angle)
    else:
        angles.append(angle)

    is_["angles"] = angles
    await proj_svc.update_image_settings(pid, user.id, is_)

    await safe_edit_text(
        msg,
        "Выберите ракурсы (можно несколько):",
        reply_markup=project_angle_kb(pid, set(angles)),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 14. Quality (multi-select)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^psettings:\d+:quality$"))
async def show_quality(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show quality multi-select."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    pid = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _load_project(callback, pid, user, db, project_service_factory)
    if not project:
        return

    is_ = _get_is(project)
    selected = set(is_.get("quality", []))
    await safe_edit_text(
        msg,
        "Выберите качество изображений (можно несколько):",
        reply_markup=project_quality_kb(pid, selected),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^psettings:\d+:ql:\d+$"))
async def toggle_quality(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Toggle a quality option on/off."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    pid, idx = int(parts[1]), int(parts[3])

    if idx < 0 or idx >= len(QUALITY):
        await callback.answer("Неизвестное значение", show_alert=True)
        return

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(pid, user.id)
    if not project:
        await callback.answer("Проект не найден", show_alert=True)
        return

    q = QUALITY[idx]
    is_ = _get_is(project)
    quals: list[str] = list(is_.get("quality", []))

    if q in quals:
        quals.remove(q)
    else:
        quals.append(q)

    is_["quality"] = quals
    await proj_svc.update_image_settings(pid, user.id, is_)

    await safe_edit_text(
        msg,
        "Выберите качество изображений (можно несколько):",
        reply_markup=project_quality_kb(pid, set(quals)),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 15. Tones (multi-select)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^psettings:\d+:tone$"))
async def show_tones(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show tone multi-select."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    pid = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _load_project(callback, pid, user, db, project_service_factory)
    if not project:
        return

    is_ = _get_is(project)
    selected = set(is_.get("tones", []))
    await safe_edit_text(
        msg,
        "Выберите тональность цветов (можно несколько):",
        reply_markup=project_tone_kb(pid, selected),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^psettings:\d+:tn:\d+$"))
async def toggle_tone(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Toggle a tone on/off."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    pid, idx = int(parts[1]), int(parts[3])

    if idx < 0 or idx >= len(TONES):
        await callback.answer("Неизвестная тональность", show_alert=True)
        return

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(pid, user.id)
    if not project:
        await callback.answer("Проект не найден", show_alert=True)
        return

    tone = TONES[idx]
    is_ = _get_is(project)
    tones: list[str] = list(is_.get("tones", []))

    if tone in tones:
        tones.remove(tone)
    else:
        tones.append(tone)

    is_["tones"] = tones
    await proj_svc.update_image_settings(pid, user.id, is_)

    await safe_edit_text(
        msg,
        "Выберите тональность цветов (можно несколько):",
        reply_markup=project_tone_kb(pid, set(tones)),
    )
    await callback.answer()
