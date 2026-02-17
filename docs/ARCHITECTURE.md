# SEO Master Bot v2 — Техническая архитектура

> Связанные документы: [PRD.md](PRD.md) (продуктовые требования), [API_CONTRACTS.md](API_CONTRACTS.md) (QStash, Stars, rate limits, сервисные контракты, промпты, ротация фраз), [FSM_SPEC.md](FSM_SPEC.md) (FSM-состояния и валидация), [EDGE_CASES.md](EDGE_CASES.md) (обработка ошибок), [UX_PIPELINE.md](UX_PIPELINE.md) + [UX_TOOLBOX.md](UX_TOOLBOX.md) (UX-спецификации)

---

## 1. Стек технологий

| Слой | Технология | Назначение |
|------|-----------|------------|
| Рантайм | Python 3.14.3 | JIT-компилятор, +25% производительности |
| Пакетный менеджер | uv | В 100 раз быстрее pip |
| Фреймворк бота | Aiogram 3.25+ | Async, роутеры, FSM, middleware, Bot API 9.4 |
| База данных | Supabase (PostgreSQL 17) | Managed, миграции, Row Filtering в Repository layer. RLS включён на всех таблицах (defense-in-depth), но политики не создаются — используется service_role key, который обходит RLS |
| Кеш/Состояние | Upstash Redis | Хранение FSM, лимиты запросов, кеширование |
| Планировщик | Upstash QStash | Бессерверный cron, гарантированная доставка |
| AI-модели | OpenRouter (OpenAI-совместимый API) | 300+ моделей, fallbacks, structured outputs, prompt caching, streaming. Контракт: [API_CONTRACTS.md §3.1](API_CONTRACTS.md) |
| Веб-данные | Firecrawl API | Branding v2, `/map` (URL discovery), `/scrape` (markdown + summary), `/extract` (structured SEO) |
| Аудит сайтов | Google PageSpeed API | Бесплатный, всесторонний аудит |
| SEO-данные | DataForSEO API | Реальные объемы поиска, сложность ключевиков |
| Web Search | Serper API | Актуальные данные Google для промптов статей |
| Предпросмотр статей | Telegraph API | Бесплатное превью перед публикацией |
| Markdown → HTML | mistune 3.x + SEORenderer | Детерминистичный HTML: heading IDs, ToC, figure, lazy loading |
| NLP (русский) | razdel + pymorphy3 | Токенизация, морфология для ContentQualityScorer |
| Изображения | Pillow (PIL) | WebP-конвертация + post-processing (sharpen, contrast, color) |
| Платежи | Telegram Stars + ЮKassa | Нативные + карточные платежи |
| Мониторинг | Sentry + структурированный логгинг | Отслеживание ошибок, производительность |

---

## 2. Структура проекта

