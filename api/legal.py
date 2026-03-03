"""Legal document redirect handlers — thin aiohttp.web redirects to Telegraph.

Pinterest/VK app review requires privacy policy URL on the app's own domain.
These handlers redirect to the Telegraph-hosted documents.
"""

from aiohttp import web

from bot.texts.legal import PRIVACY_POLICY_URL, TERMS_OF_SERVICE_URL


async def legal_privacy(_request: web.Request) -> web.Response:
    """GET /api/legal/privacy → redirect to Telegraph privacy policy."""
    raise web.HTTPFound(location=PRIVACY_POLICY_URL)


async def legal_terms(_request: web.Request) -> web.Response:
    """GET /api/legal/terms → redirect to Telegraph terms of service."""
    raise web.HTTPFound(location=TERMS_OF_SERVICE_URL)
