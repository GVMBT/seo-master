"""Router: SocialPostPublishFSM — TG/VK/Pinterest social post publish flow.

FSM_SPEC.md: SocialPostPublishFSM (5 states: confirm_cost, generating, review, publishing, regenerating).
Triggered from category card (category:{id}:publish:{tg|vk|pin}:{conn_id}) and quick publish.
"""

import html

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery

from bot.config import get_settings
from bot.fsm_utils import ensure_no_active_fsm
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import PublicationLogCreate, User
from db.repositories.categories import CategoriesRepository
from db.repositories.connections import ConnectionsRepository
from db.repositories.projects import ProjectsRepository
from db.repositories.publications import PublicationsRepository
from keyboards.publish import insufficient_balance_kb, social_confirm_kb, social_review_kb
from routers._helpers import guard_callback_message
from services.ai.rate_limiter import RateLimiter
from services.tokens import TokenService, estimate_social_post_cost

log = structlog.get_logger()

router = Router(name="publishing_social")

# ---------------------------------------------------------------------------
# Platform code mapping
# ---------------------------------------------------------------------------

_PLATFORM_MAP: dict[str, str] = {"tg": "telegram", "vk": "vk", "pin": "pinterest"}
_PLATFORM_DISPLAY: dict[str, str] = {"telegram": "Telegram", "vk": "VK", "pinterest": "Pinterest"}

# ---------------------------------------------------------------------------
# FSM definition
# ---------------------------------------------------------------------------


class SocialPostPublishFSM(StatesGroup):
    confirm_cost = State()
    generating = State()
    review = State()
    publishing = State()
    regenerating = State()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _select_keyword(keywords: list[dict[str, object]]) -> str | None:
    """Pick first available keyword/phrase from keywords list.

    Supports both cluster format (main_phrase) and legacy flat format (phrase).
    """
    if not keywords:
        return None
    first = keywords[0]
    # Cluster format
    if "main_phrase" in first:
        return str(first["main_phrase"]) if first.get("main_phrase") else None
    # Legacy flat format
    if "phrase" in first:
        return str(first["phrase"]) if first.get("phrase") else None
    return None


# ---------------------------------------------------------------------------
# 1. cb_social_start — entry point
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:(\d+):publish:(tg|vk|pin):(\d+)$"))
async def cb_social_start(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient,
) -> None:
    """Start SocialPostPublishFSM: show cost confirmation."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    category_id = int(parts[1])
    platform_short = parts[3]
    connection_id = int(parts[4])

    platform = _PLATFORM_MAP.get(platform_short)
    if not platform:
        await callback.answer("Неизвестная платформа.", show_alert=True)
        return

    # Load category and verify ownership
    category = await CategoriesRepository(db).get_by_id(category_id)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    project = await ProjectsRepository(db).get_by_id(category.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    # E16: check keywords
    if not category.keywords:
        await msg.edit_text(
            "В категории нет ключевых фраз. Добавьте хотя бы одну фразу для генерации контента.",
            reply_markup=None,
        )
        await callback.answer()
        return

    # Verify connection exists and belongs to project
    settings = get_settings()
    cm = CredentialManager(settings.encryption_key.get_secret_value())
    conn = await ConnectionsRepository(db, cm).get_by_id(connection_id)
    if not conn or conn.project_id != project.id:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    # Estimate cost and check balance
    cost = estimate_social_post_cost()
    token_svc = TokenService(db, settings.admin_id)
    has_balance = await token_svc.check_balance(user.id, cost)

    if not has_balance:
        balance = await token_svc.get_balance(user.id)
        await msg.edit_text(
            token_svc.format_insufficient_msg(cost, balance),
            reply_markup=insufficient_balance_kb().as_markup(),
        )
        await callback.answer()
        return

    # Auto-reset any active FSM (E29)
    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(SocialPostPublishFSM.confirm_cost)
    await state.update_data(
        category_id=category_id,
        project_id=project.id,
        connection_id=connection_id,
        platform=platform,
        cost=cost,
    )

    plat_display = _PLATFORM_DISPLAY.get(platform, platform)
    await msg.edit_text(
        f"Генерация поста для {plat_display}\n"
        f"Категория: {html.escape(category.name)}\n"
        f"Стоимость: {cost} токенов\n\n"
        f"Подтвердите генерацию:",
        reply_markup=social_confirm_kb(category_id, platform, connection_id, cost).as_markup(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 2. cb_social_confirm — charge and generate
# ---------------------------------------------------------------------------


@router.callback_query(SocialPostPublishFSM.confirm_cost, F.data == "pub:social:confirm")
async def cb_social_confirm(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient,
    rate_limiter: RateLimiter,
) -> None:
    """Charge tokens and generate social post content."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    # E25: rate limit check (raises RateLimitError → global handler)
    await rate_limiter.check(user.id, "text_generation")

    data = await state.get_data()
    cost = data.get("cost", 40)
    category_id = data.get("category_id")
    platform = data.get("platform", "")

    settings = get_settings()
    token_svc = TokenService(db, settings.admin_id)

    # Charge tokens
    try:
        await token_svc.charge(
            user_id=user.id,
            amount=cost,
            operation_type="social_post",
            description=f"Social post generation ({platform})",
        )
    except Exception:
        log.exception("social_charge_failed", user_id=user.id, cost=cost)
        await msg.edit_text("Ошибка списания токенов. Попробуйте позже.")
        await state.clear()
        await callback.answer()
        return

    await state.set_state(SocialPostPublishFSM.generating)
    await msg.edit_text("Генерирую пост...")
    await callback.answer()

    # Pick keyword
    keyword: str | None = None
    if category_id is not None:
        category = await CategoriesRepository(db).get_by_id(int(category_id))
        keyword = _select_keyword(category.keywords) if category else None

    # Placeholder for actual AI generation (wired in service layer later)
    generated_content = f"Пост для платформы {platform}. Ключевое слово: {keyword or 'N/A'}"

    await state.update_data(
        keyword=keyword,
        generated_content=generated_content,
        regeneration_count=0,
    )
    await state.set_state(SocialPostPublishFSM.review)

    await msg.edit_text(
        f"Готово! Текст поста:\n\n{html.escape(generated_content)}",
        reply_markup=social_review_kb(regen_count=0).as_markup(),
    )