```
seo-master-bot-v2/
├── bot/
│   ├── main.py                     # Запуск Aiogram, вебхук, lifecycle
│   ├── config.py                   # Pydantic Settings v2
│   ├── exceptions.py               # AppError hierarchy (9 классов)
│   └── middlewares/
│       ├── db.py                   # DBSessionMiddleware (outer)
│       ├── auth.py                 # AuthMiddleware + FSMInactivityMiddleware
│       ├── throttling.py           # ThrottlingMiddleware (Redis INCR+EXPIRE)
│       └── logging.py             # LoggingMiddleware (correlation_id, latency)
│
├── keyboards/                      # Клавиатуры Telegram
│   ├── inline.py                   # Inline-клавиатуры (проекты, категории, настройки)
│   ├── reply.py                    # Reply-клавиатуры (главное меню, cancel, skip)
│   ├── pipeline.py                # Pipeline-клавиатуры (CTA, readiness, confirmation, preview)
│   └── pagination.py              # Generic paginator (PAGE_SIZE=8)
│
├── routers/                        # Роутеры Aiogram (~25 роутеров вместо 382 обработчиков)
│   ├── start.py                    # /start, главное меню
│   ├── projects/
│   │   ├── create.py               # FSM быстрый старт (4 поля) + редактирование (11 доп.)
│   │   ├── card.py                 # Карточка проекта и действия
│   │   └── list.py                 # Список с пагинацией
│   ├── categories/
│   │   ├── manage.py               # CRUD
│   │   ├── keywords.py             # Генерация SEO ключевых фраз (FSM)
│   │   ├── media.py                # Медиа-галерея
│   │   ├── prices.py               # Загрузка/скачивание Excel
│   │   └── reviews.py              # AI-генерация отзывов
│   ├── platforms/
│   │   ├── connections.py          # Добавление/удаление/валидация всех платформ
│   │   └── settings.py             # Настройки контента по платформам
│   ├── publishing/
│   │   ├── preview.py              # Telegraph-предпросмотр + подтверждение
│   │   ├── social.py               # (legacy, replaced by SocialPipelineFSM)
│   │   ├── scheduler.py            # Настройка расписания (FSM)
│   │   └── pipeline/               # Goal-Oriented Pipeline (замена Quick Publish)
│   │       ├── __init__.py          # Регистрация роутеров
│   │       ├── article.py           # ArticlePipelineFSM (25 состояний, шаги 1-8 + inline sub-flows)
│   │       ├── social.py            # SocialPipelineFSM (28 состояний, соц. посты + кросс-постинг)
│   │       └── readiness.py         # Inline readiness handlers (sub-flows через Service Layer)
│   ├── profile.py                  # Профиль, расходы, реферал
│   ├── tariffs.py                  # Пакеты + Telegram Stars
│   ├── settings.py                 # Пользовательские настройки
│   ├── help.py                     # Встроенная справка (F46)
│   ├── analysis.py                 # Аудит сайта (Firecrawl + PSI)
│   └── admin/
│       ├── dashboard.py            # Статистика, статус AI, статус БД
│       ├── broadcast.py            # Рассылки
│       └── monitoring.py           # Системные метрики, логи
│
├── services/                       # Бизнес-логика (без зависимости от Telegram)
│   ├── ai/
│   │   ├── orchestrator.py         # Маршрутизация OpenRouter + резерв + исправление
│   │   ├── articles.py             # Генерация SEO-статей
│   │   ├── social_posts.py         # Генерация постов для TG/VK/Pinterest
│   │   ├── keywords.py             # Генерация семантического ядра
│   │   ├── images.py               # Генерация изображений (Nano Banana / Gemini via OpenRouter)
│   │   ├── reviews.py              # Генерация отзывов
│   │   ├── description.py          # Генерация описаний категорий
│   │   ├── content_validator.py    # Валидация контента перед публикацией (nh3, лимиты)
│   │   ├── quality_scorer.py       # ContentQualityScorer: программная SEO-оценка (0-100)
│   │   ├── markdown_renderer.py    # SEORenderer (mistune): Markdown → HTML с heading IDs, ToC
│   │   ├── niche_detector.py       # detect_niche(): specialization → 15+1 ниш, YMYL
│   │   ├── anti_hallucination.py   # check_fabricated_data(): regex fact-checking (цены, контакты)
│   │   ├── rate_limiter.py         # Per-action rate limits (token-bucket в Redis)
│   │   ├── prompt_engine.py        # Jinja2 рендеринг промптов (<< >> delimiters)
│   │   └── prompts/                # YAML-шаблоны промптов (seed → DB prompt_versions)
│   │       ├── article_v7.yaml          # v7: multi-step, Markdown output, anti-slop, niche
│   │       ├── article_outline_v1.yaml  # v1: outline generation (DeepSeek, multi-step stage 1)
│   │       ├── article_critique_v1.yaml # v1: conditional critique (DeepSeek, stage 3)
│   │       ├── social_v3.yaml           # v3: social posts for TG/VK/Pinterest
│   │       ├── keywords_cluster_v3.yaml  # v3: data-first clustering
│   │       ├── keywords_v2.yaml         # v2: legacy AI-only (fallback при E03)
│   │       ├── image_v1.yaml            # v1: image generation prompts (+ niche styles, negatives)
│   │       ├── review_v1.yaml           # v1: review generation
│   │       ├── description_v1.yaml      # v1: category description generation
│   │       └── cross_post_v1.yaml          # v1: text adaptation between platforms (Pipeline кросс-постинг)
│   ├── publishers/
│   │   ├── base.py                 # BasePublisher (валидация -> публикация -> отчет)
│   │   ├── wordpress.py            # WP REST API
│   │   ├── telegram.py             # Bot API
│   │   ├── vk.py                   # VK API
│   │   └── pinterest.py            # Pinterest API v5
│   ├── external/
│   │   ├── firecrawl.py            # Клиент Firecrawl (/map, /scrape+summary, branding v2, /extract)
│   │   ├── pagespeed.py            # Клиент Google PSI
│   │   ├── dataforseo.py           # Клиент DataForSEO (объемы, сложность ключевиков)
│   │   ├── serper.py               # Клиент Serper (поиск Google в реальном времени)
│   │   └── telegraph.py            # Клиент Telegraph API (предпросмотр статей)
│   ├── tokens.py                   # Токеновая экономика (проверка, списание, возврат)
│   ├── storage.py                  # ImageStorage: Supabase Storage upload/cleanup (§5.9)
│   ├── notifications.py            # Автоуведомления
│   ├── readiness.py               # ReadinessService: чеклист готовности для Pipeline
│   └── payments/                   # Платежи
│       ├── packages.py             # Пакеты и тарифы
│       ├── stars.py                # Telegram Stars
│       └── yookassa.py             # YooKassa (recurring + autopayments)
│
├── db/
│   ├── client.py                   # Асинхронный клиент Supabase (postgrest)
│   ├── models.py                   # Pydantic-модели (35 моделей для 13 таблиц)
│   ├── credential_manager.py       # Fernet encrypt/decrypt для credentials
│   ├── repositories/               # Паттерн Repository
│   │   ├── base.py                 # BaseRepository + typed PostgREST helpers
│   │   ├── users.py
│   │   ├── projects.py
│   │   ├── categories.py
│   │   ├── connections.py          # Fernet encrypt/decrypt через CredentialManager
│   │   ├── schedules.py
│   │   ├── publications.py         # + cluster rotation (round-robin, LRU, cluster_type filter)
│   │   ├── payments.py             # payments + token_expenses
│   │   ├── audits.py               # site_audits + site_brandings
│   │   ├── previews.py             # article_previews
│   │   └── prompts.py              # prompt_versions
│   └── migrations/                 # Миграции Supabase
│
├── api/                            # HTTP-эндпоинты для вебхуков QStash и OAuth
│   ├── publish.py                  # QStash -> автопубликация
│   ├── cleanup.py                  # QStash -> очистка expired превью, старых логов
│   ├── notify.py                   # QStash -> уведомления
│   ├── yookassa.py                 # YooKassa webhook + QStash renew подписки
│   ├── auth.py                     # Pinterest OAuth callback
│   ├── auth_service.py             # Pinterest OAuth service logic (token exchange)
│   └── health.py                   # Проверка здоровья
│
├── cache/
│   ├── client.py                   # Асинхронный клиент Upstash Redis
│   ├── fsm_storage.py              # FSM Aiogram на Redis
│   └── keys.py                     # Определения пространств имен ключей
│
└── platform_rules/                 # Валидация контента по платформам
    ├── telegram.py
    ├── vk.py
    ├── pinterest.py
    └── website.py
```

---

## 2.1 Middleware chain (Aiogram)

Порядок выполнения — сверху вниз при входящем update, снизу вверх при ответе:

| # | Middleware | Файл | Что делает |
|---|-----------|------|------------|
| 1 | **DBSessionMiddleware** | `middlewares/db.py` | Outer middleware. Инъекция `data["db"]`, `data["redis"]`, `data["http_client"]`. Клиенты — shared singletons, cleanup только в `on_shutdown`. |
| 2 | **AuthMiddleware** | `middlewares/auth.py` | Автозагрузка/авторегистрация пользователя → `data["user"]`. Проверка `role == 'admin'` → `data["is_admin"]`. |
| 3 | **ThrottlingMiddleware** | `middlewares/throttling.py` | Redis INCR+EXPIRE: 30 msg/min per user. При превышении — молча дропает event (`return None`). |
| 4 | **FSMInactivityMiddleware** | `middlewares/auth.py` | Проверяет `last_update_time` в `state.data`. Если `now - last_update_time > FSM_INACTIVITY_TIMEOUT` → сброс FSM, сообщение "Сессия истекла". Обновляет `last_update_time`. |
| 5 | **LoggingMiddleware** | `middlewares/logging.py` | Записывает `correlation_id` (UUID4) в `data["correlation_id"]`. Структурированный JSON-лог: user_id, update_type, latency_ms. |

**Регистрация:** `dp.update.outer_middleware(DBSessionMiddleware())`, далее inner middleware в порядке 2-5.

