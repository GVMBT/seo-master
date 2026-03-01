"""HTTP API endpoints (aiohttp.web) — webhooks, OAuth, health."""

import json
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any

import structlog
from aiohttp import web

log = structlog.get_logger()


def require_qstash_signature(
    handler: Callable[..., Coroutine[Any, Any, web.Response]],
) -> Callable[..., Coroutine[Any, Any, web.Response]]:
    """Decorator: verify QStash webhook signature (API_CONTRACTS.md section 1.3).

    Uses ``qstash.Receiver`` to verify the signature header.
    On success, stores parsed body as ``request["verified_body"]``
    and Upstash-Message-Id as ``request["qstash_msg_id"]``.
    Returns 401 on invalid/missing signature.
    """

    @wraps(handler)
    async def wrapper(request: web.Request) -> web.Response:
        from qstash import Receiver

        settings = request.app["settings"]
        body = await request.read()
        signature = request.headers.get("Upstash-Signature", "")

        # Use public URL for signature verification (Railway reverse proxy
        # makes request.url return internal http://0.0.0.0:8080/... URL,
        # but QStash signed against the public URL).
        public_base = settings.railway_public_url.rstrip("/")
        url = f"{public_base}{request.path}" if public_base else str(request.url)

        if not signature:
            log.warning("qstash_missing_signature", url=url)
            return web.Response(status=401, text="Missing signature")

        receiver = Receiver(
            current_signing_key=settings.qstash_current_signing_key.get_secret_value(),
            next_signing_key=settings.qstash_next_signing_key.get_secret_value(),
        )

        try:
            receiver.verify(
                body=body.decode("utf-8"),
                signature=signature,
                url=url,
            )
        except Exception:
            log.warning("qstash_invalid_signature", url=url)
            return web.Response(status=401, text="Invalid signature")

        try:
            request["verified_body"] = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            log.warning("qstash_malformed_body", url=url)
            return web.Response(status=401, text="Malformed body")

        request["qstash_msg_id"] = request.headers.get("Upstash-Message-Id", "")
        return await handler(request)

    return wrapper
