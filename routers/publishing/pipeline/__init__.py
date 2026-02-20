"""Pipeline routers — Article and Social goal-oriented pipelines."""

from aiogram import Router

from routers.publishing.pipeline import article, generation, readiness

router = Router()
router.include_router(article.router)
router.include_router(readiness.router)
router.include_router(generation.router)
# TODO F6: router.include_router(social.router)
