"""Application configuration via Pydantic Settings v2."""

from functools import lru_cache
from typing import Annotated

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """All env vars from docs/API_CONTRACTS.md section 4.2."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # === Required ===
    telegram_bot_token: SecretStr
    admin_ids: Annotated[list[int], NoDecode]
    supabase_url: str
    supabase_key: SecretStr
    upstash_redis_url: str
    upstash_redis_token: SecretStr
    qstash_token: SecretStr
    qstash_current_signing_key: SecretStr
    qstash_next_signing_key: SecretStr
    openrouter_api_key: SecretStr
    firecrawl_api_key: SecretStr = SecretStr("")
    encryption_key: SecretStr
    telegram_webhook_secret: SecretStr

    # === Optional ===
    dataforseo_login: str = ""
    dataforseo_password: SecretStr = SecretStr("")
    serper_api_key: SecretStr = SecretStr("")
    yookassa_shop_id: str = ""
    yookassa_secret_key: SecretStr = SecretStr("")
    yookassa_return_url: str = ""
    sentry_dsn: str = ""
    railway_public_url: str = ""
    pinterest_app_id: str = ""
    pinterest_app_secret: SecretStr = SecretStr("")
    health_check_token: SecretStr = SecretStr("")
    usd_rub_rate: float = 92.5

    # === Defaults ===
    default_timezone: str = "Europe/Moscow"
    fsm_ttl_seconds: int = 86400
    fsm_inactivity_timeout: int = 1800
    preview_ttl_seconds: int = 86400
    max_regenerations_free: int = 2
    railway_graceful_shutdown_timeout: int = 120

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, v: str | list[int]) -> list[int]:
        if isinstance(v, list):
            ids = v
        else:
            ids = [int(x.strip()) for x in str(v).split(",") if x.strip()]
        if not ids:
            msg = "ADMIN_IDS must contain at least one admin ID"
            raise ValueError(msg)
        return ids

    @field_validator("supabase_url")
    @classmethod
    def _supabase_url_must_be_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            msg = "SUPABASE_URL must start with https://"
            raise ValueError(msg)
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton Settings instance (cached after first call)."""
    return Settings()  # type: ignore[call-arg]