**Обработка ошибок:** Aiogram global error handler перехватывает все необработанные исключения → Sentry capture + лог ERROR + ответ пользователю "Произошла ошибка. Попробуйте позже." FSM НЕ сбрасывается при ошибке (пользователь может повторить действие).

---

## 2.2 Пулы соединений

| Клиент | Библиотека | Параметры |
|--------|-----------|-----------|
| Supabase PostgreSQL | `postgrest` (AsyncPostgrestClient) | Supabase Pooler (PgBouncer, transaction mode), макс. 50 connections на Railway instance |
| Upstash Redis | `upstash-redis` (HTTP-based) | Stateless HTTP-запросы, без пула TCP-соединений (serverless-архитектура Upstash) |
| Внешние API (OpenRouter, Firecrawl, DataForSEO) | `httpx.AsyncClient` | `limits=httpx.Limits(max_connections=20, max_keepalive_connections=10)`, один shared client на приложение, `timeout=httpx.Timeout(30.0, connect=5.0)` |

**Инициализация:** Все клиенты создаются синхронно в `create_app()` при запуске приложения, закрываются в `on_shutdown`. Инъекция через `DBSessionMiddleware` в `data["db"]`, `data["redis"]`, `data["http_client"]`.

---

## 2.3 Web-фреймворк для API-эндпоинтов (aiohttp)

Модуль `api/` (QStash webhooks, YooKassa, Pinterest OAuth, health) работает на **aiohttp.web** — том же HTTP-сервере, что использует Aiogram для вебхуков. Отдельный веб-фреймворк (FastAPI, Starlette) НЕ нужен.

```python
from aiohttp import web

def create_app() -> web.Application:
    app = web.Application()

    # Aiogram webhook
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    SimpleRequestHandler(
        dispatcher=dp, bot=bot, secret_token=config.telegram_webhook_secret
    ).register(app, path="/webhook")

    # API endpoints (QStash, YooKassa, health)
    app.router.add_post("/api/publish", publish_handler)
    app.router.add_post("/api/cleanup", cleanup_handler)
    app.router.add_post("/api/notify", notify_handler)
    app.router.add_post("/api/yookassa/webhook", yookassa_handler)
    app.router.add_post("/api/yookassa/renew", yookassa_renew_handler)
    app.router.add_get("/api/auth/pinterest/callback", pinterest_callback)
    app.router.add_get("/api/health", health_handler)

    return app
```

**Доступ к зависимостям:** API-хендлеры получают клиенты через `request.app["db"]`, `request.app["redis"]`, `request.app["http_client"]` (инициализируются в `on_startup`, НЕ через Aiogram middleware).

**Отличие от роутеров Aiogram:** API-хендлеры — thin wrappers (JSON in → Pydantic validate → Service Layer → JSON out). Бизнес-логика — только в `services/`.

**Верификация подписи QStash** — декоратор `@require_qstash_signature` (реализация в `api/__init__.py`):

```python
from qstash import Receiver

receiver = Receiver(
    current_signing_key=os.environ["QSTASH_CURRENT_SIGNING_KEY"],
    next_signing_key=os.environ["QSTASH_NEXT_SIGNING_KEY"],
)

def require_qstash_signature(handler):
    """Decorator: verify QStash HMAC signature. Returns 401 if invalid."""
    async def wrapper(request: web.Request) -> web.Response:
        body = await request.read()
        signature = request.headers.get("Upstash-Signature", "")
        url = f"{os.environ['RAILWAY_PUBLIC_URL']}{request.path}"
        if not receiver.verify(body=body, signature=signature, url=url):
            return web.Response(status=401, text="Invalid signature")
        request["verified_body"] = json.loads(body)
        return await handler(request)
    return wrapper
```

**Scope:** Применяется ТОЛЬКО к QStash endpoints:
- `/api/publish` — QStash
- `/api/cleanup` — QStash
- `/api/notify` — QStash

НЕ применяется:
- `/api/yookassa/webhook` — своя верификация (IP whitelist, см. API_CONTRACTS §2)
- `/api/yookassa/renew` — вызывается QStash cron (верификация QStash подписью)
- `/api/auth/pinterest/callback` — OAuth redirect (HMAC state, см. E30)
- `/api/health` — публичный (без токена — только `{"status": "ok"}`)

---

## 3. Полная схема базы данных (Supabase PostgreSQL)

> **Примечание:** Это единственная актуальная схема БД. BUSINESS_LOGIC_SPEC.md раздел 2 содержит устаревшую модель (подключения в JSONB на уровне users). В v2 подключения — **отдельная таблица на уровне проекта**.

### 3.1 Схема связей

```
users (1) ──── (N) projects ──── (N) categories ──── (N) platform_schedules
  │                   │               │
  │                   │               ├── (N) platform_content_overrides
  │                   │               ├── image_settings (JSONB)
  │                   │               ├── text_settings (JSONB)
  │                   │               └── keywords (JSONB)
  │                   │
  │                   ├── (N) platform_connections
  │                   ├── (1) site_audit  (UNIQUE project_id)
  │                   └── (1) site_branding (UNIQUE project_id)
  │
  ├── (N) payments
  ├── (N) token_expenses
  ├── (N) publication_logs
  └── (N) article_previews

prompt_versions — глобальная таблица (без FK на пользователей)
```

### 3.2 SQL-определения таблиц

#### Таблица: users

```sql
CREATE TABLE users (
    id              BIGINT PRIMARY KEY,        -- Telegram user ID
    username        VARCHAR(255),              -- @username
    first_name      VARCHAR(255),              -- Имя
    last_name       VARCHAR(255),              -- Фамилия
    balance         INTEGER NOT NULL DEFAULT 1500, -- Баланс токенов (1500 welcome bonus)
    language        VARCHAR(10) DEFAULT 'ru',
    role            VARCHAR(20) DEFAULT 'user', -- user, admin
    referrer_id     BIGINT REFERENCES users(id) ON DELETE SET NULL, -- Кто пригласил
    notify_publications BOOLEAN DEFAULT TRUE,   -- Уведомления о публикациях
    notify_balance  BOOLEAN DEFAULT TRUE,      -- Уведомления о балансе
    notify_news     BOOLEAN DEFAULT TRUE,      -- Уведомления о новостях
    created_at      TIMESTAMPTZ DEFAULT now(),
    last_activity   TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_users_referrer ON users(referrer_id);
CREATE INDEX idx_users_activity ON users(last_activity);
```

#### Таблица: projects (бывш. bots)

