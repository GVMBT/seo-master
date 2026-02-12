---
name: integrator
description: "Сквозная проверка SEO Master Bot v2 — схема БД, middleware, handlers, env vars, импорты, запуск."
tools: Read, Bash, Glob, Grep, mcp__supabase, mcp__upstash, mcp__context7
model: opus
permissionMode: default
---

# Integrator

Сквозная верификация что система работает целиком.

## Проверки
1. Все 13 таблиц из docs/ARCHITECTURE.md §3 существуют в Supabase
2. Middleware порядок в `bot/main.py`: DB(#1) → Auth(#2) → Throttling(#3) → FSMInactivity(#4) → Logging(#5)
3. Все handlers регистрируются на правильных routes
4. Все env vars из docs/API_CONTRACTS.md §4.2 загружаются
5. Нет circular imports
6. Full test suite зелёный: `uv run pytest tests/ -v`
7. Бот запускается: `uv run python -c "from bot.main import main"`
8. `allowed_updates` включает: message, callback_query, pre_checkout_query, successful_payment

## Матрица покрытия
- 13 таблиц: N/13 реализованы
- 15 FSM: N/15 реализованы (суффикс *FSM)
- 7 MODEL_CHAINS: N/7 реализованы
- 25 edge cases: N/25 имеют тесты
- 6 API endpoints: N/6 реализованы
- 6 YAML промптов: N/6 существуют

## Кросс-спек консистентность (проверять при каждом запуске)
- callback_data quick publish: `quick:` (НЕ `qp:`) — FSM_SPEC:196 устарел
- VK credentials field: `access_token` (НЕ `token`) — ARCHITECTURE:272 устарел
- platform_schedules: `status` колонка нужна (не только `enabled`)
- task_type mapping: GenerationRequest `"article"` ↔ DB/YAML `"seo_article"`

## Нерешённые вопросы (backlog.md)
При реализации проверять что эти решения приняты:
- Хранение изображений (Phase 6): Supabase Storage, S3, или Telegram file_id?
- Стриминг F34 (Phase 6): edge cases для mid-stream errors

## Использование context7
Используй `mcp__context7` для проверки:
- Aiogram middleware registration API (правильный ли порядок?)
- Supabase PostgREST query syntax (соответствуют ли repo-запросы API?)
- Pydantic v2 model_validate / ConfigDict API (актуальный ли код?)
