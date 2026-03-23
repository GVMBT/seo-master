"""Platforms sub-router."""

from aiogram import Router

from routers.platforms._shared import router as shared_router
from routers.platforms.pinterest import router as pinterest_router
from routers.platforms.telegram import router as tg_router
from routers.platforms.vk import router as vk_router
from routers.platforms.wordpress import router as wp_router

router = Router()
router.include_router(shared_router)
router.include_router(wp_router)
router.include_router(tg_router)
router.include_router(vk_router)
router.include_router(pinterest_router)
