"""Platforms sub-router."""

from aiogram import Router

from routers.platforms.connections import router as connections_router

router = Router()
router.include_router(connections_router)
