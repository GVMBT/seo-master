"""Router: category price input (PriceInputFSM)."""

import html
import io

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.fsm_utils import ensure_no_active_fsm
from db.client import SupabaseClient
from db.models import CategoryUpdate, User
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from keyboards.category import price_existing_kb, price_method_kb, price_result_kb
from keyboards.inline import category_card_kb
from keyboards.reply import cancel_kb, main_menu
from routers._helpers import guard_callback_message

log = structlog.get_logger()

router = Router(name="categories_prices")

_MAX_LINES = 1000  # E09: max 1000 items
_MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


# ---------------------------------------------------------------------------
# FSM definition
# ---------------------------------------------------------------------------


class PriceInputFSM(StatesGroup):
    choose_method = State()
    text_input = State()
    file_upload = State()


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
# Entry: category:{id}:prices
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:(\d+):prices$"))
async def cb_prices_start(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show current prices or offer methods to add."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    cat = await CategoriesRepository(db).get_by_id(category_id)
    if not cat:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    project = await ProjectsRepository(db).get_by_id(cat.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    if cat.prices:
        lines = cat.prices.strip().split("\n")
        preview = "\n".join(lines[:20])
        text = f"<b>Прайс-лист ({len(lines)} позиций)</b>\n\n<pre>{html.escape(preview)}</pre>"
        if len(lines) > 20:
            text += f"\n\n... и ещё {len(lines) - 20} позиций"
        # Truncate to Telegram message limit (4096 chars)
        if len(text) > 4000:
            text = text[:3990] + "\n...</pre>"
        await msg.edit_text(text, reply_markup=price_existing_kb(cat.id).as_markup())
    else:
        text = "Прайс-лист пуст. Выберите способ загрузки:"
        await msg.edit_text(text, reply_markup=price_method_kb(cat.id).as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# Update entry (from existing prices)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:(\d+):prices:update$"))
async def cb_prices_update(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show method selection for price update."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    result = await _get_cat_with_owner_check(category_id, user.id, db, callback)
    if not result:
        return
    cat_id, _ = result
    text = "Выберите способ загрузки нового прайса:"
    await msg.edit_text(text, reply_markup=price_method_kb(cat_id).as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# Text input method
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^price:cat:(\d+):text$"))
async def cb_price_text(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Start text input for prices."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    category_id = int(callback.data.split(":")[2])  # type: ignore[union-attr]
    result = await _get_cat_with_owner_check(category_id, user.id, db, callback)
    if not result:
        return
    cat_id, project_id = result

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(PriceInputFSM.text_input)
    await state.update_data(category_id=cat_id, project_id=project_id)

    await msg.answer(
        "Введите прайс-лист. Каждая строка — одна позиция.\n"
        "Формат: Товар — Цена\n\n"
        "Пример:\n"
        "Кухонный гарнитур — от 50 000 руб.\n"
        "Столешница — от 10 000 руб.",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(PriceInputFSM.text_input, F.text)
async def fsm_price_text_input(message: Message, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Parse text input for prices and show preview."""
    text = message.text.strip()  # type: ignore[union-attr]
    if not text:
        await message.answer("Введите непустой прайс-лист.")
        return

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) > _MAX_LINES:
        await message.answer(f"Максимум {_MAX_LINES} позиций. У вас: {len(lines)}.")
        return

    prices_text = "\n".join(lines)
    await state.update_data(prices_text=prices_text)

    data = await state.get_data()
    cat_id: int = data.get("category_id", 0)

    preview = "\n".join(lines[:10])
    text_preview = f"<b>Прайс-лист ({len(lines)} позиций):</b>\n\n<pre>{html.escape(preview)}</pre>"
    if len(lines) > 10:
        text_preview += f"\n\n... и ещё {len(lines) - 10} позиций"
    text_preview += "\n\nСохранить?"
    # Truncate to Telegram message limit (4096 chars)
    if len(text_preview) > 4000:
        text_preview = text_preview[:3990] + "\n...</pre>\n\nСохранить?"
    await message.answer(text_preview, reply_markup=price_result_kb(cat_id).as_markup())


# ---------------------------------------------------------------------------
# Excel upload method
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^price:cat:(\d+):excel$"))
async def cb_price_excel(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Start Excel upload for prices."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    category_id = int(callback.data.split(":")[2])  # type: ignore[union-attr]
    result = await _get_cat_with_owner_check(category_id, user.id, db, callback)
    if not result:
        return
    cat_id, project_id = result

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(PriceInputFSM.file_upload)
    await state.update_data(category_id=cat_id, project_id=project_id)

    await msg.answer(
        f"Отправьте файл Excel (.xlsx).\nКолонки: Название | Цена\nМаксимум: {_MAX_LINES} строк, 5 МБ.",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(PriceInputFSM.file_upload, F.document)
async def fsm_price_file_upload(message: Message, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Parse uploaded Excel file and show preview."""
    doc = message.document
    if not doc:
        await message.answer("Отправьте файл Excel (.xlsx).")
        return

    filename = doc.file_name or ""
    if not filename.lower().endswith(".xlsx"):
        await message.answer("Поддерживается только формат .xlsx.")
        return

    if doc.file_size and doc.file_size > _MAX_FILE_SIZE:
        await message.answer(f"Файл слишком большой. Максимум: {_MAX_FILE_SIZE // (1024 * 1024)} МБ.")
        return

    try:
        file = await message.bot.download(doc)  # type: ignore[union-attr]
        if file is None:
            await message.answer("Не удалось скачать файл.")
            return

        import openpyxl  # type: ignore[import-untyped]

        wb = openpyxl.load_workbook(io.BytesIO(file.read()), read_only=True)
        ws = wb.active
        if ws is None:
            wb.close()
            await message.answer("Файл не содержит данных.")
            return

        lines: list[str] = []
        for row in ws.iter_rows(min_row=2, values_only=True):  # skip header
            if len(lines) >= _MAX_LINES:
                break
            cells = [str(c).strip() if c is not None else "" for c in row[:2]]
            if cells[0]:
                line = f"{cells[0]} — {cells[1]}" if len(cells) > 1 and cells[1] else cells[0]
                lines.append(line)
        wb.close()
    except Exception:
        log.exception("excel_parse_failed", user_id=user.id)
        await message.answer("Не удалось прочитать Excel-файл. Проверьте формат.")
        return

    if not lines:
        await message.answer("Файл не содержит данных (пропускаем первую строку как заголовок).")
        return

    prices_text = "\n".join(lines)
    await state.update_data(prices_text=prices_text)

    data = await state.get_data()
    cat_id: int = data.get("category_id", 0)

    preview = "\n".join(lines[:10])
    text = f"<b>Прайс-лист ({len(lines)} позиций):</b>\n\n<pre>{html.escape(preview)}</pre>"
    if len(lines) > 10:
        text += f"\n\n... и ещё {len(lines) - 10} позиций"
    text += "\n\nСохранить?"
    # Truncate to Telegram message limit (4096 chars)
    if len(text) > 4000:
        text = text[:3990] + "\n...</pre>\n\nСохранить?"
    await message.answer(text, reply_markup=price_result_kb(cat_id).as_markup())


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


@router.callback_query(PriceInputFSM.text_input, F.data == "price:save")
async def fsm_price_save_text(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Save prices from text input to category."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    data = await state.get_data()
    cat_id = data.get("category_id")
    prices_text = data.get("prices_text", "")

    if not cat_id:
        await state.clear()
        await callback.answer("Сессия истекла.", show_alert=True)
        return

    category = await CategoriesRepository(db).update(cat_id, CategoryUpdate(prices=prices_text))
    await state.clear()

    if category:
        from routers.categories.manage import _format_category_card

        await msg.edit_text(
            f"Прайс-лист сохранён!\n\n{_format_category_card(category)}",
            reply_markup=category_card_kb(category).as_markup(),
        )
    else:
        from keyboards.errors import error_not_found_kb

        await msg.edit_text("Категория не найдена.", reply_markup=error_not_found_kb().as_markup())
    await msg.answer("\u200b", reply_markup=main_menu(is_admin=user.role == "admin"))
    await callback.answer()


@router.callback_query(PriceInputFSM.file_upload, F.data == "price:save")
async def fsm_price_save_excel(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Save prices from Excel upload to category."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    data = await state.get_data()
    cat_id = data.get("category_id")
    prices_text = data.get("prices_text", "")

    if not cat_id:
        await state.clear()
        await callback.answer("Сессия истекла.", show_alert=True)
        return

    category = await CategoriesRepository(db).update(cat_id, CategoryUpdate(prices=prices_text))
    await state.clear()

    if category:
        from routers.categories.manage import _format_category_card

        await msg.edit_text(
            f"Прайс-лист сохранён!\n\n{_format_category_card(category)}",
            reply_markup=category_card_kb(category).as_markup(),
        )
    else:
        from keyboards.errors import error_not_found_kb

        await msg.edit_text("Категория не найдена.", reply_markup=error_not_found_kb().as_markup())
    await msg.answer("\u200b", reply_markup=main_menu(is_admin=user.role == "admin"))
    await callback.answer()


# ---------------------------------------------------------------------------
# Clear prices
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^price:cat:(\d+):clear$"))
async def cb_price_clear(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Clear prices for a category."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    category_id = int(callback.data.split(":")[2])  # type: ignore[union-attr]
    result = await _get_cat_with_owner_check(category_id, user.id, db, callback)
    if not result:
        return
    cat_id, _ = result

    await CategoriesRepository(db).update(cat_id, CategoryUpdate(prices=""))

    await msg.edit_text("Прайс-лист очищен.", reply_markup=price_method_kb(cat_id).as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# FSM guards / stubs for unused states
# ---------------------------------------------------------------------------


@router.message(PriceInputFSM.choose_method)
async def fsm_price_choose_method_guard(message: Message, _state: FSMContext) -> None:
    """TODO Phase 11: choose_method state is currently unused (entry skips to text/file).

    Guard handler to prevent stuck state.
    """
    await message.answer("Выберите способ загрузки кнопкой выше.")


@router.message(PriceInputFSM.file_upload, ~F.document)
async def fsm_price_file_upload_text_guard(message: Message) -> None:
    """Guard: user sent text instead of a document in file_upload state."""
    await message.answer("Ожидаю файл Excel (.xlsx). Отправьте файл как документ.")
