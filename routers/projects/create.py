"""ProjectCreateFSM and ProjectEditFSM handlers."""

import html
import time

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_message
from bot.service_factory import ProjectServiceFactory
from bot.validators import URL_RE
from db.client import SupabaseClient
from db.models import Project, ProjectCreate, ProjectUpdate, User
from keyboards.inline import cancel_kb, menu_kb, project_created_kb, project_edit_kb
from services.projects import MAX_PROJECTS_PER_USER

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
    "timezone": "часовой пояс",
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
    "timezone": (3, 50),
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
) -> None:
    """Step 1: project name (2-100 chars)."""
    text = (message.text or "").strip()

    if text == "Отмена":
        await state.clear()
        await message.answer("Создание проекта отменено.", reply_markup=menu_kb())
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
        await message.answer("Создание проекта отменено.", reply_markup=menu_kb())
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
        await message.answer("Создание проекта отменено.", reply_markup=menu_kb())
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
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Step 4: website URL (optional, skippable)."""
    text = (message.text or "").strip()

    if text == "Отмена":
        await state.clear()
        await message.answer("Создание проекта отменено.", reply_markup=menu_kb())
        return

    website_url: str | None = None
    if text not in ("Пропустить", "нет", "-", ""):
        if not URL_RE.match(text):
            await message.answer("Некорректный URL. Попробуйте ещё раз или нажмите «Пропустить».")
            return
        website_url = text if text.startswith("http") else f"https://{text}"

    data = await state.get_data()
    await state.clear()

    proj_svc = project_service_factory(db)
    project = await proj_svc.create_project(
        ProjectCreate(
            user_id=user.id,
            name=data["name"],
            company_name=data["company_name"],
            specialization=data["specialization"],
            website_url=website_url,
        )
    )

    if not project:
        await message.answer("Достигнут лимит проектов.", reply_markup=menu_kb())
        return

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
    await msg.edit_text(text, reply_markup=project_edit_kb(project_id))
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
                await message.answer(edit_text, reply_markup=project_edit_kb(int(project_id)))
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
    update_data = ProjectUpdate(**{field: text or None})
    project = await proj_svc.update_project(project_id, user.id, update_data)

    if project:
        label = _FIELD_LABELS.get(field, field)
        edit_text = f"Поле «{label}» обновлено.\n\n" + _build_edit_text(project)
        await message.answer(edit_text, reply_markup=project_edit_kb(project_id))
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
    await msg.edit_text("Создание проекта отменено.", reply_markup=menu_kb())
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
            await msg.edit_text(edit_text, reply_markup=project_edit_kb(int(project_id)))
            await callback.answer()
            return

    await msg.edit_text("Редактирование отменено.", reply_markup=menu_kb())
    await callback.answer()
