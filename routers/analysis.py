"""Router: PageSpeed audit (callback-based) + CompetitorAnalysisFSM.

Spec: docs/USER_FLOWS_AND_UI_MAP.md level 3 "Анализ сайта"
FSM: docs/FSM_SPEC.md section 1 (CompetitorAnalysisFSM, 4 states)
Edge cases: E31 (Firecrawl unavailable), E38 (insufficient balance)
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

import httpx
import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.fsm_utils import ensure_no_active_fsm
from db.client import SupabaseClient
from db.models import Project, SiteAudit, SiteAuditCreate, User
from db.repositories.audits import AuditsRepository
from db.repositories.projects import ProjectsRepository
from keyboards.publish import (
    audit_menu_kb,
    audit_results_kb,
    competitor_confirm_kb,
    competitor_results_kb,
    insufficient_balance_kb,
)
from keyboards.reply import cancel_kb, main_menu
from routers._helpers import guard_callback_message
from services.ai.rate_limiter import RateLimiter
from services.external.firecrawl import FirecrawlClient
from services.external.pagespeed import PageSpeedClient
from services.tokens import COST_AUDIT, COST_COMPETITOR, TokenService

log = structlog.get_logger()

router = Router(name="analysis")


# ---------------------------------------------------------------------------
# FSM definition (docs/FSM_SPEC.md section 1)
# ---------------------------------------------------------------------------


class CompetitorAnalysisFSM(StatesGroup):
    url = State()  # Enter competitor URL
    confirm = State()  # Confirm cost (50 tokens)
    analyzing = State()  # Progress: Firecrawl extraction running
    results = State()  # Show results: back to project


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"^https?://[^\s]{3,}$")


def _validate_url(text: str) -> bool:
    """Check URL starts with http/https and has basic structure."""
    return bool(_URL_RE.match(text.strip()))


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_audit_results(audit: SiteAudit) -> str:
    """Format PageSpeed audit results for display."""
    lines = [
        f"Аудит сайта: {audit.url}\n",
        f"Performance: {audit.performance}/100",
        f"Accessibility: {audit.accessibility}/100",
        f"Best Practices: {audit.best_practices}/100",
        f"SEO: {audit.seo_score}/100\n",
        "Core Web Vitals:",
        f"  LCP: {audit.lcp_ms}ms",
        f"  INP: {audit.inp_ms}ms",
        f"  CLS: {audit.cls}",
        f"  TTFB: {audit.ttfb_ms}ms",
    ]
    if audit.recommendations:
        lines.append("\nТоп рекомендации:")
        for i, rec in enumerate(audit.recommendations[:5], 1):
            lines.append(f"  {i}. {rec.get('title', '?')}")
    return "\n".join(lines)


def _format_competitor_results(data: dict[str, Any]) -> str:
    """Format competitor analysis results."""
    lines = [
        f"Анализ конкурента: {data.get('company_name', 'N/A')}\n",
        f"Основные темы: {', '.join(data.get('main_topics', [])[:5])}",
    ]
    usps = data.get("unique_selling_points", [])
    if usps:
        lines.append(f"\nПреимущества ({len(usps)}):")
        for u in usps[:5]:
            lines.append(f"  - {u}")
    gaps = data.get("content_gaps", [])
    if gaps:
        lines.append(f"\nПробелы в контенте ({len(gaps)}):")
        for g in gaps[:5]:
            lines.append(f"  - {g}")
    keywords = data.get("primary_keywords", [])
    if keywords:
        lines.append(f"\nОсновные ключевики: {', '.join(keywords[:7])}")
    estimated = data.get("estimated_pages")
    if estimated:
        lines.append(f"\nСтраниц: ~{estimated}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _get_project_or_notify(
    project_id: int,
    user_id: int,
    db: SupabaseClient,
    callback: CallbackQuery,
) -> Project | None:
    """Fetch project and verify ownership. Answers callback on failure."""
    project = await ProjectsRepository(db).get_by_id(project_id)
    if not project or project.user_id != user_id:
        await callback.answer("Проект не найден.", show_alert=True)
        return None
    return project


# ---------------------------------------------------------------------------
# 1. cb_project_audit — entry point from project card
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:(\d+):audit$"))
async def cb_project_audit(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show audit menu or last audit results."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _get_project_or_notify(project_id, user.id, db, callback)
    if not project:
        return

    audit = await AuditsRepository(db).get_audit_by_project(project_id)

    if audit:
        text = _format_audit_results(audit)
        await msg.edit_text(text, reply_markup=audit_results_kb(project_id).as_markup())
    else:
        await msg.edit_text(
            "Анализ сайта\n\nЗапустите технический аудит или проанализируйте конкурентов.",
            reply_markup=audit_menu_kb(project_id, has_audit=False).as_markup(),
        )
    await callback.answer()


# ---------------------------------------------------------------------------
# 2. cb_audit_run — execute PageSpeed audit
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:(\d+):audit:run$"))
async def cb_audit_run(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
) -> None:
    """Run PageSpeed audit, charge tokens, save results."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _get_project_or_notify(project_id, user.id, db, callback)
    if not project:
        return

    if not project.website_url:
        await callback.answer(
            "Укажите URL сайта в настройках проекта.",
            show_alert=True,
        )
        return

    settings = get_settings()
    token_svc = TokenService(db, settings.admin_ids)

    # Check balance before charging
    if not await token_svc.check_balance(user.id, COST_AUDIT):
        await msg.edit_text(
            token_svc.format_insufficient_msg(COST_AUDIT, user.balance),
            reply_markup=insufficient_balance_kb().as_markup(),
        )
        await callback.answer()
        return

    # Charge tokens
    await token_svc.charge(
        user.id,
        COST_AUDIT,
        operation_type="audit",
        description=f"Site audit: {project.website_url}",
    )

    await msg.edit_text("Запускаю аудит сайта...")
    await callback.answer()

    psi = PageSpeedClient(http_client)
    result = await psi.audit(project.website_url)

    if result is None:
        # Refund on failure
        await token_svc.refund(
            user.id,
            COST_AUDIT,
            reason="audit_failed",
            description="PageSpeed audit failed",
        )
        await msg.edit_text(
            "Не удалось выполнить аудит. Попробуйте позже.",
            reply_markup=audit_menu_kb(project_id, has_audit=False).as_markup(),
        )
        return

    # Upsert audit data
    audit_data = SiteAuditCreate(
        project_id=project_id,
        url=project.website_url,
        performance=result.performance_score,
        accessibility=result.accessibility_score,
        best_practices=result.best_practices_score,
        seo_score=result.seo_score,
        lcp_ms=result.lcp_ms,
        inp_ms=result.inp_ms,
        cls=Decimal(str(result.cls)),
        ttfb_ms=result.ttfb_ms,
        full_report=result.full_report,
        recommendations=result.recommendations,
    )
    audit = await AuditsRepository(db).upsert_audit(audit_data)
    text = _format_audit_results(audit)
    await msg.edit_text(text, reply_markup=audit_results_kb(project_id).as_markup())


