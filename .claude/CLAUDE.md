# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# SEO Master Bot v2

Telegram-бот для AI-powered SEO-контента. Пишем с нуля. Деплой: Railway.
Язык интерфейса: русский. Код и комментарии: английский.

## Стек
- Python 3.14, uv, Aiogram 3.25+ (Bot API 9.4)
- Supabase PostgreSQL 17, Upstash Redis (HTTP), Upstash QStash
- OpenRouter SDK 0.1.3 (AI), Firecrawl v2 (native httpx), DataForSEO v3, Serper
- Telegram Stars + YooKassa (платежи)
- Fernet encryption для credentials
- Jinja2 с разделителями (<< >>) для промптов
- Sentry + structlog JSON logging
- Railway (деплой, auto-build)

## Спецификации (ЕДИНСТВЕННЫЙ источник истины)
- docs/PRD.md — фичи F01-F46, токеномика, роадмап
- docs/ARCHITECTURE.md — стек, middleware, 13 таблиц SQL, паттерны
- docs/API_CONTRACTS.md — все API-контракты, MODEL_CHAINS, промпты
- docs/FSM_SPEC.md — 14 FSM StatesGroup, валидация, переходы
- docs/EDGE_CASES.md — E01-E52, обработка ошибок
- docs/UX_PIPELINE.md — Pipeline UX: Dashboard, статьи, соцсети, кросс-постинг
- docs/UX_TOOLBOX.md — Toolbox UX: проекты, категории, подключения, профиль, токены

ПЕРЕД реализацией любого модуля — ПРОЧИТАЙ соответствующие секции спеков.
НЕ выдумывай имена таблиц, колонок, env vars — бери ТОЛЬКО из спеков.

## Архитектура (docs/ARCHITECTURE.md §2)
```
bot/            — main.py, config.py, exceptions.py, middlewares/ (запуск, конфиг, ошибки, middleware)
routers/        — Aiogram роутеры: nested packages (projects/, categories/, platforms/, publishing/, admin/)
keyboards/      — reply.py, inline.py, pagination.py (UI-клавиатуры, PAGE_SIZE=8)
services/       — бизнес-логика (ZERO зависимости от Telegram/Aiogram)
db/             — client.py, models.py, credential_manager.py, repositories/ (Repository pattern, Fernet)
api/            — HTTP-эндпоинты (QStash webhooks, YooKassa, Pinterest OAuth, health)
cache/          — Redis client, FSM storage, key namespaces
platform_rules/ — валидация контента по платформам
tests/          — зеркалит top-level: unit/bot/, unit/db/, unit/routers/, unit/keyboards/
```
Каждый модуль имеет свой CLAUDE.md с деталями реализации — читай его перед работой с модулем.

