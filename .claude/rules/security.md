---
paths:
  - "**/*.py"
---

# Security Rules

## Шифрование и секреты
- Credentials: ТОЛЬКО Fernet encryption через `db/credential_manager.py`, ключ из env var ENCRYPTION_KEY
- API-ключи в config: `SecretStr` (pydantic) — значение не попадает в логи/repr
- Env vars: НЕ хардкодить, НЕ логировать, НЕ коммитить
- `except Exception: pass` ЗАПРЕЩЁН — логируй через structlog и обрабатывай

## Запросы и валидация
- SQL: параметризованные запросы ВСЕГДА (никаких f-string/конкатенаций в SQL)
- User input: sanitize перед передачей в AI-промпты (Jinja2 `<< >>` авто-экранирует)
- Input boundaries: max lengths, allowed chars — валидируй в FSM-хендлерах ДО сохранения

## Авторизация
- Admin: проверка role=='admin' через middleware (data["is_admin"]), не в хендлерах
- **callback_data tampering**: пользователь может подделать ID в callback. ВСЕГДА проверяй `project.user_id == user.id` после загрузки из БД. НЕ доверяй ID из callback_data без проверки владельца.

## Webhooks
- Telegram webhook: верификация secret_token (docs/API_CONTRACTS.md §4.3)
- QStash webhook: верификация подписи (docs/API_CONTRACTS.md §1.3)
- YooKassa webhook: IP-whitelist (docs/API_CONTRACTS.md §2.4)

## Rate limits
- Anti-flood: Redis token-bucket в ThrottlingMiddleware (docs/API_CONTRACTS.md §4.1)
- Per-action limits: 10 gen/hr, 20 img/hr — проверяются в services/ layer
