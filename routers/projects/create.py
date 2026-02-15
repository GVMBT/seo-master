"""Router: project create FSM (4 steps) + edit FSM (single field)."""

import re
import typing

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.fsm_utils import ensure_no_active_fsm
from db.client import SupabaseClient
from db.models import ProjectCreate, ProjectUpdate, User
from db.repositories.projects import ProjectsRepository
from keyboards.inline import (
    PROJECT_FIELDS,
    project_card_kb,
    project_edit_fields_kb,
)
from keyboards.reply import cancel_kb, main_menu, skip_cancel_kb
from routers._helpers import guard_callback_message
from routers.projects.card import _format_project_card, _get_project_or_notify

router = Router(name="projects_create")


# ---------------------------------------------------------------------------
# FSM definitions (per routers/CLAUDE.md: FSM defined in router file)
# ---------------------------------------------------------------------------


class ProjectCreateFSM(StatesGroup):
    name = State()
    company_name = State()
    specialization = State()
    website_url = State()


class ProjectEditFSM(StatesGroup):
    field_value = State()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[\w\s\-.,!?()\"'«»/&#@:;№]+$")
_URL_RE = re.compile(r"^https?://\S+$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^[\d\s()+\-]{5,20}$")
_WHITESPACE_ONLY_RE = re.compile(r"^\s+$")

_FIELD_NAMES = {name for name, _ in PROJECT_FIELDS}
_FIELD_LABELS = {name: label for name, label in PROJECT_FIELDS}


def _validate_name(value: str) -> str | None:
    if len(value.strip()) < 2 or len(value) > 100:
        return "Введите название от 2 до 100 символов."
    if not _NAME_RE.match(value):
        return "Название содержит недопустимые символы."
    return None


def _validate_company_name(value: str) -> str | None:
    return "Введите название компании от 2 до 200 символов." if len(value) < 2 or len(value) > 200 else None


def _validate_specialization(value: str) -> str | None:
    return "Опишите подробнее (от 5 до 500 символов)." if len(value) < 5 or len(value) > 500 else None


def _validate_website_url(value: str) -> str | None:
    return "Введите корректный URL (https://...)." if not _URL_RE.match(value) else None


def _validate_email(value: str) -> str | None:
    return "Введите корректный email." if not _EMAIL_RE.match(value) else None


def _validate_phone(value: str) -> str | None:
    return "Введите корректный номер телефона." if not _PHONE_RE.match(value) else None


def _validate_generic(value: str) -> str | None:
    return "Введите значение от 2 до 500 символов." if len(value) < 2 or len(value) > 500 else None


_FIELD_VALIDATORS: dict[str, typing.Callable[[str], str | None]] = {
    "name": _validate_name,
    "company_name": _validate_company_name,
    "specialization": _validate_specialization,
    "website_url": _validate_website_url,
    "company_email": _validate_email,
    "company_phone": _validate_phone,
}


def _validate_field(field_name: str, value: str) -> str | None:
    """Validate a project field value. Returns error message or None."""
    if _WHITESPACE_ONLY_RE.match(value):
        return "Введите непустое значение."
    validator = _FIELD_VALIDATORS.get(field_name, _validate_generic)
    return validator(value)


# ---------------------------------------------------------------------------
# Create project FSM (4 steps)
# ---------------------------------------------------------------------------


_MAX_PROJECTS_PER_USER = 20


