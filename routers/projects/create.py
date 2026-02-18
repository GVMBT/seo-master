"""ProjectCreateFSM and ProjectEditFSM handlers."""

import html
import time

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from bot.fsm_utils import ensure_no_active_fsm
from bot.validators import URL_RE
from db.client import SupabaseClient
from db.models import Project, ProjectCreate, ProjectUpdate, User
from db.repositories.projects import ProjectsRepository
from keyboards.inline import cancel_kb, project_created_kb, project_edit_kb

log = structlog.get_logger()
router = Router()


# ---------------------------------------------------------------------------
# FSM definitions (FSM_SPEC.md section 1)
# ---------------------------------------------------------------------------


class ProjectCreateFSM(StatesGroup):
    name = State()
    company_name = State()
    specialization = State()
    website_url = State()


class ProjectEditFSM(StatesGroup):
    field_value = State()


# ---------------------------------------------------------------------------
# Field metadata for edit
# ---------------------------------------------------------------------------

_FIELD_LABELS: dict[str, str] = {
    "name": "название проекта",
    "company_name": "название компании",
    "specialization": "специализацию",
    "website_url": "URL сайта",
    "company_city": "город",
    "company_address": "адрес",
    "company_phone": "телефон",
    "company_email": "email",
    "timezone": "часовой пояс",
}

_FIELD_LIMITS: dict[str, tuple[int, int]] = {
    "name": (2, 100),
    "company_name": (2, 255),
    "specialization": (2, 500),
    "website_url": (0, 500),
    "company_city": (2, 100),
    "company_address": (2, 255),
    "company_phone": (5, 30),
    "company_email": (5, 100),
    "timezone": (3, 50),
}


