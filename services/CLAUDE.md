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
- MODEL_CHAINS по задачам (docs/API_CONTRACTS.md §3.1):
  article: claude-sonnet-4.5 → gpt-5.2 → deepseek-v3.2
  social_post: deepseek-v3.2 → claude-sonnet-4.5
  keywords: deepseek-v3.2 → gpt-5.2
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
