"""Admin routers — dashboard, broadcast."""

from aiogram import Router

from routers.admin import dashboard

router = Router()
router.include_router(dashboard.router)
