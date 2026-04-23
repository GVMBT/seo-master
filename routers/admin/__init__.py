"""Admin routers — dashboard, broadcast, costs, users, bamboodom."""

from aiogram import Router

from routers.admin import bamboodom, costs, dashboard, users

router = Router()
router.include_router(users.router)
router.include_router(costs.router)
router.include_router(dashboard.router)
router.include_router(bamboodom.router)
