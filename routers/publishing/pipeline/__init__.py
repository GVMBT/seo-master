"""Pipeline router package -- Goal-Oriented Pipeline (UX_PIPELINE.md)."""

from aiogram import F, Router
from aiogram.types import CallbackQuery

from routers.publishing.pipeline.article import router as article_pipeline_router

router = Router(name="pipeline")
router.include_router(article_pipeline_router)


@router.callback_query(F.data == "pipeline:social:start")
async def cb_social_pipeline_stub(callback: CallbackQuery) -> None:
    """Stub for Social Pipeline (Phase 13C)."""
    await callback.answer("Публикация постов — в разработке", show_alert=True)
