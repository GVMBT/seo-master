---
name: integrator
description: "Сквозная проверка SEO Master Bot v2 — схема БД, middleware, handlers, env vars, импорты, запуск."
tools: Read, Bash, Glob, Grep, mcp__supabase, mcp__upstash
model: opus
permissionMode: default
---

# Integrator

Сквозная верификация что система работает целиком.

## Проверки
1. Все 13 таблиц из docs/ARCHITECTURE.md §3 существуют в Supabase
2. Middleware регистрируются в правильном порядке (§2.1)
3. Все handlers регистрируются на правильных routes
4. Все env vars из docs/API_CONTRACTS.md §4.2 загружаются
5. Нет circular imports
6. Full test suite зелёный: `uv run pytest tests/ -v`
7. Бот запускается: `uv run python -c "from bot.main import main"`

## Матрица покрытия
- 13 таблиц: N/13 реализованы
- 15 FSM: N/15 реализованы
- 7 MODEL_CHAINS: N/7 реализованы
- 25 edge cases: N/25 имеют тесты
- 6 API endpoints: N/6 реализованы
- 6 YAML промптов: N/6 существуют
