"""Pydantic v2 models for all 13 database tables.

Schema source of truth: docs/ARCHITECTURE.md section 3.2.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# 1. users
# ---------------------------------------------------------------------------


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int  # Telegram user ID (BIGINT PK)
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    balance: int = 1500
    language: str = "ru"
    role: str = "user"
    referrer_id: int | None = None
    notify_publications: bool = True
    notify_balance: bool = True
    notify_news: bool = True
    created_at: datetime | None = None
    last_activity: datetime | None = None


class UserCreate(BaseModel):
    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    referrer_id: int | None = None


class UserUpdate(BaseModel):
    """Partial update model for users table.

    NOTE: `balance` is intentionally excluded. All balance mutations MUST go through
    atomic RPC functions (charge_balance, refund_balance, credit_balance) in
    UsersRepository to prevent race conditions. See ARCHITECTURE.md section 5.5.
    """

    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language: str | None = None
    role: str | None = None
    referrer_id: int | None = None
    notify_publications: bool | None = None
    notify_balance: bool | None = None
    notify_news: bool | None = None
    last_activity: datetime | None = None


# ---------------------------------------------------------------------------
# 2. projects
# ---------------------------------------------------------------------------


class Project(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    company_name: str
    specialization: str
    website_url: str | None = None
    company_city: str | None = None
    company_address: str | None = None
    company_phone: str | None = None
    company_email: str | None = None
    company_instagram: str | None = None
    company_vk: str | None = None
    company_pinterest: str | None = None
    company_telegram: str | None = None
    experience: str | None = None
    advantages: str | None = None
    description: str | None = None
    timezone: str = "Europe/Moscow"
    created_at: datetime | None = None


class ProjectCreate(BaseModel):
    user_id: int
    name: str
    company_name: str
    specialization: str
    website_url: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    company_name: str | None = None
    specialization: str | None = None
    website_url: str | None = None
    company_city: str | None = None
    company_address: str | None = None
    company_phone: str | None = None
    company_email: str | None = None
    company_instagram: str | None = None
    company_vk: str | None = None
    company_pinterest: str | None = None
    company_telegram: str | None = None
    experience: str | None = None
    advantages: str | None = None
    description: str | None = None
    timezone: str | None = None


# ---------------------------------------------------------------------------
# 3. platform_connections
# ---------------------------------------------------------------------------


class PlatformConnection(BaseModel):
    """Read model for platform_connections table.

    WARNING: `credentials` here is the DECRYPTED dict, not the raw DB value.
    In the database, credentials is stored as Fernet-encrypted TEXT.
    The repository layer (ConnectionsRepository) decrypts it via CredentialManager
    before constructing this model. NEVER write `credentials` back to the DB
    without re-encrypting through CredentialManager.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    platform_type: str
    status: str = "active"
    credentials: dict[str, Any]  # Decrypted read model — raw DB value is Fernet TEXT
    metadata: dict[str, Any] = Field(default_factory=dict)
    identifier: str
    created_at: datetime | None = None


class PlatformConnectionCreate(BaseModel):
    """Create model for platform_connections.

    Note: `credentials` is NOT included here. The repository layer
    encrypts credentials via CredentialManager and passes them
    separately to the INSERT query. See db/credential_manager.py.
    """

    project_id: int
    platform_type: str
    identifier: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlatformConnectionUpdate(BaseModel):
    status: str | None = None
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# 4. categories
# ---------------------------------------------------------------------------


