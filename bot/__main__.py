"""Entry point: python -m bot."""

import asyncio
import os
import sys


def _run_seed() -> None:
    """Run prompt seeding before app startup (replaces separate uv run call)."""
    # Only seed in production (Railway sets RAILWAY_ENVIRONMENT)
    if not os.environ.get("RAILWAY_ENVIRONMENT"):
        return

    try:
        # Inject --force flag so seed_prompts updates existing prompts
        if "--force" not in sys.argv:
            sys.argv.append("--force")

        from scripts.seed_prompts import main as seed_main

        asyncio.run(seed_main())

        # Clean up injected flag
        if "--force" in sys.argv:
            sys.argv.remove("--force")
    except Exception as exc:
        print(f"WARNING: seed_prompts failed: {exc}", file=sys.stderr)
        # Non-fatal — app can start without fresh seeds


if __name__ == "__main__":
    _run_seed()

    from aiohttp import web

    from bot.main import create_app

    app = create_app()
    port = int(os.environ.get("PORT", "8080"))
    web.run_app(app, host="0.0.0.0", port=port)  # noqa: S104  # nosec B104 — Railway requires bind to all interfaces
