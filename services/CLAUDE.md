# Модуль services/ — Бизнес-логика

## Принцип: ZERO зависимости от Telegram/Aiogram
Сервисы принимают и возвращают Pydantic-модели. Никакого Bot, Message, CallbackQuery.

## Паттерн сервиса
```python
class ArticleService:
    def __init__(self, ai: AIOrchestrator, db: SupabaseClient):
        self.ai = ai
        self.db = db

    async def generate(self, context: GenerationContext) -> GenerationResult:
        # Бизнес-логика без зависимости от Telegram
```

## services/ai/
- orchestrator.py — AIOrchestrator: generate(), generate_stream()
- MODEL_CHAINS по задачам (docs/API_CONTRACTS.md §3.1, 7 task types):
  article: claude-sonnet-4.5 → gpt-5.2 → deepseek-v3.2
  social_post: deepseek-v3.2 → claude-sonnet-4.5
  keywords: deepseek-v3.2 → gpt-5.2
  review: deepseek-v3.2 → claude-sonnet-4.5
  description: deepseek-v3.2 → claude-sonnet-4.5
  competitor_analysis: gpt-5.2 → claude-sonnet-4.5
  image: gemini-3-pro-image → gemini-2.5-flash-image
- OpenAI SDK с base_url="https://openrouter.ai/api/v1"
- extra_body.models для нативных fallbacks
- response_format: json_schema + strict: true для structured outputs
- Streaming через SSE
- prompts/ — YAML-файлы с Jinja2 (разделители <<>>, <%%>)
- **Phase 10 rework**: article_v5→v6 (clusters, images_meta), keywords_v2→v3 (data-first), WebP, parallel pipeline

## services/publishers/
- BasePublisher(ABC): validate_connection(), publish(), delete_post()
- WordPressPublisher: WP REST API, Basic Auth, загрузка media
- TelegramPublisher: Bot API через бот пользователя, caption 1024 / text 4096
- VKPublisher: VK API v5.199, photo 3-step upload, wall.post
- PinterestPublisher: API v5, refresh_token при expires_at < now() + 1 day

## services/external/
- TelegraphClient: create_page(), delete_page() — РЕАЛИЗОВАН (Phase 7)
- FirecrawlClient: /scrape (markdown), crawl_site, branding — Phase 10
- DataForSEOClient: keyword_suggestions, related_keywords, enrich — Phase 10
- SerperClient: search() с кешем 24ч в Redis — Phase 10
- PageSpeedClient: audit(url) — Phase 10

## services/tokens.py
- check_balance(user_id, required) → bool
- charge(user_id, amount, operation_type, metadata) → bool
- refund(user_id, amount, reason) → bool
- Формула: ceil(word_count / 100) × 10
- GOD_MODE (ADMIN_ID): не списывать, показывать стоимость

## services/payments.py
- Stars: sendInvoice(currency="XTR", provider_token="")
- ЮKassa: Payment.create → redirect → webhook → начисление
- Подписки Stars: createInvoiceLink(subscription_period=2592000)
- Подписки ЮKassa: save_payment_method → payment_method_id → QStash cron

## services/scheduler.py (Phase 9)
- SchedulerService: QStash cron schedule management
- __init__(db, qstash_token, base_url) — wraps QStash SDK
- create_schedule() — DB insert + QStash cron creation for each time slot
- delete_schedule() — cancel QStash first, then delete DB row
- toggle_schedule() — enable/disable: creates or deletes QStash cron jobs
- cancel_schedules_for_category() — E24: cancel all QStash before CASCADE delete
- cancel_schedules_for_project() — E11: cancel all QStash for all project categories
- cancel_schedules_for_connection() — cancel QStash when connection removed
- estimate_weekly_cost() — static, calculates token cost per week
- Cron format: CRON_TZ={timezone} {min} {hour} * * {days}
- Injected via dp.workflow_data["scheduler_service"] + app["scheduler_service"]

## services/publish.py (Phase 9)
- PublishService: auto-publish pipeline triggered by QStash webhook
- __init__(db, redis, http_client, ai_orchestrator, image_storage, admin_ids)
- execute(PublishPayload) -> PublishOutcome(status, reason, post_url, keyword, tokens_spent, user_id, notify)
- Pipeline: load user -> load category -> check keywords (E17) -> load connection -> rotate keyword (E22/E23) -> check balance (E01) -> charge -> generate+publish -> log -> return
- Insufficient balance (E01): sets schedule enabled=False, status="error", deletes QStash crons via SchedulerService; notifies user if user.notify_publications is True
- Refund on any error after charge (with sentry capture if refund fails)
- TODO Phase 10: actual AI generation + publisher integration (currently logs placeholder)

## services/cleanup.py (Phase 9)
- CleanupService: daily cleanup triggered by QStash cron
- __init__(db, http_client, image_storage, admin_ids)
- execute() -> CleanupResult(expired_count, refunded[], logs_deleted, images_deleted)
- _expire_previews(): find expired draft previews, atomic_mark_expired (prevents double-processing), refund tokens, clean Supabase Storage images, delete Telegraph pages
  - Loads user to read notify_publications preference; each refund entry includes {user_id, keyword, tokens_refunded, notify_publications}
  - Cleanup handler in api/cleanup.py respects notify_publications before sending notification
- _delete_old_logs(): delegates to PublicationsRepository.delete_old_logs(cutoff_iso) (not inline SQL)

## services/notifications.py (Phase 9)
- NotifyService: batch notification builder (zero Telegram deps)
- __init__(db)
- build_low_balance(threshold=100) -> list[(user_id, text)] — users with low balance + notify_balance=True
- build_weekly_digest() -> list[(user_id, text)] — active users (30 days) + notify_news=True
- build_reactivation() -> list[(user_id, text)] — inactive users (>14 days)
