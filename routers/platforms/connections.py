"""Backward-compatible re-exports from split platform modules.

The original monolithic connections.py has been split into:
- _shared.py: shared constants, helpers, CRUD handlers
- wordpress.py: ConnectWordPressFSM wizard
- telegram.py: ConnectTelegramFSM wizard
- vk.py: ConnectVKFSM wizard
- pinterest.py: ConnectPinterestFSM wizard

This file exists only for backward compatibility. New code should
import from the specific modules or use routers.platforms.__init__.
"""

from routers.platforms._shared import router  # noqa: F401
from routers.platforms.pinterest import ConnectPinterestFSM  # noqa: F401
from routers.platforms.telegram import ConnectTelegramFSM  # noqa: F401
from routers.platforms.vk import ConnectVKFSM  # noqa: F401
from routers.platforms.wordpress import ConnectWordPressFSM  # noqa: F401
