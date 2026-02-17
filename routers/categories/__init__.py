"""Categories sub-router."""

from aiogram import Router

from routers.categories.content_settings import router as content_settings_router
from routers.categories.description import router as description_router
from routers.categories.keywords import router as keywords_router
from routers.categories.manage import router as manage_router
from routers.categories.prices import router as prices_router

router = Router()
router.include_router(manage_router)
router.include_router(keywords_router)
router.include_router(description_router)
router.include_router(prices_router)
router.include_router(content_settings_router)
