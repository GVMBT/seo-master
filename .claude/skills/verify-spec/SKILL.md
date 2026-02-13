---
name: verify-spec
description: Проверить что реализация соответствует спецификации
context: fork
agent: integrator
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - mcp__supabase
  - mcp__context7
---

## Задача
Сквозная проверка реализации vs спецификация.

## Проверки
1. **13 таблиц:** Каждая CREATE TABLE из ARCHITECTURE.md §3 существует в Supabase
2. **16 FSM:** Каждый StatesGroup из FSM_SPEC.md реализован в routers/
3. **MODEL_CHAINS:** 7 задач из API_CONTRACTS.md §3.1 реализованы
4. **42 edge cases:** Каждый E-код из EDGE_CASES.md имеет тест
5. **ENV vars:** Все 16+ переменных из API_CONTRACTS.md §4.2 используются
6. **Endpoints:** 6 файлов из api/ реализованы и обрабатывают запросы
7. **Промпты:** 6 YAML-файлов из API_CONTRACTS.md §5 существуют

Выведи матрицу покрытия с процентами.
