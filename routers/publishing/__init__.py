"""Publishing routers -- scheduler and pipeline."""

from aiogram import Router

from routers.publishing import scheduler

router = Router()
router.include_router(scheduler.router)
