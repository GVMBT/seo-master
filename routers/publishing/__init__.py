"""Publishing routers -- scheduler and pipeline."""

from aiogram import Router

from routers.publishing import scheduler
from routers.publishing.pipeline import router as pipeline_router

router = Router()
router.include_router(pipeline_router)
router.include_router(scheduler.router)