# ---------------------------------------------------------------------------
# ProjectCreateFSM
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "project:create")
async def start_create(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Start project creation flow."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await callback.message.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(ProjectCreateFSM.name)
    await state.update_data(last_update_time=time.time())

    await callback.message.answer(
        "Как назовём проект?\nЭто внутреннее имя для вашего удобства.\n\n<i>Пример: Мебель Комфорт</i>",
        reply_markup=cancel_kb("project:create:cancel"),
    )
    await callback.answer()


@router.message(ProjectCreateFSM.name, F.text)
async def process_name(
    message: Message,
    state: FSMContext,
) -> None:
    """Step 1: project name (2-100 chars)."""
    text = (message.text or "").strip()

    if text == "Отмена":
        await state.clear()
        await message.answer("Создание отменено.")
        return

    if len(text) < 2 or len(text) > 100:
        await message.answer("Название должно быть от 2 до 100 символов. Попробуйте ещё раз.")
        return

    await state.update_data(name=text)
    await state.set_state(ProjectCreateFSM.company_name)
    await message.answer(
        "Как называется ваша компания?\nБудет использоваться в текстах.\n\n<i>Пример: ООО Мебель Комфорт</i>",
        reply_markup=cancel_kb("project:create:cancel"),
    )


@router.message(ProjectCreateFSM.company_name, F.text)
async def process_company_name(
    message: Message,
    state: FSMContext,
) -> None:
    """Step 2: company name (2-255 chars)."""
    text = (message.text or "").strip()

    if text == "Отмена":
        await state.clear()
        await message.answer("Создание отменено.")
        return

    if len(text) < 2 or len(text) > 255:
        await message.answer("Название компании: от 2 до 255 символов.")
        return

    await state.update_data(company_name=text)
    await state.set_state(ProjectCreateFSM.specialization)
    await message.answer(
        "Опишите специализацию в 2-3 словах.\n\n<i>Пример: мебель на заказ</i>",
        reply_markup=cancel_kb("project:create:cancel"),
    )


@router.message(ProjectCreateFSM.specialization, F.text)
async def process_specialization(
    message: Message,
    state: FSMContext,
) -> None:
    """Step 3: specialization (2-500 chars)."""
    text = (message.text or "").strip()

    if text == "Отмена":
        await state.clear()
        await message.answer("Создание отменено.")
        return

    if len(text) < 2 or len(text) > 500:
        await message.answer("Специализация: от 2 до 500 символов.")
        return

    await state.update_data(specialization=text)
    await state.set_state(ProjectCreateFSM.website_url)
    await message.answer(
        "Адрес вашего сайта (необязательно).\nЕсли нет — напишите «Пропустить».\n\n<i>Пример: comfort-mebel.ru</i>",
        reply_markup=cancel_kb("project:create:cancel"),
    )


@router.message(ProjectCreateFSM.website_url, F.text)
async def process_website_url(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Step 4: website URL (optional, skippable)."""
    text = (message.text or "").strip()

    if text == "Отмена":
        await state.clear()
        await message.answer("Создание отменено.")
        return

    website_url: str | None = None
    if text not in ("Пропустить", "нет", "-", ""):
        if not URL_RE.match(text):
            await message.answer("Некорректный URL. Попробуйте ещё раз или нажмите «Пропустить».")
            return
        website_url = text if text.startswith("http") else f"https://{text}"

    data = await state.get_data()
    await state.clear()

    repo = ProjectsRepository(db)
    project = await repo.create(
        ProjectCreate(
            user_id=user.id,
            name=data["name"],
            company_name=data["company_name"],
            specialization=data["specialization"],
            website_url=website_url,
        )
    )

    safe_name = html.escape(project.name)
    await message.answer(
        f"Проект «{safe_name}» создан!\nТеперь подключите платформу для публикации.",
        reply_markup=project_created_kb(project.id),
    )

    log.info("project_created", project_id=project.id, user_id=user.id)


# ---------------------------------------------------------------------------
# ProjectEditFSM
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:\d+:edit$"))
async def show_edit_screen(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show project edit screen with field buttons."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    repo = ProjectsRepository(db)
    project = await repo.get_by_id(project_id)

    if not project or project.user_id != user.id:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    text = _build_edit_text(project)
    await callback.message.edit_text(text, reply_markup=project_edit_kb(project_id))
    await callback.answer()


def _build_edit_text(project: Project) -> str:
    """Build edit screen text with current field values."""
    fields = [
        ("Название", project.name),
        ("Компания", project.company_name),
        ("Специализация", project.specialization),
        ("Сайт", project.website_url or "—"),
        ("Город", project.company_city or "—"),
        ("Адрес", project.company_address or "—"),
        ("Телефон", project.company_phone or "—"),
        ("Email", project.company_email or "—"),
        ("Часовой пояс", project.timezone),
    ]

    safe_name = html.escape(project.name)
    lines = [f"{safe_name} — Редактирование\n"]
    for label, value in fields:
        lines.append(f"{label}: {html.escape(str(value))}")
    return "\n".join(lines)


@router.callback_query(F.data.regexp(r"^project:\d+:edit:\w+$"))
async def start_field_edit(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Start editing a specific field — enter ProjectEditFSM."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    project_id = int(parts[1])
    field = parts[3]

    if field not in _FIELD_LABELS:
        await callback.answer("Неизвестное поле.", show_alert=True)
        return

    repo = ProjectsRepository(db)
    project = await repo.get_by_id(project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await callback.message.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(ProjectEditFSM.field_value)
    await state.update_data(
        last_update_time=time.time(),
        edit_project_id=project_id,
        edit_field=field,
    )

    label = _FIELD_LABELS[field]
    current = getattr(project, field, None) or "—"
    await callback.message.answer(
        f"Введите новое значение для поля «{label}».\n"
        f"Текущее: {html.escape(str(current))}",
        reply_markup=cancel_kb("project:edit:cancel"),
    )
    await callback.answer()


@router.message(ProjectEditFSM.field_value, F.text)
async def process_field_value(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Process new field value and save."""
    text = (message.text or "").strip()

    if text == "Отмена":
        data = await state.get_data()
        project_id = data.get("edit_project_id")
        await state.clear()
        if project_id:
            repo = ProjectsRepository(db)
            project = await repo.get_by_id(int(project_id))
            if project and project.user_id == user.id:
                edit_text = _build_edit_text(project)
                await message.answer(edit_text, reply_markup=project_edit_kb(int(project_id)))
                return
        await message.answer("Редактирование отменено.")
        return

    data = await state.get_data()
    project_id = int(data["edit_project_id"])
    field = str(data["edit_field"])

    # Validate length
    min_len, max_len = _FIELD_LIMITS.get(field, (1, 500))

    # URL validation for website_url
    if field == "website_url":
        if text.lower() in ("нет", "-", ""):
            text = ""
        elif not URL_RE.match(text):
            await message.answer("Некорректный URL. Попробуйте ещё раз.")
            return
        else:
            if not text.startswith("http"):
                text = f"https://{text}"
            if len(text) > max_len:
                await message.answer(f"URL слишком длинный (макс. {max_len} символов).")
                return
    elif len(text) < min_len or len(text) > max_len:
        await message.answer(f"Значение: от {min_len} до {max_len} символов.")
        return

    await state.clear()

    # Ownership check
    repo = ProjectsRepository(db)
    project = await repo.get_by_id(project_id)
    if not project or project.user_id != user.id:
        await message.answer("Проект не найден.")
        return

    # Build update
    update_data = ProjectUpdate(**{field: text or None})
    project = await repo.update(project_id, update_data)

    if project:
        label = _FIELD_LABELS.get(field, field)
        edit_text = f"Поле «{label}» обновлено.\n\n" + _build_edit_text(project)
        await message.answer(edit_text, reply_markup=project_edit_kb(project_id))
    else:
        await message.answer("Ошибка обновления.")

    log.info("project_field_updated", project_id=project_id, field=field, user_id=user.id)


# ---------------------------------------------------------------------------
# Cancel handlers (inline button)
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "project:create:cancel")
async def cancel_create(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Cancel project creation via inline button."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    await state.clear()
    await callback.message.edit_text("Создание проекта отменено.")
    await callback.answer()


@router.callback_query(F.data == "project:edit:cancel")
async def cancel_edit(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Cancel project field edit via inline button — return to edit screen."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    data = await state.get_data()
    project_id = data.get("edit_project_id")
    await state.clear()

    if project_id:
        repo = ProjectsRepository(db)
        project = await repo.get_by_id(int(project_id))
        if project and project.user_id == user.id:
            edit_text = _build_edit_text(project)
            await callback.message.edit_text(edit_text, reply_markup=project_edit_kb(int(project_id)))
            await callback.answer()
            return

    await callback.message.edit_text("Редактирование отменено.")
    await callback.answer()
