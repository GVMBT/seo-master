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
- docs/FSM_SPEC.md — 16 FSM StatesGroup, валидация, переходы
- docs/EDGE_CASES.md — E01-E57, обработка ошибок
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
- Текст: ceil(word_count / 100) * 10, Изображение: 30, Ключевые фразы: бесплатно, Аудит: 50
- Списание в момент ГЕНЕРАЦИИ (до превью), возврат при ошибке
- GOD_MODE (ADMIN_ID): не списывать, показывать стоимость

## Команды
```bash
uv run pytest tests/ -x -v                # тесты (один файл: -k "test_name")
uv run ruff check . --select=E,F,I,S,C901,B,UP,SIM,RUF  # расширенный линтинг
uv run ruff format .                       # форматирование
uv run mypy bot/ routers/ services/ db/ api/ cache/ --check-untyped-defs  # проверка типов (0 ошибок!)
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
- `callback.message`: ВСЕГДА используй `msg = safe_message(callback)`, затем `msg.*` (НИКОГДА `callback.message.*` после guard)
- FSM-классы: суффикс `*FSM` (ProjectCreateFSM, CategoryCreateFSM, etc.)

## Архив решений
Подробный лог решений и расхождений: `.claude/DECISIONS.md`

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
- `edge-cases.md` → `routers/`, `services/`, `api/` (E01-E57 чеклист)
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