## Ключевые архитектурные границы
- **routers/ → services/**: роутеры делегируют всю логику. SQL, токены, API-вызовы — только в services/.
- **services/ → db/repositories/**: сервисы не делают SQL напрямую.
- **credentials**: encrypt/decrypt ТОЛЬКО в db/repositories/ через CredentialManager.
- **Удаление с QStash**: ВСЕГДА отменить QStash-расписания ПЕРЕД CASCADE delete (E11, E24).

## callback_data формат
`{entity}:{id}:{action}` или `{entity}:{id}:{sub}:{sub_id}:{action}`
Максимум 64 байта. Числовые ID. Примеры:
- `project:5:card`, `category:12:edit`
- `tariff:pro:stars`, `pipeline:article:5:wp:7`
- `page:projects:2`

## Токеновая экономика
- 1 токен = 1 рубль, 1500 welcome bonus
- Текст: ceil(word_count / 100) * 10, Изображение: 30, Ключевые фразы: 50-200, Аудит: 50
- Списание в момент ГЕНЕРАЦИИ (до превью), возврат при ошибке
- GOD_MODE (ADMIN_ID): не списывать, показывать стоимость

## Команды
```bash
uv run pytest tests/ -x -v                # тесты (один файл: -k "test_name")
uv run ruff check . --select=E,F,I,S,C901,B,UP,SIM,RUF  # расширенный линтинг
uv run ruff format .                       # форматирование
uv run mypy bot/ services/ db/ api/ cache/ --check-untyped-defs  # проверка типов
uv run bandit -r bot/ services/ db/ api/ cache/ platform_rules/ -ll  # безопасность (Medium+)
uv run vulture bot/ services/ db/ api/ cache/ platform_rules/ --min-confidence 80  # мёртвый код
```

## Stop hooks (выполняются автоматически при завершении)
При каждом завершении сессии автоматически запускаются pytest, ruff, mypy.
Если что-то красное — сессия блокируется до исправления. Держи код зелёным.

## Статический анализ (полный набор)
- **ruff** — линтинг + форматирование (расширенные правила)
- **mypy** — type checking
- **bandit** — сканер безопасности (`-ll` = Medium+ severity, `# nosec BXXX` для осознанных исключений)
- **vulture** — обнаружение мёртвого кода (`--min-confidence 80`)
- **ty** (Astral) — когда выйдет stable, заменит mypy + vulture

## Стандарты кода
- async/await повсюду, type hints обязательны (`X | None`, не `Optional[X]`)
- Pydantic v2 для моделей, Pydantic Settings для конфига
- structlog JSON logging, не print()
- Параметризованные SQL запросы ВСЕГДА
- Кастомные исключения наследуют от базового AppError
- Max line length: 120, cyclomatic complexity: 15
- `db` параметр в хендлерах: `db: SupabaseClient` (НЕ `object`, НЕ `Any`)
- `assert` запрещён в продакшен-коде — используй `if not x: raise AppError(...)`
- `callback.message`: ВСЕГДА проверяй на None/InaccessibleMessage перед доступом
- FSM-классы: суффикс `*FSM` (ProjectCreateFSM, CategoryCreateFSM, etc.)

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
- Markdown → HTML: mistune 3.x + SEORenderer (heading IDs, ToC, figure/figcaption, lazy loading)
- ContentQualityScorer: программная SEO-оценка (0-100), 5 категорий, quality gates
- Anti-hallucination: <VERIFIED_DATA> блок + regex fact-checking (цены, контакты, статистика)
- Niche specialization: detect_niche() → 15+1 ниш, YMYL disclaimers, tone modules
- Anti-slop blacklist: ~20 запрещённых слов-штампов AI в system prompt
- keywords_v2→v3: data-first (DataForSEO → AI clustering), кластерный JSON
- Image improvements: negative prompts, niche style presets, post-processing (Pillow), smart aspect ratio
- WP publisher: WebP + images_meta (alt_text, filename, caption) через WP REST
- Parallel pipeline: text + images через asyncio.gather; 96с→56с
- Rotation: кластерная ротация (cluster_type, total_volume, main_phrase cooldown, <3 warning)
- SimHash: content uniqueness check в publication_logs.content_hash (warning при >70% совпадении)
- NLP зависимости: razdel (токенизация), pymorphy3 (морфология), mistune (Markdown→HTML)
- Персона: "контент-редактор в штате компании" (не "SEO-копирайтер")
- Temperature: 0.6 для статей (не 0.7)
- Cost per article: ~$0.30 avg (multi-step +$0.02), маржа ~91%

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

## Agent Teams (slash-команды)
```
/implement-module <path>  — реализация модуля (implementer agent)
/review-module <path>     — code review (reviewer agent, read-only)
/test-module <name>       — тесты до зелёного (tester agent)
/find-gaps <target>       — поиск дыр в спеках/коде/тестах (gap-finder agent)
/verify-spec              — сквозная проверка vs спецификации (integrator agent)
/enrich-specs <target>    — обновление rules/skills/specs (spec-enricher agent)
```

## Регламент вызова агентов (ОБЯЗАТЕЛЬНО к исполнению)

Агенты вызываются АВТОМАТИЧЕСКИ — без запроса пользователя — в следующих ситуациях:

### A. Пайплайн реализации фазы
```
Phase N:
  1. /find-gaps phase N  → gap-finder (ДО начала кода — найти дыры в спеках)
     P0/P1 в спеках → /enrich-specs → исправить спеки → повторить find-gaps
     PASS → шаг 2
  2. /implement-module   → implementer
  3. /review-module      → reviewer
  4. /test-module        → tester
  5. /find-gaps phase N  → gap-finder (ПОСЛЕ кода — найти дыры между спеками и кодом)
     P0/P1 → назад к шагу 2
     Только P2 или PASS → шаг 6
  6. /verify-spec        → integrator
     Issues → назад к шагу 2
     PASS → Phase N DONE
```

### B. После обновления внешних зависимостей
Когда обновляется API библиотеки (Firecrawl, Bot API, OpenRouter, etc.):
```
  1. /enrich-specs <library>  → обновить спеки актуальной документацией
  2. /find-gaps               → проверить что код и спеки синхронизированы
  3. Исправить код/спеки если нужно
```

### C. Начало новой сессии (если прошло >2 сессий с последнего аудита)
```
  1. /find-gaps full          → полный аудит спеков, кода и тестов
  2. Приоритизация: P0 → fix немедленно, P1 → в план, P2 → backlog
```

### D. После крупных изменений в спеках
Когда обновляются docs/*.md (новые фичи, изменение схемы, новые edge cases):
```
  1. /find-gaps               → проверить целостность после изменений
  2. /verify-spec             → проверить что существующий код соответствует
```

### E. Перед релизом / мержем в main
```
  1. /find-gaps full          → финальный аудит
  2. /verify-spec             → сквозная проверка
  3. pytest + ruff + mypy     → всё зелёное
```

## Контекстные правила (.claude/rules/)
Правила из `.claude/rules/` автоматически применяются к файлам по path-glob:
- `python-style.md` → `**/*.py` (ruff, mypy, type hints)
- `security.md` → `**/*.py` (Fernet, SQL injection, rate limits)
- `testing.md` → `tests/**/*.py` (pytest-asyncio, httpx.MockTransport, naming)
- `edge-cases.md` → `routers/`, `services/`, `api/` (E01-E52 чеклист)
- `aiohttp-handlers.md` → `api/**/*.py` (thin handlers, shared http_client, Service Layer)
- `pipeline.md` → `routers/publishing/pipeline/**/*.py` (inline handlers, checkpoint, ButtonStyle, exit protection)

## MCP-серверы (настроены в settings.json)
- **supabase** — управление БД, миграции, SQL через MCP
- **upstash** — Redis (run commands, list keys, databases) + Upstash API (НЕ QStash schedules)
- **context7** — поиск актуальной документации библиотек (Aiogram, Pydantic, etc.)

## Фазы разработки
Полный план в `.progress/phases.md` (12 фаз). Текущий статус в `.progress/current.md`.

## Контекст-менеджмент
При длинных сессиях: обнови `.progress/current.md` перед /compact или /clear.
Новая сессия: "Прочитай .progress/current.md и продолжай."

## Модель
ТОЛЬКО claude-opus-4-6. Никаких sonnet/haiku.
