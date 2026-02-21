"""Social Pipeline routers — goal-oriented pipeline for social post creation (F6)."""

from aiogram import Router

from routers.publishing.pipeline.social import connection, social

router = Router()
router.include_router(social.router)
router.include_router(connection.router)
# TODO F6.3: router.include_router(readiness.router)
# TODO F6.3: router.include_router(generation.router)
# TODO F6.4: router.include_router(crosspost.router)
