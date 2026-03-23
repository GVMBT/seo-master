# Архив архитектурных решений

Решения и расхождения, зафиксированные в ходе разработки (фев-мар 2026).
Актуальные правила — в `.claude/CLAUDE.md`.

## Известные расхождения в спеках (audit.md + февр. 2026)
Спеки — source of truth. Конфликты (из аудита Part 1):
1. **~~Quick publish callback_data~~**: Заменено Pipeline — `pipeline:article:*`, `pipeline:social:*` (UX_PIPELINE.md)
2. ~~**VK credentials field**~~: РЕШЕНО — оба файла используют `"access_token"`
3. **platform_schedules.status**: колонка `status` ДОБАВЛЕНА в схему (ARCHITECTURE.md §3.2), active | error

Решено из аудита Part 2 (#21-#43, февр. 2026):
- #21 aiohttp: §2.3 добавлен в ARCHITECTURE.md — api/ на aiohttp.web
- #22 atomic balance: §5.5 — RPC-функции charge_balance/refund_balance/credit_balance
- #24 backpressure: §5.6 — asyncio.Semaphore(10) для publish webhook
- #25 RLS: уточнено — RLS НЕ используется, service_role key, row filtering в Repository
- #26 XSS: §5.8 — nh3 санитизация HTML перед публикацией
- #27 health security: Bearer token для детального health check
- #28 regen cost: фиксируется на первой генерации
- #29 FSM conflict: автосброс текущей FSM при входе в новую
- #31 referral renewal: бонус на КАЖДЫЙ successful_payment включая продления
- #35 cost estimate: OpenRouter ~$1000-1500/мес (изображения 63% бюджета)
- #37 Realtime: убрано из стека
- #38 social post storage: FSM state.data (Redis), потеря при таймауте допустима
- #39 image.yaml: image_number + variation_hint для multi-image
- #40 social regen: 2 бесплатных, аналогично ArticlePublish
- #42 graceful shutdown: §5.7 — SIGTERM + 120с drain
- #43 multiple WP: шаг выбора подключения при >1 WP

Решено из SEO-ревью (февр. 2026):
- **Data-first keywords**: DataForSEO keyword_suggestions/related → AI кластеризация → enrich (не "AI фантазирует → DataForSEO валидирует")
- **Keyword clustering**: categories.keywords хранит кластеры (cluster_name, main_phrase, phrases[]), не плоский список. Ротация по кластерам §6
- **Competitor scraping**: Firecrawl v2 /scrape (markdown) + /extract (LLM-structured competitor data). article_v5→v7
- **Dynamic article length**: median(конкуренты) × 1.1, cap [1500, 5000]. Fallback на text_settings
- **Competitor gaps**: AI определяет темы, которых нет у конкурентов → уникальная ценность статьи

Решено:
- Хранение изображений: Supabase Storage bucket `content-images` для промежуточного хранения (ARCHITECTURE.md §5.9). Генерация → in-memory → WebP → Supabase Storage (24ч) → publish на платформу
- Стриминг (F34) — editMessage spec есть в API_CONTRACTS §3.1

Решено (Phase 9):
- **QStash schedule management**: SchedulerService wraps QStash SDK; injected via dp.workflow_data["scheduler_service"] + app["scheduler_service"]
- **Backpressure**: PUBLISH_SEMAPHORE(10) + SHUTDOWN_EVENT in bot/main.py; publish_handler acquires semaphore with 300s timeout
- **Idempotency**: all QStash handlers (publish/cleanup/notify) use `Upstash-Message-Id` header for Redis NX lock (unique per trigger, same on retry)
- **Cron format**: numeric DOW via `_DAY_MAP` (API_CONTRACTS §1.8); `CRON_TZ={tz} {min} {hour} * * {numeric_days}`
- **QStash signature**: `require_qstash_signature` decorator in api/__init__.py; Receiver.verify()
- **QStash SDK sync calls**: wrapped in `asyncio.to_thread()` (scheduler.py, health.py)
- **Notifications delivery**: _send_notifications() in api/notify.py; TelegramRetryAfter retry, 50ms spacing; checks `notify_publications`
- **Cleanup refund**: atomic_mark_expired prevents double-processing; refund + notify user (if notify_publications) + clean images + delete Telegraph
- **Insufficient balance**: schedule → `enabled=False, status="error"` + delete QStash cron jobs via SchedulerService
- **E42 preview refund**: both project delete (card.py) and category delete (manage.py) refund active previews before CASCADE
- **Partial QStash cleanup**: if schedule creation fails midway, already-created schedules are cleaned up
- **Auto-publish notifications**: Russian templates per EDGE_CASES.md (_REASON_TEMPLATES in api/publish.py); no_keywords/connection_inactive/insufficient_balance all use `notify_publications` preference

Решено (Phase 10.1 — Research step):
- **Web Research**: Perplexity Sonar Pro Search (perplexity/sonar-pro-search) через OpenRouter. Agentic multi-step search, structured outputs
- **Pipeline**: Research параллельно с Serper (шаг 2b). current_research → Outline + Expand + Critique (3 разных wording)
- **Cache**: Redis `research:{md5(keyword)[:12]}`, TTL 7 дней. Cost ~$0.01/req, amortized ~$0.005
- **Graceful degradation**: E53 — Sonar недоступен → pipeline продолжает без research, warning в лог
- **Prompt wording**: Outline="используй для планирования", Expand="приоритизируй при противоречиях", Critique="используй для верификации"

Нерешённые вопросы:
- QStash Pro plan limits (#23) — проверить при росте числа расписаний (schedule limits не документированы публично)
- ~~F34 streaming edge cases~~ — Закрыто: F34 replaced by progress messages (UX_PIPELINE.md §11), deferred to v3 via sendMessageDraft

Goal-Oriented Pipeline (Phase 13 — UX_PIPELINE.md):
- Pipeline заменяет Quick Publish: воронка "Написать статью" / "Пост в соцсети" (2-3 клика для returning users)
- ArticlePipelineFSM (25 состояний), SocialPipelineFSM (28 состояний) — итого 15 StatesGroup
- Inline handlers (NOT FSM delegation): pipeline реализует sub-flows внутри себя, переиспользуя Service Layer
- ReadinessService: чеклист готовности (keywords обяз., description обяз. для новичков, prices/media опциональны)
- ButtonStyle (Bot API 9.4): PRIMARY/SUCCESS/DANGER семантика, макс. 1 PRIMARY на экране
- Checkpoint: Redis `pipeline:{user_id}:state` (TTL 24h), возобновление с Dashboard (E49)
- Кросс-постинг: AI-адаптация (cross_post task_type), обязательный ревью (E52)
- Фазирование: A (Core Pipeline) → B (Readiness + inline sub-flows) → C (Social + кросс-пост) → D (Presets + batch)
- Checklist UX: editMessageText для простых sub-flows, deleteMessage+send для сложных (3+ промежуточных сообщений)

AI Pipeline Rework (Phase 10):
- article_v6→v7: multi-step (outline→expand→critique), Markdown output, anti-slop, niche specialization
- Multi-step: Outline (DeepSeek) → Expand (Claude) → Conditional Critique (DeepSeek, if score < 80)
- **Research step (Phase 10.1)**: Perplexity Sonar Pro → JSON Schema (facts, trends, statistics) → current_research в Outline + Expand + Critique
- Research parallel with Serper (шаг 2b), Redis cache 7d, graceful degradation E53
- Markdown → HTML: mistune 3.x + SEORenderer (heading IDs, ToC, figure/figcaption, lazy loading)
- ContentQualityScorer: программная SEO-оценка (0-100), 5 категорий, quality gates
- Anti-hallucination: <VERIFIED_DATA> блок + regex fact-checking (цены, контакты, статистика)
- Niche specialization: detect_niche() → 15+1 ниш, YMYL disclaimers, tone modules
- Anti-slop blacklist: ~20 запрещённых слов-штампов AI в system prompt
- keywords_v2→v3: data-first (DataForSEO → AI clustering), кластерный JSON
- Image improvements: negative prompts, niche style presets, post-processing (Pillow), smart aspect ratio
- **Image Director (§7.4.2)**: AI-слой промпт-инжиниринга между text и image generation. DeepSeek V3.2 (reasoning) анализирует статью + секции → structured JSON (prompt, negative_prompt, aspect_ratio per image). ~$0.001/статья, +3-5с. Graceful degradation E54 → механические промпты
- WP publisher: WebP + images_meta (alt_text, filename, caption) через WP REST
- Parallel pipeline: text + images через asyncio.gather; 96с→56с
- Rotation: кластерная ротация (cluster_type, total_volume, main_phrase cooldown, <3 warning)
- SimHash: content uniqueness check в publication_logs.content_hash (warning при >70% совпадении)
- NLP зависимости: razdel (токенизация), pymorphy3 (морфология), mistune (Markdown→HTML)
- Персона: "контент-редактор в штате компании" (не "SEO-копирайтер")
- Temperature: 0.6 для статей (не 0.7)
- Cost per article: ~$0.31 avg (multi-step + research +$0.01), маржа ~91%

P2 (Phase 11+):
- **SERP intent check**: Serper → если >70% результатов e-commerce → пометить кластер "product_page" (не для статей)
- **Site re-crawl**: QStash cron раз в 14 дней → Firecrawl /map → обновить internal_links ($0.001/сайт)
- **Rank tracking cron**: QStash раз в неделю → DataForSEO SERP → обновить rank_position

Решено: A/B тестирование промптов deferred to v3 (колонка ab_test_group убрана из схемы).

Решено — Firecrawl v2 API (февр. 2026, native httpx, NOT SDK):
- **v1→v2 migration**: base URL `/v2/`, httpx.AsyncClient (shared), NO firecrawl-py SDK
- **`/v2/scrape`**: markdown конкурентов. 1 credit/page. Cache 24h
- **`/v2/map`**: internal links (NOT /crawl). 1 credit per 5000 URLs. Cache 14d
- **`/v2/extract` (NEW)**: LLM-structured data extraction via JSON Schema. ~5 credits. Used for:
  - `scrape_branding()` → real CSS colors/fonts via `_BRANDING_SCHEMA` (NOT hardcoded fallbacks)
  - ~~`extract_competitor()`~~ — deferred to v3 (F39 standalone competitor analysis removed from v2)
- **`/v2/search` (NEW)**: search + scrape in one call. 2 credits/10 results. Potential Serper replacement (but no PAA)
- **DataForSEO**: остаётся (keyword volumes/CPC/difficulty — Firecrawl этого не умеет)
- **Serper**: остаётся (People Also Ask для антиканнибализации — Firecrawl /search не возвращает PAA)
- **Firecrawl `/agent` (Spark)**: deferred to v3 (Research Preview, динамическая цена)
- **Firecrawl `changeTracking`**: deferred to v3 (F45)

Решено — Аудит всех сервисов (февр. 2026):
- **OpenRouter**: SDK через `openai` с `base_url` — по-прежнему правильный подход. Новое: расширенные provider routing параметры (`max_price`, `preferred_min_throughput`, `quantizations`, `only`/`ignore`). Prompt caching Claude: $0.30/M vs $3.00/M (90% экономии). Seedream 4.5 — потенциальный 3-й image fallback ($0.04/img)
- **DataForSEO**: v3 API, v2 sunset 5 мая 2026. Ценовая коррекция: suggestions/related ~$0.01/req (не $0.0015). Новое: `search_intent/live` (ground-truth intent), `keyword_suggestions_for_url` (ключевики конкурента), `stop_crawl_on_match` (50% экономии rank tracking)
- **Serper**: КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ — 2500 free credits одноразово (НЕ ежемесячно). Starter $50/50K кредитов. PAA возвращает objects `{question, snippet, link}` (не plain strings). `/autocomplete` — потенциальный E03 fallback
- **Upstash Redis**: Redis Functions (server-side Lua) — оптимизация rate limiter. QStash: free tier 1000 msg/day, local dev server, Batch API. Upstash Workflow — deferred to v3
- **Supabase**: PostgREST v14 (20% быстрее GET). Signed URLs для content-images bucket. Image Transformations для thumbnail. **BUG: postgrest>=2.28 → >=2.27** (исправлен)
- **Telegram Bot API 9.4 + Aiogram 3.25**: мы на последних версиях. `sendMessageDraft` (9.3) — нативный стриминг (но требует forum topics). `getMyStarBalance` (9.1) — для health check
- **Все модели OpenRouter актуальны**: Claude Sonnet 4.5, DeepSeek V3.2, GPT-5.2, Gemini image — цены и ID без изменений

