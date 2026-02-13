"""Publishing router package — scheduler and related handlers."""

from aiogram import Router

from routers.publishing.scheduler import router as scheduler_router

router = Router(name="publishing")
router.include_router(scheduler_router)
