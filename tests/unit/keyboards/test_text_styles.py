"""Tests for text style list and styles/style key consistency.

Verifies:
- _TEXT_STYLES in keyboards/inline.py contains exactly 8 items (no gender styles)
- _TEXT_STYLES in routers/categories/content_settings.py matches keyboards/inline.py
- AI services read text_settings["styles"] (plural, list) and join with comma
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from keyboards.inline import _TEXT_STYLES as INLINE_TEXT_STYLES
from routers.categories.content_settings import _TEXT_STYLES as ROUTER_TEXT_STYLES

# ---------------------------------------------------------------------------
# 1. Gender styles removed
# ---------------------------------------------------------------------------

_EXPECTED_STYLES: list[str] = [
    "\u0420\u0435\u043a\u043b\u0430\u043c\u043d\u044b\u0439",
    "\u041c\u043e\u0442\u0438\u0432\u0430\u0446\u0438\u043e\u043d\u043d\u044b\u0439",
    "\u0414\u0440\u0443\u0436\u0435\u043b\u044e\u0431\u043d\u044b\u0439",
    "\u0420\u0430\u0437\u0433\u043e\u0432\u043e\u0440\u043d\u044b\u0439",
    "\u041f\u0440\u043e\u0444\u0435\u0441\u0441\u0438\u043e\u043d\u0430\u043b\u044c\u043d\u044b\u0439",
    "\u041a\u0440\u0435\u0430\u0442\u0438\u0432\u043d\u044b\u0439",
    "\u0418\u043d\u0444\u043e\u0440\u043c\u0430\u0442\u0438\u0432\u043d\u044b\u0439",
    "\u0421 \u044e\u043c\u043e\u0440\u043e\u043c",
]


def test_inline_text_styles_has_no_gender_styles() -> None:
    """_TEXT_STYLES in keyboards/inline.py must not contain gender styles."""
    assert "\u041c\u0443\u0436\u0441\u043a\u043e\u0439" not in INLINE_TEXT_STYLES
    assert "\u0416\u0435\u043d\u0441\u043a\u0438\u0439" not in INLINE_TEXT_STYLES


def test_router_text_styles_has_no_gender_styles() -> None:
    """_TEXT_STYLES in content_settings.py must not contain gender styles."""
    assert "\u041c\u0443\u0436\u0441\u043a\u043e\u0439" not in ROUTER_TEXT_STYLES
    assert "\u0416\u0435\u043d\u0441\u043a\u0438\u0439" not in ROUTER_TEXT_STYLES


def test_text_styles_count_is_eight() -> None:
    """Both _TEXT_STYLES lists must have exactly 8 items."""
    assert len(INLINE_TEXT_STYLES) == 8
    assert len(ROUTER_TEXT_STYLES) == 8


def test_text_styles_lists_match() -> None:
    """keyboards/inline.py and routers/categories/content_settings.py lists must be identical."""
    assert INLINE_TEXT_STYLES == ROUTER_TEXT_STYLES


def test_text_styles_exact_content() -> None:
    """Both lists must contain exactly the expected 8 styles in order."""
    assert INLINE_TEXT_STYLES == _EXPECTED_STYLES
    assert ROUTER_TEXT_STYLES == _EXPECTED_STYLES


# ---------------------------------------------------------------------------
# 2. AI services read "styles" (plural) key and join with comma
# ---------------------------------------------------------------------------


def _make_project(**overrides: Any) -> Any:
    """Minimal project for testing text_style context."""
    from db.models import Project

    defaults: dict[str, Any] = {
        "id": 1,
        "user_id": 123,
        "name": "Test Project",
        "company_name": "TestCo",
        "specialization": "SEO",
        "company_city": "Moscow",
        "advantages": "Best quality",
    }
    defaults.update(overrides)
    return Project(**defaults)


def _make_category(**overrides: Any) -> Any:
    """Minimal category for testing text_style context."""
    from db.models import Category

    defaults: dict[str, Any] = {
        "id": 1,
        "project_id": 1,
        "name": "Test Cat",
        "keywords": [{"phrase": "test keyword", "volume": 100, "difficulty": 30}],
        "prices": "Price list here",
        "text_settings": {
            "styles": [
                "\u041f\u0440\u043e\u0444\u0435\u0441\u0441\u0438\u043e\u043d\u0430\u043b\u044c\u043d\u044b\u0439",
                "\u0418\u043d\u0444\u043e\u0440\u043c\u0430\u0442\u0438\u0432\u043d\u044b\u0439",
            ],
        },
    }
    defaults.update(overrides)
    return Category(**defaults)


async def test_article_service_reads_styles_plural_key() -> None:
    """ArticleService must read text_settings['styles'] and join with comma."""
    from services.ai.orchestrator import GenerationResult

    # Build v7 multi-step mocks
    outline_content = {
        "h1": "Guide",
        "sections": [],
        "faq_questions": [],
        "target_word_count": 2000,
        "suggested_images": [],
    }
    sentences = " ".join(f"TestCo delivers test keyword services since {yr}." for yr in range(2018, 2026))
    md = (
        f"# Complete guide to test keyword for business\n\n"
        f"TestCo helps with test keyword for over 10 years. {sentences}\n\n"
        f"## What is test keyword\n\n{sentences}\n\n"
        f"## Benefits of test keyword\n\n{sentences}\n\n"
        f"## How to choose test keyword\n\n{sentences}\n\n"
        f"## FAQ\n\n**How much?**\n\n15000 rubles.\n\n"
        f"## Conclusion\n\nTestCo is your partner for test keyword. {sentences}\n"
    )
    article_content = {
        "title": "Guide",
        "meta_description": "Desc",
        "content_markdown": md,
        "faq_schema": [],
        "images_meta": [],
    }
    critique_content = {**article_content, "changes_summary": "Improved"}

    mock_results = [
        GenerationResult(
            content=outline_content,
            model_used="test",
            input_tokens=100,
            output_tokens=200,
            cost_usd=0.01,
            generation_time_ms=500,
            prompt_version="v7",
            fallback_used=False,
        ),
        GenerationResult(
            content=article_content,
            model_used="test",
            input_tokens=100,
            output_tokens=200,
            cost_usd=0.01,
            generation_time_ms=500,
            prompt_version="v7",
            fallback_used=False,
        ),
        GenerationResult(
            content=critique_content,
            model_used="test",
            input_tokens=100,
            output_tokens=200,
            cost_usd=0.01,
            generation_time_ms=500,
            prompt_version="v7",
            fallback_used=False,
        ),
    ]
    mock_orch = AsyncMock()
    mock_orch.generate = AsyncMock(side_effect=mock_results)
    mock_db = MagicMock()

    with (
        patch("services.ai.articles.ProjectsRepository") as MockProjRepo,
        patch("services.ai.articles.CategoriesRepository") as MockCatRepo,
    ):
        MockProjRepo.return_value.get_by_id = AsyncMock(return_value=_make_project())
        MockCatRepo.return_value.get_by_id = AsyncMock(return_value=_make_category())

        from services.ai.articles import ArticleService

        svc = ArticleService(orchestrator=mock_orch, db=mock_db)
        svc._projects = MockProjRepo.return_value
        svc._categories = MockCatRepo.return_value

        await svc.generate(user_id=123, project_id=1, category_id=1, keyword="test keyword")

    # Article expand is the 2nd generate call (index 1)
    article_call = mock_orch.generate.call_args_list[1]
    request = article_call.args[0]
    expected = (
        "\u041f\u0440\u043e\u0444\u0435\u0441\u0441\u0438\u043e\u043d\u0430\u043b\u044c\u043d\u044b\u0439, "
        "\u0418\u043d\u0444\u043e\u0440\u043c\u0430\u0442\u0438\u0432\u043d\u044b\u0439"
    )
    assert request.context["text_style"] == expected


async def test_social_post_service_reads_styles_plural_key() -> None:
    """SocialPostService must read text_settings['styles'] and join with comma."""
    from services.ai.orchestrator import GenerationResult

    post_content = {"text": "Post!", "hashtags": ["#seo"], "pin_title": "Title"}
    mock_orch = AsyncMock()
    mock_orch.generate = AsyncMock(
        return_value=GenerationResult(
            content=post_content,
            model_used="test",
            input_tokens=50,
            output_tokens=100,
            cost_usd=0.005,
            generation_time_ms=200,
            prompt_version="v3",
            fallback_used=False,
        ),
    )
    mock_db = MagicMock()

    with (
        patch("services.ai.social_posts.ProjectsRepository") as MockProjRepo,
        patch("services.ai.social_posts.CategoriesRepository") as MockCatRepo,
    ):
        MockProjRepo.return_value.get_by_id = AsyncMock(return_value=_make_project())
        MockCatRepo.return_value.get_by_id = AsyncMock(return_value=_make_category())

        from services.ai.social_posts import SocialPostService

        svc = SocialPostService(orchestrator=mock_orch, db=mock_db)
        svc._projects = MockProjRepo.return_value
        svc._categories = MockCatRepo.return_value

        await svc.generate(
            user_id=123,
            project_id=1,
            category_id=1,
            keyword="test keyword",
            platform="telegram",
        )

    request = mock_orch.generate.call_args.args[0]
    expected = (
        "\u041f\u0440\u043e\u0444\u0435\u0441\u0441\u0438\u043e\u043d\u0430\u043b\u044c\u043d\u044b\u0439, "
        "\u0418\u043d\u0444\u043e\u0440\u043c\u0430\u0442\u0438\u0432\u043d\u044b\u0439"
    )
    assert request.context["text_style"] == expected


async def test_article_service_default_style_when_no_styles_key() -> None:
    """ArticleService must default to 'Informативный' when styles key is missing."""
    from services.ai.orchestrator import GenerationResult

    outline_content = {
        "h1": "Guide",
        "sections": [],
        "faq_questions": [],
        "target_word_count": 2000,
        "suggested_images": [],
    }
    sentences = " ".join(f"TestCo delivers test keyword services since {yr}." for yr in range(2018, 2026))
    md = (
        f"# Complete guide to test keyword for business\n\n"
        f"TestCo helps with test keyword for over 10 years. {sentences}\n\n"
        f"## What is test keyword\n\n{sentences}\n\n"
        f"## Benefits of test keyword\n\n{sentences}\n\n"
        f"## How to choose test keyword\n\n{sentences}\n\n"
        f"## FAQ\n\n**How much?**\n\n15000 rubles.\n\n"
        f"## Conclusion\n\nTestCo is your partner for test keyword. {sentences}\n"
    )
    article_content = {
        "title": "Guide",
        "meta_description": "Desc",
        "content_markdown": md,
        "faq_schema": [],
        "images_meta": [],
    }
    critique_content = {**article_content, "changes_summary": "Improved"}

    mock_results = [
        GenerationResult(
            content=outline_content,
            model_used="test",
            input_tokens=100,
            output_tokens=200,
            cost_usd=0.01,
            generation_time_ms=500,
            prompt_version="v7",
            fallback_used=False,
        ),
        GenerationResult(
            content=article_content,
            model_used="test",
            input_tokens=100,
            output_tokens=200,
            cost_usd=0.01,
            generation_time_ms=500,
            prompt_version="v7",
            fallback_used=False,
        ),
        GenerationResult(
            content=critique_content,
            model_used="test",
            input_tokens=100,
            output_tokens=200,
            cost_usd=0.01,
            generation_time_ms=500,
            prompt_version="v7",
            fallback_used=False,
        ),
    ]
    mock_orch = AsyncMock()
    mock_orch.generate = AsyncMock(side_effect=mock_results)
    mock_db = MagicMock()

    # Category with NO text_settings (empty dict)
    cat_no_styles = _make_category(text_settings={})

    with (
        patch("services.ai.articles.ProjectsRepository") as MockProjRepo,
        patch("services.ai.articles.CategoriesRepository") as MockCatRepo,
    ):
        MockProjRepo.return_value.get_by_id = AsyncMock(return_value=_make_project())
        MockCatRepo.return_value.get_by_id = AsyncMock(return_value=cat_no_styles)

        from services.ai.articles import ArticleService

        svc = ArticleService(orchestrator=mock_orch, db=mock_db)
        svc._projects = MockProjRepo.return_value
        svc._categories = MockCatRepo.return_value

        await svc.generate(user_id=123, project_id=1, category_id=1, keyword="test keyword")

    article_call = mock_orch.generate.call_args_list[1]
    request = article_call.args[0]
    assert request.context["text_style"] == (
        "\u0418\u043d\u0444\u043e\u0440\u043c\u0430\u0442\u0438\u0432\u043d\u044b\u0439"
    )


async def test_social_post_service_default_style_when_no_styles_key() -> None:
    """SocialPostService must default to 'Разговорный' when styles key is missing."""
    from services.ai.orchestrator import GenerationResult

    mock_orch = AsyncMock()
    mock_orch.generate = AsyncMock(
        return_value=GenerationResult(
            content={"text": "Post!", "hashtags": [], "pin_title": ""},
            model_used="test",
            input_tokens=50,
            output_tokens=100,
            cost_usd=0.005,
            generation_time_ms=200,
            prompt_version="v3",
            fallback_used=False,
        ),
    )
    mock_db = MagicMock()

    cat_no_styles = _make_category(text_settings={})

    with (
        patch("services.ai.social_posts.ProjectsRepository") as MockProjRepo,
        patch("services.ai.social_posts.CategoriesRepository") as MockCatRepo,
    ):
        MockProjRepo.return_value.get_by_id = AsyncMock(return_value=_make_project())
        MockCatRepo.return_value.get_by_id = AsyncMock(return_value=cat_no_styles)

        from services.ai.social_posts import SocialPostService

        svc = SocialPostService(orchestrator=mock_orch, db=mock_db)
        svc._projects = MockProjRepo.return_value
        svc._categories = MockCatRepo.return_value

        await svc.generate(
            user_id=123,
            project_id=1,
            category_id=1,
            keyword="test keyword",
            platform="vk",
        )

    request = mock_orch.generate.call_args.args[0]
    assert request.context["text_style"] == "\u0420\u0430\u0437\u0433\u043e\u0432\u043e\u0440\u043d\u044b\u0439"
