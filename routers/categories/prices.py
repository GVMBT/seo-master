"""Price list management: text input and Excel upload (UX_TOOLBOX.md section 11)."""

import html
import time
from io import BytesIO

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from bot.fsm_utils import ensure_no_active_fsm
from db.client import SupabaseClient
from db.models import Category, CategoryUpdate, Project, User
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from keyboards.inline import cancel_kb, category_card_kb, prices_kb

log = structlog.get_logger()
router = Router()

# Limits (E09)
_MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
_MAX_ROWS = 1000


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

    if prices:
        # Count lines for display
        lines = [ln for ln in prices.splitlines() if ln.strip()]
        count = len(lines)
        # Show first 10 lines as preview
        preview_lines = lines[:10]
        preview = "\n".join(f"  \u2022 {html.escape(ln)}" for ln in preview_lines)
        if count > 10:
            preview += f"\n  ... ещё {count - 10}"
        text = f"<b>Цены \u2014 {safe_name}</b>\n\nТекущий прайс ({count} позиций):\n{preview}"
    else:
        text = (
            f"<b>Цены \u2014 {safe_name}</b>\n\nПрайс-лист не загружен. Добавьте \u2014 в статьях будут реальные цены."
        )

    await message.edit_text(text, reply_markup=prices_kb(category_id, has_prices=bool(prices)))


async def _verify_category_ownership(
    category_id: int,
    user: User,
    db: SupabaseClient,
) -> tuple[CategoriesRepository, Category | None, Project | None]:
    """Load category and verify ownership. Returns (repo, category, project) or (repo, None, None)."""
    cats_repo = CategoriesRepository(db)
    category = await cats_repo.get_by_id(category_id)
    if not category:
        return cats_repo, None, None

    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(category.project_id)
    if not project or project.user_id != user.id:
        return cats_repo, None, None

    return cats_repo, category, project


