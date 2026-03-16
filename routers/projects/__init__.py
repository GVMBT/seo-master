"""Projects sub-router — list, create, card."""

from aiogram import Router

from routers.projects import card, create
from routers.projects import list as project_list
from routers.projects.content_settings import router as content_settings_router

router = Router()
router.include_router(project_list.router)
router.include_router(create.router)
router.include_router(card.router)
router.include_router(content_settings_router)