# ---------------------------------------------------------------------------
# 3. cb_competitor_start — entry into CompetitorAnalysisFSM
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:(\d+):competitor$"))
async def cb_competitor_start(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    state: FSMContext,
) -> None:
    """Start competitor analysis FSM. Check balance (E38)."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _get_project_or_notify(project_id, user.id, db, callback)
    if not project:
        return

    # E38: check balance
    settings = get_settings()
    token_svc = TokenService(db, settings.admin_ids)
    if not await token_svc.check_balance(user.id, COST_COMPETITOR):
        await msg.edit_text(
            token_svc.format_insufficient_msg(COST_COMPETITOR, user.balance),
            reply_markup=insufficient_balance_kb().as_markup(),
        )
        await callback.answer()
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(CompetitorAnalysisFSM.url)
    await state.update_data(project_id=project_id)

    await msg.answer(
        "Введите URL сайта конкурента (https://...)",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 4. fsm_competitor_url — validate URL, show confirm
# ---------------------------------------------------------------------------


@router.message(CompetitorAnalysisFSM.url, F.text)
async def fsm_competitor_url(
    message: Message,
    user: User,
    state: FSMContext,
) -> None:
    """Validate competitor URL and ask for confirmation."""
    text = (message.text or "").strip()

    if not _validate_url(text):
        await message.answer(
            "Введите корректный URL сайта конкурента (начиная с https:// или http://)",
        )
        return

    data = await state.get_data()
    project_id: int = data["project_id"]

    await state.update_data(competitor_url=text)
    await state.set_state(CompetitorAnalysisFSM.confirm)

    await message.answer(
        f"Анализ сайта {text}\nСтоимость: {COST_COMPETITOR} токенов\nБаланс: {user.balance}",
        reply_markup=competitor_confirm_kb(project_id, COST_COMPETITOR).as_markup(),
    )


# ---------------------------------------------------------------------------
# 5. cb_competitor_confirm — charge + analyze via Firecrawl
# ---------------------------------------------------------------------------


@router.callback_query(CompetitorAnalysisFSM.confirm, F.data == "comp:confirm")
async def cb_competitor_confirm(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    state: FSMContext,
    http_client: httpx.AsyncClient,
    rate_limiter: RateLimiter,
) -> None:
    """Charge tokens and run competitor analysis via Firecrawl (E31 on failure)."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    # E25: rate limit check (raises RateLimitError → global handler)
    await rate_limiter.check(user.id, "text_generation")

    data = await state.get_data()
    competitor_url: str = data["competitor_url"]
    project_id: int = data["project_id"]

    settings = get_settings()
    token_svc = TokenService(db, settings.admin_ids)

    # Charge tokens
    await token_svc.charge(
        user.id,
        COST_COMPETITOR,
        operation_type="competitor_analysis",
        description=f"Competitor analysis: {competitor_url}",
    )

    await state.set_state(CompetitorAnalysisFSM.analyzing)
    await msg.edit_text("Анализирую сайт конкурента...")
    await callback.answer()

    # Call Firecrawl extract_competitor
    firecrawl = FirecrawlClient(
        api_key=settings.firecrawl_api_key.get_secret_value(),
        http_client=http_client,
    )
    result = await firecrawl.extract_competitor(competitor_url)

    if result is None:
        # E31: Firecrawl failed -> refund tokens, clear FSM
        await token_svc.refund(
            user.id,
            COST_COMPETITOR,
            reason="competitor_analysis_failed",
            description=f"Firecrawl unavailable for {competitor_url}",
        )
        log.warning("e31_firecrawl_failed", url=competitor_url, user_id=user.id)
        await state.clear()
        await msg.edit_text(
            "Анализ конкурентов недоступен. Попробуйте позже.",
            reply_markup=audit_menu_kb(project_id, has_audit=False).as_markup(),
        )
        await msg.answer("Меню", reply_markup=main_menu(is_admin=user.role == "admin"))
        return

    # Format and show results
    result_text = _format_competitor_results(result.data)
    await state.clear()
    await msg.edit_text(
        result_text,
        reply_markup=competitor_results_kb(project_id).as_markup(),
    )
    await msg.answer("Меню", reply_markup=main_menu(is_admin=user.role == "admin"))
