"""Root entry point for Railway Railpack auto-detection.

Railpack requires main.py/app.py/bot.py in root to detect the start command.
The actual deploy uses startCommand from railway.json, not this file.
"""

import os

from aiohttp import web

from bot.main import create_app

if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", "8080"))
    web.run_app(app, host="0.0.0.0", port=port)  # noqa: S104  # nosec B104
