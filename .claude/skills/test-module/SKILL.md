---
name: test-module
description: Запустить тесты модуля и исправить падающие
argument-hint: "<module-name>"
context: fork
agent: tester
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
---

## Задача
Протестируй модуль `$ARGUMENTS`.

## Алгоритм
1. Найди тесты: `find tests/ -name "*$ARGUMENTS*" -o -name "test_*.py"`
2. Запусти: `uv run pytest tests/ -k "$ARGUMENTS" -v --tb=long`
3. При падении:
   a. Прочитай traceback
   b. Определи: баг в тесте или в коде?
   c. Исправь
   d. Перезапусти
4. Повтори до зелёного
5. Проверь покрытие: `uv run pytest --cov=bot --cov=routers --cov=services --cov=db --cov=api --cov=cache --cov-report=term-missing -k "$ARGUMENTS"`
6. Если покрытие < 80% — допиши недостающие тесты

7. Проверь типы:
   ```bash
   uv run mypy bot/ routers/ services/ db/ api/ cache/ --check-untyped-defs --no-error-summary 2>&1 | head -30
   ```
   Если mypy находит ошибки в модуле $ARGUMENTS — исправь (баг в коде, не в тесте).

8. Расширенный линтинг:
   ```bash
   uv run ruff check bot/ routers/ services/ db/ api/ cache/ tests/ --select=E,F,I,S,C901,B,UP,SIM,RUF --quiet
   ```
   Исправь всё кроме S101 (assert в тестах — OK).
