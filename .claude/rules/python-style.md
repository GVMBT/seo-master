---
paths:
  - "**/*.py"
---

# Python Style

- Python 3.14+, type hints обязательны (PEP 604: `X | None`)
- Async/await везде (никаких sync вызовов в async контексте)
- Форматирование: ruff format, линтинг: ruff check
- Импорты: стандартная библиотека, сторонние, локальные — разделены пустой строкой
- Dataclasses или Pydantic v2 для моделей данных
- Logging: structlog с JSON-выводом, не print()
- Ошибки: кастомные исключения наследуют от базового AppError
- Docstrings только для публичных API (не для каждой функции)
- Максимальная длина строки: 120 символов

## Ruff (расширенный набор правил)
`ruff check --select=E,F,I,S,C901,B,UP,SIM,RUF`
- E, F — pyflakes + pycodestyle (ошибки, не стиль)
- I — isort (порядок импортов)
- S — bandit (security: hardcoded passwords, SQL injection, etc.)
- C901 — cyclomatic complexity (порог 15)
- B — bugbear (частые баги: mutable defaults, except Exception, etc.)
- UP — pyupgrade (устаревший синтаксис → modern Python 3.14)
- SIM — simplify (упрощение условий, циклов)
- RUF — ruff-specific (unused noqa, ambiguous characters)

## Mypy
`mypy bot/ routers/ services/ db/ api/ cache/ --check-untyped-defs --no-error-summary`
- Проверяет тела функций даже без аннотаций
- Все публичные функции ДОЛЖНЫ иметь полные type hints
- `| None` вместо `Optional[]`
- Используй `TYPE_CHECKING` для импортов, нужных только типам
