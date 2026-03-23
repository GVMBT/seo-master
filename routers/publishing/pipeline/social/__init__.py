"""Social Pipeline routers — goal-oriented pipeline for social post creation (F6)."""

from aiogram import Router

from routers.publishing.pipeline.social import connection, crosspost, generation, readiness, social

router = Router()
router.include_router(social.router)
router.include_router(connection.router)
router.include_router(readiness.router)
router.include_router(generation.router)
router.include_router(crosspost.router)
