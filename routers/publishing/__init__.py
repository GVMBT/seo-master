"""Publishing router package -- scheduler, preview, social, dispatch, quick, pipeline."""

from aiogram import Router

from routers.publishing.dispatch import router as dispatch_router
from routers.publishing.pipeline import router as pipeline_router
from routers.publishing.preview import router as preview_router
from routers.publishing.quick import router as quick_router
from routers.publishing.scheduler import router as scheduler_router
from routers.publishing.social import router as social_router

router = Router(name="publishing")
router.include_router(preview_router)
router.include_router(social_router)
router.include_router(dispatch_router)
router.include_router(quick_router)
router.include_router(pipeline_router)
router.include_router(scheduler_router)
