"""Test helpers for keyboard tests — model factories."""

from db.models import Category, Project, User


def make_project(
    id: int = 1,
    user_id: int = 100,
    name: str = "Test Project",
    company_name: str = "Test Co",
    specialization: str = "Testing things",
    **kwargs: object,
) -> Project:
    """Create a Project instance for testing."""
    return Project(
        id=id,
        user_id=user_id,
        name=name,
        company_name=company_name,
        specialization=specialization,
        **kwargs,  # type: ignore[arg-type]
    )


def make_category(
    id: int = 1,
    project_id: int = 1,
    name: str = "Test Category",
    **kwargs: object,
) -> Category:
    """Create a Category instance for testing."""
    return Category(id=id, project_id=project_id, name=name, **kwargs)  # type: ignore[arg-type]


def make_user(
    id: int = 100,
    balance: int = 1500,
    role: str = "user",
    notify_publications: bool = True,
    notify_balance: bool = True,
    notify_news: bool = True,
    **kwargs: object,
) -> User:
    """Create a User instance for testing."""
    return User(
        id=id,
        balance=balance,
        role=role,
        notify_publications=notify_publications,
        notify_balance=notify_balance,
        notify_news=notify_news,
        **kwargs,  # type: ignore[arg-type]
    )
