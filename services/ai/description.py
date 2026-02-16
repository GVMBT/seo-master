"""Category description generation service.

Source of truth: API_CONTRACTS.md section 5 (description_v1.yaml).
Returns plain text (no JSON). Zero Telegram/Aiogram dependencies.
"""

from typing import Any

import structlog

from db.client import SupabaseClient
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from services.ai.orchestrator import AIOrchestrator, GenerationRequest, GenerationResult

log = structlog.get_logger()


class DescriptionService:
    """Generates category descriptions (plain text)."""

    def __init__(self, orchestrator: AIOrchestrator, db: SupabaseClient) -> None:
        self._orchestrator = orchestrator
        self._db = db
        self._projects = ProjectsRepository(db)
        self._categories = CategoriesRepository(db)

    async def generate(
        self,
        user_id: int,
        project_id: int,
        category_id: int,
    ) -> GenerationResult:
        """Generate a category description.

        Returns GenerationResult with content as plain text string.
        """
        project = await self._projects.get_by_id(project_id)
        category = await self._categories.get_by_id(category_id)

        if project is None or category is None:
            from bot.exceptions import AIGenerationError

            raise AIGenerationError(message="Project or category not found")

        # Build keywords sample (first 10)
        keywords_sample = "не заданы"
        if category.keywords:
            phrases = [kw.get("phrase", "") for kw in category.keywords[:10]]
            keywords_sample = ", ".join(p for p in phrases if p)

        # Build reviews excerpt (first 3)
        reviews_excerpt = ""
        if category.reviews:
            excerpts = []
            for r in category.reviews[:3]:
                text = r.get("text", "")
                if text:
                    excerpts.append(text[:100])
            reviews_excerpt = "\n".join(excerpts)

        context: dict[str, Any] = {
            "category_name": category.name,
            "company_name": project.company_name,
            "specialization": project.specialization,
            "language": "ru",
            "keywords_sample": keywords_sample,
            "prices_excerpt": (category.prices or "")[:300],
            "reviews_excerpt": reviews_excerpt,
        }

        request = GenerationRequest(
            task="description",
            context=context,
            user_id=user_id,
            # No response_schema — description returns plain text
        )

        return await self._orchestrator.generate(request)
