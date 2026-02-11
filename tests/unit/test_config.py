"""Tests for bot/config.py — Settings and get_settings singleton."""

import pytest
from pydantic import SecretStr, ValidationError

from bot.config import Settings, get_settings

# All required env vars for a valid Settings
REQUIRED_ENV = {
    "TELEGRAM_BOT_TOKEN": "123:ABC",
    "ADMIN_ID": "203473623",
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_KEY": "test-supabase-key",  # noqa: S105
    "UPSTASH_REDIS_URL": "https://redis.upstash.io",
    "UPSTASH_REDIS_TOKEN": "test-redis-token",  # noqa: S105
    "QSTASH_TOKEN": "test-qstash-token",  # noqa: S105
    "QSTASH_CURRENT_SIGNING_KEY": "test-sig-current",  # noqa: S105
    "QSTASH_NEXT_SIGNING_KEY": "test-sig-next",  # noqa: S105
    "OPENROUTER_API_KEY": "test-openrouter",  # noqa: S105
    "FIRECRAWL_API_KEY": "test-firecrawl",  # noqa: S105
    "ENCRYPTION_KEY": "test-encryption-key",  # noqa: S105
    "TELEGRAM_WEBHOOK_SECRET": "test-webhook-secret",  # noqa: S105
}


def _make_settings(**overrides: str) -> Settings:
    """Create Settings from REQUIRED_ENV, ignoring .env file.

    Pass UPPERCASE keys in overrides to match env var names.
    """
    env = {**REQUIRED_ENV, **overrides}
    # Pydantic Settings expects lowercase field names as kwargs
    lower_env = {k.lower(): v for k, v in env.items()}
    return Settings(_env_file=None, **lower_env)  # type: ignore[call-arg]


@pytest.fixture
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set all required env vars and block .env file."""
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)


class TestSettings:
    def test_loads_required_vars(self) -> None:
        s = _make_settings()
        assert s.admin_id == 203473623
        assert s.supabase_url == "https://test.supabase.co"

    def test_secret_str_fields_hide_values(self) -> None:
        s = _make_settings()
        assert isinstance(s.telegram_bot_token, SecretStr)
        assert "123:ABC" not in repr(s.telegram_bot_token)
        assert s.telegram_bot_token.get_secret_value() == "123:ABC"

    def test_optional_defaults(self) -> None:
        s = _make_settings()
        assert s.dataforseo_login == ""
        assert s.yookassa_shop_id == ""
        assert s.sentry_dsn == ""
        assert s.railway_public_url == ""
        assert s.pinterest_app_id == ""
        assert s.usd_rub_rate == 92.5

    def test_default_config_values(self) -> None:
        s = _make_settings()
        assert s.default_timezone == "Europe/Moscow"
        assert s.fsm_ttl_seconds == 86400
        assert s.fsm_inactivity_timeout == 1800
        assert s.preview_ttl_seconds == 86400
        assert s.max_regenerations_free == 2

    def test_supabase_url_must_be_https(self) -> None:
        with pytest.raises(ValidationError, match="https://"):
            _make_settings(SUPABASE_URL="http://bad.supabase.co")

    def test_missing_required_var_raises(self) -> None:
        env = {k.lower(): v for k, v in REQUIRED_ENV.items() if k != "TELEGRAM_BOT_TOKEN"}
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **env)  # type: ignore[call-arg]

    def test_admin_id_must_be_int(self) -> None:
        with pytest.raises(ValidationError):
            _make_settings(ADMIN_ID="not-a-number")


@pytest.mark.usefixtures("_env")
class TestGetSettings:
    def test_returns_settings_instance(self) -> None:
        get_settings.cache_clear()
        s = get_settings()
        assert isinstance(s, Settings)

    def test_singleton_returns_same_instance(self) -> None:
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
