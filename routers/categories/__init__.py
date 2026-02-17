"""Categories sub-router."""

from aiogram import Router

from routers.categories.manage import router as manage_router

router = Router()
router.include_router(manage_router)
