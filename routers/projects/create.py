"""ProjectCreateFSM and ProjectEditFSM handlers."""

import html
import time

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_edit_text, safe_message
from bot.service_factory import ProjectServiceFactory
from bot.validators import URL_RE
from db.client import SupabaseClient
from db.models import Project, ProjectCreate, ProjectUpdate, User
from keyboards.inline import cancel_kb, menu_kb, project_created_kb, project_edit_kb
from services.projects import MAX_PROJECTS_PER_USER

log = structlog.get_logger()
router = Router()


def _project_completed(project: Project) -> dict[str, bool]:
    """Build ``completed`` dict for project_edit_kb checkmarks."""
    return {
        "name": bool(project.name),
        "company_name": bool(project.company_name),
        "specialization": bool(project.specialization),
        "description": bool(project.description),
        "advantages": bool(project.advantages),
        "experience": bool(project.experience),
        "website_url": bool(project.website_url),
        "company_city": bool(project.company_city),
        "company_phone": bool(project.company_phone),
        "company_email": bool(project.company_email),
        "company_address": bool(project.company_address),
    }


# ---------------------------------------------------------------------------
# FSM definitions (FSM_SPEC.md section 1)
# ---------------------------------------------------------------------------


class ProjectCreateFSM(StatesGroup):
    name = State()


class ProjectEditFSM(StatesGroup):
    field_value = State()


# ---------------------------------------------------------------------------
# Field metadata for edit
# ---------------------------------------------------------------------------


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis for display."""
    return text[:max_len] + "…" if len(text) > max_len else text


_FIELD_LABELS: dict[str, str] = {
    "name": "название проекта",
    "company_name": "название компании",
    "specialization": "специализацию",
    "website_url": "URL сайта",
    "description": "описание компании",
    "advantages": "преимущества",
    "experience": "опыт работы",
    "company_city": "город",
    "company_address": "адрес",
    "company_phone": "телефон",
    "company_email": "email",
}

_FIELD_LIMITS: dict[str, tuple[int, int]] = {
    "name": (2, 100),
    "company_name": (2, 255),
    "specialization": (2, 500),
    "website_url": (0, 500),
    "description": (10, 2000),
    "advantages": (5, 1000),
    "experience": (2, 500),
    "company_city": (2, 100),
    "company_address": (2, 255),
    "company_phone": (5, 30),
    "company_email": (5, 100),
}


# ---------------------------------------------------------------------------
# ProjectCreateFSM
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "project:create")
async def start_create(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Start project creation flow."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    # H17: enforce project limit per user
    proj_svc = project_service_factory(db)
    under_limit = await proj_svc.check_project_limit(user.id)
    if not under_limit:
        await callback.answer(
            f"Достигнут лимит проектов ({MAX_PROJECTS_PER_USER}).",
            show_alert=True,
        )
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(ProjectCreateFSM.name)
    await state.update_data(last_update_time=time.time())

    await msg.answer(
        "Как назовём проект?\nЭто внутреннее имя для вашего удобства.\n\n<i>Пример: Мебель Комфорт</i>",
        reply_markup=cancel_kb("project:create:cancel"),
    )
    await callback.answer()


@router.message(ProjectCreateFSM.name, F.text)
async def process_name(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Single step: project name (2-100 chars) -> create project."""
    text = (message.text or "").strip()

    if text == "Отмена":
        await state.clear()
        await message.answer("Создание проекта отменено.", reply_markup=menu_kb())
        return

    if len(text) < 2 or len(text) > 100:
        await message.answer("Название должно быть от 2 до 100 символов. Попробуйте ещё раз.")
        return

    await state.clear()

    proj_svc = project_service_factory(db)
    project = await proj_svc.create_project(
        ProjectCreate(user_id=user.id, name=text, company_name=text)
    )

    if not project:
        await message.answer("Достигнут лимит проектов.", reply_markup=menu_kb())
        return

    safe_name = html.escape(project.name)
    await message.answer(
        f"Проект «{safe_name}» создан!",
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
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show project edit screen with field buttons."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(project_id, user.id)
    if not project:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    text = _build_edit_text(project)
    await safe_edit_text(msg, text, reply_markup=project_edit_kb(project_id, _project_completed(project)))
    await callback.answer()


def _build_edit_text(project: Project) -> str:
    """Build edit screen text with current field values."""
    fields = [
        ("Название", project.name),
        ("Компания", project.company_name),
        ("Специализация", project.specialization),
        ("Сайт", project.website_url or "—"),
        ("Описание", _truncate(project.description, 100) if project.description else "—"),
        ("Преимущества", _truncate(project.advantages, 100) if project.advantages else "—"),
        ("Опыт", _truncate(project.experience, 100) if project.experience else "—"),
        ("Город", project.company_city or "—"),
        ("Адрес", project.company_address or "—"),
        ("Телефон", project.company_phone or "—"),
        ("Email", project.company_email or "—"),
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
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Start editing a specific field — enter ProjectEditFSM."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    project_id = int(parts[1])
    field = parts[3]

    if field not in _FIELD_LABELS:
        await callback.answer("Неизвестное поле.", show_alert=True)
        return

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(project_id, user.id)
    if not project:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(ProjectEditFSM.field_value)
    await state.update_data(
        last_update_time=time.time(),
        edit_project_id=project_id,
        edit_field=field,
    )

    label = _FIELD_LABELS[field]
    current = getattr(project, field, None) or "—"
    await msg.answer(
        f"Введите новое значение для поля «{label}».\nТекущее: {html.escape(str(current))}",
        reply_markup=cancel_kb("project:edit:cancel"),
    )
    await callback.answer()


@router.message(ProjectEditFSM.field_value, F.text)
async def process_field_value(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Process new field value and save."""
    text = (message.text or "").strip()

    proj_svc = project_service_factory(db)

    if text == "Отмена":
        data = await state.get_data()
        project_id = data.get("edit_project_id")
        await state.clear()
        if project_id:
            project = await proj_svc.get_owned_project(int(project_id), user.id)
            if project:
                edit_text = _build_edit_text(project)
                await message.answer(
                    edit_text,
                    reply_markup=project_edit_kb(int(project_id), _project_completed(project)),
                )
                return
        await message.answer("Редактирование отменено.", reply_markup=menu_kb())
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

    # Ownership-verified update
    update_data = ProjectUpdate(**{field: text or None})  # type: ignore[arg-type]
    project = await proj_svc.update_project(project_id, user.id, update_data)

    if project:
        label = _FIELD_LABELS.get(field, field)
        edit_text = f"Поле «{label}» обновлено.\n\n" + _build_edit_text(project)
        await message.answer(edit_text, reply_markup=project_edit_kb(project_id, _project_completed(project)))
    else:
        await message.answer("\u26a0\ufe0f Ошибка обновления. Попробуйте позже.", reply_markup=menu_kb())

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
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    await state.clear()
    await safe_edit_text(msg, "Создание проекта отменено.", reply_markup=menu_kb())
    await callback.answer()


@router.callback_query(F.data == "project:edit:cancel")
async def cancel_edit(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Cancel project field edit via inline button — return to edit screen."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    project_id = data.get("edit_project_id")
    await state.clear()

    if project_id:
        proj_svc = project_service_factory(db)
        project = await proj_svc.get_owned_project(int(project_id), user.id)
        if project:
            edit_text = _build_edit_text(project)
            await safe_edit_text(
                msg,
                edit_text,
                reply_markup=project_edit_kb(int(project_id), _project_completed(project)),
            )
            await callback.answer()
            return

    await safe_edit_text(msg, "Редактирование отменено.", reply_markup=menu_kb())
    await callback.answer()
