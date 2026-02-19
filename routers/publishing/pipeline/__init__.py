"""Pipeline routers — Article and Social goal-oriented pipelines."""

from aiogram import Router

from routers.publishing.pipeline import article, readiness

router = Router()
router.include_router(article.router)
router.include_router(readiness.router)
# TODO F6: router.include_router(social.router)
