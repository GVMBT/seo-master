"""FSM conflict resolution utility (E26, FSM_SPEC section 2)."""

from aiogram.fsm.context import FSMContext

# Human-readable names for FSM states (Russian UI)
_FSM_NAMES: dict[str, str] = {
    "ProjectCreate": "создание проекта",
    "ProjectEdit": "редактирование проекта",
    "CategoryCreate": "создание категории",
    "KeywordGeneration": "подбор ключевых фраз",
    "KeywordUpload": "загрузка ключевых фраз",
    "ArticlePublish": "публикация статьи",
    "SocialPostPublish": "публикация поста",
    "ScheduleSetup": "настройка расписания",
    "ConnectWordPress": "подключение WordPress",
    "ConnectTelegram": "подключение Telegram",
    "ConnectVK": "подключение VK",
    "ConnectPinterest": "подключение Pinterest",
    "PriceInput": "ввод цен",
    "ReviewGeneration": "генерация отзывов",
    "DescriptionGenerate": "генерация описания",
    "CompetitorAnalysis": "анализ конкурентов",
}


async def ensure_no_active_fsm(state: FSMContext) -> str | None:
    """Clear any active FSM and return interrupted process name, or None.

    Call this before ``state.set_state()`` in every FSM entry point.
    Returns human-readable name of the interrupted FSM, or ``None`` if no
    conflict existed.

    Usage in routers::

        interrupted = await ensure_no_active_fsm(state)
        if interrupted:
            await callback.message.answer(
                f"Предыдущий процесс ({interrupted}) прерван."
            )
        await state.set_state(SomeFSM.first_state)
    """
    current = await state.get_state()
    if current is None:
        return None

    # State string format: "ClassName:state_name" (e.g. "ProjectCreate:name")
    fsm_class = current.split(":")[0]
    await state.clear()
    return _FSM_NAMES.get(fsm_class, fsm_class)
