"""Tests for db/repositories/prompts.py."""

import pytest

from db.models import PromptVersion, PromptVersionCreate, PromptVersionUpdate
from db.repositories.prompts import PromptsRepository

from .conftest import MockResponse, MockSupabaseClient


@pytest.fixture
def prompt_row() -> dict:
    return {
        "id": 1,
        "task_type": "article",
        "version": "v1",
        "prompt_yaml": "system: Generate SEO article\nvariables:\n  - keyword\n  - tone",
        "is_active": True,
        "success_rate": "0.92",
        "avg_quality": "4.5",
        "created_at": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture
def repo(mock_db: MockSupabaseClient) -> PromptsRepository:
    return PromptsRepository(mock_db)  # type: ignore[arg-type]


class TestGetActive:
    async def test_found(self, repo: PromptsRepository, mock_db: MockSupabaseClient, prompt_row: dict) -> None:
        mock_db.set_response("prompt_versions", MockResponse(data=prompt_row))
        prompt = await repo.get_active("article")
        assert prompt is not None
        assert isinstance(prompt, PromptVersion)
        assert prompt.is_active is True

    async def test_not_found(self, repo: PromptsRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("prompt_versions", MockResponse(data=None))
        assert await repo.get_active("nonexistent") is None


class TestGetByTaskAndVersion:
    async def test_found(self, repo: PromptsRepository, mock_db: MockSupabaseClient, prompt_row: dict) -> None:
        mock_db.set_response("prompt_versions", MockResponse(data=prompt_row))
        prompt = await repo.get_by_task_and_version("article", "v1")
        assert prompt is not None
        assert prompt.version == "v1"


class TestUpsert:
    async def test_upsert(self, repo: PromptsRepository, mock_db: MockSupabaseClient, prompt_row: dict) -> None:
        mock_db.set_response("prompt_versions", MockResponse(data=[prompt_row]))
        data = PromptVersionCreate(task_type="article", version="v1", prompt_yaml="test yaml", is_active=True)
        prompt = await repo.upsert(data)
        assert isinstance(prompt, PromptVersion)


class TestUpdateStats:
    async def test_update(self, repo: PromptsRepository, mock_db: MockSupabaseClient, prompt_row: dict) -> None:
        from decimal import Decimal

        updated = {**prompt_row, "success_rate": "0.95"}
        mock_db.set_response("prompt_versions", MockResponse(data=[updated]))
        prompt = await repo.update_stats(1, PromptVersionUpdate(success_rate=Decimal("0.95")))
        assert prompt is not None

    async def test_empty_update_returns_none(self, repo: PromptsRepository, mock_db: MockSupabaseClient) -> None:
        result = await repo.update_stats(1, PromptVersionUpdate())
        assert result is None
