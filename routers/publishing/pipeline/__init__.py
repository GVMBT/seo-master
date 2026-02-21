"""Pipeline routers — Article and Social goal-oriented pipelines."""

from aiogram import Router

from routers.publishing.pipeline import article, exit_protection, generation, readiness

router = Router()
# Exit protection FIRST — intercepts "Меню"/"Отмена"/"/cancel" before other handlers
router.include_router(exit_protection.router)
router.include_router(article.router)
router.include_router(readiness.router)
router.include_router(generation.router)
# TODO F6: router.include_router(social.router)