class Category(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    description: str | None = None
    # Cluster: [{cluster_name, cluster_type, main_phrase, total_volume, avg_difficulty, phrases: [...]}]
    # Legacy flat: [{phrase, volume, difficulty, intent, cpc}] — both supported
    keywords: list[dict[str, Any]] = Field(default_factory=list)
    media: list[dict[str, Any]] = Field(default_factory=list)  # [{file_id, type, file_size, uploaded_at}]
    prices: str | None = None
    reviews: list[dict[str, Any]] = Field(default_factory=list)  # [{author, date, rating, text, pros, cons}]
    image_settings: dict[str, Any] = Field(default_factory=dict)
    text_settings: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class CategoryCreate(BaseModel):
    project_id: int
    name: str
    description: str | None = None


class CategoryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    keywords: list[dict[str, Any]] | None = None
    media: list[dict[str, Any]] | None = None
    prices: str | None = None
    reviews: list[dict[str, Any]] | None = None
    image_settings: dict[str, Any] | None = None
    text_settings: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# 5. platform_content_overrides
# ---------------------------------------------------------------------------


class PlatformContentOverride(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    platform_type: str
    image_settings: dict[str, Any] | None = None
    text_settings: dict[str, Any] | None = None


class PlatformContentOverrideCreate(BaseModel):
    category_id: int
    platform_type: str
    image_settings: dict[str, Any] | None = None
    text_settings: dict[str, Any] | None = None


class PlatformContentOverrideUpdate(BaseModel):
    image_settings: dict[str, Any] | None = None
    text_settings: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# 6. platform_schedules
# ---------------------------------------------------------------------------


class PlatformSchedule(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    platform_type: str
    connection_id: int
    schedule_days: list[str] = Field(default_factory=list)
    schedule_times: list[str] = Field(default_factory=list)
    posts_per_day: int = Field(default=1, ge=1, le=5)
    enabled: bool = False
    status: str = "active"
    qstash_schedule_ids: list[str] = Field(default_factory=list)
    cross_post_connection_ids: list[int] = Field(default_factory=list)
    last_post_at: datetime | None = None
    created_at: datetime | None = None


class PlatformScheduleCreate(BaseModel):
    category_id: int
    platform_type: str
    connection_id: int
    schedule_days: list[str] = Field(default_factory=list)
    schedule_times: list[str] = Field(default_factory=list)
    posts_per_day: int = Field(default=1, ge=1, le=5)
    cross_post_connection_ids: list[int] = Field(default_factory=list)


class PlatformScheduleUpdate(BaseModel):
    schedule_days: list[str] | None = None
    schedule_times: list[str] | None = None
    posts_per_day: int | None = Field(default=None, ge=1, le=5)
    enabled: bool | None = None
    status: str | None = None
    qstash_schedule_ids: list[str] | None = None
    cross_post_connection_ids: list[int] | None = None
    last_post_at: datetime | None = None


# ---------------------------------------------------------------------------
# 7. publication_logs
# ---------------------------------------------------------------------------


class PublicationLog(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    project_id: int
    category_id: int | None = None
    platform_type: str
    connection_id: int | None = None
    keyword: str | None = None
    content_type: str = "article"
    images_count: int = 0
    post_url: str | None = None
    word_count: int = 0
    tokens_spent: int = 0
    ai_model: str | None = None
    generation_time_ms: int | None = None
    prompt_version: str | None = None
    content_hash: int | None = None  # simhash for anti-cannibalization (P2)
    status: str = "success"
    error_message: str | None = None
    rank_position: int | None = None  # Google SERP position (P2, Phase 11+)
    rank_checked_at: datetime | None = None
    created_at: datetime | None = None


class PublicationLogCreate(BaseModel):
    user_id: int
    project_id: int
    category_id: int | None = None
    platform_type: str
    connection_id: int | None = None
    keyword: str | None = None
    content_type: str = "article"
    images_count: int = 0
    post_url: str | None = None
    word_count: int = 0
    tokens_spent: int = 0
    ai_model: str | None = None
    generation_time_ms: int | None = None
    prompt_version: str | None = None
    content_hash: int | None = None
    status: str = "success"
    error_message: str | None = None


class PublicationLogUpdate(BaseModel):
    status: str | None = None
    error_message: str | None = None
    post_url: str | None = None
    rank_position: int | None = None
    rank_checked_at: datetime | None = None


# ---------------------------------------------------------------------------
# 8. token_expenses
# ---------------------------------------------------------------------------


class TokenExpense(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    amount: int
    operation_type: str
    description: str | None = None
    ai_model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Decimal | None = None
    created_at: datetime | None = None


class TokenExpenseCreate(BaseModel):
    user_id: int
    amount: int
    operation_type: str
    description: str | None = None
    ai_model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Decimal | None = None


# ---------------------------------------------------------------------------
# 9. payments
# ---------------------------------------------------------------------------


class Payment(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    provider: str
    status: str = "pending"
    telegram_payment_charge_id: str | None = None
    provider_payment_charge_id: str | None = None
    stars_amount: int | None = None
    yookassa_payment_id: str | None = None
    yookassa_payment_method_id: str | None = None
    package_name: str | None = None
    tokens_amount: int
    amount_rub: Decimal | None = None
    is_subscription: bool = False
    subscription_id: str | None = None
    subscription_status: str | None = None
    subscription_expires_at: datetime | None = None
    referral_bonus_credited: bool = False
    created_at: datetime | None = None


class PaymentCreate(BaseModel):
    user_id: int
    provider: str
    tokens_amount: int
    package_name: str | None = None
    amount_rub: Decimal | None = None
    stars_amount: int | None = None
    is_subscription: bool = False


class PaymentUpdate(BaseModel):
    status: str | None = None
    telegram_payment_charge_id: str | None = None
    provider_payment_charge_id: str | None = None
    yookassa_payment_id: str | None = None
    yookassa_payment_method_id: str | None = None
    subscription_id: str | None = None
    subscription_status: str | None = None
    subscription_expires_at: datetime | None = None
    referral_bonus_credited: bool | None = None


# ---------------------------------------------------------------------------
# 10. site_audits
# ---------------------------------------------------------------------------


class SiteAudit(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    url: str
    performance: int | None = None
    accessibility: int | None = None
    best_practices: int | None = None
    seo_score: int | None = None
    lcp_ms: int | None = None
    inp_ms: int | None = None
    cls: Decimal | None = None
    ttfb_ms: int | None = None
    full_report: dict[str, Any] | None = None
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    audited_at: datetime | None = None


class SiteAuditCreate(BaseModel):
    project_id: int
    url: str
    performance: int | None = None
    accessibility: int | None = None
    best_practices: int | None = None
    seo_score: int | None = None
    lcp_ms: int | None = None
    inp_ms: int | None = None
    cls: Decimal | None = None
    ttfb_ms: int | None = None
    full_report: dict[str, Any] | None = None
    recommendations: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 11. site_brandings
# ---------------------------------------------------------------------------


class SiteBranding(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    url: str
    colors: dict[str, Any] = Field(default_factory=dict)
    fonts: dict[str, Any] = Field(default_factory=dict)
    logo_url: str | None = None
    extracted_at: datetime | None = None


class SiteBrandingCreate(BaseModel):
    project_id: int
    url: str
    colors: dict[str, Any] = Field(default_factory=dict)
    fonts: dict[str, Any] = Field(default_factory=dict)
    logo_url: str | None = None


# ---------------------------------------------------------------------------
# 12. article_previews
# ---------------------------------------------------------------------------


class ArticlePreview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    project_id: int
    category_id: int
    connection_id: int | None = None
    telegraph_url: str | None = None
    telegraph_path: str | None = None
    title: str | None = None
    keyword: str | None = None
    meta_description: str | None = None
    word_count: int | None = None
    images_count: int | None = None
    tokens_charged: int | None = None
    regeneration_count: int = 0
    status: str = "draft"
    content_html: str | None = None
    images: list[dict[str, Any]] = Field(default_factory=list)  # [{url, storage_path, width, height}]
    created_at: datetime | None = None
    expires_at: datetime | None = None


class ArticlePreviewCreate(BaseModel):
    user_id: int
    project_id: int
    category_id: int
    connection_id: int | None = None
    telegraph_url: str | None = None
    telegraph_path: str | None = None
    title: str | None = None
    keyword: str | None = None
    meta_description: str | None = None
    word_count: int | None = None
    images_count: int | None = None
    tokens_charged: int | None = None
    content_html: str | None = None
    images: list[dict[str, Any]] = Field(default_factory=list)


class ArticlePreviewUpdate(BaseModel):
    telegraph_url: str | None = None
    telegraph_path: str | None = None
    title: str | None = None
    word_count: int | None = None
    images_count: int | None = None
    tokens_charged: int | None = None
    regeneration_count: int | None = None
    status: str | None = None
    content_html: str | None = None
    images: list[dict[str, Any]] | None = None
    connection_id: int | None = None
    meta_description: str | None = None


# ---------------------------------------------------------------------------
# 13. prompt_versions
# ---------------------------------------------------------------------------


class PromptVersion(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_type: str  # "article", "social_post", "keywords", "review", "image", "description", "competitor_analysis"
    version: str
    prompt_yaml: str
    is_active: bool = False
    success_rate: Decimal | None = None
    avg_quality: Decimal | None = None
    created_at: datetime | None = None


class PromptVersionCreate(BaseModel):
    task_type: str
    version: str
    prompt_yaml: str
    is_active: bool = False


class PromptVersionUpdate(BaseModel):
    prompt_yaml: str | None = None
    is_active: bool | None = None
    success_rate: Decimal | None = None
    avg_quality: Decimal | None = None
