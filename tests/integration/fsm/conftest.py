"""FSM integration test helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from tests.integration.conftest import (
    ADMIN_ID,
    DEFAULT_USER,
    MockResponse,
    MockSupabaseClient,
)

# Valid Fernet key for test mocks (NOT a secret — generated once for deterministic tests)
TEST_FERNET_KEY = "UmghTYp__Hb9Pg5feH76qp_Nam7gTEUhCV40FcK6Dk8="  # noqa: S105  # nosec B105


def make_mock_settings() -> MagicMock:
    """Create a mock Settings object with valid Fernet key for get_settings() patches.

    Reusable across all FSM integration tests.
    """
    settings = MagicMock()
    settings.admin_id = ADMIN_ID
    settings.encryption_key = MagicMock()
    settings.encryption_key.get_secret_value.return_value = TEST_FERNET_KEY
    settings.fsm_ttl_seconds = 86400
    settings.fsm_inactivity_timeout = 1800
    settings.max_regenerations_free = 2
    settings.railway_public_url = "https://test.railway.app"
    settings.pinterest_app_id = ""
    settings.pinterest_app_secret = MagicMock()
    settings.pinterest_app_secret.get_secret_value.return_value = ""
    return settings


def setup_user_with_projects(
    mock_db: MockSupabaseClient,
    user_data: dict[str, Any] | None = None,
    projects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Set up DB responses for a user who has projects.

    ConfigureS users + projects table responses.
    """
    data = user_data or DEFAULT_USER
    mock_db.set_response("users", MockResponse(data=data))

    if projects:
        mock_db.set_response("projects", MockResponse(data=projects))
    else:
        mock_db.set_response("projects", MockResponse(data=[]))

    return data


def setup_user_with_categories(
    mock_db: MockSupabaseClient,
    user_data: dict[str, Any] | None = None,
    projects: list[dict[str, Any]] | None = None,
    categories: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Set up DB responses for a user who has projects and categories."""
    data = setup_user_with_projects(mock_db, user_data, projects)

    if categories:
        mock_db.set_response("categories", MockResponse(data=categories))
    else:
        mock_db.set_response("categories", MockResponse(data=[]))

    return data


DEFAULT_PROJECT = {
    "id": 1,
    "user_id": DEFAULT_USER["id"],
    "name": "Test Project",
    "company_name": "Test Co",
    "specialization": "SEO Testing",
    "website_url": "https://example.com",
    "timezone": "Europe/Moscow",
    "created_at": "2025-01-01T00:00:00Z",
}

DEFAULT_CATEGORY = {
    "id": 10,
    "project_id": 1,
    "name": "Test Category",
    "description": "Test category desc",
    "keywords": [],
    "media": [],
    "prices": None,
    "reviews": [],
    "image_settings": {},
    "text_settings": {},
    "created_at": "2025-01-01T00:00:00Z",
}

DEFAULT_CONNECTION_WP = {
    "id": 100,
    "project_id": 1,
    "platform_type": "wordpress",
    "status": "active",
    "credentials": {"url": "https://blog.example.com", "username": "admin", "app_password": "xxxx"},
    "metadata": {},
    "identifier": "https://blog.example.com",
    "created_at": "2025-01-01T00:00:00Z",
}

DEFAULT_SCHEDULE = {
    "id": 200,
    "category_id": 10,
    "platform_type": "wordpress",
    "connection_id": 100,
    "schedule_days": ["mon", "wed", "fri"],
    "schedule_times": ["09:00", "15:00"],
    "posts_per_day": 1,
    "enabled": True,
    "status": "active",
    "qstash_schedule_ids": ["sched_abc123"],
    "last_post_at": None,
    "created_at": "2025-01-01T00:00:00Z",
}
