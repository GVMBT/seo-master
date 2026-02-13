"""Review generation service — realistic customer reviews.

Source of truth: API_CONTRACTS.md section 5 (review_v1.yaml).
Zero Telegram/Aiogram dependencies.
"""

from typing import Any

import structlog

from db.client import SupabaseClient
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from services.ai.orchestrator import AIOrchestrator, GenerationRequest, GenerationResult

log = structlog.get_logger()

# JSON Schema for structured output
REVIEW_SCHEMA: dict[str, Any] = {
    "name": "review_response",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "reviews": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "author": {"type": "string"},
                        "date": {"type": "string"},
                        "rating": {"type": "integer"},
                        "text": {"type": "string"},
                        "pros": {"type": "string"},
                        "cons": {"type": "string"},
                    },
                    "required": ["author", "date", "rating", "text", "pros", "cons"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["reviews"],
        "additionalProperties": False,
    },
}


class ReviewService:
    """Generates realistic customer reviews."""

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
        quantity: int,
    ) -> GenerationResult:
        """Generate realistic customer reviews.

        Returns GenerationResult with content as dict:
        {reviews: [{author, date, rating, text, pros, cons}]}
        """
        project = await self._projects.get_by_id(project_id)
        category = await self._categories.get_by_id(category_id)

        if project is None or category is None:
            from bot.exceptions import AIGenerationError
            raise AIGenerationError(message="Project or category not found")

        context: dict[str, Any] = {
            "quantity": str(quantity),
            "company_name": project.company_name,
            "specialization": project.specialization,
            "language": "ru",
            "prices_excerpt": (category.prices or "")[:300],
        }

        request = GenerationRequest(
            task="review",
            context=context,
            user_id=user_id,
            response_schema=REVIEW_SCHEMA,
        )

        return await self._orchestrator.generate(request)
