"""Router: platform content overrides (F41).

Stub for Phase 10+ detailed settings. Currently provides view/edit entry points
for category+platform content overrides (image_settings, text_settings).
"""

from aiogram import F, Router
from aiogram.types import CallbackQuery

from routers._helpers import guard_callback_message

router = Router(name="platforms_settings")


@router.callback_query(F.data.regexp(r"^category:(\d+):override:(\w+)$"))
async def cb_override_stub(callback: CallbackQuery) -> None:
    """Stub: view/edit content overrides for a category+platform.

    Full implementation deferred to Phase 10 (image_settings, text_settings
    per platform with inheritance from category defaults).
    """
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    await callback.answer("Настройки контента для платформы — в разработке.", show_alert=True)
