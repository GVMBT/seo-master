"""Content settings: text length, text style, image count, image style.

Source of truth: UX_TOOLBOX.md section 12, FSM_SPEC.md section 2.1.1.
Text length needs FSM for 2 text inputs; styles use pure callbacks.
"""

import html
import time
from typing import Any

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_message
from db.client import SupabaseClient
from db.models import Category, CategoryUpdate, User
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from keyboards.inline import (
    cancel_kb,
    category_card_kb,
    content_settings_kb,
    image_count_kb,
    image_style_kb,
    text_style_kb,
)

log = structlog.get_logger()
router = Router()

# Ordered lists (must match keyboards/inline.py _TEXT_STYLES / _IMAGE_STYLES)
_TEXT_STYLES: list[str] = [
    "Рекламный",
    "Мотивационный",
    "Дружелюбный",
    "Разговорный",
    "Профессиональный",
    "Креативный",
    "Информативный",
    "С юмором",
]

_IMAGE_STYLES: list[str] = [
    "Фотореализм",
    "Аниме",
    "Масло",
    "Акварель",
    "Мультяшный",
    "Минимализм",
]

_VALID_TEXT_STYLES: set[str] = set(_TEXT_STYLES)
_VALID_IMAGE_STYLES: set[str] = set(_IMAGE_STYLES)


# ---------------------------------------------------------------------------
# FSM for text length input only (2 text inputs → need states)
# ---------------------------------------------------------------------------


class ContentSettingsFSM(StatesGroup):
    min_words = State()  # Input: min word count (500-10000)
    max_words = State()  # Input: max word count (> min, ≤10000)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _check_category_ownership(
    category_id: int,
    user: User,
    db: SupabaseClient,
) -> tuple[CategoriesRepository, Category | None]:
    """Load category and verify ownership. Returns (repo, category) or (repo, None)."""
    cats_repo = CategoriesRepository(db)
    category = await cats_repo.get_by_id(category_id)
    if not category:
        return cats_repo, None

    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(category.project_id)
    if not project or project.user_id != user.id:
        return cats_repo, None

    return cats_repo, category


def _get_text_settings(category: Category) -> dict[str, Any]:
    """Get text_settings dict from category."""
    return category.text_settings if category.text_settings else {}


def _get_image_settings(category: Category) -> dict[str, Any]:
    """Get image_settings dict from category."""
    return category.image_settings if category.image_settings else {}


