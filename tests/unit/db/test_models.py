"""Tests for db/models.py — Pydantic models for all 13 tables."""

from datetime import datetime
from decimal import Decimal

from db.models import (
    ArticlePreview,
    ArticlePreviewCreate,
    Category,
    CategoryCreate,
    Payment,
    PaymentCreate,
    PlatformConnection,
    PlatformConnectionCreate,
    PlatformContentOverride,
    PlatformContentOverrideCreate,
    PlatformSchedule,
    PlatformScheduleCreate,
    Project,
    ProjectCreate,
    PromptVersion,
    PromptVersionCreate,
    PublicationLog,
    PublicationLogCreate,
    SiteAudit,
    SiteAuditCreate,
    SiteBranding,
    SiteBrandingCreate,
    TokenExpense,
    TokenExpenseCreate,
    User,
    UserCreate,
)


class TestUserModel:
    def test_defaults_match_sql(self) -> None:
        u = User(id=123)
        assert u.balance == 1500
        assert u.language == "ru"
        assert u.role == "user"
        assert u.notify_publications is True
        assert u.notify_balance is True
        assert u.notify_news is True

    def test_user_create_minimal(self) -> None:
        uc = UserCreate(id=123)
        assert uc.id == 123
        assert uc.username is None
        assert uc.referrer_id is None

    def test_optional_fields(self) -> None:
        u = User(id=1, username="test", first_name="John", last_name="Doe", referrer_id=999)
        assert u.username == "test"
        assert u.referrer_id == 999


class TestProjectModel:
    def test_defaults(self) -> None:
        p = Project(id=1, user_id=1, name="Test", company_name="Co", specialization="SEO")
        assert p.timezone == "Europe/Moscow"
        assert p.website_url is None

    def test_create_minimal(self) -> None:
        pc = ProjectCreate(user_id=1, name="Test", company_name="Co", specialization="SEO")
        assert pc.user_id == 1


class TestPlatformConnectionModel:
    def test_defaults(self) -> None:
        c = PlatformConnection(
            id=1, project_id=1, platform_type="wordpress", credentials={"token": "abc"}, identifier="x"
        )
        assert c.status == "active"
        assert c.metadata == {}

    def test_create(self) -> None:
        cc = PlatformConnectionCreate(
            project_id=1, platform_type="telegram", identifier="-100123"
        )
        assert cc.platform_type == "telegram"


class TestCategoryModel:
    def test_defaults_jsonb_fields(self) -> None:
        c = Category(id=1, project_id=1, name="SEO")
        assert c.keywords == []
        assert c.media == []
        assert c.reviews == []
        assert c.image_settings == {}
        assert c.text_settings == {}
        assert c.prices is None

    def test_create_minimal(self) -> None:
        cc = CategoryCreate(project_id=1, name="Test")
        assert cc.description is None


class TestPlatformContentOverrideModel:
    def test_nullable_settings(self) -> None:
        o = PlatformContentOverride(id=1, category_id=1, platform_type="wordpress")
        assert o.image_settings is None
        assert o.text_settings is None

    def test_create(self) -> None:
        oc = PlatformContentOverrideCreate(
            category_id=1, platform_type="vk", image_settings={"count": 2}
        )
        assert oc.image_settings == {"count": 2}


class TestPlatformScheduleModel:
    def test_defaults(self) -> None:
        s = PlatformSchedule(id=1, category_id=1, platform_type="wordpress", connection_id=1)
        assert s.schedule_days == []
        assert s.schedule_times == []
        assert s.posts_per_day == 1
        assert s.enabled is False
        assert s.qstash_schedule_ids == []
        assert s.last_post_at is None

    def test_create(self) -> None:
        sc = PlatformScheduleCreate(category_id=1, platform_type="telegram", connection_id=2)
        assert sc.posts_per_day == 1


class TestPublicationLogModel:
    def test_defaults(self) -> None:
        pl = PublicationLog(id=1, user_id=1, project_id=1, platform_type="wordpress")
        assert pl.content_type == "article"
        assert pl.images_count == 0
        assert pl.word_count == 0
        assert pl.tokens_spent == 0
        assert pl.status == "success"
        assert pl.category_id is None

    def test_create(self) -> None:
        plc = PublicationLogCreate(user_id=1, project_id=1, platform_type="telegram")
        assert plc.status == "success"


class TestTokenExpenseModel:
    def test_required_fields(self) -> None:
        te = TokenExpense(id=1, user_id=1, amount=-100, operation_type="text_generation")
        assert te.amount == -100
        assert te.cost_usd is None

    def test_create_with_cost(self) -> None:
        tec = TokenExpenseCreate(
            user_id=1, amount=-50, operation_type="api_openrouter", cost_usd=Decimal("0.0025")
        )
        assert tec.cost_usd == Decimal("0.0025")


class TestPaymentModel:
    def test_defaults(self) -> None:
        p = Payment(id=1, user_id=1, provider="stars", tokens_amount=3500)
        assert p.status == "pending"
        assert p.is_subscription is False
        assert p.referral_bonus_credited is False
        assert p.yookassa_payment_method_id is None

    def test_create(self) -> None:
        pc = PaymentCreate(user_id=1, provider="yookassa", tokens_amount=7200, amount_rub=Decimal("6000.00"))
        assert pc.amount_rub == Decimal("6000.00")


class TestSiteAuditModel:
    def test_optional_metrics(self) -> None:
        sa = SiteAudit(id=1, project_id=1, url="https://example.com")
        assert sa.performance is None
        assert sa.cls is None
        assert sa.recommendations == []

    def test_create(self) -> None:
        sac = SiteAuditCreate(project_id=1, url="https://example.com", performance=85)
        assert sac.performance == 85


class TestSiteBrandingModel:
    def test_defaults(self) -> None:
        sb = SiteBranding(id=1, project_id=1, url="https://example.com")
        assert sb.colors == {}
        assert sb.fonts == {}
        assert sb.logo_url is None

    def test_create(self) -> None:
        sbc = SiteBrandingCreate(
            project_id=1, url="https://example.com", colors={"primary": "#333"}
        )
        assert sbc.colors == {"primary": "#333"}


class TestArticlePreviewModel:
    def test_defaults(self) -> None:
        ap = ArticlePreview(id=1, user_id=1, project_id=1, category_id=1)
        assert ap.regeneration_count == 0
        assert ap.status == "draft"
        assert ap.images == []
        assert ap.connection_id is None

    def test_create(self) -> None:
        apc = ArticlePreviewCreate(user_id=1, project_id=1, category_id=1)
        assert apc.images == []


class TestPromptVersionModel:
    def test_defaults(self) -> None:
        pv = PromptVersion(id=1, task_type="seo_article", version="v5", prompt_yaml="test: true")
        assert pv.is_active is False
        assert pv.success_rate is None

    def test_create(self) -> None:
        pvc = PromptVersionCreate(task_type="keywords", version="v2", prompt_yaml="yaml content")
        assert pvc.is_active is False


class TestDatetimeHandling:
    def test_accepts_datetime_object(self) -> None:
        now = datetime.now()
        u = User(id=1, created_at=now, last_activity=now)
        assert u.created_at == now

    def test_accepts_iso_string(self) -> None:
        u = User(id=1, created_at="2026-01-01T00:00:00Z")
        assert isinstance(u.created_at, datetime)
