"""Price list management: text input and Excel upload (UX_TOOLBOX.md section 11)."""

import html
import itertools
import time
from io import BytesIO
from typing import Any

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_callback_data, safe_edit_text, safe_message
from bot.service_factory import CategoryServiceFactory
from bot.texts import strings as S
from bot.texts.emoji import E
from bot.texts.screens import Screen
from db.client import SupabaseClient
from db.models import User
from keyboards.inline import cancel_kb, category_card_kb, menu_kb, prices_kb

log = structlog.get_logger()
router = Router()

# Limits (E09)
_MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
_MAX_ROWS = 1000

_HEADER_KEYWORDS: set[str] = {
    "название",
    "наименование",
    "товар",
    "услуга",
    "продукт",
    "цена",
    "стоимость",
    "прайс",
    "артикул",
    "код",
    "sku",
    "описание",
    "характеристика",
    "материал",
    "размер",
    "вес",
    "количество",
    "ед",
    "категория",
    "бренд",
    "марка",
}


def _is_numeric(text: str) -> bool:
    """Check if text looks like a number (prices, quantities)."""
    cleaned = text.replace(" ", "").replace("\xa0", "").replace(",", ".").replace("-", "")
    if not cleaned:
        return False
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def _is_header_row(row: tuple[Any, ...]) -> bool:
    """Detect if a row is likely a header (keyword match or all-text heuristic)."""
    cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
    if not cells:
        return False
    for cell in cells:
        if cell.lower() in _HEADER_KEYWORDS:
            return True
    all_text = all(not _is_numeric(c) for c in cells)
    avg_len = sum(len(c) for c in cells) / len(cells)
    return all_text and avg_len < 30


# ---------------------------------------------------------------------------
# FSM definition (FSM_SPEC.md section 1)
# ---------------------------------------------------------------------------


class PriceInputFSM(StatesGroup):
    text_input = State()  # Text: "Name - Price" per line
    file_upload = State()  # Excel .xlsx upload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _show_prices_screen(
    message: Message,
    category_id: int,
    category_name: str,
    prices: str | None,
) -> None:
    """Render the prices screen (section 11 filled / 11.3 empty)."""
    safe_name = html.escape(category_name)
    s = Screen(E.PRICE, f"ЦЕНЫ \u2014 {safe_name}")
    s.blank()

    if prices:
        lines_count = len([ln for ln in prices.splitlines() if ln.strip()])
        s.check(S.PRICES_LOADED, ok=True, detail=f"{lines_count} позиций")
    else:
        s.line(S.PRICES_EMPTY)
    s.hint(S.PRICES_HINT)
    text = s.build()

    await safe_edit_text(message, text, reply_markup=prices_kb(category_id, has_prices=bool(prices)))


