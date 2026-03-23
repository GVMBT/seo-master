"""Backward-compatible re-exports from split keyboard modules.

All keyboard functions are now organized by domain:
- common.py: menu_kb, cancel_kb, consent_kb, format_connection_display
- dashboard.py: dashboard_kb, dashboard_resume_kb
- projects.py: project_list_kb, project_card_kb, etc.
- categories.py: category_*, connection_*, keywords_*, description_*, prices_*
- content_settings.py: project_content_settings_kb, all option keyboards
- profile_admin.py: profile_*, tariffs_*, scheduler_*, admin_*

Existing imports like ``from keyboards.inline import X`` continue to work.
"""

from keyboards.categories import *  # noqa: F403
from keyboards.common import *  # noqa: F403
from keyboards.content_settings import *  # noqa: F403
from keyboards.dashboard import *  # noqa: F403
from keyboards.profile_admin import *  # noqa: F403
from keyboards.profile_admin import _DAY_LABELS as _DAY_LABELS
from keyboards.profile_admin import _PRESETS as _PRESETS
from keyboards.projects import *  # noqa: F403
