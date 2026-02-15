"""Router: category media gallery (F23). No FSM — callback + message handlers."""

import html
from datetime import UTC, datetime

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db.client import SupabaseClient
from db.models import User
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from keyboards.category import media_menu_kb
from routers._helpers import guard_callback_message

log = structlog.get_logger()

router = Router(name="categories_media")

_MAX_MEDIA = 20  # soft limit per category


# ---------------------------------------------------------------------------
# Ownership helper
# ---------------------------------------------------------------------------


async def _get_cat_with_owner_check(
    category_id: int, user_id: int, db: SupabaseClient, callback: CallbackQuery
) -> tuple[int, int] | None:
    """Verify category ownership. Returns (category_id, project_id) or None."""
    cat = await CategoriesRepository(db).get_by_id(category_id)
    if not cat:
        await callback.answer("Категория не найдена.", show_alert=True)
        return None
    project = await ProjectsRepository(db).get_by_id(cat.project_id)
    if not project or project.user_id != user_id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return None
    return cat.id, project.id


# ---------------------------------------------------------------------------
# Entry: category:{id}:media
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:(\d+):media$"))
async def cb_media_start(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show media count + menu."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    result = await _get_cat_with_owner_check(category_id, user.id, db, callback)
    if not result:
        return
    cat_id, _ = result

    cat = await CategoriesRepository(db).get_by_id(cat_id)
    count = len(cat.media) if cat and cat.media else 0
    has_media = count > 0
    name = html.escape(cat.name) if cat else "?"

    text = f"<b>Медиа категории «{name}»</b>\n\nФайлов: {count} / {_MAX_MEDIA}"
    await msg.edit_text(text, reply_markup=media_menu_kb(cat_id, has_media).as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# Upload prompt
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^media:cat:(\d+):upload$"))
async def cb_media_upload_prompt(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient
) -> None:
    """Prompt user to send media files."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    category_id = int(callback.data.split(":")[2])  # type: ignore[union-attr]
    result = await _get_cat_with_owner_check(category_id, user.id, db, callback)
    if not result:
        return
    cat_id, _ = result

    await state.update_data(awaiting_media_cat=cat_id)
    await msg.edit_text(
        "Отправьте фото, видео или документ.\n"
        "Файлы будут добавлены к медиа категории.\n"
        f"Лимит: {_MAX_MEDIA} файлов.",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Media received (photo or document)
# ---------------------------------------------------------------------------


@router.message(F.photo)
async def on_photo_received(message: Message, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Handle photo upload to media gallery."""
    data = await state.get_data()
    cat_id = data.get("awaiting_media_cat")
    if not cat_id:
        return  # not in media upload mode — let other handlers process

    if not message.photo:
        return
    photo = message.photo[-1]  # largest resolution
    await _append_media(message, state, db, cat_id, photo.file_id, "photo", photo.file_size or 0)


@router.message(F.document)
async def on_document_received(message: Message, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Handle document upload to media gallery."""
    data = await state.get_data()
    cat_id = data.get("awaiting_media_cat")
    if not cat_id:
        return  # not in media upload mode

    doc = message.document
    if not doc:
        return
    await _append_media(message, state, db, cat_id, doc.file_id, "document", doc.file_size or 0)


async def _append_media(
    message: Message,
    state: FSMContext,
    db: SupabaseClient,
    cat_id: int,
    file_id: str,
    file_type: str,
    file_size: int,
) -> None:
    """Append a media item to category's media array via repository."""
    repo = CategoriesRepository(db)
    cat = await repo.get_by_id(cat_id)
    if not cat:
        await message.answer("Категория не найдена.")
        await state.update_data(awaiting_media_cat=None)
        return

    media = list(cat.media) if cat.media else []
    if len(media) >= _MAX_MEDIA:
        await message.answer(f"Достигнут лимит: {_MAX_MEDIA} файлов.")
        await state.update_data(awaiting_media_cat=None)
        return

    media.append({
        "file_id": file_id,
        "type": file_type,
        "file_size": file_size,
        "uploaded_at": datetime.now(tz=UTC).isoformat(),
    })
    await repo.update_media(cat_id, media)

    count = len(media)
    await message.answer(
        f"Файл добавлен ({count}/{_MAX_MEDIA}).\n"
        "Отправьте ещё или нажмите кнопку ниже.",
        reply_markup=media_menu_kb(cat_id, has_media=True).as_markup(),
    )


# ---------------------------------------------------------------------------
# Clear all media
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^media:cat:(\d+):clear$"))
async def cb_media_clear(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Clear all media for a category."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    category_id = int(callback.data.split(":")[2])  # type: ignore[union-attr]
    result = await _get_cat_with_owner_check(category_id, user.id, db, callback)
    if not result:
        return
    cat_id, _ = result

    await CategoriesRepository(db).update_media(cat_id, [])
    await state.update_data(awaiting_media_cat=None)

    cat = await CategoriesRepository(db).get_by_id(cat_id)
    name = html.escape(cat.name) if cat else "?"
    text = f"<b>Медиа категории «{name}»</b>\n\nФайлов: 0 / {_MAX_MEDIA}"
    await msg.edit_text(text, reply_markup=media_menu_kb(cat_id, has_media=False).as_markup())
    await callback.answer("Медиа очищены.")