# ---------------------------------------------------------------------------
# Show prices screen
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:\d+:prices$"))
async def show_prices(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Show prices screen (UX_TOOLBOX.md section 11)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cb_data = safe_callback_data(callback)
    category_id = int(cb_data.split(":")[1])
    cat_svc = category_service_factory(db)
    category = await cat_svc.get_owned_category(category_id, user.id)

    if not category:
        await callback.answer(S.CATEGORY_NOT_FOUND, show_alert=True)
        return

    await _show_prices_screen(msg, category.id, category.name, category.prices)
    await callback.answer()


# ---------------------------------------------------------------------------
# Text input flow
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^prices:\d+:text$"))
async def start_text(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Start text-based price input (section 11.1)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cb_data = safe_callback_data(callback)
    cat_id = int(cb_data.split(":")[1])
    cat_svc = category_service_factory(db)
    category = await cat_svc.get_owned_category(cat_id, user.id)
    if not category:
        await callback.answer(S.CATEGORY_NOT_FOUND, show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(PriceInputFSM.text_input)
    await state.update_data(last_update_time=time.time(), prices_cat_id=cat_id)

    await msg.answer(
        S.PRICES_TEXT_PROMPT,
        reply_markup=cancel_kb(f"price:{cat_id}:cancel"),
    )
    await callback.answer()


@router.message(PriceInputFSM.text_input, F.text)
async def process_text(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Process text price input. Store as-is (plain text)."""
    text = (message.text or "").strip()

    if text == "Отмена":
        await state.clear()
        await message.answer(S.PRICES_CANCELLED, reply_markup=menu_kb())
        return

    # Validate: at least 1 non-empty line
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        await message.answer(S.PRICES_TEXT_EMPTY)
        return

    if len(lines) > _MAX_ROWS:
        await message.answer(S.PRICES_TEXT_MAX_ROWS.format(max=_MAX_ROWS, count=len(lines)))
        return

    data = await state.get_data()
    cat_id = int(data["prices_cat_id"])
    await state.clear()

    cat_svc = category_service_factory(db)
    prices_text = "\n".join(lines)
    result = await cat_svc.update_prices(cat_id, user.id, prices_text)
    if not result:
        await message.answer(S.CATEGORY_NOT_FOUND, reply_markup=menu_kb())
        return

    log.info("prices_updated_text", category_id=cat_id, lines=len(lines), user_id=user.id)

    safe_name = html.escape(result.name)
    count = len(lines)
    preview_lines = lines[:10]
    preview = "\n".join(f"  \u2022 {html.escape(ln)}" for ln in preview_lines)
    if count > 10:
        preview += f"\n  ... ещё {count - 10}"

    result_text = (
        Screen(E.PRICE, f"ЦЕНЫ \u2014 {safe_name}")
        .blank()
        .line(f"{E.CHECK} {S.PRICES_SAVED.format(count=count)}:")
        .line(preview)
        .hint(S.PRICES_HINT)
        .build()
    )
    await message.answer(result_text, reply_markup=prices_kb(cat_id, has_prices=True))


# ---------------------------------------------------------------------------
# Excel upload flow
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^prices:\d+:excel$"))
async def start_excel(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Start Excel-based price upload (section 11.2)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cb_data = safe_callback_data(callback)
    cat_id = int(cb_data.split(":")[1])
    cat_svc = category_service_factory(db)
    category = await cat_svc.get_owned_category(cat_id, user.id)
    if not category:
        await callback.answer(S.CATEGORY_NOT_FOUND, show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(PriceInputFSM.file_upload)
    await state.update_data(last_update_time=time.time(), prices_cat_id=cat_id)

    await msg.answer(
        S.PRICES_EXCEL_PROMPT,
        reply_markup=cancel_kb(f"price:{cat_id}:cancel"),
    )
    await callback.answer()


@router.message(PriceInputFSM.file_upload, F.text)
async def handle_text_in_excel_state(
    message: Message,
    state: FSMContext,
) -> None:
    """Handle text message while waiting for Excel file."""
    text = (message.text or "").strip()
    if text == "Отмена":
        await state.clear()
        await message.answer(S.PRICES_CANCELLED, reply_markup=menu_kb())
        return

    await message.answer(S.PRICES_EXCEL_EXPECT)


def parse_excel_rows(file_bytes: bytes) -> list[str] | str:
    """Parse Excel — reads ALL columns, auto-detects headers."""
    import openpyxl  # type: ignore[import-untyped]

    wb = openpyxl.load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
    try:
        ws = wb.active
        if ws is None:
            return "empty"

        rows_iter = (
            r
            for r in ws.iter_rows(values_only=True)
            if r and not all(c is None or str(c).strip() == "" for c in r)
        )
        first_row = next(rows_iter, None)
        if first_row is None:
            return "empty"

        # Detect headers (only when >1 row to avoid treating single data row as header)
        second_row = next(rows_iter, None)
        headers: list[str] | None = None
        if second_row is not None and _is_header_row(first_row):
            headers = [
                str(c).strip() if c is not None else f"Столбец {i + 1}" for i, c in enumerate(first_row)
            ]
            data_rows: itertools.chain[tuple[Any, ...]] = itertools.chain([second_row], rows_iter)
        elif second_row is not None:
            data_rows = itertools.chain([first_row, second_row], rows_iter)
        else:
            data_rows = itertools.chain([first_row])

        lines: list[str] = []
        for row in data_rows:
            if len(lines) >= _MAX_ROWS:
                return "too_many_rows"

            cells = [str(c).strip() if c is not None else "" for c in row]
            if not any(cells):
                continue

            if headers:
                parts = [
                    f"{headers[i] if i < len(headers) else f'Столбец {i + 1}'}: {v}"
                    for i, v in enumerate(cells)
                    if v
                ]
                if parts:
                    lines.append(" | ".join(parts))
            else:
                non_empty = [c for c in cells if c]
                if non_empty:
                    lines.append(" \u2014 ".join(non_empty))
        return lines
    finally:
        wb.close()


@router.message(PriceInputFSM.file_upload, F.document)
async def process_excel(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Process uploaded Excel file (E09: max 1000 rows, 5 MB)."""
    doc = message.document
    if not doc:
        await message.answer(S.FILE_NOT_FOUND)
        return

    filename = doc.file_name or ""
    if not filename.lower().endswith(".xlsx"):
        await message.answer(S.PRICES_EXCEL_WRONG_FORMAT)
        return

    if doc.file_size and doc.file_size > _MAX_FILE_SIZE:
        size_mb = doc.file_size / (1024 * 1024)
        await message.answer(S.PRICES_EXCEL_TOO_BIG.format(size_mb=size_mb))
        return

    bot = message.bot
    if not bot:
        await message.answer(S.ERROR_INTERNAL)
        return

    file_bytes_io = await bot.download(doc)
    if not file_bytes_io:
        await message.answer(S.FILE_DOWNLOAD_ERROR)
        return

    try:
        result = parse_excel_rows(file_bytes_io.read())
    except Exception:
        log.exception("excel_parse_error")
        await state.clear()
        await message.answer(S.PRICES_EXCEL_READ_ERROR, reply_markup=menu_kb())
        return

    if result == "empty":
        await state.clear()
        await message.answer(S.PRICES_EXCEL_EMPTY, reply_markup=menu_kb())
        return

    if result == "too_many_rows":
        await state.clear()
        await message.answer(f"{E.WARNING} Максимум {_MAX_ROWS} строк.", reply_markup=menu_kb())
        return

    lines = result
    if not lines:
        await state.clear()
        await message.answer(S.PRICES_EXCEL_NO_DATA, reply_markup=menu_kb())
        return

    data = await state.get_data()
    cat_id = int(data["prices_cat_id"])
    await state.clear()

    cat_svc = category_service_factory(db)
    prices_text = "\n".join(lines)
    updated = await cat_svc.update_prices(cat_id, user.id, prices_text)
    if not updated:
        await message.answer(S.CATEGORY_NOT_FOUND, reply_markup=menu_kb())
        return

    log.info("prices_updated_excel", category_id=cat_id, lines=len(lines), user_id=user.id)

    safe_name = html.escape(updated.name)
    count = len(lines)

    result_text = (
        Screen(E.PRICE, f"ЦЕНЫ \u2014 {safe_name}")
        .blank()
        .line(f"{E.CHECK} {S.PRICES_EXCEL_UPLOADED.format(count=count)}")
        .hint(S.PRICES_HINT)
        .build()
    )
    await message.answer(result_text, reply_markup=prices_kb(cat_id, has_prices=True))


# ---------------------------------------------------------------------------
# Delete prices
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^prices:\d+:delete$"))
async def delete_prices(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Delete prices (set to NULL)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cb_data = safe_callback_data(callback)
    cat_id = int(cb_data.split(":")[1])
    cat_svc = category_service_factory(db)
    category = await cat_svc.get_owned_category(cat_id, user.id)

    if not category:
        await callback.answer(S.CATEGORY_NOT_FOUND, show_alert=True)
        return

    await cat_svc.clear_prices(cat_id, user.id)

    log.info("prices_deleted", category_id=cat_id, user_id=user.id)

    await _show_prices_screen(msg, category.id, category.name, None)
    await callback.answer(S.PRICES_DELETED)


# ---------------------------------------------------------------------------
# Cancel handler (inline button)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^price:\d+:cancel$"))
async def cancel_prices_inline(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Cancel price input via inline button — return to category card."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cb_data = safe_callback_data(callback)
    cat_id = int(cb_data.split(":")[1])
    await state.clear()

    cat_svc = category_service_factory(db)
    category = await cat_svc.get_owned_category(cat_id, user.id)
    if category:
        await safe_edit_text(msg, 
            f"<b>{html.escape(category.name)}</b>",
            reply_markup=category_card_kb(cat_id, category.project_id),
        )
        await callback.answer()
        return

    await safe_edit_text(msg, S.PRICES_CANCELLED, reply_markup=menu_kb())
    await callback.answer()
