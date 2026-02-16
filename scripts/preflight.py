"""Pre-flight check: verify all required env vars and connectivity before deploy.

Usage:
    uv run python scripts/preflight.py

Checks:
  1. Required env vars are set
  2. Supabase DB is reachable (query users table)
  3. RPC functions exist (charge_balance, refund_balance, credit_balance)
  4. Redis is reachable (PING)
  5. OpenRouter API key is valid (list models)
  6. Telegram bot token is valid (getMe)
  7. Prompt versions are seeded
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

_REQUIRED_VARS = [
    "TELEGRAM_BOT_TOKEN",
    "ADMIN_IDS",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "UPSTASH_REDIS_URL",
    "UPSTASH_REDIS_TOKEN",
    "QSTASH_TOKEN",
    "QSTASH_CURRENT_SIGNING_KEY",
    "QSTASH_NEXT_SIGNING_KEY",
    "OPENROUTER_API_KEY",
    "ENCRYPTION_KEY",
    "TELEGRAM_WEBHOOK_SECRET",
]

_OPTIONAL_VARS = [
    "FIRECRAWL_API_KEY",
    "DATAFORSEO_LOGIN",
    "SERPER_API_KEY",
    "YOOKASSA_SHOP_ID",
    "SENTRY_DSN",
    "RAILWAY_PUBLIC_URL",
    "HEALTH_CHECK_TOKEN",
]

passed = 0
failed = 0
warnings = 0


def ok(msg: str) -> None:
    global passed
    passed += 1
    print(f"  [OK] {msg}")


def fail(msg: str) -> None:
    global failed
    failed += 1
    print(f"  [FAIL] {msg}")


def warn(msg: str) -> None:
    global warnings
    warnings += 1
    print(f"  [WARN] {msg}")


def _get_supabase_creds() -> tuple[str, str]:
    return os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_KEY", "")


def check_env_vars() -> None:
    """Check required and optional env vars."""
    print("\n1. Environment variables")
    for var in _REQUIRED_VARS:
        if os.environ.get(var):
            ok(f"{var} is set")
        else:
            fail(f"{var} is MISSING")

    for var in _OPTIONAL_VARS:
        if os.environ.get(var):
            ok(f"{var} is set")
        else:
            warn(f"{var} not set (optional)")


async def check_supabase() -> None:
    """Check Supabase DB connectivity."""
    import httpx

    print("\n2. Supabase Database")
    url, key = _get_supabase_creds()
    if not (url and key):
        fail("SUPABASE_URL or SUPABASE_KEY not set — skipping")
        return
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{url}/rest/v1/users?select=id&limit=1",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                timeout=10,
            )
            if resp.status_code == 200:
                ok("users table reachable")
            else:
                fail(f"users table returned {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        fail(f"Supabase connection failed: {e}")


async def check_rpc() -> None:
    """Check that RPC functions exist in Supabase."""
    import httpx

    print("\n3. RPC Functions")
    url, key = _get_supabase_creds()
    if not (url and key):
        fail("Supabase not configured — skipping RPC check")
        return
    for fn in ["charge_balance", "refund_balance", "credit_balance"]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{url}/rest/v1/rpc/{fn}",
                    json={"p_user_id": 0, "p_amount": 0},
                    headers={"apikey": key, "Authorization": f"Bearer {key}"},
                    timeout=10,
                )
                if resp.status_code in (200, 400):
                    ok(f"RPC {fn} exists")
                elif resp.status_code == 404:
                    fail(f"RPC {fn} NOT FOUND — run migration")
                else:
                    warn(f"RPC {fn} returned {resp.status_code}")
        except Exception as e:
            fail(f"RPC {fn} check failed: {e}")


async def check_redis() -> None:
    """Check Redis connectivity."""
    import httpx

    print("\n4. Upstash Redis")
    redis_url = os.environ.get("UPSTASH_REDIS_URL", "")
    redis_token = os.environ.get("UPSTASH_REDIS_TOKEN", "")
    if not (redis_url and redis_token):
        fail("Redis not configured")
        return
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{redis_url}/ping",
                headers={"Authorization": f"Bearer {redis_token}"},
                timeout=10,
            )
            if resp.status_code == 200 and "PONG" in resp.text:
                ok("Redis PING -> PONG")
            else:
                fail(f"Redis PING failed: {resp.status_code}")
    except Exception as e:
        fail(f"Redis connection failed: {e}")


async def check_openrouter() -> None:
    """Check OpenRouter API key."""
    import httpx

    print("\n5. OpenRouter API")
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not or_key:
        fail("OPENROUTER_API_KEY not set")
        return
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://openrouter.ai/api/v1/auth/key",
                headers={"Authorization": f"Bearer {or_key}"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                balance = data.get("limit_remaining")
                ok(f"OpenRouter key valid (balance: ${balance})" if balance else "OpenRouter key valid")
            else:
                fail(f"OpenRouter key invalid: {resp.status_code}")
    except Exception as e:
        fail(f"OpenRouter check failed: {e}")


async def check_telegram() -> None:
    """Check Telegram bot token."""
    import httpx

    print("\n6. Telegram Bot")
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        fail("TELEGRAM_BOT_TOKEN not set")
        return
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=10)
            if resp.status_code == 200 and resp.json().get("ok"):
                username = resp.json()["result"].get("username", "?")
                ok(f"Bot @{username} is alive")
            else:
                fail(f"Bot token invalid: {resp.text[:100]}")
    except Exception as e:
        fail(f"Telegram check failed: {e}")


async def check_prompts() -> None:
    """Check that prompt_versions table is seeded."""
    import httpx

    print("\n7. Prompt Versions")
    url, key = _get_supabase_creds()
    if not (url and key):
        return
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{url}/rest/v1/prompt_versions?select=task_type,version,is_active",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                timeout=10,
            )
            if resp.status_code == 200:
                prompts = resp.json()
                active = [p for p in prompts if p.get("is_active")]
                if len(active) >= 5:
                    ok(f"{len(prompts)} prompts ({len(active)} active)")
                elif prompts:
                    warn(f"{len(prompts)} prompts but only {len(active)} active")
                else:
                    fail("prompt_versions empty — run: uv run python scripts/seed_prompts.py")
            else:
                fail(f"prompt_versions query failed: {resp.status_code}")
    except Exception as e:
        fail(f"Prompt check failed: {e}")


async def main() -> None:
    print("=" * 60)
    print("SEO Master Bot v2 -- Pre-flight Check")
    print("=" * 60)

    check_env_vars()
    await check_supabase()
    await check_rpc()
    await check_redis()
    await check_openrouter()
    await check_telegram()
    await check_prompts()

    # Summary
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {warnings} warnings")
    if failed:
        print("STATUS: NOT READY -- fix failures above before deploy")
        sys.exit(1)
    elif warnings:
        print("STATUS: READY with warnings (optional services missing)")
    else:
        print("STATUS: ALL CLEAR -- ready to deploy!")


if __name__ == "__main__":
    asyncio.run(main())
