"""Smoke test — verifies test infrastructure works."""


def test_project_importable() -> None:
    """All top-level packages are importable."""
    import api  # noqa: F401
    import bot  # noqa: F401
    import cache  # noqa: F401
    import db  # noqa: F401
    import platform_rules  # noqa: F401
    import services  # noqa: F401
