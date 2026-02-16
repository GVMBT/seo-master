---
paths:
  - "tests/**/*.py"
---

# Testing Rules

## Фреймворк
- pytest + pytest-asyncio (`asyncio_mode = "auto"` в pyproject.toml)
- НЕ добавляй `@pytest.mark.asyncio` — все async def test_ автоматически asyncio
- Naming: `test_{feature}_{scenario}_{expected_result}`

## Структура
- tests/ зеркалит top-level: `tests/unit/bot/`, `tests/unit/db/`, `tests/unit/routers/`, `tests/unit/keyboards/`, `tests/unit/services/`
- conftest.py в каждой поддиректории с fixtures для этого модуля

## Готовые fixtures (НЕ дублируй — используй)
- `tests/unit/routers/conftest.py`: `mock_callback`, `mock_message`, `mock_state`, `mock_db`, `user`, `project`, `category`
- `tests/unit/keyboards/helpers.py`: `make_project()`, `make_category()`, `make_user()` — фабрики тестовых данных
- `tests/unit/db/repositories/conftest.py`: `mock_table`, `mock_rpc` — моки PostgREST

## patch() конвенция
- Патчи по месту импорта (НЕ по месту определения):
  - `patch("routers.projects.card.ProjectsRepository")` — ПРАВИЛЬНО
  - `patch("db.repositories.projects.ProjectsRepository")` — НЕПРАВИЛЬНО
- Если хендлер в `routers/projects/create.py` импортирует `ProjectsRepository`, патчи `routers.projects.create.ProjectsRepository`

## Моки
- httpx.MockTransport для внешних API (OpenRouter, Firecrawl, etc.)
- `unittest.mock.AsyncMock` для async repo methods
- PostgREST chain: `.select().eq().execute()` → mock return_value

## Покрытие
- Минимум: каждый handler, каждый service method, каждый repository
- Edge cases: КАЖДЫЙ E01-E52 из docs/EDGE_CASES.md = минимум 1 тест
- Minimum 80% coverage per module

## Чего НЕ тестировать
- Aiogram internals (фильтры, middleware chain — тестируются aiogram)
- Pydantic built-in validation (Field(ge=0) — тестируется Pydantic)
- PostgREST SQL generation — тестируем только что правильный метод вызван с правильными аргументами
