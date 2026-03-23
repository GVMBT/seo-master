"""Project-level content settings -- facade module.

Re-exports a combined router from _settings_common, text_settings,
and image_settings sub-modules. External code imports
``from routers.projects.content_settings import router``.
"""

from aiogram import Router

from routers.projects._settings_common import router as _common_router
from routers.projects.image_settings import router as _image_router
from routers.projects.text_settings import router as _text_router

router = Router()
router.include_router(_common_router)
router.include_router(_text_router)
router.include_router(_image_router)