```sql
CREATE TABLE projects (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,     -- Название проекта
    company_name    VARCHAR(255) NOT NULL,      -- Название компании (обязательно при создании)
    specialization  TEXT NOT NULL,              -- Чем занимается (обязательно при создании)
    website_url     VARCHAR(500),              -- URL сайта (может быть пустым)
    -- Дополнительные поля (заполняются при редактировании)
    company_city    VARCHAR(255),
    company_address TEXT,
    company_phone   VARCHAR(50),
    company_email   VARCHAR(255),
    company_instagram VARCHAR(255),
    company_vk      VARCHAR(255),
    company_pinterest VARCHAR(255),
    company_telegram VARCHAR(255),
    experience      TEXT,
    advantages      TEXT,
    description     TEXT,
    timezone        VARCHAR(50) DEFAULT 'Europe/Moscow',
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_projects_user ON projects(user_id);
```

#### Таблица: platform_connections

```sql
CREATE TABLE platform_connections (
    id              SERIAL PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    platform_type   VARCHAR(20) NOT NULL,      -- wordpress, telegram, vk, pinterest
    status          VARCHAR(20) DEFAULT 'active', -- active, error, disconnected
    credentials     TEXT NOT NULL,              -- Зашифрованный JSON (Fernet), расшифровывается в repository layer
    metadata        JSONB DEFAULT '{}',        -- Доп. данные платформы
    identifier      VARCHAR(500) NOT NULL,     -- Идентификатор подключения (plaintext, для UNIQUE)
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(project_id, platform_type, identifier)
);
CREATE INDEX idx_connections_project ON platform_connections(project_id);
```

**Структура credentials по платформам:**
```json
// WordPress:
{"url": "https://...", "login": "admin", "app_password": "xxxx xxxx xxxx xxxx",
 "wp_categories": ["Блог"], "wp_tags": [], "internal_links": [...],
 "seo_canonical": "", "seo_robots": "index, follow", "schema_type": "Article",
 "identifier": "https://example.com"}

// Telegram:
{"channel_id": "-100123456", "channel_username": "@channel",
 "bot_token": "123:ABC...", "identifier": "-100123456"}

// VK:
{"group_id": "-123456", "group_name": "Группа", "access_token": "vk1.a.XXX",
 "identifier": "-123456"}

// Pinterest:
{"access_token": "pina_...", "refresh_token": "pinr_...", "expires_at": "2026-03-14T00:00:00Z",
 "board_id": "12345", "board_name": "My Board", "identifier": "12345"}
```

#### Таблица: categories

```sql
CREATE TABLE categories (
    id              SERIAL PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,                      -- Описание (промпт для AI)
    keywords        JSONB DEFAULT '[]',        -- Cluster format: [{cluster_name, cluster_type, main_phrase, total_volume, avg_difficulty, phrases: [{phrase, volume, difficulty, cpc, intent, ai_suggested}]}]
                                               -- Legacy format (v1, без cluster_name): [{phrase, volume, difficulty, cpc}]. Detect: if keywords[0] has no "cluster_name" → flat list. Repository converts at read-time
    media           JSONB DEFAULT '[]',        -- [{file_id, type, file_size, uploaded_at}]
    prices          TEXT,                      -- Текстовый прайс-лист ("Товар — Цена" per line)
    reviews         JSONB DEFAULT '[]',        -- [{author, date, rating(1-5), text, pros, cons}]
    -- Настройки контента (наследуются всеми платформами, переопределяются в platform_content_overrides)
    image_settings  JSONB DEFAULT '{}',        -- {formats, styles, tones, cameras, angles, quality, count, text_on_image, collage}
                                               -- Fallback при пустом {}: см. IMAGE_DEFAULTS ниже
    text_settings   JSONB DEFAULT '{}',        -- {style, html_style, words_min, words_max}
                                               -- Fallback при пустом {}: см. TEXT_DEFAULTS ниже
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_categories_project ON categories(project_id);
```

**Дефолтные настройки контента (fallback в коде при `{}`):**

```python
IMAGE_DEFAULTS = {
    "formats": ["1:1"],
    "styles": ["Фотореализм"],
    "tones": ["Нейтральный"],
    "cameras": [],                # не указано — AI решает
    "angles": [],                 # не указано — AI решает
    "quality": "HD",
    "count": 1,                   # default; WP override = 4 через platform_content_overrides
    "text_on_image": 0,
    "collage": 0,
}

TEXT_DEFAULTS = {
    "style": "Информативный",     # для сайта; "Разговорный" для соцсетей
    "html_style": "Блог",
    "words_min": 1500,            # для статей; ~100 для соцсетей
    "words_max": 2500,
}
```

> Единственный источник истины для дефолтов. PRD §6 (Правило 2) ссылается сюда. Применяются на уровне `services/ai/` при сборке промпта, если `image_settings = {}`.

#### Таблица: platform_content_overrides

```sql
CREATE TABLE platform_content_overrides (
    id              SERIAL PRIMARY KEY,
    category_id     INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    platform_type   VARCHAR(20) NOT NULL,      -- wordpress, telegram, vk, pinterest
    image_settings  JSONB,                     -- NULL = наследовать от категории
    text_settings   JSONB,                     -- NULL = наследовать от категории
    UNIQUE(category_id, platform_type)
);
```

#### Таблица: platform_schedules

```sql
CREATE TABLE platform_schedules (
    id              SERIAL PRIMARY KEY,
    category_id     INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    platform_type   VARCHAR(20) NOT NULL,
    connection_id   INTEGER NOT NULL REFERENCES platform_connections(id) ON DELETE CASCADE,
    schedule_days   TEXT[] DEFAULT '{}',        -- {mon, tue, wed, thu, fri, sat, sun}
    schedule_times  TEXT[] DEFAULT '{}',        -- {09:00, 12:00, 18:00}
    posts_per_day   INTEGER DEFAULT 1 CHECK (posts_per_day BETWEEN 1 AND 5),
    enabled         BOOLEAN DEFAULT FALSE,
    status          VARCHAR(20) DEFAULT 'active', -- active | error (E24: 3 retry fail → error)
    qstash_schedule_ids TEXT[] DEFAULT '{}',   -- ID расписаний в QStash (один per time slot)
    last_post_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(category_id, platform_type, connection_id),
    CHECK (schedule_times = '{}' OR array_length(schedule_times, 1) = posts_per_day)
    -- schedule_times пуст при создании (CHECK пропускает '{}'); при заполнении — ровно posts_per_day элементов
);
CREATE INDEX idx_schedules_enabled ON platform_schedules(enabled) WHERE enabled = TRUE;

-- Правило: len(schedule_times) == posts_per_day.
-- Валидация в FSM: при выборе времени кнопки ограничены значением posts_per_day.
-- Если posts_per_day=2, пользователь выбирает ровно 2 времени.
```

