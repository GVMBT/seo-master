"""Tests for bot/config.py — Settings and get_settings singleton."""

import pytest
from pydantic import SecretStr, ValidationError

from bot.config import Settings, get_settings

# All required env vars for a valid Settings
REQUIRED_ENV = {
    "TELEGRAM_BOT_TOKEN": "123:ABC",
    "ADMIN_IDS": "203473623",
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_KEY": "test-supabase-key",
    "UPSTASH_REDIS_URL": "https://redis.upstash.io",
    "UPSTASH_REDIS_TOKEN": "test-redis-token",
    "QSTASH_TOKEN": "test-qstash-token",
    "QSTASH_CURRENT_SIGNING_KEY": "test-sig-current",
    "QSTASH_NEXT_SIGNING_KEY": "test-sig-next",
    "OPENROUTER_API_KEY": "test-openrouter",
    "FIRECRAWL_API_KEY": "test-firecrawl",
    "ENCRYPTION_KEY": "test-encryption-key",
    "TELEGRAM_WEBHOOK_SECRET": "test-webhook-secret",
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
        assert s.admin_ids == [203473623]
        assert s.supabase_url == "https://test.supabase.co"

    def test_secret_str_fields_hide_values(self) -> None:
        s = _make_settings()
        assert isinstance(s.telegram_bot_token, SecretStr)
        assert "123:ABC" not in repr(s.telegram_bot_token)
        assert s.telegram_bot_token.get_secret_value() == "123:ABC"

    def test_optional_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Clear optional env vars that may leak from host OS
        for var in (
            "DATAFORSEO_LOGIN", "YOOKASSA_SHOP_ID", "SENTRY_DSN",
            "RAILWAY_PUBLIC_URL", "PINTEREST_APP_ID", "HEALTH_CHECK_TOKEN",
            "USD_RUB_RATE",
        ):
            monkeypatch.delenv(var, raising=False)
        s = _make_settings()
        assert s.dataforseo_login == ""
        assert s.yookassa_shop_id == ""
        assert s.sentry_dsn == ""
        assert s.railway_public_url == ""
        assert s.pinterest_app_id == ""
        assert s.health_check_token.get_secret_value() == ""
        assert s.usd_rub_rate == 92.5

    def test_default_config_values(self) -> None:
        s = _make_settings()
        assert s.default_timezone == "Europe/Moscow"
        assert s.fsm_ttl_seconds == 86400
        assert s.fsm_inactivity_timeout == 1800
        assert s.preview_ttl_seconds == 86400
        assert s.max_regenerations_free == 2
        assert s.railway_graceful_shutdown_timeout == 120

    def test_supabase_url_must_be_https(self) -> None:
        with pytest.raises(ValidationError, match="https://"):
            _make_settings(SUPABASE_URL="http://bad.supabase.co")

    def test_missing_required_var_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        env = {k.lower(): v for k, v in REQUIRED_ENV.items() if k != "TELEGRAM_BOT_TOKEN"}
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **env)  # type: ignore[call-arg]

    def test_admin_ids_must_be_ints(self) -> None:
        with pytest.raises(ValidationError):
            _make_settings(ADMIN_IDS="not-a-number")

    def test_admin_ids_comma_separated(self) -> None:
        s = _make_settings(ADMIN_IDS="111,222,333")
        assert s.admin_ids == [111, 222, 333]

    def test_admin_ids_single_value(self) -> None:
        s = _make_settings(ADMIN_IDS="42")
        assert s.admin_ids == [42]


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
