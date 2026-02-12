---
name: review-module
description: Проверить реализацию модуля на соответствие спецификации
argument-hint: "<module-path> (например: routers/projects/create.py)"
context: fork
agent: reviewer
allowed-tools:
  - Read
  - Glob
  - Grep
  - mcp__context7
---

## Задача
Проведи code review модуля `$ARGUMENTS`.

## Чеклист
1. **Соответствие спеке:** Каждая функция/класс имеет основание в docs/
2. **Схема БД:** Все таблицы, колонки, типы точно совпадают с ARCHITECTURE.md §3
3. **ENV vars:** Все переменные окружения из docs/API_CONTRACTS.md §4.2
4. **Edge cases:** Все релевантные E-коды из docs/EDGE_CASES.md обработаны
5. **Security:** Нет SQL-инъекций, XSS, хардкоженных секретов
6. **Тесты:** Покрытие >=80%, edge cases протестированы
7. **Стиль:** ruff clean, type hints, async/await

## Статический анализ (запустить и включить результаты в отчёт)
```bash
uv run ruff check $ARGUMENTS --select=E,F,I,S,C901,B,UP,SIM,RUF --output-format=concise
uv run mypy $ARGUMENTS --check-untyped-defs --no-error-summary
```
Если есть ошибки — добавь в секцию "Важные" отчёта с точным файлом и строкой.

## Формат отчёта
```
## Review: {module_path}
Статус: PASS / FAIL / NEEDS_FIXES
Найдено проблем: N

### Критические (блокируют мерж)
- ...

### Важные (нужно исправить)
- ...

### Рекомендации (можно отложить)
- ...
```
