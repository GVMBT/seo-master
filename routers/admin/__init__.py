"""Admin routers — dashboard, broadcast, costs."""

from aiogram import Router

from routers.admin import costs, dashboard

router = Router()
router.include_router(costs.router)
router.include_router(dashboard.router)
