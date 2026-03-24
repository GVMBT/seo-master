"""Text-related content settings handlers.

Callback format: psettings:{pid}:{target}:{action}
Handles: text menu, word count, HTML style, text styles (multi-select),
brand style template (FSM: file upload or text input).
"""

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_callback_data, safe_edit_text, safe_message
from bot.service_factory import ProjectServiceFactory
from bot.texts import strings as S
from bot.texts.content_options import HTML_STYLES, TEXT_STYLES, WORD_COUNTS
from bot.texts.emoji import E
from bot.texts.screens import Screen
from db.client import SupabaseClient
from db.models import User
from keyboards.inline import (
    project_brand_style_kb,
    project_html_style_kb,
    project_text_menu_kb,
    project_text_style_kb,
    project_word_count_kb,
)
from routers.projects._settings_common import (
    _PT_RE,
    _load_project,
    _load_ts,
    _save_ts,
)

log = structlog.get_logger()
router = Router()


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
# 8. Brand style template
# ---------------------------------------------------------------------------

_MAX_BRAND_STYLE = 2000


class BrandStyleFSM(StatesGroup):
    waiting_input = State()


@router.callback_query(F.data.regexp(rf"^psettings:\d+:{_PT_RE}:bstyle$"))
async def show_brand_style(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
    state: FSMContext,
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
    current = ts.get("brand_style", "")

    lines = [
        Screen(E.DOC, S.CONTENT_BRAND_STYLE_TITLE)
        .blank()
        .line(S.CONTENT_BRAND_STYLE_DESC)
        .hint(S.CONTENT_BRAND_STYLE_HINT)
        .build(),
    ]
    if current:
        preview = current[:200] + ("..." if len(current) > 200 else "")
        lines.append(
            f"\n{E.CHECK} <b>{S.CONTENT_BRAND_STYLE_CURRENT}:</b>\n"
            f"<pre>{preview}</pre>"
        )
    text = "\n".join(lines)

    await ensure_no_active_fsm(state)
    await state.set_state(BrandStyleFSM.waiting_input)
    await state.update_data(pid=pid, target=target)

    await safe_edit_text(
        msg, text,
        reply_markup=project_brand_style_kb(pid, bool(current), target),
    )
    await callback.answer()


@router.callback_query(
    F.data.regexp(rf"^psettings:\d+:{_PT_RE}:bstyle_clear$"),
)
async def clear_brand_style(
    callback: CallbackQuery, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
    state: FSMContext,
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
    ts.pop("brand_style", None)
    await _save_ts(db, pid, user.id, target, ts, project_service_factory)
    await state.clear()
    log.info("brand_style_cleared", project_id=pid, target=target)
    await callback.answer(S.CONTENT_BRAND_STYLE_CLEARED)
    # Return to text menu
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


@router.message(BrandStyleFSM.waiting_input, F.document)
async def brand_style_file(
    message: Message, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
    state: FSMContext,
) -> None:
    """Handle .md / .txt file upload for brand style."""
    doc = message.document
    if not doc or not doc.file_name:
        await message.answer(S.CONTENT_BRAND_STYLE_FILE_ERROR)
        return
    ext = doc.file_name.rsplit(".", 1)[-1].lower() if "." in doc.file_name else ""
    if ext not in ("md", "txt"):
        await message.answer(S.CONTENT_BRAND_STYLE_FILE_ERROR)
        return
    if not message.bot:
        await message.answer(S.CONTENT_BRAND_STYLE_FILE_ERROR)
        return
    file = await message.bot.download(doc)
    if not file:
        await message.answer(S.CONTENT_BRAND_STYLE_FILE_ERROR)
        return
    content = file.read().decode("utf-8", errors="replace").strip()
    if len(content) > _MAX_BRAND_STYLE:
        await message.answer(S.CONTENT_BRAND_STYLE_TOO_LONG)
        return
    await _save_brand_style(message, user, db, project_service_factory, state, content)


@router.message(BrandStyleFSM.waiting_input, F.text)
async def brand_style_text(
    message: Message, user: User,
    db: SupabaseClient, project_service_factory: ProjectServiceFactory,
    state: FSMContext,
) -> None:
    """Handle plain text input for brand style."""
    content = (message.text or "").strip()
    if not content:
        return
    if len(content) > _MAX_BRAND_STYLE:
        await message.answer(S.CONTENT_BRAND_STYLE_TOO_LONG)
        return
    await _save_brand_style(message, user, db, project_service_factory, state, content)


async def _save_brand_style(
    message: Message, user: User,
    db: SupabaseClient, psf: ProjectServiceFactory,
    state: FSMContext, content: str,
) -> None:
    data = await state.get_data()
    pid, target = data["pid"], data["target"]
    project = await psf(db).get_owned_project(pid, user.id)
    if not project:
        await state.clear()
        return
    ts = await _load_ts(db, project, target, psf)
    ts["brand_style"] = content
    await _save_ts(db, pid, user.id, target, ts, psf)
    await state.clear()
    log.info("brand_style_saved", project_id=pid, target=target, length=len(content))
    await message.answer(f"{E.CHECK} {S.CONTENT_BRAND_STYLE_SAVED}")
