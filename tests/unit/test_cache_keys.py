"""Tests for cache/keys.py — key namespaces and TTL constants."""

from cache.keys import (
    BRANDING_TTL,
    FSM_TTL,
    PINTEREST_AUTH_TTL,
    PUBLISH_LOCK_TTL,
    SERPER_TTL,
    CacheKeys,
)


class TestTTLConstants:
    def test_fsm_ttl_24h(self) -> None:
        assert FSM_TTL == 86400

    def test_publish_lock_ttl_5min(self) -> None:
        assert PUBLISH_LOCK_TTL == 300

    def test_branding_ttl_7days(self) -> None:
        assert BRANDING_TTL == 604800

    def test_serper_ttl_24h(self) -> None:
        assert SERPER_TTL == 86400

    def test_pinterest_auth_ttl_30min(self) -> None:
        assert PINTEREST_AUTH_TTL == 1800


class TestCacheKeys:
    def test_fsm_key(self) -> None:
        assert CacheKeys.fsm(123) == "fsm:123"

    def test_throttle_key(self) -> None:
        assert CacheKeys.throttle(123, "generate") == "throttle:123:generate"

    def test_publish_lock_key(self) -> None:
        key = CacheKeys.publish_lock("pub_42_2026-02-11T10:00:00Z")
        assert key == "publish_lock:pub_42_2026-02-11T10:00:00Z"

    def test_branding_key(self) -> None:
        assert CacheKeys.branding(5) == "branding:5"

    def test_serper_key(self) -> None:
        assert CacheKeys.serper("abc123") == "serper:abc123"

    def test_pinterest_auth_key(self) -> None:
        assert CacheKeys.pinterest_auth("nonce123") == "pinterest_auth:nonce123"
