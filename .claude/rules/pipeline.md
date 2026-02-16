---
paths:
  - "routers/publishing/pipeline/**/*.py"
---

# Pipeline Rules (Goal-Oriented Pipeline)

## Архитектура (UX_PIPELINE.md)

Pipeline — воронка "Написать статью" / "Пост в соцсети". Заменяет Quick Publish.

### Inline Handlers (НЕ FSM delegation)
Pipeline **сам** реализует sub-flows, переиспользуя Service Layer:
```python
# ПРАВИЛЬНО — inline handler внутри PipelineFSM:
@router.message(ArticlePipelineFSM.readiness_keywords)
async def pipeline_keywords_input(message, state, db):
    service = KeywordService(db=db, http_client=data["http_client"])
    result = await service.generate(products, geo, count)
    await state.set_state(ArticlePipelineFSM.readiness_check)

# ЗАПРЕЩЕНО — вызов чужого FSM:
await state.set_state(KeywordGenerationFSM.waiting_products)  # НЕТ
```

### Redis Checkpoint (E49)
Отдельный ключ от Aiogram FSM:
```python
# Checkpoint = snapshot для возобновления с Dashboard
key = f"pipeline:{user_id}:state"  # TTL 24h
# Содержит: step, project_id, category_id, readiness_status
# НЕ дублирует Aiogram FSMContext — это для resume после timeout
```

### ButtonStyle (Bot API 9.4)
```python
# Семантическая система кнопок:
# PRIMARY (request_chat style) — максимум 1 на экране, главное действие
# SUCCESS (green via copy_text) — подтверждение, публикация
# DANGER (red via switch_inline) — удаление, отмена, выход
# DEFAULT — все остальные кнопки

# ПРАВИЛЬНО:
InlineKeyboardButton(text="Опубликовать", ...)  # 1 PRIMARY
InlineKeyboardButton(text="Редактировать", ...)  # DEFAULT
InlineKeyboardButton(text="Отмена", ...)         # DANGER

# ЗАПРЕЩЕНО:
# 2+ PRIMARY на одном экране
# DANGER для навигационных кнопок
```

### Exit Protection (§7.5)
На шагах 4-7 (после readiness check) — подтверждение при выходе:
```python
# При /cancel или "Назад" на шагах 4+:
"Прервать публикацию? Прогресс сохранится на 24ч."
[Да, выйти]  [Продолжить]
```

### Checklist UX (§16.15)
- Простые sub-flows (1 ответ): `editMessageText` чеклиста
- Сложные sub-flows (3+ сообщений): `deleteMessage` старого + новое сообщение внизу

## Чеклист для Pipeline-роутеров

- [ ] Все sub-flows через Service Layer (KeywordService, ConnectionService, etc.)
- [ ] Никаких импортов из других FSM StatesGroup
- [ ] Redis checkpoint обновляется на каждом шаге (pipeline:{user_id}:state)
- [ ] Exit protection на шагах 4-7
- [ ] ButtonStyle: максимум 1 PRIMARY на экране
- [ ] Readiness check через ReadinessService (не inline логика)
- [ ] Cross-post: обязательный review перед публикацией (E52)
- [ ] callback_data: `pipeline:article:*` или `pipeline:social:*` (не `quick:*`)
