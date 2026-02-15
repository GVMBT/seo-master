"""Entry point: python -m bot."""

import os

from aiohttp import web

from bot.main import create_app

if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", "8080"))
    web.run_app(app, host="0.0.0.0", port=port)  # noqa: S104  # nosec B104 — Railway requires bind to all interfaces
