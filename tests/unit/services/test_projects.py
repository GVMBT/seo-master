"""Tests for services/projects.py — ProjectService.

Covers: ownership checks, CRUD, H17 limit, card data aggregation,
delete with E11+E42 cleanup, update with ownership verification.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.projects import MAX_PROJECTS_PER_USER, ProjectCardData, ProjectService

_SVC_MODULE = "services.projects"


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def proj_svc(mock_db: MagicMock) -> ProjectService:
    return ProjectService(db=mock_db, encryption_key="test-key")


# ---------------------------------------------------------------------------
# get_owned_project
# ---------------------------------------------------------------------------


class TestGetOwnedProject:
    async def test_returns_project_when_owned(self, proj_svc: ProjectService) -> None:
        project = MagicMock(user_id=42)
        proj_svc._repo.get_by_id = AsyncMock(return_value=project)

        result = await proj_svc.get_owned_project(5, 42)
        assert result is project
        proj_svc._repo.get_by_id.assert_awaited_once_with(5)

    async def test_returns_none_when_not_found(self, proj_svc: ProjectService) -> None:
        proj_svc._repo.get_by_id = AsyncMock(return_value=None)

        result = await proj_svc.get_owned_project(5, 42)
        assert result is None

    async def test_returns_none_when_not_owned(self, proj_svc: ProjectService) -> None:
        project = MagicMock(user_id=99)
        proj_svc._repo.get_by_id = AsyncMock(return_value=project)

        result = await proj_svc.get_owned_project(5, 42)
        assert result is None


# ---------------------------------------------------------------------------
# list_by_user
# ---------------------------------------------------------------------------


class TestListByUser:
    async def test_returns_projects(self, proj_svc: ProjectService) -> None:
        projects = [MagicMock(), MagicMock()]
        proj_svc._repo.get_by_user = AsyncMock(return_value=projects)

        result = await proj_svc.list_by_user(42)
        assert result == projects
        proj_svc._repo.get_by_user.assert_awaited_once_with(42)

    async def test_returns_empty_list(self, proj_svc: ProjectService) -> None:
        proj_svc._repo.get_by_user = AsyncMock(return_value=[])

        result = await proj_svc.list_by_user(42)
        assert result == []


# ---------------------------------------------------------------------------
# check_project_limit
# ---------------------------------------------------------------------------


class TestCheckProjectLimit:
    async def test_under_limit_returns_true(self, proj_svc: ProjectService) -> None:
        proj_svc._repo.get_count_by_user = AsyncMock(return_value=5)

        result = await proj_svc.check_project_limit(42)
        assert result is True

    async def test_at_limit_returns_false(self, proj_svc: ProjectService) -> None:
        proj_svc._repo.get_count_by_user = AsyncMock(return_value=MAX_PROJECTS_PER_USER)

        result = await proj_svc.check_project_limit(42)
        assert result is False

    async def test_over_limit_returns_false(self, proj_svc: ProjectService) -> None:
        proj_svc._repo.get_count_by_user = AsyncMock(return_value=MAX_PROJECTS_PER_USER + 1)

        result = await proj_svc.check_project_limit(42)
        assert result is False

    def test_constant_value(self) -> None:
        assert MAX_PROJECTS_PER_USER == 20


# ---------------------------------------------------------------------------
# create_project
# ---------------------------------------------------------------------------


class TestCreateProject:
    async def test_creates_and_returns(self, proj_svc: ProjectService) -> None:
        data = MagicMock(user_id=42)
        created = MagicMock(id=1)
        proj_svc._repo.get_count_by_user = AsyncMock(return_value=5)
        proj_svc._repo.create = AsyncMock(return_value=created)

        result = await proj_svc.create_project(data)
        assert result is created
        proj_svc._repo.get_count_by_user.assert_awaited_once_with(42)
        proj_svc._repo.create.assert_awaited_once_with(data)

    async def test_returns_none_at_limit(self, proj_svc: ProjectService) -> None:
        data = MagicMock(user_id=42)
        proj_svc._repo.get_count_by_user = AsyncMock(return_value=MAX_PROJECTS_PER_USER)
        proj_svc._repo.create = AsyncMock()

        result = await proj_svc.create_project(data)
        assert result is None
        proj_svc._repo.create.assert_not_awaited()


# ---------------------------------------------------------------------------
# update_project
# ---------------------------------------------------------------------------


class TestUpdateProject:
    async def test_updates_owned_project(self, proj_svc: ProjectService) -> None:
        project = MagicMock(user_id=42)
        updated = MagicMock()
        update = MagicMock()
        proj_svc._repo.get_by_id = AsyncMock(return_value=project)
        proj_svc._repo.update = AsyncMock(return_value=updated)

        result = await proj_svc.update_project(5, 42, update)
        assert result is updated
        proj_svc._repo.update.assert_awaited_once_with(5, update)

    async def test_returns_none_when_not_owned(self, proj_svc: ProjectService) -> None:
        project = MagicMock(user_id=99)
        proj_svc._repo.get_by_id = AsyncMock(return_value=project)

        result = await proj_svc.update_project(5, 42, MagicMock())
        assert result is None

    async def test_returns_none_when_not_found(self, proj_svc: ProjectService) -> None:
        proj_svc._repo.get_by_id = AsyncMock(return_value=None)

        result = await proj_svc.update_project(5, 42, MagicMock())
        assert result is None


# ---------------------------------------------------------------------------
# build_card_data
# ---------------------------------------------------------------------------


class TestBuildCardData:
    @patch(f"{_SVC_MODULE}.PublicationsRepository")
    @patch(f"{_SVC_MODULE}.CategoriesRepository")
    @patch(f"{_SVC_MODULE}.ConnectionsRepository")
    @patch(f"{_SVC_MODULE}.CredentialManager")
    async def test_returns_card_data(
        self,
        _mock_cm_cls: MagicMock,
        mock_conn_cls: MagicMock,
        mock_cats_cls: MagicMock,
        mock_pubs_cls: MagicMock,
        proj_svc: ProjectService,
    ) -> None:
        project = MagicMock(user_id=42)
        proj_svc._repo.get_by_id = AsyncMock(return_value=project)

        mock_conn = MagicMock()
        mock_conn.get_platform_types_by_project = AsyncMock(return_value=["wordpress"])
        mock_conn_cls.return_value = mock_conn

        categories = [MagicMock(), MagicMock()]
        mock_cats = MagicMock()
        mock_cats.get_by_project = AsyncMock(return_value=categories)
        mock_cats_cls.return_value = mock_cats

        mock_pubs = MagicMock()
        mock_pubs.get_count_by_project = AsyncMock(return_value=15)
        mock_pubs_cls.return_value = mock_pubs

        result = await proj_svc.build_card_data(5, 42)
        assert result is not None
        assert isinstance(result, ProjectCardData)
        assert result.project is project
        assert result.platform_types == ["wordpress"]
        assert result.categories == categories
        assert result.pub_count == 15

    async def test_returns_none_when_not_owned(self, proj_svc: ProjectService) -> None:
        proj_svc._repo.get_by_id = AsyncMock(return_value=None)

        result = await proj_svc.build_card_data(5, 42)
        assert result is None


# ---------------------------------------------------------------------------
# delete_project (E11 + E42)
# ---------------------------------------------------------------------------


class TestDeleteProject:
    async def test_returns_false_when_not_owned(self, proj_svc: ProjectService) -> None:
        proj_svc._repo.get_by_id = AsyncMock(return_value=None)
        scheduler = MagicMock()
        token_svc = MagicMock()

        deleted, project = await proj_svc.delete_project(5, 42, scheduler, token_svc)
        assert deleted is False
        assert project is None

    @patch(f"{_SVC_MODULE}.PreviewsRepository")
    async def test_deletes_with_e11_e42(
        self,
        mock_previews_cls: MagicMock,
        proj_svc: ProjectService,
    ) -> None:
        project = MagicMock(user_id=42)
        proj_svc._repo.get_by_id = AsyncMock(return_value=project)
        proj_svc._repo.delete = AsyncMock(return_value=True)

        # E42: mock active previews
        active_previews = [MagicMock()]
        mock_previews = MagicMock()
        mock_previews.get_active_drafts_by_project = AsyncMock(return_value=active_previews)
        mock_previews_cls.return_value = mock_previews

        scheduler = MagicMock()
        scheduler.cancel_schedules_for_project = AsyncMock()

        token_svc = MagicMock()
        token_svc.refund_active_previews = AsyncMock()

        deleted, result_project = await proj_svc.delete_project(5, 42, scheduler, token_svc)

        assert deleted is True
        assert result_project is project

        # E11: QStash cancelled BEFORE delete
        scheduler.cancel_schedules_for_project.assert_awaited_once_with(5)
        # E42: previews refunded
        token_svc.refund_active_previews.assert_awaited_once_with(
            active_previews, 42, "удаление проекта #5"
        )
        proj_svc._repo.delete.assert_awaited_once_with(5)

    @patch(f"{_SVC_MODULE}.PreviewsRepository")
    async def test_skips_refund_when_no_active_previews(
        self,
        mock_previews_cls: MagicMock,
        proj_svc: ProjectService,
    ) -> None:
        project = MagicMock(user_id=42)
        proj_svc._repo.get_by_id = AsyncMock(return_value=project)
        proj_svc._repo.delete = AsyncMock(return_value=True)

        mock_previews = MagicMock()
        mock_previews.get_active_drafts_by_project = AsyncMock(return_value=[])
        mock_previews_cls.return_value = mock_previews

        scheduler = MagicMock()
        scheduler.cancel_schedules_for_project = AsyncMock()

        token_svc = MagicMock()
        token_svc.refund_active_previews = AsyncMock()

        deleted, _ = await proj_svc.delete_project(5, 42, scheduler, token_svc)
        assert deleted is True
        token_svc.refund_active_previews.assert_not_awaited()

    @patch(f"{_SVC_MODULE}.PreviewsRepository")
    async def test_returns_false_when_delete_fails(
        self,
        mock_previews_cls: MagicMock,
        proj_svc: ProjectService,
    ) -> None:
        project = MagicMock(user_id=42)
        proj_svc._repo.get_by_id = AsyncMock(return_value=project)
        proj_svc._repo.delete = AsyncMock(return_value=False)

        mock_previews = MagicMock()
        mock_previews.get_active_drafts_by_project = AsyncMock(return_value=[])
        mock_previews_cls.return_value = mock_previews

        scheduler = MagicMock()
        scheduler.cancel_schedules_for_project = AsyncMock()

        token_svc = MagicMock()
        token_svc.refund_active_previews = AsyncMock()

        deleted, result_project = await proj_svc.delete_project(5, 42, scheduler, token_svc)
        assert deleted is False
        assert result_project is project
