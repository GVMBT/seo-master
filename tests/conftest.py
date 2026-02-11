"""Root conftest — shared fixtures for all tests."""

import pytest


@pytest.fixture
def admin_id() -> int:
    """ADMIN_ID for GOD_MODE testing."""
    return 203473623


@pytest.fixture
def regular_user_id() -> int:
    """Non-admin user_id."""
    return 999999999