#### Таблица: publication_logs

```sql
CREATE TABLE publication_logs (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    category_id     INTEGER REFERENCES categories(id) ON DELETE SET NULL,  -- NULL = категория удалена, лог сохранён
    platform_type   VARCHAR(20) NOT NULL,
    connection_id   INTEGER REFERENCES platform_connections(id) ON DELETE SET NULL,
    keyword         VARCHAR(500),              -- Ключевая фраза для ротации
    content_type    VARCHAR(20) NOT NULL DEFAULT 'article', -- article, social_post, review
    images_count    INTEGER DEFAULT 0,         -- Количество сгенерированных изображений
    post_url        TEXT,
    word_count      INTEGER DEFAULT 0,
    tokens_spent    INTEGER DEFAULT 0,
    ai_model        VARCHAR(100),              -- anthropic/claude-sonnet-4.5, deepseek/deepseek-v3.2
    generation_time_ms INTEGER,
    prompt_version  VARCHAR(20),               -- v1, v2, v3...
    content_hash    BIGINT,                    -- simhash for anti-cannibalization (P2, Phase 11+). NULL до реализации. Заполняется при генерации
    status          VARCHAR(20) DEFAULT 'success', -- success, failed, cancelled
    error_message   TEXT,
    -- P2 columns (Phase 11+): колонки добавлены в схему заранее, заполняются NULL до реализации
    rank_position   INTEGER,                   -- Позиция в Google SERP (DataForSEO SERP API, $0.002/check)
    rank_checked_at TIMESTAMPTZ,               -- Когда последний раз проверяли (QStash cron раз в неделю)
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_pub_logs_user ON publication_logs(user_id, created_at DESC);
CREATE INDEX idx_pub_logs_project ON publication_logs(project_id);
CREATE INDEX idx_pub_logs_category ON publication_logs(category_id, created_at DESC);
-- Covering index для ротации кластеров (API_CONTRACTS §6). keyword = cluster.main_phrase:
CREATE INDEX idx_pub_logs_rotation ON publication_logs(category_id, created_at DESC) INCLUDE (keyword);
```

#### Таблица: token_expenses

```sql
CREATE TABLE token_expenses (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id),  -- NO ACTION: финансовые записи не удаляются при удалении пользователя (аудит)
    amount          INTEGER NOT NULL,          -- Отрицательное = списание, положительное = пополнение/возврат
    operation_type  VARCHAR(50) NOT NULL,      -- text_generation (статьи И соц. посты), image_generation, keyword_generation, audit, review, description, cross_post, purchase, refund, referral_bonus, api_openrouter, api_dataforseo, api_firecrawl, api_pagespeed
    description     TEXT,
    ai_model        VARCHAR(100),
    input_tokens    INTEGER,                   -- Токены LLM (входящие)
    output_tokens   INTEGER,                   -- Токены LLM (исходящие)
    cost_usd        DECIMAL(10,6),             -- Себестоимость в USD
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_expenses_user ON token_expenses(user_id, created_at DESC);
```

#### Таблица: payments

```sql
CREATE TABLE payments (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id),  -- NO ACTION: платежи сохраняются для финансового аудита
    provider        VARCHAR(20) NOT NULL,      -- stars, yookassa
    status          VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending, completed, refunded, failed
    -- Stars-специфичные поля
    telegram_payment_charge_id VARCHAR(255),
    provider_payment_charge_id VARCHAR(255),
    stars_amount    INTEGER,                   -- Количество Stars
    -- ЮKassa-специфичные поля
    yookassa_payment_id VARCHAR(255),
    yookassa_payment_method_id VARCHAR(255), -- Сохранённый метод для автоплатежей (рекуррентные подписки)
    -- Общие поля
    package_name    VARCHAR(50),               -- mini, starter, pro, business, enterprise
    tokens_amount   INTEGER NOT NULL,          -- Сколько токенов начислено
    amount_rub      DECIMAL(10,2),             -- Сумма в рублях
    is_subscription BOOLEAN DEFAULT FALSE,     -- Подписка или разовый платёж
    subscription_id VARCHAR(255),              -- ID подписки Stars (для отмены)
    subscription_status VARCHAR(20),            -- active, paused, cancelled (NULL для разовых)
    subscription_expires_at TIMESTAMPTZ,        -- Дата следующего продления
    referral_bonus_credited BOOLEAN DEFAULT FALSE, -- Был ли начислен реферальный бонус
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_payments_user ON payments(user_id);
CREATE INDEX idx_payments_status ON payments(status) WHERE status = 'pending';
```

#### Таблица: site_audits

```sql
CREATE TABLE site_audits (
    id              SERIAL PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    url             VARCHAR(500) NOT NULL,
    -- PageSpeed метрики
    performance     INTEGER,                   -- 0-100
    accessibility   INTEGER,
    best_practices  INTEGER,
    seo_score       INTEGER,
    lcp_ms          INTEGER,                   -- Largest Contentful Paint
    inp_ms          INTEGER,                   -- Interaction to Next Paint (заменяет FID с марта 2024)
    cls             DECIMAL(5,3),              -- Cumulative Layout Shift
    ttfb_ms         INTEGER,                   -- Time to First Byte
    full_report     JSONB,                     -- Полный JSON ответ PageSpeed API
    recommendations JSONB DEFAULT '[]',        -- [{title, description, priority}]
    audited_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(project_id)
);
CREATE INDEX idx_audits_project ON site_audits(project_id);
```

#### Таблица: site_brandings

```sql
CREATE TABLE site_brandings (
    id              SERIAL PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    url             VARCHAR(500) NOT NULL,
    colors          JSONB DEFAULT '{}',        -- {background, text, accent, primary, secondary}
    fonts           JSONB DEFAULT '{}',        -- {heading, body}
    logo_url        TEXT,
    extracted_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE(project_id)
);
CREATE INDEX idx_brandings_project ON site_brandings(project_id);
```

#### Таблица: article_previews

