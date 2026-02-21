"""Tests for services/publish.py — auto-publish pipeline."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from api.models import PublishPayload
from db.models import Category, PlatformConnection, PlatformSchedule, User
from services.publish import PublishService

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_user(**overrides) -> User:
    defaults = {
        "id": 1,
        "balance": 1000,
        "notify_publications": True,
        "notify_balance": True,
        "notify_news": True,
    }
    defaults.update(overrides)
    return User(**defaults)


def _make_category(**overrides) -> Category:
    defaults = {
        "id": 10,
        "project_id": 1,
        "name": "Test",
        "keywords": [{"cluster_name": "SEO", "cluster_type": "article", "main_phrase": "seo tips"}],
    }
    defaults.update(overrides)
    return Category(**defaults)


def _make_connection(**overrides) -> PlatformConnection:
    defaults = {
        "id": 5,
        "project_id": 1,
        "platform_type": "wordpress",
        "status": "active",
        "credentials": {"url": "https://test.com"},
        "identifier": "test.com",
    }
    defaults.update(overrides)
    return PlatformConnection(**defaults)


def _make_payload(**overrides) -> PublishPayload:
    defaults = {
        "schedule_id": 1,
        "category_id": 10,
        "connection_id": 5,
        "platform_type": "wordpress",
        "user_id": 1,
        "project_id": 1,
    }
    defaults.update(overrides)
    return PublishPayload(**defaults)


def _make_schedule(**overrides) -> PlatformSchedule:
    defaults = {
        "id": 1,
        "category_id": 10,
        "platform_type": "wordpress",
        "connection_id": 5,
        "schedule_days": ["mon"],
        "schedule_times": ["09:00"],
        "posts_per_day": 1,
        "enabled": True,
        "status": "active",
        "qstash_schedule_ids": ["qs_1"],
        "last_post_at": None,
        "created_at": None,
    }
    defaults.update(overrides)
    return PlatformSchedule(**defaults)


def _make_gen_result():
    """Mock GenerationResult for _generate_and_publish."""
    result = MagicMock()
    result.content = {
        "title": "SEO Tips",
        "meta_description": "Best SEO tips",
        "content_html": "<h1>SEO Tips</h1><p>Content</p>",
        "images_meta": [{"alt": "seo", "filename": "seo.webp", "figcaption": "SEO"}],
    }
    return result


def _make_pub_result():
    """Mock PublishResult for _generate_and_publish."""
    result = MagicMock()
    result.success = True
    result.post_url = "https://test.com/seo-tips"
    return result


def _make_service() -> PublishService:
    mock_scheduler = MagicMock()
    mock_scheduler.delete_qstash_schedules = AsyncMock()
    svc = PublishService(
        db=MagicMock(),
        redis=MagicMock(),
        http_client=MagicMock(),
        ai_orchestrator=MagicMock(),
        image_storage=MagicMock(),
        admin_ids=[999],
        scheduler_service=cast(Any, mock_scheduler),
    )
    return svc


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@patch("services.publish.get_settings")
@patch("services.publish.CredentialManager")
@patch("services.publish.ConnectionsRepository")
async def test_publish_happy_path(
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """Full pipeline: load -> rotate -> charge -> generate -> log -> ok."""
    svc = _make_service()
    svc._users.get_by_id = AsyncMock(return_value=_make_user())
    svc._categories.get_by_id = AsyncMock(return_value=_make_category())
    svc._publications.get_rotation_keyword = AsyncMock(return_value=("seo tips", False))
    svc._publications.create_log = AsyncMock(return_value=MagicMock(post_url="https://test.com/seo"))
    svc._schedules.update = AsyncMock(return_value=None)
    svc._schedules.get_by_id = AsyncMock(return_value=_make_schedule(cross_post_connection_ids=[]))
    svc._tokens.check_balance = AsyncMock(return_value=True)
    svc._tokens.charge = AsyncMock(return_value=680)

    # Mock the actual generation + publish pipeline
    svc._generate_and_publish = AsyncMock(return_value=(_make_gen_result(), _make_pub_result(), 0))

    mock_conn = MagicMock()
    mock_conn.get_by_id = AsyncMock(return_value=_make_connection())
    mock_conn_cls.return_value = mock_conn
    mock_settings.return_value = MagicMock(encryption_key=MagicMock(get_secret_value=MagicMock(return_value="key")))

    result = await svc.execute(_make_payload())

    assert result.status == "ok"
    assert result.keyword == "seo tips"
    assert result.notify is True
    svc._tokens.charge.assert_called_once()
    svc._generate_and_publish.assert_awaited_once()


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


async def test_user_not_found() -> None:
    """Missing user returns error."""
    svc = _make_service()
    svc._users.get_by_id = AsyncMock(return_value=None)

    result = await svc.execute(_make_payload())
    assert result.status == "error"
    assert result.reason == "user_not_found"


async def test_category_not_found() -> None:
    """Missing category returns error."""
    svc = _make_service()
    svc._users.get_by_id = AsyncMock(return_value=_make_user())
    svc._categories.get_by_id = AsyncMock(return_value=None)

    result = await svc.execute(_make_payload())
    assert result.status == "error"
    assert result.reason == "category_not_found"


async def test_no_keywords_e17() -> None:
    """E17: No keywords configured returns error with notify=True."""
    svc = _make_service()
    svc._users.get_by_id = AsyncMock(return_value=_make_user(notify_publications=True))
    svc._categories.get_by_id = AsyncMock(return_value=_make_category(keywords=[]))

    result = await svc.execute(_make_payload())
    assert result.status == "error"
    assert result.reason == "no_keywords"
    assert result.notify is True


async def test_no_keywords_e17_notify_off() -> None:
    """E17: No keywords with notify_publications=False does not notify."""
    svc = _make_service()
    svc._users.get_by_id = AsyncMock(return_value=_make_user(notify_publications=False))
    svc._categories.get_by_id = AsyncMock(return_value=_make_category(keywords=[]))

    result = await svc.execute(_make_payload())
    assert result.status == "error"
    assert result.reason == "no_keywords"
    assert result.notify is False


@patch("services.publish.get_settings")
@patch("services.publish.CredentialManager")
@patch("services.publish.ConnectionsRepository")
async def test_connection_inactive(
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """Inactive connection returns error."""
    svc = _make_service()
    svc._users.get_by_id = AsyncMock(return_value=_make_user())
    svc._categories.get_by_id = AsyncMock(return_value=_make_category())

    mock_conn = MagicMock()
    mock_conn.get_by_id = AsyncMock(return_value=_make_connection(status="error"))
    mock_conn_cls.return_value = mock_conn
    mock_settings.return_value = MagicMock(encryption_key=MagicMock(get_secret_value=MagicMock(return_value="key")))

    result = await svc.execute(_make_payload())
    assert result.status == "error"
    assert result.reason == "connection_inactive"
    assert result.notify is True  # user.notify_publications defaults True


@patch("services.publish.get_settings")
@patch("services.publish.CredentialManager")
@patch("services.publish.ConnectionsRepository")
async def test_insufficient_balance_e01_notifies(
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """E01: Insufficient balance uses notify_publications (not notify_balance)."""
    svc = _make_service()
    svc._users.get_by_id = AsyncMock(return_value=_make_user(notify_publications=True, notify_balance=False))
    svc._categories.get_by_id = AsyncMock(return_value=_make_category())
    svc._publications.get_rotation_keyword = AsyncMock(return_value=("seo tips", False))
    svc._tokens.check_balance = AsyncMock(return_value=False)
    svc._schedules.get_by_id = AsyncMock(return_value=_make_schedule())
    svc._schedules.update = AsyncMock(return_value=None)

    mock_conn = MagicMock()
    mock_conn.get_by_id = AsyncMock(return_value=_make_connection())
    mock_conn_cls.return_value = mock_conn
    mock_settings.return_value = MagicMock(encryption_key=MagicMock(get_secret_value=MagicMock(return_value="key")))

    result = await svc.execute(_make_payload())
    assert result.status == "error"
    assert result.reason == "insufficient_balance"
    # Uses notify_publications=True (NOT notify_balance=False)
    assert result.notify is True


@patch("services.publish.get_settings")
@patch("services.publish.CredentialManager")
@patch("services.publish.ConnectionsRepository")
async def test_no_available_keyword(
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """No available keyword after rotation returns error."""
    svc = _make_service()
    svc._users.get_by_id = AsyncMock(return_value=_make_user())
    svc._categories.get_by_id = AsyncMock(return_value=_make_category())
    svc._publications.get_rotation_keyword = AsyncMock(return_value=(None, True))

    mock_conn = MagicMock()
    mock_conn.get_by_id = AsyncMock(return_value=_make_connection())
    mock_conn_cls.return_value = mock_conn
    mock_settings.return_value = MagicMock(encryption_key=MagicMock(get_secret_value=MagicMock(return_value="key")))

    result = await svc.execute(_make_payload())
    assert result.status == "error"
    assert result.reason == "no_available_keyword"


@patch("services.publish.get_settings")
@patch("services.publish.CredentialManager")
@patch("services.publish.ConnectionsRepository")
async def test_insufficient_balance_e01(
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """E01: Insufficient balance disables schedule + deletes QStash."""
    svc = _make_service()
    svc._users.get_by_id = AsyncMock(return_value=_make_user(balance=10))
    svc._categories.get_by_id = AsyncMock(return_value=_make_category())
    svc._publications.get_rotation_keyword = AsyncMock(return_value=("seo tips", False))
    svc._tokens.check_balance = AsyncMock(return_value=False)
    svc._schedules.get_by_id = AsyncMock(return_value=_make_schedule(qstash_schedule_ids=["qs_1"]))
    svc._schedules.update = AsyncMock(return_value=None)

    mock_conn = MagicMock()
    mock_conn.get_by_id = AsyncMock(return_value=_make_connection())
    mock_conn_cls.return_value = mock_conn
    mock_settings.return_value = MagicMock(encryption_key=MagicMock(get_secret_value=MagicMock(return_value="key")))

    result = await svc.execute(_make_payload())
    assert result.status == "error"
    assert result.reason == "insufficient_balance"
    # Verify schedule disabled + QStash cleaned
    svc._schedules.update.assert_awaited_once()
    update_arg = svc._schedules.update.call_args.args[1]
    assert update_arg.enabled is False
    assert update_arg.status == "error"
    assert update_arg.qstash_schedule_ids == []
    svc._scheduler_service.delete_qstash_schedules.assert_awaited_once_with(["qs_1"])


@patch("services.publish.get_settings")
@patch("services.publish.CredentialManager")
@patch("services.publish.ConnectionsRepository")
async def test_low_pool_warning_e22(
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """E22/E23: Low keyword pool still proceeds but logs warning."""
    svc = _make_service()
    svc._users.get_by_id = AsyncMock(return_value=_make_user())
    svc._categories.get_by_id = AsyncMock(return_value=_make_category())
    svc._publications.get_rotation_keyword = AsyncMock(return_value=("seo tips", True))
    svc._publications.create_log = AsyncMock(return_value=MagicMock(post_url=""))
    svc._schedules.update = AsyncMock(return_value=None)
    svc._schedules.get_by_id = AsyncMock(return_value=_make_schedule(cross_post_connection_ids=[]))
    svc._tokens.check_balance = AsyncMock(return_value=True)
    svc._tokens.charge = AsyncMock(return_value=680)

    # Mock the actual generation + publish pipeline
    svc._generate_and_publish = AsyncMock(return_value=(_make_gen_result(), _make_pub_result(), 0))

    mock_conn = MagicMock()
    mock_conn.get_by_id = AsyncMock(return_value=_make_connection())
    mock_conn_cls.return_value = mock_conn
    mock_settings.return_value = MagicMock(encryption_key=MagicMock(get_secret_value=MagicMock(return_value="key")))

    result = await svc.execute(_make_payload())
    assert result.status == "ok"


# ---------------------------------------------------------------------------
# Refund on error
# ---------------------------------------------------------------------------


@patch("services.publish.get_settings")
@patch("services.publish.CredentialManager")
@patch("services.publish.ConnectionsRepository")
async def test_refund_on_generation_error(
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """Error after charge triggers refund + error log."""
    svc = _make_service()
    svc._users.get_by_id = AsyncMock(return_value=_make_user())
    svc._categories.get_by_id = AsyncMock(return_value=_make_category())
    svc._publications.get_rotation_keyword = AsyncMock(return_value=("seo tips", False))
    svc._tokens.check_balance = AsyncMock(return_value=True)
    svc._tokens.charge = AsyncMock(return_value=680)
    svc._tokens.refund = AsyncMock(return_value=1000)
    svc._publications.create_log = AsyncMock(return_value=MagicMock())

    # Generation fails
    svc._generate_and_publish = AsyncMock(side_effect=RuntimeError("AI generation failed"))

    mock_conn = MagicMock()
    mock_conn.get_by_id = AsyncMock(return_value=_make_connection())
    mock_conn_cls.return_value = mock_conn
    mock_settings.return_value = MagicMock(encryption_key=MagicMock(get_secret_value=MagicMock(return_value="key")))

    result = await svc.execute(_make_payload())
    assert result.status == "error"
    svc._tokens.refund.assert_called_once()


# ---------------------------------------------------------------------------
# Social post pipeline
# ---------------------------------------------------------------------------


@patch("services.publish.get_settings")
@patch("services.publish.CredentialManager")
@patch("services.publish.ConnectionsRepository")
async def test_social_post_content_type(
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """Non-wordpress platform uses social_post content_type."""
    svc = _make_service()
    svc._users.get_by_id = AsyncMock(return_value=_make_user())
    svc._categories.get_by_id = AsyncMock(
        return_value=_make_category(
            keywords=[{"cluster_name": "SEO", "cluster_type": "social", "main_phrase": "seo tips"}]
        )
    )
    svc._publications.get_rotation_keyword = AsyncMock(return_value=("seo tips", False))
    svc._publications.create_log = AsyncMock(return_value=MagicMock(post_url=""))
    svc._schedules.update = AsyncMock(return_value=None)
    svc._schedules.get_by_id = AsyncMock(return_value=_make_schedule(cross_post_connection_ids=[]))
    svc._tokens.check_balance = AsyncMock(return_value=True)
    svc._tokens.charge = AsyncMock(return_value=960)

    # Mock the actual generation + publish pipeline
    social_result = MagicMock()
    social_result.content = "Social post text"
    svc._generate_and_publish = AsyncMock(return_value=(social_result, _make_pub_result(), 0))

    mock_conn = MagicMock()
    mock_conn.get_by_id = AsyncMock(return_value=_make_connection(platform_type="telegram"))
    mock_conn_cls.return_value = mock_conn
    mock_settings.return_value = MagicMock(encryption_key=MagicMock(get_secret_value=MagicMock(return_value="key")))

    result = await svc.execute(_make_payload(platform_type="telegram"))
    assert result.status == "ok"


# ---------------------------------------------------------------------------
# Parallel pipeline unit tests
# ---------------------------------------------------------------------------


async def test_get_publisher_wordpress() -> None:
    """_get_publisher returns WordPressPublisher for wordpress."""
    svc = _make_service()
    pub = svc._get_publisher("wordpress")
    from services.publishers.wordpress import WordPressPublisher

    assert isinstance(pub, WordPressPublisher)


# ---------------------------------------------------------------------------
# Cross-post tests
# ---------------------------------------------------------------------------


def _make_social_gen_result():
    """Mock GenerationResult for social post adaptation."""
    result = MagicMock()
    result.content = {"text": "Adapted social post text", "hashtags": "#seo"}
    return result


@patch("services.ai.social_posts.SocialPostService", autospec=True)
@patch("services.ai.content_validator.ContentValidator", autospec=True)
@patch("services.publish.get_settings")
@patch("services.publish.CredentialManager")
@patch("services.publish.ConnectionsRepository")
async def test_cross_post_happy_path(
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
    mock_validator_cls: MagicMock,
    mock_social_cls: MagicMock,
) -> None:
    """Cross-posts execute after lead publish for configured connections."""
    svc = _make_service()
    svc._users.get_by_id = AsyncMock(return_value=_make_user())
    svc._categories.get_by_id = AsyncMock(return_value=_make_category())
    svc._publications.get_rotation_keyword = AsyncMock(return_value=("seo tips", False))
    svc._publications.create_log = AsyncMock(return_value=MagicMock(post_url="https://t.me/post"))
    svc._schedules.update = AsyncMock(return_value=None)
    svc._schedules.get_by_id = AsyncMock(
        return_value=_make_schedule(cross_post_connection_ids=[20, 30])
    )
    svc._tokens.check_balance = AsyncMock(return_value=True)
    svc._tokens.charge = AsyncMock(return_value=680)

    # Lead generates with text
    gen = MagicMock()
    gen.content = {"text": "Lead post text", "images_meta": []}
    svc._generate_and_publish = AsyncMock(return_value=(gen, _make_pub_result(), 0))

    # Cross-post connections
    vk_conn = _make_connection(id=20, platform_type="vk", identifier="VK Group")
    pin_conn = _make_connection(id=30, platform_type="pinterest", identifier="Board")
    conn_repo = MagicMock()
    conn_repo.get_by_id = AsyncMock(side_effect=lambda cid: {5: _make_connection(), 20: vk_conn, 30: pin_conn}[cid])
    mock_conn_cls.return_value = conn_repo
    mock_settings.return_value = MagicMock(encryption_key=MagicMock(get_secret_value=MagicMock(return_value="key")))

    # SocialPostService.adapt_for_platform returns adapted text
    mock_social_inst = MagicMock()
    mock_social_inst.adapt_for_platform = AsyncMock(return_value=_make_social_gen_result())
    mock_social_cls.return_value = mock_social_inst

    # Validator passes
    mock_val_inst = MagicMock()
    mock_val_inst.validate.return_value = MagicMock(is_valid=True, errors=[])
    mock_validator_cls.return_value = mock_val_inst

    # Publisher succeeds
    svc._get_publisher = MagicMock(return_value=MagicMock(
        publish=AsyncMock(return_value=MagicMock(success=True, post_url="https://vk.com/wall123"))
    ))

    result = await svc.execute(_make_payload(platform_type="telegram"))
    assert result.status == "ok"
    assert len(result.cross_post_results) == 2
    assert all(xp.status == "ok" for xp in result.cross_post_results)


@patch("services.ai.social_posts.SocialPostService", autospec=True)
@patch("services.publish.get_settings")
@patch("services.publish.CredentialManager")
@patch("services.publish.ConnectionsRepository")
async def test_cross_post_inactive_connection_skipped(
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
    mock_social_cls: MagicMock,
) -> None:
    """Inactive cross-post target is skipped with error."""
    svc = _make_service()
    svc._users.get_by_id = AsyncMock(return_value=_make_user())
    svc._categories.get_by_id = AsyncMock(return_value=_make_category())
    svc._publications.get_rotation_keyword = AsyncMock(return_value=("seo tips", False))
    svc._publications.create_log = AsyncMock(return_value=MagicMock(post_url="https://t.me/post"))
    svc._schedules.update = AsyncMock(return_value=None)
    svc._schedules.get_by_id = AsyncMock(
        return_value=_make_schedule(cross_post_connection_ids=[20])
    )
    svc._tokens.check_balance = AsyncMock(return_value=True)
    svc._tokens.charge = AsyncMock(return_value=680)

    gen = MagicMock()
    gen.content = {"text": "Lead text", "images_meta": []}
    svc._generate_and_publish = AsyncMock(return_value=(gen, _make_pub_result(), 0))

    # Cross-post connection is inactive
    inactive_conn = _make_connection(id=20, platform_type="vk", status="error")
    conn_repo = MagicMock()
    conn_repo.get_by_id = AsyncMock(side_effect=lambda cid: {5: _make_connection(), 20: inactive_conn}[cid])
    mock_conn_cls.return_value = conn_repo
    mock_settings.return_value = MagicMock(encryption_key=MagicMock(get_secret_value=MagicMock(return_value="key")))

    result = await svc.execute(_make_payload(platform_type="telegram"))
    assert result.status == "ok"
    assert len(result.cross_post_results) == 1
    assert result.cross_post_results[0].status == "error"
    assert result.cross_post_results[0].error == "connection_inactive"


@patch("services.publish.get_settings")
@patch("services.publish.CredentialManager")
@patch("services.publish.ConnectionsRepository")
async def test_cross_post_insufficient_balance_stops_remaining(
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """Insufficient balance for cross-post stops remaining targets."""
    svc = _make_service()
    svc._users.get_by_id = AsyncMock(return_value=_make_user())
    svc._categories.get_by_id = AsyncMock(return_value=_make_category())
    svc._publications.get_rotation_keyword = AsyncMock(return_value=("seo tips", False))
    svc._publications.create_log = AsyncMock(return_value=MagicMock(post_url="https://t.me/post"))
    svc._schedules.update = AsyncMock(return_value=None)
    svc._schedules.get_by_id = AsyncMock(
        return_value=_make_schedule(cross_post_connection_ids=[20, 30])
    )
    # Lead charge OK, but cross-post balance check fails
    svc._tokens.check_balance = AsyncMock(side_effect=[True, False])
    svc._tokens.charge = AsyncMock(return_value=680)

    gen = MagicMock()
    gen.content = {"text": "Lead text", "images_meta": []}
    svc._generate_and_publish = AsyncMock(return_value=(gen, _make_pub_result(), 0))

    vk_conn = _make_connection(id=20, platform_type="vk")
    conn_repo = MagicMock()
    conn_repo.get_by_id = AsyncMock(side_effect=lambda cid: {5: _make_connection(), 20: vk_conn}[cid])
    mock_conn_cls.return_value = conn_repo
    mock_settings.return_value = MagicMock(encryption_key=MagicMock(get_secret_value=MagicMock(return_value="key")))

    result = await svc.execute(_make_payload(platform_type="telegram"))
    assert result.status == "ok"
    # First cross-post fails with balance, second never attempted (break)
    assert len(result.cross_post_results) == 1
    assert result.cross_post_results[0].error == "insufficient_balance"


@patch("services.publish.get_settings")
@patch("services.publish.CredentialManager")
@patch("services.publish.ConnectionsRepository")
async def test_cross_post_empty_ids_no_cross_posts(
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """Empty cross_post_connection_ids means no cross-posts attempted."""
    svc = _make_service()
    svc._users.get_by_id = AsyncMock(return_value=_make_user())
    svc._categories.get_by_id = AsyncMock(return_value=_make_category())
    svc._publications.get_rotation_keyword = AsyncMock(return_value=("seo tips", False))
    svc._publications.create_log = AsyncMock(return_value=MagicMock(post_url="https://t.me/post"))
    svc._schedules.update = AsyncMock(return_value=None)
    svc._schedules.get_by_id = AsyncMock(
        return_value=_make_schedule(cross_post_connection_ids=[])
    )
    svc._tokens.check_balance = AsyncMock(return_value=True)
    svc._tokens.charge = AsyncMock(return_value=680)
    svc._generate_and_publish = AsyncMock(return_value=(_make_gen_result(), _make_pub_result(), 0))

    conn_repo = MagicMock()
    conn_repo.get_by_id = AsyncMock(return_value=_make_connection())
    mock_conn_cls.return_value = conn_repo
    mock_settings.return_value = MagicMock(encryption_key=MagicMock(get_secret_value=MagicMock(return_value="key")))

    result = await svc.execute(_make_payload())
    assert result.status == "ok"
    assert result.cross_post_results == []


async def test_get_publisher_telegram() -> None:
    """_get_publisher returns TelegramPublisher for telegram."""
    svc = _make_service()
    pub = svc._get_publisher("telegram")
    from services.publishers.telegram import TelegramPublisher

    assert isinstance(pub, TelegramPublisher)


async def test_get_publisher_unknown_raises() -> None:
    """_get_publisher raises ValueError for unknown platform."""
    svc = _make_service()
    try:
        svc._get_publisher("unknown")
        raise AssertionError("Should have raised ValueError")
    except ValueError as e:
        assert "unknown" in str(e).lower()


async def test_get_content_type_mapping() -> None:
    """_get_content_type returns correct mappings."""
    assert PublishService._get_content_type("wordpress") == "html"
    assert PublishService._get_content_type("telegram") == "telegram_html"
    assert PublishService._get_content_type("vk") == "plain_text"
    assert PublishService._get_content_type("pinterest") == "pin_text"
    assert PublishService._get_content_type("unknown") == "plain_text"
