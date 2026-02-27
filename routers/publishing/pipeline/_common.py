"""Shared FSM and helpers for Article/Social pipeline modules.

Extracted to avoid circular imports between article.py, readiness.py, and social/.
"""

from __future__ import annotations

import json
import random
from typing import Literal

import structlog
from aiogram.fsm.state import State, StatesGroup

from bot.config import get_settings
from cache.client import RedisClient
from cache.keys import PIPELINE_CHECKPOINT_TTL, CacheKeys
from db.client import SupabaseClient
from db.models import User
from db.repositories.categories import CategoriesRepository
from services.tokens import TokenService

log = structlog.get_logger()

# Pipeline type literal for checkpoint & ReadinessService
PipelineType = Literal["article", "social"]

# ---------------------------------------------------------------------------
# FSM (FSM_SPEC.md §1 — ArticlePipelineFSM, 25 states)
# ---------------------------------------------------------------------------


class ArticlePipelineFSM(StatesGroup):
    """Article pipeline FSM — 25 states covering 8 steps + inline sub-flows."""

    # Step 1: Project selection
    select_project = State()
    create_project_name = State()
    create_project_company = State()
    create_project_spec = State()
    create_project_url = State()

    # Step 2: WP connection check
    select_wp = State()
    connect_wp_url = State()
    connect_wp_login = State()
    connect_wp_password = State()

    # Step 3: Category selection
    select_category = State()
    create_category_name = State()

    # Step 4: Readiness check + inline sub-flows
    readiness_check = State()
    readiness_keywords_products = State()
    readiness_keywords_geo = State()
    readiness_keywords_qty = State()
    readiness_keywords_generating = State()
    readiness_description = State()
    readiness_prices = State()
    readiness_photos = State()

    # Step 5-8: Confirmation, generation, preview, result
    confirm_cost = State()
    generating = State()
    preview = State()
    publishing = State()
    result = State()
    regenerating = State()


# ---------------------------------------------------------------------------
# FSM (FSM_SPEC.md §2.2 — SocialPipelineFSM, 28 states)
# ---------------------------------------------------------------------------


class SocialPipelineFSM(StatesGroup):
    """Social pipeline FSM — 28 states for social post creation + cross-posting."""

    # Step 1: Project selection
    select_project = State()
    create_project_name = State()
    create_project_company = State()
    create_project_spec = State()
    create_project_url = State()

    # Step 2: Connection selection (TG/VK/Pinterest)
    select_connection = State()
    connect_tg_channel = State()
    connect_tg_token = State()
    connect_tg_verify = State()
    connect_vk_token = State()
    connect_vk_group = State()
    connect_pinterest_oauth = State()
    connect_pinterest_board = State()

    # Step 3: Category selection
    select_category = State()
    create_category_name = State()

    # Step 4: Readiness check (simplified: keywords + description only)
    readiness_check = State()
    readiness_keywords_products = State()
    readiness_keywords_geo = State()
    readiness_keywords_qty = State()
    readiness_keywords_generating = State()
    readiness_description = State()

    # Steps 5-7: Confirm, generate, review, publish
    confirm_cost = State()
    generating = State()
    review = State()
    publishing = State()
    regenerating = State()

    # Cross-posting (E52)
    cross_post_review = State()
    cross_post_publishing = State()


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------


async def save_checkpoint(
    redis: RedisClient,
    user_id: int,
    *,
    current_step: str,
    pipeline_type: PipelineType = "article",
    project_id: int | None = None,
    project_name: str | None = None,
    connection_id: int | None = None,
    category_id: int | None = None,
    **extra: object,
) -> None:
    """Save pipeline checkpoint to Redis (UX_PIPELINE.md §10.3).

    Single key per user (§8.7: one pipeline at a time).
    pipeline_type distinguishes article vs social for resume routing.
    """
    data: dict[str, object] = {
        "pipeline_type": pipeline_type,
        "current_step": current_step,
        "project_id": project_id,
        "project_name": project_name,
        "connection_id": connection_id,
        "category_id": category_id,
    }
    # step_label for Dashboard resume display
    _ARTICLE_LABELS: dict[str, str] = {
        "select_project": "выбор проекта",
        "select_wp": "выбор сайта",
        "select_category": "выбор темы",
        "readiness_check": "подготовка",
        "confirm_cost": "подтверждение",
        "generating": "генерация",
        "preview": "превью",
        "publishing": "публикация",
        "result": "результат",
    }
    _SOCIAL_LABELS: dict[str, str] = {
        "select_project": "выбор проекта",
        "select_connection": "выбор подключения",
        "select_category": "выбор темы",
        "readiness_check": "подготовка",
        "confirm_cost": "подтверждение",
        "generating": "генерация",
        "review": "ревью",
        "publishing": "публикация",
        "cross_post_review": "кросс-пост",
    }
    labels = _SOCIAL_LABELS if pipeline_type == "social" else _ARTICLE_LABELS
    data["step_label"] = labels.get(current_step, current_step)
    data.update(extra)  # type: ignore[arg-type]
    await redis.set(
        CacheKeys.pipeline_state(user_id),
        json.dumps(data, ensure_ascii=False),
        ex=PIPELINE_CHECKPOINT_TTL,
    )


async def clear_checkpoint(redis: RedisClient, user_id: int) -> None:
    """Remove pipeline checkpoint from Redis."""
    await redis.delete(CacheKeys.pipeline_state(user_id))


# ---------------------------------------------------------------------------
# Shared generation helpers (Zone 3 extraction from article + social)
# ---------------------------------------------------------------------------


async def select_keyword(db: SupabaseClient, category_id: int) -> str | None:
    """Select a keyword from category for generation.

    Supports both flat format [{phrase}] and cluster format [{main_phrase, phrases}].
    Phase 10 will implement full cluster rotation (API_CONTRACTS S6).
    """
    cats_repo = CategoriesRepository(db)
    category = await cats_repo.get_by_id(category_id)
    if not category or not category.keywords:
        return None

    keywords = category.keywords
    phrases: list[str] = []
    for kw in keywords:
        if isinstance(kw, dict):
            if "main_phrase" in kw:
                phrases.append(kw["main_phrase"])
            elif "phrase" in kw:
                phrases.append(kw["phrase"])
        elif isinstance(kw, str):
            phrases.append(kw)

    if not phrases:
        return None

    return random.choice(phrases)  # noqa: S311


async def try_refund(
    db: SupabaseClient,
    user: User,
    amount: int | None,
    reason_suffix: str,
) -> None:
    """Attempt to refund tokens on error (with GOD_MODE bypass)."""
    if not amount or amount <= 0:
        return
    settings = get_settings()
    is_god = user.id in settings.admin_ids
    if is_god:
        return
    try:
        token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
        await token_svc.refund(
            user_id=user.id,
            amount=amount,
            reason="refund",
            description=f"Возврат: {reason_suffix}",
        )
    except Exception:
        log.exception("pipeline.refund_failed", user_id=user.id, amount=amount)
