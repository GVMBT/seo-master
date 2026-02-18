"""Shared FSM and helpers for Article/Social pipeline modules.

Extracted to avoid circular imports between article.py and readiness.py.
"""

from __future__ import annotations

import json

from aiogram.fsm.state import State, StatesGroup

from cache.client import RedisClient
from cache.keys import PIPELINE_CHECKPOINT_TTL, CacheKeys

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
# Checkpoint helpers
# ---------------------------------------------------------------------------


async def save_checkpoint(
    redis: RedisClient,
    user_id: int,
    *,
    current_step: str,
    project_id: int | None = None,
    project_name: str | None = None,
    connection_id: int | None = None,
    category_id: int | None = None,
    **extra: object,
) -> None:
    """Save pipeline checkpoint to Redis (UX_PIPELINE.md §10.3)."""
    data: dict[str, object] = {
        "pipeline_type": "article",
        "current_step": current_step,
        "project_id": project_id,
        "project_name": project_name,
        "connection_id": connection_id,
        "category_id": category_id,
    }
    # step_label for Dashboard resume display
    step_labels = {
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
    data["step_label"] = step_labels.get(current_step, current_step)
    data.update(extra)  # type: ignore[arg-type]
    await redis.set(
        CacheKeys.pipeline_state(user_id),
        json.dumps(data, ensure_ascii=False),
        ex=PIPELINE_CHECKPOINT_TTL,
    )


async def clear_checkpoint(redis: RedisClient, user_id: int) -> None:
    """Remove pipeline checkpoint from Redis."""
    await redis.delete(CacheKeys.pipeline_state(user_id))
