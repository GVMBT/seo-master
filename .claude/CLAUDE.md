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
- docs/FSM_SPEC.md — 15 FSM StatesGroup, валидация, переходы
- docs/EDGE_CASES.md — E01-E25, обработка ошибок
- docs/USER_FLOWS_AND_UI_MAP.md — все экраны, навигация

ПЕРЕД реализацией любого модуля — ПРОЧИТАЙ соответствующие секции спеков.
НЕ выдумывай имена таблиц, колонок, env vars — бери ТОЛЬКО из спеков.

## Архитектура (docs/ARCHITECTURE.md §2)
```
bot/           — main.py, config.py, middlewares/ (запуск, конфиг, цепочка middleware)
routers/       — Aiogram роутеры (ТОЛЬКО маршрутизация и UI, бизнес-логика в services/)
services/      — бизнес-логика (ZERO зависимости от Telegram/Aiogram)
db/            — client.py, models.py, repositories/ (Repository pattern, Fernet в repo layer)
api/           — HTTP-эндпоинты (QStash webhooks, YooKassa, Pinterest OAuth, health)
cache/         — Redis client, FSM storage, key namespaces
platform_rules/ — валидация контента по платформам
tests/         — зеркалит top-level: unit/services/, unit/db/, integration/fsm/, integration/api/
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

## Agent Teams (slash-команды)
```
/implement-module <path>  — реализация модуля (implementer agent)
/review-module <path>     — code review (reviewer agent, read-only)
/test-module <name>       — тесты до зелёного (tester agent)
/verify-spec              — сквозная проверка vs спецификации (integrator agent)
```

## Контекстные правила (.claude/rules/)
Правила из `.claude/rules/` автоматически применяются к файлам по path-glob:
- `python-style.md` → `**/*.py` (ruff, mypy, type hints)
- `security.md` → `**/*.py` (Fernet, SQL injection, rate limits)
- `testing.md` → `tests/**/*.py` (pytest-asyncio, httpx.MockTransport, naming)
- `edge-cases.md` → `routers/`, `services/`, `api/` (E01-E25 чеклист)

## MCP-серверы (настроены в settings.json)
- **supabase** — управление БД, миграции, SQL через MCP
- **upstash** — Redis (run commands, list keys, databases) + Upstash API (НЕ QStash schedules)
- **context7** — поиск актуальной документации библиотек (Aiogram, Pydantic, etc.)

## Фазы разработки
Полный план в `.progress/phases.md` (10 фаз). Текущий статус в `.progress/current.md`.

## Контекст-менеджмент
При длинных сессиях: обнови `.progress/current.md` перед /compact или /clear.
Новая сессия: "Прочитай .progress/current.md и продолжай."

## Модель
ТОЛЬКО claude-opus-4-6. Никаких sonnet/haiku.
