"""Token economy service — balance operations, cost estimation, history.

Source of truth: PRD.md §9 (token costs), ARCHITECTURE.md §5.5 (atomic RPCs).
Zero dependencies on Telegram/Aiogram.
"""

import math
from decimal import Decimal

import structlog

from db.client import SupabaseClient
from db.models import TokenExpense, TokenExpenseCreate, User
from db.repositories.categories import CategoriesRepository
from db.repositories.payments import PaymentsRepository
from db.repositories.projects import ProjectsRepository
from db.repositories.schedules import SchedulesRepository
from db.repositories.users import UsersRepository

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Token costs (PRD.md §9.1 + §9.2)
# ---------------------------------------------------------------------------

COST_PER_100_WORDS = 10
COST_PER_IMAGE = 30
COST_AUDIT = 50
COST_COMPETITOR = 50
COST_DESCRIPTION = 20
COST_REVIEW_EACH = 10

# Keyword generation: 50 for 50, 100 for 100, 150 for 150, 200 for 200
COST_KEYWORDS_PER_UNIT = 1  # 1 token per keyword


def estimate_text_cost(word_count: int) -> int:
    """Calculate token cost for text generation.

    Formula (PRD §9.1): ceil(word_count / 100) * 10
    """
    if word_count <= 0:
        return 0
    return math.ceil(word_count / 100) * COST_PER_100_WORDS


def estimate_article_cost(word_count: int = 2000, images_count: int = 4) -> int:
    """Estimate cost for article + images (default ~320 tokens)."""
    return estimate_text_cost(word_count) + images_count * COST_PER_IMAGE


def estimate_social_post_cost(word_count: int = 100, images_count: int = 1) -> int:
    """Estimate cost for social post + image (default ~40 tokens)."""
    return estimate_text_cost(word_count) + images_count * COST_PER_IMAGE


def estimate_keywords_cost(quantity: int) -> int:
    """Keyword generation: 50-200 tokens (1:1 mapping)."""
    return max(quantity * COST_KEYWORDS_PER_UNIT, 0)


# ---------------------------------------------------------------------------
# Token service
# ---------------------------------------------------------------------------