@router.callback_query(F.data == "projects:new")
async def cb_project_new(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Start project creation FSM.

    TODO P4.11: [Прервать] (save progress) button requires a draft mechanism
    not yet in the DB schema. Deferred to a later phase.
    """
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    # Enforce project limit (S4)
    count = await ProjectsRepository(db).get_count_by_user(user.id)
    if count >= _MAX_PROJECTS_PER_USER:
        await callback.answer(f"Достигнут лимит: {_MAX_PROJECTS_PER_USER} проектов.", show_alert=True)
        return

    # Auto-clear any active FSM (P4.11, FSM conflict resolution)
    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(ProjectCreateFSM.name)
    await msg.answer(
        "Шаг 1/4. Введите название проекта (2-100 символов):",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(ProjectCreateFSM.name, F.text)
async def fsm_project_name(message: Message, state: FSMContext) -> None:
    """FSM step 1: project name."""
    error = _validate_field("name", message.text)  # type: ignore[arg-type]
    if error:
        await message.answer(error)
        return
    await state.update_data(name=message.text)
    await state.set_state(ProjectCreateFSM.company_name)
    await message.answer("Шаг 2/4. Введите название компании:")


@router.message(ProjectCreateFSM.company_name, F.text)
async def fsm_project_company(message: Message, state: FSMContext) -> None:
    """FSM step 2: company name."""
    error = _validate_field("company_name", message.text)  # type: ignore[arg-type]
    if error:
        await message.answer(error)
        return
    await state.update_data(company_name=message.text)
    await state.set_state(ProjectCreateFSM.specialization)
    await message.answer("Шаг 3/4. Опишите специализацию компании (мин. 5 символов):")


@router.message(ProjectCreateFSM.specialization, F.text)
async def fsm_project_spec(message: Message, state: FSMContext) -> None:
    """FSM step 3: specialization."""
    error = _validate_field("specialization", message.text)  # type: ignore[arg-type]
    if error:
        await message.answer(error)
        return
    await state.update_data(specialization=message.text)
    await state.set_state(ProjectCreateFSM.website_url)
    await message.answer(
        "Шаг 4/4. Введите URL сайта или нажмите «Пропустить»:",
        reply_markup=skip_cancel_kb(),
    )


@router.message(ProjectCreateFSM.website_url, F.text)
async def fsm_project_url(message: Message, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """FSM step 4: website URL (optional, skippable)."""
    url: str | None = None
    if message.text != "Пропустить":
        error = _validate_field("website_url", message.text)  # type: ignore[arg-type]
        if error:
            await message.answer(error)
            return
        url = message.text

    data = await state.get_data()
    await state.clear()

    project = await ProjectsRepository(db).create(
        ProjectCreate(
            user_id=user.id,
            name=data["name"],
            company_name=data["company_name"],
            specialization=data["specialization"],
            website_url=url,
        )
    )
    await message.answer(
        _format_project_card(project) + "\n\nЗаполните остальные данные (город, телефон, соцсети)"
        " в разделе «Редактировать данные» для лучшего качества контента.",
        reply_markup=project_card_kb(project).as_markup(),
    )
    # Restore reply keyboard after FSM completion (I3)
    await message.answer("\u200b", reply_markup=main_menu(is_admin=user.role == "admin"))


# ---------------------------------------------------------------------------
# Edit project fields
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:(\d+):edit$"))
async def cb_project_edit(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show editable fields list."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _get_project_or_notify(project_id, user.id, db, callback)
    if not project:
        return
    await msg.edit_text(
        "Выберите поле для редактирования:",
        reply_markup=project_edit_fields_kb(project).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^project:(\d+):field:(\w+)$"))
async def cb_project_field(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Start edit FSM for a specific field."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    parts = callback.data.split(":")  # type: ignore[union-attr]
    project_id = int(parts[1])
    field_name = parts[3]

    if field_name not in _FIELD_NAMES:
        await callback.answer("Неизвестное поле.", show_alert=True)
        return

    project = await _get_project_or_notify(project_id, user.id, db, callback)
    if not project:
        return

    label = _FIELD_LABELS[field_name]

    # Auto-clear any active FSM (P4.11, FSM conflict resolution)
    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(ProjectEditFSM.field_value)
    await state.update_data(project_id=project_id, field_name=field_name)
    await msg.answer(
        f"Введите новое значение для поля «{label}»:",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(ProjectEditFSM.field_value, F.text)
async def fsm_project_field_value(message: Message, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """FSM: validate and save edited field value."""
    data = await state.get_data()
    field_name = data["field_name"]
    project_id = data["project_id"]

    error = _validate_field(field_name, message.text)  # type: ignore[arg-type]
    if error:
        await message.answer(error)
        return

    await state.clear()

    repo = ProjectsRepository(db)
    updated = await repo.update(project_id, ProjectUpdate(**{field_name: message.text}))
    if updated is None:
        await message.answer("Проект не найден.", reply_markup=main_menu(is_admin=user.role == "admin"))
        return

    await message.answer(
        _format_project_card(updated),
        reply_markup=project_card_kb(updated).as_markup(),
    )
    # Restore reply keyboard after FSM completion (I3)
    await message.answer("\u200b", reply_markup=main_menu(is_admin=user.role == "admin"))
