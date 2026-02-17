"""Pipeline routers — Article and Social goal-oriented pipelines."""

from aiogram import Router

from routers.publishing.pipeline import article

router = Router()
router.include_router(article.router)
# TODO F6: router.include_router(social.router)