```sql
CREATE TABLE article_previews (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id),  -- NO ACTION: превью не удаляются при удалении пользователя (cleanup по TTL)
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    category_id     INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    connection_id   INTEGER REFERENCES platform_connections(id) ON DELETE SET NULL,
    telegraph_url   VARCHAR(500),              -- telegra.ph/...
    telegraph_path  VARCHAR(255),              -- Для удаления через API
    title           TEXT,
    keyword         VARCHAR(500),
    word_count      INTEGER,
    images_count    INTEGER,
    tokens_charged  INTEGER,                   -- Сколько списано
    regeneration_count INTEGER DEFAULT 0,      -- 0, 1, 2 (бесплатные), 3+ (платные)
    status          VARCHAR(20) DEFAULT 'draft', -- draft, published, cancelled, expired
    content_html    TEXT,                      -- Полный HTML (для перепубликации)
    images          JSONB DEFAULT '[]',        -- [{url, storage_path, width, height}]
    created_at      TIMESTAMPTZ DEFAULT now(),
    expires_at      TIMESTAMPTZ DEFAULT (now() + INTERVAL '24 hours')
);
CREATE INDEX idx_previews_user ON article_previews(user_id);
CREATE INDEX idx_previews_expires ON article_previews(expires_at) WHERE status = 'draft';
```

#### Таблица: prompt_versions

```sql
CREATE TABLE prompt_versions (
    id              SERIAL PRIMARY KEY,
    task_type       VARCHAR(50) NOT NULL,      -- article, social_post, keywords, review, image, description. keywords = clustering prompt (v3 data-first), NOT data fetching
    version         VARCHAR(20) NOT NULL,      -- v1, v2, v3...
    prompt_yaml     TEXT NOT NULL,             -- YAML-содержимое промпта
    is_active       BOOLEAN DEFAULT FALSE,
    -- A/B testing deferred to v3 (см. audit.md #10)
    success_rate    DECIMAL(5,2),              -- % успешных генераций (для ручного анализа)
    avg_quality     DECIMAL(3,1),              -- Средняя оценка качества (для ручного анализа)
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(task_type, version)
);
```

### 3.3 Итого: 13 таблиц

| # | Таблица | Назначение |
|---|---------|------------|
| 1 | `users` | Пользователи + баланс + настройки уведомлений |
| 2 | `projects` | Проекты (бывш. bots) + данные компании |
| 3 | `platform_connections` | Подключения платформ (привязаны к проекту) |
| 4 | `categories` | Категории + ключевые фразы + медиа + настройки контента |
| 5 | `platform_content_overrides` | Переопределение настроек на уровне платформы |
| 6 | `platform_schedules` | Расписания автопубликации |
| 7 | `publication_logs` | Журнал публикаций |
| 8 | `token_expenses` | История расходов токенов |
| 9 | `payments` | Транзакции Stars/ЮKassa |
| 10 | `site_audits` | Результаты PageSpeed-аудита |
| 11 | `site_brandings` | Цвета/шрифты/лого сайта (Firecrawl Branding v2) |
| 12 | `article_previews` | Telegraph-превью (временные, TTL 24ч) |
| 13 | `prompt_versions` | Версии AI-промптов |

**ON DELETE policy:** `token_expenses`, `payments`, `article_previews` используют `REFERENCES users(id)` без ON DELETE (= NO ACTION). Это намеренно: финансовые записи и превью не должны удаляться при удалении пользователя. Удаление пользователей не поддерживается в v2. Если потребуется (GDPR, v3) — создать отдельный процесс с soft-delete и анонимизацией.

---

## 4. Привязка подключений к проектам и категориям

**Иерархия:** Пользователь → Проект → Подключения (уровень проекта) → Категории → Расписания

```
Подключения создаются на уровне ПРОЕКТА (не глобально):
  │
  ├── Пользователь подключает WordPress-сайт в "Настройки проекта → Подключения"
  │     → запись в таблице `platform_connections` с FK на `project_id`
  │
  ├── Все категории проекта автоматически видят ВСЕ подключения проекта
  │     → карточка категории показывает платформы из `platform_connections WHERE project_id = текущий проект`
  │
  ├── Настройки контента (изображения, текст) задаются на уровне КАТЕГОРИИ
  │     → и наследуются всеми платформами этой категории
  │     → переопределение для конкретной платформы — опционально
  │
  └── Расписание задаётся для комбинации: категория + платформа
        → таблица `platform_schedules` (category_id, connection_id, days, times, posts_per_day)
```

**Модель данных (уточнение):**

| Таблица | Ключевые поля | Связь |
|---------|--------------|-------|
| `platform_connections` | id, project_id (FK), platform_type, credentials, status | Привязка к проекту |
| `categories` | ..., image_settings (JSONB), text_settings (JSONB) | Настройки контента — поля в таблице categories |
| `platform_content_overrides` | id, category_id (FK), platform_type, image_settings (JSONB), text_settings (JSONB) | Переопределение (nullable — если null, берётся из категории) |
| `platform_schedules` | id, category_id (FK), platform_type, connection_id (FK), days, times, posts_per_day | Расписание |

**Логика наследования настроек (F41):**
```python
def get_content_settings(category_id, platform_type):
    override = platform_content_overrides.get(category_id, platform_type)
    if override and override.image_settings is not None:
        return override
    return categories.get(category_id)  # дефолт из полей категории (image_settings, text_settings)
```

В UI платформы: если настройки переопределены — показывать "(свои настройки)" рядом с кнопкой. Кнопка "Сбросить к настройкам категории" удаляет override.

---

## 5. Паттерны реализации

### 5.1 Удаление сущностей с внешними зависимостями (QStash)

CASCADE в PostgreSQL — синхронный, нельзя вставить async-вызов QStash между DELETE и CASCADE. Отмена внешних расписаний — **в application layer до DELETE**:

```python
async def delete_category(category_id: int):
    # 1. Сначала отменить QStash-расписания (async, внешний сервис)
    schedules = await repo.get_schedules_by_category(category_id)
    for s in schedules:
        for sid in (s.qstash_schedule_ids or []):
            await qstash.schedules.delete(sid)
    # 2. Потом удалить в БД (CASCADE удалит platform_schedules, overrides, previews)
    await repo.delete_category(category_id)

async def delete_project(project_id: int):
    # Аналогично: отменить все QStash перед CASCADE
    schedules = await repo.get_schedules_by_project(project_id)
    for s in schedules:
        for sid in (s.qstash_schedule_ids or []):
            await qstash.schedules.delete(sid)
    await repo.delete_project(project_id)
```

> См. E11 и E24 в [EDGE_CASES.md](EDGE_CASES.md).

### 5.2 Формат callback_data

Для callback-driven экранов (не FSM) — единый формат callback_data:

```
{entity}:{id}:{action}
{entity}:{id}:{sub_entity}:{sub_id}:{action}
```

