"""Admin routers — dashboard, broadcast, costs, users."""

from aiogram import Router

from routers.admin import costs, dashboard, users

router = Router()
router.include_router(users.router)
router.include_router(costs.router)
router.include_router(dashboard.router)
