# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# SEO Master Bot v2

Telegram-бот для AI-powered SEO-контента. Пишем с нуля. Деплой: Railway.
Язык интерфейса: русский. Код и комментарии: английский.

## Стек
- Python 3.14, uv, Aiogram 3.25+ (Bot API 9.4)
- Supabase PostgreSQL 17, Upstash Redis (HTTP), Upstash QStash
- OpenRouter SDK 0.1.3 (AI), Firecrawl, DataForSEO, Serper
- Telegram Stars + YooKassa (платежи)
- Fernet encryption для credentials
- Jinja2 с разделителями (<< >>) для промптов
- Sentry + structlog JSON logging
- Railway (деплой, auto-build)

## Спецификации (ЕДИНСТВЕННЫЙ источник истины)
- docs/PRD.md — фичи F01-F46, токеномика, роадмап
- docs/ARCHITECTURE.md — стек, middleware, 13 таблиц SQL, паттерны
- docs/API_CONTRACTS.md — все API-контракты, MODEL_CHAINS, промпты
- docs/FSM_SPEC.md — 16 FSM StatesGroup, валидация, переходы
- docs/EDGE_CASES.md — E01-E42, обработка ошибок
- docs/USER_FLOWS_AND_UI_MAP.md — все экраны, навигация

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
- `tariff:pro:stars`, `quick:cat:12:wp:7`
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
uv run mypy bot/ routers/ services/ db/ api/ cache/ --check-untyped-defs  # проверка типов
```

## Stop hooks (выполняются автоматически при завершении)
При каждом завершении сессии автоматически запускаются pytest, ruff, mypy.
Если что-то красное — сессия блокируется до исправления. Держи код зелёным.

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
1. **Quick publish callback_data**: FSM_SPEC (`qp:`) vs ARCHITECTURE/API_CONTRACTS (`quick:`) — использовать `quick:`
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
- **Competitor scraping**: Firecrawl /scrape (markdown конкурентов) вместо /extract (только мета). article_v5→v6
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
- QStash Pro plan limits (#23) — проверить при росте числа расписаний
- F34 streaming edge cases (mid-stream error, rate limits) — не описаны

AI Pipeline Rework (Phase 10):
- article_v5→v6: кластерные промпты, images_meta, competitor_gaps, dynamic length
- keywords_v2→v3: data-first (DataForSEO → AI clustering), кластерный JSON
- Image SEO: WebP конвертация (Pillow), WP publisher alt_text/filename/caption
- Parallel pipeline: text + images через asyncio.gather
- Rotation: кластерная ротация (cluster_type, total_volume, main_phrase cooldown, <3 warning)

Решено из SEO-ревью #2 (февр. 2026):
- **Anti-cannibalization**: system prompt требует уникальность через данные компании; serper_questions random 3 of N; temperature 0.7
- **Image SEO**: images_meta (alt, filename, figcaption) в JSON-ответе AI; WebP конвертация; WP REST alt_text
- **Rank tracking**: publication_logs +rank_position +rank_checked_at; DataForSEO SERP API $0.002/проверка
- **Parallel pipeline**: text + images генерируются параллельно (asyncio.gather); 96с→56с
- **Cost per article**: $0.21-0.36 при цене 200 руб → маржа 80-90%

P2 (Phase 11+):
- **SERP intent check**: Serper → если >70% результатов e-commerce → пометить кластер "product_page" (не для статей)
- **Site re-crawl**: QStash cron раз в 14 дней → Firecrawl crawl → обновить internal_links ($0.08/сайт)
- **Content similarity**: simhash в publication_logs.content_hash → предупреждение при >70% совпадении
- **Rank tracking cron**: QStash раз в неделю → DataForSEO SERP → обновить rank_position

Решено: A/B тестирование промптов deferred to v3 (колонка ab_test_group убрана из схемы).

## Agent Teams (slash-команды)
```
/implement-module <path>  — реализация модуля (implementer agent)
/review-module <path>     — code review (reviewer agent, read-only)
/test-module <name>       — тесты до зелёного (tester agent)
/find-gaps <target>       — поиск дыр в спеках/коде/тестах (gap-finder agent)
/verify-spec              — сквозная проверка vs спецификации (integrator agent)
/enrich-specs <target>    — обновление rules/skills/specs (spec-enricher agent)
```

## Циклический пайплайн реализации фазы
```
Phase N:
  1. /implement-module   → implementer
  2. /review-module      → reviewer
  3. /test-module        → tester
  4. /find-gaps phase N  → gap-finder
     P0/P1 → назад к шагу 1
     Только P2 или PASS → шаг 5
  5. /verify-spec        → integrator
     Issues → назад к шагу 1
     PASS → Phase N DONE
```

## Контекстные правила (.claude/rules/)
Правила из `.claude/rules/` автоматически применяются к файлам по path-glob:
- `python-style.md` → `**/*.py` (ruff, mypy, type hints)
- `security.md` → `**/*.py` (Fernet, SQL injection, rate limits)
- `testing.md` → `tests/**/*.py` (pytest-asyncio, httpx.MockTransport, naming)
- `edge-cases.md` → `routers/`, `services/`, `api/` (E01-E42 чеклист)
- `aiohttp-handlers.md` → `api/**/*.py` (thin handlers, shared http_client, Service Layer)

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
