---
paths:
  - "tests/**/*.py"
---

# Testing Rules

- Фреймворк: pytest + pytest-asyncio
- Структура: tests/ зеркалит src/ (tests/handlers/, tests/services/, ...)
- Минимальное покрытие: каждый handler, каждый service method, каждый repository
- Моки: httpx.MockTransport для внешних API, не monkey-patching
- Fixtures: conftest.py в каждой поддиректории
- Тестовая БД: отдельный Supabase проект или SQLite in-memory (для unit)
- Edge cases: КАЖДЫЙ E01-E25 из docs/EDGE_CASES.md = минимум 1 тест
- Naming: test_{feature}_{scenario}_{expected_result}
