---
name: find-gaps
description: Найти дыры в спеках, логике и реализации
argument-hint: "<target> (phase 9 | module services/ai | specs)"
context: fork
agent: gap-finder
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
  - mcp__context7
---

## Задача
Проведи gap-анализ для `$ARGUMENTS`.

## Определение режима
- Если аргумент начинается с `phase` — режим A (аудит фазы)
- Если аргумент начинается с `module` — режим B (аудит модуля)
- Если аргумент = `specs` — режим C (кросс-спек аудит)

## Режим A: `phase <N>`
1. Прочитай `.progress/phases.md` — найди Phase N, список задач
2. Прочитай `.progress/current.md` — текущий статус
3. Для каждого пункта фазы проверь:
   - Код существует? (Glob + Read)
   - Тесты существуют? (Glob по tests/)
   - Edge cases из docs/EDGE_CASES.md обработаны?
4. Сформируй отчёт (макс 10 находок, P0/P1/P2)

## Режим B: `module <path>`
1. Прочитай код модуля (Read)
2. Найди упоминания в docs/ (Grep)
3. Каждый публичный метод: спек? тест? edge case?
4. Проверь покрытие тестами:
```bash
uv run pytest tests/ -x --cov=$MODULE_PATH --cov-report=term-missing -q
```
5. Сформируй отчёт (макс 10 находок)

## Режим C: `specs`
1. Прочитай все 6 файлов docs/
2. Прочитай db/models.py
3. Найди противоречия между документами (только runtime-влияющие)
4. Проверь соответствие имён таблиц/колонок между ARCHITECTURE.md и models.py
5. Сформируй отчёт (макс 10 находок)

## Формат отчёта
```
## Gap Analysis: {target}
Режим: {phase N|module path|specs}
Находок: N (P0: X, P1: Y, P2: Z)

### P0-BLOCKER
| # | Тип | Файл:Строка | Описание | Спек-ссылка |

### P1-IMPORTANT
| # | Тип | Файл:Строка | Описание | Спек-ссылка |

### P2-NOTE
(свёрнуто, если >10 общих)

### Вердикт: PASS / NEEDS_FIXES / BLOCKER
```
