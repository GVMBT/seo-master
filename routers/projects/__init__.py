"""Project routers: create, card, list."""

from aiogram import Router

from routers.projects.card import (
    _format_project_card,
    _get_project_or_notify,
    cb_project_card,
    cb_project_delete,
    cb_project_delete_confirm,
    cb_project_feature_stub,
)
from routers.projects.card import (
    router as card_router,
)
from routers.projects.create import (
    ProjectCreateFSM,
    ProjectEditFSM,
    _validate_field,
    cb_project_edit,
    cb_project_field,
    cb_project_new,
    fsm_project_company,
    fsm_project_field_value,
    fsm_project_name,
    fsm_project_spec,
    fsm_project_url,
)
from routers.projects.create import (
    router as create_router,
)
from routers.projects.list import (
    cb_project_list,
    cb_project_page,
)
from routers.projects.list import (
    router as list_router,
)

router = Router(name="projects")
router.include_router(list_router)
router.include_router(card_router)
router.include_router(create_router)

__all__ = [
    "ProjectCreateFSM",
    "ProjectEditFSM",
    "_format_project_card",
    "_get_project_or_notify",
    "_validate_field",
    "cb_project_card",
    "cb_project_delete",
    "cb_project_delete_confirm",
    "cb_project_edit",
    "cb_project_feature_stub",
    "cb_project_field",
    "cb_project_list",
    "cb_project_new",
    "cb_project_page",
    "fsm_project_company",
    "fsm_project_field_value",
    "fsm_project_name",
    "fsm_project_spec",
    "fsm_project_url",
    "router",
]
