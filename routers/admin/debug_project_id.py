"""Debug command /myprojectid — show project IDs and connections to admin.

Александр пишет /myprojectid в личке боту → видит свои проекты с их
числовым ID и список подключённых платформ. ID нужен для прописывания
в Railway env BAMBOODOM_ANNOUNCE_PROJECT_ID (services/announce/social.py).
"""

from __future__ import annotations

import structlog
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import get_settings
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import User
from db.repositories.connections import ConnectionsRepository
from db.repositories.projects import ProjectsRepository

log = structlog.get_logger()
router = Router()


@router.message(Command("myprojectid"))
async def my_project_id_handler(
    message: Message,
    user: User,
    db: SupabaseClient,
) -> None:
    """Только админ. Показывает проекты с их ID и подключения."""
    if user.role != "admin":
        return

    try:
        projects_repo = ProjectsRepository(db)
        projects = await projects_repo.get_by_user(user.id)
    except Exception as exc:
        log.exception("myprojectid_projects_failed")
        await message.answer(f"❌ Ошибка БД (projects): {exc}")
        return

    if not projects:
        await message.answer("📭 У вас нет проектов в БД.")
        return

    settings = get_settings()
    enc_key = settings.encryption_key.get_secret_value()
    conn_repo = ConnectionsRepository(db, CredentialManager(enc_key))

    parts: list[str] = ["<b>📋 Ваши проекты:</b>"]
    for project in projects:
        parts.append("")
        parts.append(f"• <b>{project.name}</b>")
        parts.append(f"  ID: <code>{project.id}</code>")

        try:
            conns = await conn_repo.get_list_by_project(project.id)
        except Exception as exc:
            log.warning("myprojectid_conn_failed", error=str(exc)[:120])
            parts.append(f"  ⚠️ connections error: {exc}")
            continue

        if not conns:
            parts.append("  (без подключений)")
            continue

        for conn in conns:
            platform = conn.get("platform_type") or "?"
            ident = conn.get("identifier") or "?"
            status = conn.get("status") or "active"
            mark = "✅" if status == "active" else "⛔"
            parts.append(f"  {mark} {platform}: {ident}")

    parts.append("")
    parts.append(
        "<i>Для автопоста в соцсети при AI-публикации скопируй ID "
        "нужного проекта и пропиши в Railway env "
        "BAMBOODOM_ANNOUNCE_PROJECT_ID.</i>"
    )

    await message.answer("\n".join(parts), parse_mode="HTML")