Примеры:
```
project:5:card                        — карточка проекта
project:5:category:12:settings        — настройки категории
category:12:platform:wordpress:publish — публикация
schedule:42:toggle                    — вкл/выкл расписания
tariff:pro:stars                      — оплата Stars
tariff:pro:yookassa                   — оплата ЮKassa
pipeline:article:start                — Pipeline: начать статью
pipeline:social:confirm               — Pipeline: подтверждение соц. поста
page:projects:2                       — пагинация: страница 2
```

Максимальная длина callback_data в Telegram: **64 байта**. Числовые ID экономят место.

### 5.3 Health Check

Эндпоинт `/api/health` — проверка доступности всех зависимостей:

```python
# GET /api/health → 200 OK | 503 Service Unavailable
{
    "status": "ok",         # ok | degraded | down
    "version": "2.0.0",
    "uptime_seconds": 86400,
    "checks": {
        "database": {"status": "ok", "latency_ms": 12},
        "redis": {"status": "ok", "latency_ms": 3},
        "openrouter": {"status": "ok"},        # ping /api/v1/models
        "qstash": {"status": "ok"}             # проверка signing key
    }
}
```

Логика статуса: `down` если database или redis недоступны; `degraded` если openrouter или qstash недоступны; `ok` иначе. Railway использует health endpoint для zero-downtime deploys.

**Безопасность health endpoint:** Эндпоинт по умолчанию возвращает только `{"status": "ok", "version": "2.0.0"}`. Детальные `checks` с `latency_ms` доступны только с заголовком `Authorization: Bearer {HEALTH_CHECK_TOKEN}` (env var). Без токена — никакой информации об инфраструктуре.

### 5.4 Админ-панель (F20) — источники данных

Доступ: `users.role = 'admin'` (проверка по `ADMIN_ID` из env).

**Дашборд (основной экран):**

```sql
-- Пользователи: всего / платных / бесплатных
SELECT
  count(*) AS total,
  count(*) FILTER (WHERE id IN (
    SELECT DISTINCT user_id FROM payments WHERE status = 'completed'
  )) AS paid
FROM users;

-- Выручка за период
SELECT coalesce(sum(amount_rub), 0) AS revenue
FROM payments
WHERE status = 'completed'
  AND created_at >= now() - interval '30 days';

-- Распределение по тарифам (последний платёж каждого пользователя)
SELECT p.package_name, count(*) AS cnt
FROM payments p
JOIN (
  SELECT user_id, max(created_at) AS last_pay
  FROM payments WHERE status = 'completed' GROUP BY user_id
) lp ON p.user_id = lp.user_id AND p.created_at = lp.last_pay
GROUP BY p.package_name;

-- Последние 5 платежей
SELECT u.first_name, p.amount_rub, p.package_name, p.created_at
FROM payments p JOIN users u ON p.user_id = u.id
WHERE p.status = 'completed'
ORDER BY p.created_at DESC LIMIT 5;

-- Реферальная программа
SELECT
  count(*) FILTER (WHERE referral_bonus_credited = true) AS activations,
  coalesce(sum(te.amount), 0) AS total_bonus
FROM payments
LEFT JOIN token_expenses te ON te.user_id = payments.user_id
  AND te.operation_type = 'referral_bonus';
```

**Затраты API ($):**

```sql
-- Расходы за 7/30/90 дней (из token_expenses с типом api_cost)
SELECT
  operation_type,  -- 'api_openrouter', 'api_dataforseo', 'api_firecrawl', 'api_pagespeed'
  sum(cost_usd) AS total_cost_usd,
  count(*) AS requests
FROM token_expenses
WHERE operation_type LIKE 'api_%'
  AND created_at >= now() - interval '30 days'
GROUP BY operation_type;
```

Примечание: API-расходы в USD хранятся в `token_expenses.cost_usd` с `operation_type = 'api_openrouter'` и т.д. Конвертация USD→RUB — по курсу из env (`USD_RUB_RATE`).

**Рассылка (broadcast):**

```python
async def broadcast(text: str, audience: str):
    """audience: 'all' | 'active_7d' | 'active_30d' | 'paid'"""
    filters = {
        "all": "1=1",
        "active_7d": "last_activity >= now() - interval '7 days'",
        "active_30d": "last_activity >= now() - interval '30 days'",
        "paid": "id IN (SELECT DISTINCT user_id FROM payments WHERE status = 'completed')",
    }
    # audience → pre-defined filter, no user input interpolation
    # NOTE: get_broadcast_users RPC will be created in Phase 12 (admin panel)
    rows = await db.rpc("get_broadcast_users", {"audience_key": audience}).execute()
    users = rows.data or []
    sent, failed = 0, 0
    for user in users:
        try:
            await bot.send_message(user["id"], text)
            sent += 1
        except TelegramForbiddenError:
            failed += 1  # пользователь заблокировал бота
        await asyncio.sleep(0.05)  # rate limit: 20 msg/sec
    return {"sent": sent, "failed": failed}
```

### 5.5 Атомарные операции с балансом

Баланс пользователя обновляется ТОЛЬКО через RPC-функции Supabase (серверные SQL-функции). Это гарантирует атомарность и защиту от race conditions при параллельных списаниях (автопубликация + ручная генерация).

```sql
-- charge_balance: атомарное списание с проверкой
CREATE OR REPLACE FUNCTION charge_balance(p_user_id BIGINT, p_amount INTEGER)
RETURNS INTEGER AS $$
DECLARE
    new_balance INTEGER;
BEGIN
    UPDATE users SET balance = balance - p_amount
    WHERE id = p_user_id AND balance >= p_amount
    RETURNING balance INTO new_balance;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'insufficient_balance';
    END IF;
    RETURN new_balance;
END;
$$ LANGUAGE plpgsql;

-- refund_balance: атомарный возврат
CREATE OR REPLACE FUNCTION refund_balance(p_user_id BIGINT, p_amount INTEGER)
RETURNS INTEGER AS $$
DECLARE
    new_balance INTEGER;
BEGIN
    UPDATE users SET balance = balance + p_amount
    WHERE id = p_user_id
    RETURNING balance INTO new_balance;
    RETURN new_balance;
END;
$$ LANGUAGE plpgsql;

-- credit_balance: пополнение (покупка, реферальный бонус)
CREATE OR REPLACE FUNCTION credit_balance(p_user_id BIGINT, p_amount INTEGER)
RETURNS INTEGER AS $$
DECLARE
    new_balance INTEGER;
BEGIN
    UPDATE users SET balance = balance + p_amount
    WHERE id = p_user_id
    RETURNING balance INTO new_balance;
    RETURN new_balance;
END;
$$ LANGUAGE plpgsql;
```

