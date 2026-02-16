# Модуль routers/ — Aiogram роутеры

## Правила
- Роутер = ТОЛЬКО маршрутизация и UI-логика
- Бизнес-логика ВСЕГДА в services/
- FSM StatesGroup определяются в роутере, который их использует
- Всегда проверять data["user"] и data["is_admin"] из middleware
- callback_data: формат {entity}:{id}:{action}, max 64 байта
- Пагинация по 8 кнопок + [Ещё ▼]
- Лимит Telegram: 4096 символов на сообщение, 1024 на caption

## Паттерн роутера
```python
router = Router(name="projects")

@router.callback_query(F.data.startswith("project:"))
async def project_card(callback: CallbackQuery, user: User, db: SupabaseClient):
    project_id = int(callback.data.split(":")[1])
    project = await ProjectRepository(db).get_by_id(project_id, user.id)
```

## FSM-правила (docs/FSM_SPEC.md)
- /cancel из любого состояния → сброс FSM, возврат в меню
- /start во время FSM → сброс FSM, главное меню
- Невалидный ввод → повтор запроса с сообщением об ошибке
- Фото/видео/стикер вместо текста → "Отправьте текстовое сообщение"
- Двойное нажатие: FSM-переход preview→publishing одноразовый (E07)

## 18 StatesGroup (полный список → docs/FSM_SPEC.md §1)
ProjectCreate(4), CategoryCreate(1), ProjectEdit(1),
KeywordGeneration(8), KeywordUpload(4),
ArticlePublish(5), SocialPostPublish(5),
ScheduleSetup(3), DescriptionGenerate(2), ReviewGeneration(4),
CompetitorAnalysis(4), PriceInput(3),
ConnectWordPress(3), ConnectTelegram(2), ConnectVK(2), ConnectPinterest(2),
ArticlePipeline(23), SocialPipeline(10)