# ---------------------------------------------------------------------------
# 3. cb_social_publish — publish post
# ---------------------------------------------------------------------------


@router.callback_query(SocialPostPublishFSM.review, F.data == "pub:social:publish")
async def cb_social_publish(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient,
) -> None:
    """Publish the generated social post."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    await state.set_state(SocialPostPublishFSM.publishing)

    data = await state.get_data()
    category_id = data.get("category_id")
    project_id = data.get("project_id")
    connection_id = data.get("connection_id")
    platform = data.get("platform", "")
    keyword = data.get("keyword")
    content = data.get("generated_content", "")
    cost = data.get("cost", 40)

    await msg.edit_text("Публикую пост...")
    await callback.answer()

    # Placeholder for actual publisher (wired later)
    # In real implementation: get connection credentials, call platform publisher
    post_url = None

    try:
        # Create publication log
        await PublicationsRepository(db).create_log(
            PublicationLogCreate(
                user_id=user.id,
                project_id=project_id or 0,
                category_id=category_id,
                platform_type=platform,
                connection_id=connection_id,
                keyword=keyword,
                content_type="social_post",
                images_count=0,
                post_url=post_url,
                word_count=len(content.split()) if content else 0,
                tokens_spent=cost,
                status="success",
            )
        )
    except Exception:
        log.exception("social_publication_log_failed", user_id=user.id)

    await state.clear()

    plat_display = _PLATFORM_DISPLAY.get(platform, platform)
    success_text = f"Пост опубликован в {plat_display}!"
    if post_url:
        success_text += f"\n\nСсылка: {post_url}"

    await msg.edit_text(success_text)


# ---------------------------------------------------------------------------
# 4. cb_social_regen — regenerate post
# ---------------------------------------------------------------------------


@router.callback_query(SocialPostPublishFSM.review, F.data == "pub:social:regen")
async def cb_social_regen(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient,
) -> None:
    """Regenerate the social post (2 free, then paid)."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    data = await state.get_data()
    regen_count = data.get("regeneration_count", 0)
    cost = data.get("cost", 40)
    platform = data.get("platform", "")
    keyword = data.get("keyword")

    # Free regenerations: 0, 1 (indices), paid from 2+
    if regen_count >= 2:
        # E10: Paid regeneration
        settings = get_settings()
        token_svc = TokenService(db, settings.admin_id)
        has_balance = await token_svc.check_balance(user.id, cost)

        if not has_balance:
            balance = await token_svc.get_balance(user.id)
            await callback.answer(
                f"Перегенерация стоит {cost} токенов, у вас {balance}.",
                show_alert=True,
            )
            return

        try:
            await token_svc.charge(
                user_id=user.id,
                amount=cost,
                operation_type="social_post_regen",
                description=f"Social post regeneration #{regen_count + 1} ({platform})",
            )
        except Exception:
            log.exception("social_regen_charge_failed", user_id=user.id)
            await callback.answer("Ошибка списания. Попробуйте позже.", show_alert=True)
            return

    await state.set_state(SocialPostPublishFSM.regenerating)
    await msg.edit_text("Перегенерирую пост...")
    await callback.answer()

    # Placeholder for actual AI generation
    new_content = f"Новый пост (попытка {regen_count + 2}) для {platform}. Ключевое слово: {keyword or 'N/A'}"

    new_count = regen_count + 1
    await state.update_data(
        generated_content=new_content,
        regeneration_count=new_count,
    )
    await state.set_state(SocialPostPublishFSM.review)

    await msg.edit_text(
        f"Готово! Текст поста:\n\n{html.escape(new_content)}",
        reply_markup=social_review_kb(regen_count=new_count).as_markup(),
    )


# ---------------------------------------------------------------------------
# 5. cb_social_cancel — cancel generation
# ---------------------------------------------------------------------------


@router.callback_query(SocialPostPublishFSM.review, F.data == "pub:social:cancel")
async def cb_social_cancel(
    callback: CallbackQuery, state: FSMContext,
) -> None:
    """Cancel social post generation. No refund for cheap posts (~40 tokens, E27)."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    data = await state.get_data()
    category_id = data.get("category_id")

    await state.clear()

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    if category_id:
        builder.button(text="К категории", callback_data=f"category:{category_id}:card")
    builder.adjust(1)

    await msg.edit_text(
        "Генерация отменена.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 6. cb_social_publishing_guard — E07: double-click guard
# ---------------------------------------------------------------------------


@router.callback_query(SocialPostPublishFSM.publishing)
async def cb_social_publishing_guard(callback: CallbackQuery) -> None:
    """E07: Prevent double-click during publishing."""
    await callback.answer("Публикация в процессе.", show_alert=True)
