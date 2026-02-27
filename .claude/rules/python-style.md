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
- Logging: `log = structlog.get_logger()` в начале модуля, не print()
- Ошибки: кастомные исключения наследуют от AppError (bot/exceptions.py)
- `except Exception` — ВСЕГДА `log.exception(...)` + re-raise или return error. ЗАПРЕЩЕНО: `except Exception: pass`
- Docstrings только для публичных API (не для каждой функции)
- Максимальная длина строки: 120 символов
- callback_data: формат `{entity}:{id}:{action}`, макс. 64 байта (см. CLAUDE.md)

## Типизация в хендлерах и репозиториях
- `db` параметр: `db: SupabaseClient` из `db.client` (ЗАПРЕЩЕНО: `object`, `Any`)
- `callback.message`: перед доступом проверяй `if callback.message and isinstance(callback.message, Message):`
- Bare `list`, `dict` без параметров запрещены в Pydantic моделях — `list[str]`, `dict[str, Any]`

## assert в продакшен-коде
- `assert` ЗАПРЕЩЁН вне тестов — удаляется при `python -O`
- Вместо `assert row is not None` → `if row is None: raise AppError("Insert returned no data")`
- В тестах `assert` допустим (S101 в noqa)

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

## Mypy — ZERO TOLERANCE
`mypy bot/ routers/ services/ db/ api/ cache/ --check-untyped-defs --no-error-summary`
- **0 ошибок mypy — обязательное условие. Ошибки type checker — это реальные баги, не шум.**
- Проверяет тела функций даже без аннотаций
- Все публичные функции ДОЛЖНЫ иметь полные type hints
- `| None` вместо `Optional[]`
- Используй `TYPE_CHECKING` для импортов, нужных только типам
- Новый код НЕ может добавлять ошибки mypy — проверяй ПЕРЕД коммитом

## callback.message — обязательный паттерн
```python
# ПРАВИЛЬНО: используй msg после safe_message()
msg = safe_message(callback)
if not msg:
    await callback.answer()
    return
await msg.edit_text(text)  # msg — это Message, type checker доволен

# ЗАПРЕЩЕНО: callback.message.* после safe_message() guard
msg = safe_message(callback)
if not msg:
    await callback.answer()
    return
await callback.message.edit_text(text)  # BUG: callback.message всё ещё Message|InaccessibleMessage|None
```
- `callback.message` — тип `Message | InaccessibleMessage | None`
- `InaccessibleMessage` (сообщения >48ч) НЕ имеет `.edit_text()`, `.delete()`, `.answer()` — это runtime crash
- `safe_message()` из `bot/helpers.py` возвращает `Message | None` — используй ТОЛЬКО результат
