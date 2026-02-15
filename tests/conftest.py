"""Root conftest — shared fixtures for all tests."""

from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env at the root so E2E / smoke tests pick up credentials.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)


@pytest.fixture
def admin_id() -> int:
    """ADMIN_ID for GOD_MODE testing."""
    return 203473623


@pytest.fixture
def regular_user_id() -> int:
    """Non-admin user_id."""
    return 999999999
