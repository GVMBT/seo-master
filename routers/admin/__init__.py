"""Admin panel routers: dashboard + broadcast."""

from aiogram import Router

from routers.admin.broadcast import BroadcastFSM
from routers.admin.broadcast import router as broadcast_router
from routers.admin.dashboard import router as dashboard_router

router = Router(name="admin")
router.include_router(dashboard_router)
router.include_router(broadcast_router)

__all__ = ["BroadcastFSM", "router"]