class TokenService:
    """Manages balance checks, charges, refunds, and expense history.

    All balance mutations use atomic RPCs via UsersRepository (§5.5).
    GOD_MODE: admin_id never gets charged but sees the cost.
    """

    def __init__(self, db: SupabaseClient, admin_id: int) -> None:
        self._db = db
        self._users = UsersRepository(db)
        self._payments = PaymentsRepository(db)
        self._admin_id = admin_id

    async def check_balance(self, user_id: int, required: int) -> bool:
        """Check if user has enough tokens. Returns True if sufficient."""
        user = await self._users.get_by_id(user_id)
        if user is None:
            return False
        return user.balance >= required

    async def get_balance(self, user_id: int) -> int:
        """Get current balance for user. Returns 0 if user not found."""
        user = await self._users.get_by_id(user_id)
        return user.balance if user else 0

    async def charge(
        self,
        user_id: int,
        amount: int,
        operation_type: str,
        description: str | None = None,
        ai_model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: Decimal | None = None,
    ) -> int:
        """Deduct tokens and record expense. Returns new balance.

        GOD_MODE: if user_id == admin_id, records expense but doesn't charge.
        Raises InsufficientBalanceError if balance < amount (E01).
        """
        if amount <= 0:
            return await self.get_balance(user_id)

        is_god_mode = user_id == self._admin_id

        if not is_god_mode:
            new_balance = await self._users.charge_balance(user_id, amount)
        else:
            new_balance = await self.get_balance(user_id)
            log.info("god_mode_skip_charge", user_id=user_id, amount=amount)

        # Record expense (negative = deduction)
        await self._payments.create_expense(
            TokenExpenseCreate(
                user_id=user_id,
                amount=-amount,
                operation_type=operation_type,
                description=description,
                ai_model=ai_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            )
        )

        log.info(
            "tokens_charged",
            user_id=user_id,
            amount=amount,
            operation_type=operation_type,
            new_balance=new_balance,
            god_mode=is_god_mode,
        )
        return new_balance

    async def refund(
        self,
        user_id: int,
        amount: int,
        reason: str = "refund",
        description: str | None = None,
    ) -> int:
        """Return tokens to user and record refund expense. Returns new balance."""
        if amount <= 0:
            return await self.get_balance(user_id)

        new_balance = await self._users.refund_balance(user_id, amount)

        await self._payments.create_expense(
            TokenExpenseCreate(
                user_id=user_id,
                amount=amount,  # positive = credit
                operation_type=reason,
                description=description,
            )
        )

        log.info("tokens_refunded", user_id=user_id, amount=amount, new_balance=new_balance)
        return new_balance

    async def credit(
        self,
        user_id: int,
        amount: int,
        operation_type: str = "purchase",
        description: str | None = None,
    ) -> int:
        """Add tokens (purchase, referral bonus). Returns new balance."""
        if amount <= 0:
            return await self.get_balance(user_id)

        new_balance = await self._users.credit_balance(user_id, amount)

        await self._payments.create_expense(
            TokenExpenseCreate(
                user_id=user_id,
                amount=amount,
                operation_type=operation_type,
                description=description,
            )
        )

        log.info(
            "tokens_credited",
            user_id=user_id,
            amount=amount,
            operation_type=operation_type,
            new_balance=new_balance,
        )
        return new_balance

    async def get_history(
        self, user_id: int, limit: int = 20, offset: int = 0
    ) -> list[TokenExpense]:
        """Get expense history for a user, newest first."""
        return await self._payments.get_expenses_by_user(user_id, limit=limit, offset=offset)

    async def get_referral_bonus_total(self, user_id: int) -> int:
        """Sum all referral_bonus expenses for a user."""
        expenses = await self._payments.get_expenses_by_user(user_id, limit=500)
        return sum(exp.amount for exp in expenses if exp.operation_type == "referral_bonus")

    async def get_profile_stats(self, user: User) -> dict[str, int]:
        """Gather profile statistics (project count, categories, schedules, referrals, forecast).

        Returns dict with keys: project_count, category_count, schedule_count,
        referral_count, posts_per_week, tokens_per_week, tokens_per_month.
        """
        projects_repo = ProjectsRepository(self._db)
        schedules_repo = SchedulesRepository(self._db)
        categories_repo = CategoriesRepository(self._db)

        projects = await projects_repo.get_by_user(user.id)
        project_count = len(projects)

        # Count categories and enabled schedules across all user's projects
        category_count = 0
        schedule_count = 0
        posts_per_week = 0
        for project in projects:
            cats = await categories_repo.get_by_project(project.id)
            category_count += len(cats)

            cat_ids = [c.id for c in cats]
            schedules = await schedules_repo.get_by_project(cat_ids)
            for s in schedules:
                if s.enabled:
                    schedule_count += 1
                    # posts_per_day * days per week for this schedule
                    days_count = len(s.schedule_days) if s.schedule_days else 7
                    posts_per_week += s.posts_per_day * days_count

        referral_count = await self._users.get_referral_count(user.id)

        # Cost forecast: average ~40 tokens per scheduled post
        avg_cost_per_post = 40
        tokens_per_week = posts_per_week * avg_cost_per_post
        tokens_per_month = tokens_per_week * 4

        return {
            "project_count": project_count,
            "category_count": category_count,
            "schedule_count": schedule_count,
            "referral_count": referral_count,
            "posts_per_week": posts_per_week,
            "tokens_per_week": tokens_per_week,
            "tokens_per_month": tokens_per_month,
        }

    def format_insufficient_msg(self, required: int, balance: int) -> str:
        """Format user-friendly insufficient balance message (E01, E10)."""
        return f"Недостаточно токенов. Нужно {required}, у вас {balance}."  # noqa: RUF001
