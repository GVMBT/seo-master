---
name: implement-module
description: Реализовать модуль проекта по спецификации
argument-hint: "<module-name> (например: db/repositories, routers/projects, services/ai)"
context: fork
agent: implementer
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - mcp__supabase
---

## Задача
Реализуй модуль `$ARGUMENTS` для SEO Master Bot v2.

## Алгоритм
1. Прочитай ВСЕ релевантные секции спеков:
   - docs/ARCHITECTURE.md — структура, схема, паттерны
   - docs/API_CONTRACTS.md — контракты для этого модуля
   - docs/FSM_SPEC.md — если модуль связан с FSM
   - docs/EDGE_CASES.md — все E-коды для этого модуля

2. Проверь зависимости: какие модули уже реализованы?
   `!find . -name "*.py" -not -path "./.claude/*" | head -50`

3. Реализуй модуль:
   - Следуй структуре из ARCHITECTURE.md §2
   - Используй ТОЧНЫЕ имена из спеков (таблицы, колонки, env vars)
   - Импортируй существующие утилиты, не дублируй

4. Напиши тесты в tests/ (зеркальная структура)

5. Запусти линтер, типы и тесты:
   ```bash
   uv run ruff check . --select=E,F,I,S,C901,B,UP,SIM,RUF --quiet
   uv run mypy bot/ routers/ services/ db/ api/ cache/ --check-untyped-defs --no-error-summary 2>&1 | head -30
   uv run pytest tests/ -x -v
   ```

6. Если что-то падает — исправь и перезапусти (цикл до зелёного)