# ---------------------------------------------------------------------------
# Show prices screen
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:\d+:prices$"))
async def show_prices(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show prices screen (UX_TOOLBOX.md section 11)."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    cats_repo = CategoriesRepository(db)
    category = await cats_repo.get_by_id(category_id)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(category.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    await _show_prices_screen(callback.message, category.id, category.name, category.prices)
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
) -> None:
    """Start text-based price input (section 11.1)."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category, _ = await _verify_category_ownership(cat_id, user, db)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await callback.message.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(PriceInputFSM.text_input)
    await state.update_data(last_update_time=time.time(), prices_cat_id=cat_id)

    await callback.message.answer(
        "Введите прайс-лист. Формат: Название \u2014 Цена\n"
        "Каждый товар с новой строки.\n\n"
        "<i>Пример:\n"
        "Кухня угловая \u00abМодена\u00bb \u2014 89 900 руб\n"
        "Стол обеденный \u00abЛофт\u00bb \u2014 24 500 руб</i>",
        reply_markup=cancel_kb(f"price:{cat_id}:cancel"),
    )
    await callback.answer()


@router.message(PriceInputFSM.text_input, F.text)
async def process_text(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Process text price input. Store as-is (plain text)."""
    text = (message.text or "").strip()

    if text == "Отмена":
        await state.clear()
        await message.answer("Ввод цен отменён.")
        return

    # Validate: at least 1 non-empty line
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        await message.answer(
            "Не найдено ни одной строки. Введите прайс в формате:\nНазвание \u2014 Цена\nКаждый товар с новой строки."
        )
        return

    if len(lines) > _MAX_ROWS:
        await message.answer(f"Максимум {_MAX_ROWS} строк. Сейчас: {len(lines)}.")
        return

    data = await state.get_data()
    cat_id = int(data["prices_cat_id"])
    await state.clear()

    cats_repo = CategoriesRepository(db)
    category = await cats_repo.get_by_id(cat_id)
    if not category:
        await message.answer("Категория не найдена.")
        return

    # Ownership re-check
    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(category.project_id)
    if not project or project.user_id != user.id:
        await message.answer("Категория не найдена.")
        return

    # Save as plain text
    prices_text = "\n".join(lines)
    await cats_repo.update(cat_id, CategoryUpdate(prices=prices_text))

    log.info("prices_updated_text", category_id=cat_id, lines=len(lines), user_id=user.id)

    safe_name = html.escape(category.name)
    count = len(lines)
    preview_lines = lines[:10]
    preview = "\n".join(f"  \u2022 {html.escape(ln)}" for ln in preview_lines)
    if count > 10:
        preview += f"\n  ... ещё {count - 10}"

    result_text = f"<b>Цены \u2014 {safe_name}</b>\n\nПрайс сохранён ({count} позиций):\n{preview}"
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
) -> None:
    """Start Excel-based price upload (section 11.2)."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category, _ = await _verify_category_ownership(cat_id, user, db)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await callback.message.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(PriceInputFSM.file_upload)
    await state.update_data(last_update_time=time.time(), prices_cat_id=cat_id)

    await callback.message.answer(
        "Загрузите Excel-файл (.xlsx) с прайсом.\nФормат: колонка A = название, колонка B = цена.",
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
        await message.answer("Загрузка отменена.")
        return

    await message.answer("Ожидается файл Excel (.xlsx). Для отмены напишите \u00abОтмена\u00bb.")


def parse_excel_rows(file_bytes: bytes) -> list[str] | str:
    """Parse Excel file into price lines. Returns list of lines or error string."""
    import openpyxl  # type: ignore[import-untyped]

    wb = openpyxl.load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
    try:
        ws = wb.active
        if ws is None:
            return "empty"

        lines: list[str] = []
        row_count = 0
        for row in ws.iter_rows(min_row=1, values_only=True):
            if not row or all(cell is None or str(cell).strip() == "" for cell in row):
                continue

            row_count += 1
            if row_count > _MAX_ROWS:
                return "too_many_rows"

            name = str(row[0]).strip() if len(row) > 0 and row[0] is not None else ""
            price = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
            desc = str(row[2]).strip() if len(row) > 2 and row[2] is not None else ""

            if not name:
                continue

            if desc:
                lines.append(f"{name} \u2014 {price} \u2014 {desc}")
            elif price:
                lines.append(f"{name} \u2014 {price}")
            else:
                lines.append(name)
        return lines
    finally:
        wb.close()


@router.message(PriceInputFSM.file_upload, F.document)
async def process_excel(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Process uploaded Excel file (E09: max 1000 rows, 5 MB)."""
    doc = message.document
    if not doc:
        await message.answer("Файл не найден. Загрузите .xlsx файл.")
        return

    filename = doc.file_name or ""
    if not filename.lower().endswith(".xlsx"):
        await message.answer("Неверный формат. Загрузите файл с расширением .xlsx.")
        return

    if doc.file_size and doc.file_size > _MAX_FILE_SIZE:
        size_mb = doc.file_size / (1024 * 1024)
        await message.answer(f"Файл слишком большой ({size_mb:.1f} МБ). Максимум 5 МБ.")
        return

    bot = message.bot
    if not bot:
        await message.answer("Внутренняя ошибка. Попробуйте позже.")
        return

    file_bytes_io = await bot.download(doc)
    if not file_bytes_io:
        await message.answer("Не удалось скачать файл. Попробуйте ещё раз.")
        return

    try:
        result = parse_excel_rows(file_bytes_io.read())
    except Exception:
        log.exception("excel_parse_error")
        await state.clear()
        await message.answer("Не удалось прочитать файл. Убедитесь, что это корректный .xlsx.")
        return

    if result == "empty":
        await state.clear()
        await message.answer("Файл пуст. Загрузите файл с данными.")
        return

    if result == "too_many_rows":
        await state.clear()
        await message.answer(f"Превышен лимит: максимум {_MAX_ROWS} строк (E09).")
        return

    lines = result
    if not lines:
        await state.clear()
        await message.answer("В файле не найдено данных. Колонка A = название, колонка B = цена.")
        return

    data = await state.get_data()
    cat_id = int(data["prices_cat_id"])
    await state.clear()

    cats_repo = CategoriesRepository(db)
    category = await cats_repo.get_by_id(cat_id)
    if not category:
        await message.answer("Категория не найдена.")
        return

    # Ownership re-check
    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(category.project_id)
    if not project or project.user_id != user.id:
        await message.answer("Категория не найдена.")
        return

    # Save as plain text
    prices_text = "\n".join(lines)
    await cats_repo.update(cat_id, CategoryUpdate(prices=prices_text))

    log.info("prices_updated_excel", category_id=cat_id, lines=len(lines), user_id=user.id)

    safe_name = html.escape(category.name)
    count = len(lines)
    preview_lines = lines[:10]
    preview = "\n".join(f"  \u2022 {html.escape(ln)}" for ln in preview_lines)
    if count > 10:
        preview += f"\n  ... ещё {count - 10}"

    result_text = f"<b>Цены \u2014 {safe_name}</b>\n\nПрайс загружен из Excel ({count} позиций):\n{preview}"
    await message.answer(result_text, reply_markup=prices_kb(cat_id, has_prices=True))


# ---------------------------------------------------------------------------
# Delete prices
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^prices:\d+:delete$"))
async def delete_prices(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Delete prices (set to NULL)."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    cats_repo = CategoriesRepository(db)
    category = await cats_repo.get_by_id(cat_id)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(category.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    # Use clear_prices to bypass exclude_none in update()
    await cats_repo.clear_prices(cat_id)

    log.info("prices_deleted", category_id=cat_id, user_id=user.id)

    await _show_prices_screen(callback.message, category.id, category.name, None)
    await callback.answer("Прайс удалён.")


# ---------------------------------------------------------------------------
# Cancel handler (inline button)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^price:\d+:cancel$"))
async def cancel_prices_inline(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Cancel price input via inline button — return to category card."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    await state.clear()

    _, category, project = await _verify_category_ownership(cat_id, user, db)
    if category and project:
        await callback.message.edit_text(
            f"<b>{html.escape(category.name)}</b>",
            reply_markup=category_card_kb(cat_id, category.project_id),
        )
        await callback.answer()
        return

    await callback.message.edit_text("Ввод цен отменён.")
    await callback.answer()