# ---------------------------------------------------------------------------
# 1. Show main settings screen
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:\d+:content_settings$"))
async def show_settings(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Main content settings screen (UX_TOOLBOX section 12)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category = await _check_category_ownership(category_id, user, db)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    safe_name = html.escape(category.name)
    ts = _get_text_settings(category)
    img = _get_image_settings(category)

    # Build summary
    lines = [f"<b>Настройки контента</b> — {safe_name}\n"]

    min_w = ts.get("min_words")
    max_w = ts.get("max_words")
    if min_w and max_w:
        lines.append(f"Длина статьи: {min_w}–{max_w} слов")
    else:
        lines.append("Длина статьи: по умолчанию")

    styles = ts.get("styles", [])
    if styles:
        lines.append(f"Стиль текста: {', '.join(styles)}")
    else:
        lines.append("Стиль текста: не выбран")

    img_count = img.get("count")
    if img_count is not None:
        lines.append(f"Изображений: {img_count}/статью")
    else:
        lines.append("Изображений: по умолчанию")

    img_style = img.get("style")
    if img_style:
        lines.append(f"Стиль изображений: {img_style}")
    else:
        lines.append("Стиль изображений: по умолчанию")

    settings_dict = {**ts, **img}
    await msg.edit_text(
        "\n".join(lines),
        reply_markup=content_settings_kb(category_id, settings_dict),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 2. Text length (FSM: min_words → max_words)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^settings:\d+:text_length$"))
async def text_length(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Start text length input (UX_TOOLBOX section 12.1)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category = await _check_category_ownership(cat_id, user, db)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    ts = _get_text_settings(category)
    current_min = ts.get("min_words", 1500)
    current_max = ts.get("max_words", 3000)

    await state.set_state(ContentSettingsFSM.min_words)
    await state.update_data(
        last_update_time=time.time(),
        settings_cat_id=cat_id,
    )

    await msg.edit_text(
        f"Текущая длина: {current_min}–{current_max} слов.\n\n"
        "Введите <b>минимальную</b> длину статьи (500–10000 слов):",
        reply_markup=cancel_kb(f"cs:{cat_id}:cancel"),
    )
    await callback.answer()


@router.message(ContentSettingsFSM.min_words, F.text)
async def process_min_words(
    message: Message,
    state: FSMContext,
) -> None:
    """Validate min word count (500-10000)."""
    text = (message.text or "").strip()

    try:
        min_val = int(text)
    except ValueError:
        await message.answer("Введите число от 500 до 10000.")
        return

    if min_val < 500 or min_val > 10000:
        await message.answer("Допустимый диапазон: 500–10000 слов.")
        return

    await state.set_state(ContentSettingsFSM.max_words)
    data = await state.update_data(min_words=min_val, last_update_time=time.time())
    cat_id = data.get("settings_cat_id", 0)

    await message.answer(
        f"Минимум: {min_val} слов.\n\nВведите <b>максимальную</b> длину (>{min_val}, до 10000):",
        reply_markup=cancel_kb(f"cs:{cat_id}:cancel"),
    )


@router.message(ContentSettingsFSM.max_words, F.text)
async def process_max_words(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Validate max word count (> min, ≤10000) and save."""
    text = (message.text or "").strip()
    data = await state.get_data()
    min_raw = data.get("min_words")
    cat_raw = data.get("settings_cat_id")
    if min_raw is None or cat_raw is None:
        await state.clear()
        await message.answer("Сессия устарела. Начните настройку заново.")
        return
    min_val = int(min_raw)

    try:
        max_val = int(text)
    except ValueError:
        await message.answer(f"Введите число от {min_val + 1} до 10000.")
        return

    if max_val <= min_val:
        await message.answer(f"Максимум должен быть больше минимума ({min_val}).")
        return

    if max_val > 10000:
        await message.answer("Максимум 10000 слов.")
        return

    cat_id = int(cat_raw)
    await state.clear()

    cats_repo = CategoriesRepository(db)
    category = await cats_repo.get_by_id(cat_id)
    if not category:
        await message.answer("Категория не найдена.")
        return

    # Update text_settings
    ts = _get_text_settings(category)
    ts["min_words"] = min_val
    ts["max_words"] = max_val
    await cats_repo.update(cat_id, CategoryUpdate(text_settings=ts))

    log.info("text_length_updated", cat_id=cat_id, min=min_val, max=max_val, user_id=user.id)
    await message.answer(
        f"Длина статьи: {min_val}–{max_val} слов.",
        reply_markup=content_settings_kb(cat_id, {**ts, **_get_image_settings(category)}),
    )


# ---------------------------------------------------------------------------
# 3. Text style (multi-select, pure callbacks)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^settings:\d+:text_style$"))
async def text_style(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show text style multi-select grid (UX_TOOLBOX section 12.2)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category = await _check_category_ownership(cat_id, user, db)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    ts = _get_text_settings(category)
    selected: list[str] = ts.get("styles", [])

    await msg.edit_text(
        "\u270d\ufe0f Выберите стили текста (можно несколько):",
        reply_markup=text_style_kb(cat_id, selected),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^settings:\d+:ts:\d+$"))
async def toggle_style(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Toggle a text style on/off (index-based callback)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    cat_id = int(parts[1])
    style_idx = int(parts[3])

    if style_idx < 0 or style_idx >= len(_TEXT_STYLES):
        await callback.answer("Неизвестный стиль.", show_alert=True)
        return
    style_name = _TEXT_STYLES[style_idx]

    _, category = await _check_category_ownership(cat_id, user, db)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    ts = _get_text_settings(category)
    selected: list[str] = ts.get("styles", [])

    # Toggle
    if style_name in selected:
        selected.remove(style_name)
    else:
        selected.append(style_name)

    # Save immediately (no separate "save" step for toggle)
    ts["styles"] = selected
    cats_repo = CategoriesRepository(db)
    await cats_repo.update(cat_id, CategoryUpdate(text_settings=ts))

    await msg.edit_text(
        "\u270d\ufe0f Выберите стили текста (можно несколько):",
        reply_markup=text_style_kb(cat_id, selected),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^settings:\d+:ts_save$"))
async def save_styles(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Save styles and return to settings screen."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category = await _check_category_ownership(cat_id, user, db)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    # Styles already saved on toggle — just redirect back
    ts = _get_text_settings(category)
    img = _get_image_settings(category)

    safe_name = html.escape(category.name)
    selected = ts.get("styles", [])

    lines = [f"<b>Настройки контента</b> — {safe_name}\n"]
    lines.append(f"Стиль текста: {', '.join(selected) if selected else 'не выбран'}")

    await msg.edit_text(
        "\n".join(lines),
        reply_markup=content_settings_kb(cat_id, {**ts, **img}),
    )
    await callback.answer("Стили сохранены.")


# ---------------------------------------------------------------------------
# 4. Image count (pure callbacks)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^settings:\d+:img_count$"))
async def img_count(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show image count selection 0-10 (UX_TOOLBOX section 12.3)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category = await _check_category_ownership(cat_id, user, db)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    img = _get_image_settings(category)
    current = img.get("count", 4)  # default 4

    await msg.edit_text(
        "Выберите количество изображений на статью:",
        reply_markup=image_count_kb(cat_id, current),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^settings:\d+:imgcnt:\d+$"))
async def select_img_count(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Save selected image count and return to settings."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    cat_id = int(parts[1])
    count = int(parts[3])

    if count < 0 or count > 10:
        await callback.answer("Допустимо: 0-10.", show_alert=True)
        return

    _, category = await _check_category_ownership(cat_id, user, db)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    img = _get_image_settings(category)
    img["count"] = count
    cats_repo = CategoriesRepository(db)
    await cats_repo.update(cat_id, CategoryUpdate(image_settings=img))

    log.info("img_count_updated", cat_id=cat_id, count=count, user_id=user.id)

    ts = _get_text_settings(category)
    safe_name = html.escape(category.name)
    await msg.edit_text(
        f"<b>Настройки контента</b> — {safe_name}\n\nИзображений: {count}/статью",
        reply_markup=content_settings_kb(cat_id, {**ts, **img}),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 5. Image style (single select, pure callbacks)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^settings:\d+:img_style$"))
async def img_style(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show image style selection (UX_TOOLBOX section 12.4)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category = await _check_category_ownership(cat_id, user, db)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    img = _get_image_settings(category)
    current = img.get("style")

    await msg.edit_text(
        "Выберите стиль изображений:",
        reply_markup=image_style_kb(cat_id, current),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^settings:\d+:is:\d+$"))
async def select_img_style(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Save selected image style and return to settings (index-based callback)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    cat_id = int(parts[1])
    style_idx = int(parts[3])

    if style_idx < 0 or style_idx >= len(_IMAGE_STYLES):
        await callback.answer("Неизвестный стиль.", show_alert=True)
        return
    style_name = _IMAGE_STYLES[style_idx]

    _, category = await _check_category_ownership(cat_id, user, db)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    img = _get_image_settings(category)
    img["style"] = style_name
    cats_repo = CategoriesRepository(db)
    await cats_repo.update(cat_id, CategoryUpdate(image_settings=img))

    log.info("img_style_updated", cat_id=cat_id, style=style_name, user_id=user.id)

    ts = _get_text_settings(category)
    safe_name = html.escape(category.name)
    await msg.edit_text(
        f"<b>Настройки контента</b> — {safe_name}\n\nСтиль изображений: {style_name}",
        reply_markup=content_settings_kb(cat_id, {**ts, **img}),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 6. Cancel handler (inline button)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^cs:\d+:cancel$"))
async def cancel_text_length_inline(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Cancel text length input via inline button — return to category card."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    await state.clear()

    _, category = await _check_category_ownership(cat_id, user, db)
    if category:
        safe_name = html.escape(category.name)
        await msg.edit_text(
            f"<b>{safe_name}</b>",
            reply_markup=category_card_kb(cat_id, category.project_id),
        )
        await callback.answer()
        return

    await msg.edit_text("Настройка отменена.")
    await callback.answer()
