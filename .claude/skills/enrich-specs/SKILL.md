---
name: enrich-specs
description: Обновить rules/skills/specs актуальной информацией из документации
argument-hint: "<target> (aiogram | pydantic | httpx | edge-cases | audit | skills | sync | <library-name>)"
context: fork
agent: spec-enricher
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - WebFetch
  - WebSearch
  - mcp__context7
---

## Задача
Обогати проектную базу знаний по теме: `$ARGUMENTS`.

## Алгоритм

### Если $ARGUMENTS — имя библиотеки (aiogram, pydantic, httpx, openrouter, etc.)
1. Через `mcp__context7` получи актуальную документацию библиотеки
2. Через `WebSearch` найди changelog, breaking changes, migration guides
3. Прочитай текущие правила: `.claude/rules/*.md`
4. Прочитай текущий код, использующий эту библиотеку (Grep по import)
5. Обнови rules новыми паттернами, deprecations, best practices
6. Если есть breaking changes — обнови чеклисты агентов

### Если $ARGUMENTS = "edge-cases"
1. Прочитай `docs/EDGE_CASES.md` (текущие E01-E30)
2. Прочитай код в `routers/`, `services/`, `api/`
3. Найди необработанные сценарии ошибок
4. Добавь новые E-коды (E31+) в `docs/EDGE_CASES.md`
5. Обнови `.claude/rules/edge-cases.md` соответственно

### Если $ARGUMENTS = "audit"
1. Прочитай ВСЕ `.claude/rules/*.md`
2. Для каждого правила проверь актуальность через context7
3. Удали устаревшие, обнови изменившиеся
4. Проверь что код следует правилам (выборочно)

### Если $ARGUMENTS = "skills"
1. Прочитай ВСЕ `.claude/skills/*/SKILL.md`
2. Прочитай ВСЕ `.claude/agents/*.md`
3. Найди пробелы в чеклистах на основе реального кода и спеков
4. Дополни чеклисты недостающими проверками

### Если $ARGUMENTS = "sync"
1. Прочитай все 6 файлов `docs/*.md`
2. Прочитай `audit.md` (известные расхождения)
3. Найди новые противоречия между документами
4. Предложи исправления (НЕ правь docs/ напрямую — только отчёт)

## Ограничения
- `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/API_CONTRACTS.md`, `docs/FSM_SPEC.md` — НЕ редактировать (только отчёт о проблемах)
- `docs/EDGE_CASES.md` — можно ДОБАВЛЯТЬ новые E-коды
- `.claude/rules/`, `.claude/skills/`, `.claude/agents/` — можно обновлять
- Продакшен-код (`bot/`, `routers/`, `services/`, etc.) — НЕ трогать