**Использование в Repository:**
```python
async def charge_balance(self, user_id: int, amount: int) -> int:
    result = await self.db.rpc("charge_balance", {"p_user_id": user_id, "p_amount": amount}).execute()
    return result.data  # new_balance
```

**Запрещено:** `UPDATE users SET balance = balance - ? WHERE id = ?` напрямую из Python без `WHERE balance >= ?`. Всегда через RPC.

### 5.6 Backpressure для автопубликации

QStash может отправить несколько вебхуков одновременно (несколько расписаний срабатывают в одну минуту). Для защиты от перегрузки AI-сервисов используется `asyncio.Semaphore`:

```python
# api/publish.py
PUBLISH_SEMAPHORE = asyncio.Semaphore(10)  # Максимум 10 параллельных генераций
SEMAPHORE_WAIT_TIMEOUT = 300               # Макс. ожидание в очереди семафора (5 мин)

@require_qstash_signature
async def publish_handler(request: web.Request) -> web.Response:
    try:
        async with asyncio.timeout(SEMAPHORE_WAIT_TIMEOUT):
            async with PUBLISH_SEMAPHORE:
                result = await execute_publish(request["verified_body"], request.app)
    except TimeoutError:
        # Не попали в семафор за 5 мин → 503 → QStash retry с backoff
        return web.Response(status=503, headers={"Retry-After": "120"})
    return web.json_response(result)
```

**Параметры:** 10 параллельных генераций — компромисс между пропускной способностью и нагрузкой на OpenRouter. При 10 генерациях по 45с каждая — максимум 10 * 45с = 450с wall time, но OpenRouter обрабатывает параллельно.

**Таймаут очереди (300с):** Если за 5 мин не попали в семафор → 503 → QStash retry через exponential backoff. Предотвращает накопление зависших соединений. QStash default timeout = 30 мин, наш 503 приходит раньше.

**Эскалация (если в продакшне увидим retry storms):** заменить asyncio.Semaphore на Redis-backed queue с явным приоритетом и dead-letter.

### 5.7 Graceful Shutdown (SIGTERM)

Railway отправляет SIGTERM при деплое. Бот должен завершить in-flight генерации до принудительного SIGKILL.

```python
# bot/main.py
SHUTDOWN_EVENT = asyncio.Event()

async def on_shutdown(app: web.Application):
    """Graceful shutdown: ждём завершения текущих генераций."""
    SHUTDOWN_EVENT.set()
    # Дождаться освобождения семафора (все генерации завершены)
    for _ in range(120):  # макс. 120 секунд
        if PUBLISH_SEMAPHORE._value == 10:  # все слоты свободны
            break
        await asyncio.sleep(1)
    # Закрыть клиенты
    await app["http_client"].aclose()
    await app["db"].aclose()

# Railway env: RAILWAY_GRACEFUL_SHUTDOWN_TIMEOUT=120
```

**Конфигурация Railway:** `RAILWAY_GRACEFUL_SHUTDOWN_TIMEOUT=120` — 120 секунд между SIGTERM и SIGKILL. Достаточно для завершения самой долгой генерации (статья + 4 изображения ≈ 90с).

### 5.8 HTML-санитизация контента

AI-генерируемый `content_html` ОБЯЗАТЕЛЬНО проходит санитизацию перед публикацией (защита от XSS и нежелательных тегов):

```python
import nh3

ALLOWED_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "a", "img", "ul", "ol", "li",
    "strong", "em", "b", "i", "blockquote",
    "table", "thead", "tbody", "tr", "th", "td",
    "span", "br", "hr", "figure", "figcaption",
    "script",  # только type="application/ld+json" (Schema.org)
}

ALLOWED_ATTRIBUTES = {
    "a": {"href", "title", "target", "rel"},
    "img": {"src", "alt", "width", "height", "loading"},
    "span": {"style"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
    "script": {"type"},  # только application/ld+json
}

def sanitize_html(html: str) -> str:
    """Санитизация AI-генерированного HTML перед публикацией."""
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        link_rel="noopener noreferrer",
    )
```

**Применяется:** в `services/ai/articles.py` и `services/ai/social_posts.py` ПОСЛЕ генерации, ДО передачи в Publisher. Для `<script type="application/ld+json">` (Schema.org) — дополнительная валидация JSON перед включением.

### 5.9 Хранение изображений

**Стратегия:** Supabase Storage bucket `content-images` для промежуточного хранения.
Реализовано в `services/storage.py` (ImageStorage class).

| Этап | Хранение | Срок |
|------|----------|------|
| Генерация (base64 из OpenRouter) | In-memory (bytes) | Время обработки (~10с) |
| WebP-конвертация | In-memory (PIL → BytesIO) | Время обработки |
| Upload | Supabase Storage `content-images` | 24ч (cleanup cron) |
| Превью (Telegraph) | Telegraph CDN + Supabase URL | 24ч (cleanup удаляет article_preview) |
| Публикация (WordPress) | WP Media Library (на сайте клиента) | Навсегда |
| Публикация (Telegram) | Telegram CDN | Навсегда |
| Публикация (VK) | VK CDN | Навсегда |
| Публикация (Pinterest) | Pinterest CDN | Навсегда |
| `article_previews.images` | JSONB [{url, storage_path, width, height}] | 24ч (cleanup) |

**Зачем Supabase Storage:** промежуточное хранение нужно для превью (Telegraph embed),
перегенерации (можно заново опубликовать без повторной генерации) и параллельного
pipeline (текст + изображения генерируются одновременно, изображения ждут публикации).
Path: `{user_id}/{project_id}/{timestamp}.webp`. Cleanup cron (api/cleanup.py) удаляет
файлы вместе с expired article_previews.

**Signed URLs (рекомендация):** Supabase Storage поддерживает time-limited signed URLs
(`create_signed_url(path, expires_in=86400)`). Для `content-images` bucket безопаснее
использовать signed URLs вместо public bucket URLs — они автоматически истекают через 24ч,
совпадая с TTL превью. Реализация: `ImageStorage.get_url()` возвращает signed URL.

**Image Transformations (P2):** Supabase Storage поддерживает серверный ресайз через URL-параметры
(`/render/image/sign/.../image.webp?width=400&height=300`). Для Telegram-превью можно
генерировать thumbnail без дополнительной обработки в Python.
