"""Router: user settings (notification toggles)."""

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from db.client import SupabaseClient
from db.models import User, UserUpdate
from db.repositories.users import UsersRepository
from keyboards.inline import settings_main_kb, settings_notifications_kb

router = Router(name="settings")

# ---------------------------------------------------------------------------
# Settings menu
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "settings:main")
async def cb_settings_main(callback: CallbackQuery) -> None:
    """Show settings menu."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    await callback.message.edit_text(
        "Настройки:", reply_markup=settings_main_kb().as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.in_({"settings:support", "settings:about"}))
async def cb_settings_stub(callback: CallbackQuery) -> None:
    """Stub for not-yet-implemented settings features."""
    await callback.answer("В разработке.", show_alert=True)


@router.callback_query(F.data == "settings:notifications")
async def cb_notifications(callback: CallbackQuery, user: User) -> None:
    """Show notification toggles."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    await callback.message.edit_text(
        "Уведомления:", reply_markup=settings_notifications_kb(user).as_markup()
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Toggle individual notification types
# ---------------------------------------------------------------------------

_NOTIFY_FIELDS = {
    "publications": "notify_publications",
    "balance": "notify_balance",
    "news": "notify_news",
}


@router.callback_query(F.data.startswith("settings:notify:"))
async def cb_toggle_notify(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Flip a notification boolean and re-render keyboard."""
    notify_type = callback.data.split(":")[2]  # type: ignore[union-attr]
    field_name = _NOTIFY_FIELDS.get(notify_type)
    if not field_name:
        await callback.answer("Неизвестный тип уведомлений.", show_alert=True)
        return

    current_value = getattr(user, field_name)
    new_value = not current_value

    repo = UsersRepository(db)
    updated_user = await repo.update(user.id, UserUpdate.model_validate({field_name: new_value}))
    if updated_user is None:
        await callback.answer("Ошибка обновления.", show_alert=True)
        return

    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    await callback.message.edit_reply_markup(
        reply_markup=settings_notifications_kb(updated_user).as_markup()
    )
    status = "включены" if new_value else "выключены"
    await callback.answer(f"Уведомления {status}.")
