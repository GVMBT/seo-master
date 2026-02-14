"""Publishing router package — scheduler, preview, social post, quick publish."""

from aiogram import Router

from routers.publishing.preview import router as preview_router
from routers.publishing.quick import router as quick_router
from routers.publishing.scheduler import router as scheduler_router
from routers.publishing.social import router as social_router

router = Router(name="publishing")
router.include_router(preview_router)
router.include_router(social_router)
router.include_router(quick_router)
router.include_router(scheduler_router)
