"""Keyword generation service — semantic core generation.

Source of truth: API_CONTRACTS.md section 5 (keywords_v2.yaml).
Zero Telegram/Aiogram dependencies.
"""

from typing import Any

import structlog

from db.client import SupabaseClient
from db.repositories.projects import ProjectsRepository
from services.ai.orchestrator import AIOrchestrator, GenerationRequest, GenerationResult

log = structlog.get_logger()

# JSON Schema for structured output
KEYWORDS_SCHEMA: dict[str, Any] = {
    "name": "keywords_response",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "keywords": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "phrase": {"type": "string"},
                        "intent": {
                            "type": "string",
                            "enum": ["commercial", "informational"],
                        },
                    },
                    "required": ["phrase", "intent"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["keywords"],
        "additionalProperties": False,
    },
}


class KeywordService:
    """Generates SEO keyword phrases."""

    def __init__(self, orchestrator: AIOrchestrator, db: SupabaseClient) -> None:
        self._orchestrator = orchestrator
        self._db = db
        self._projects = ProjectsRepository(db)

    async def generate(
        self,
        user_id: int,
        project_id: int,
        quantity: int,
        products: str,
        geography: str,
    ) -> GenerationResult:
        """Generate keyword phrases.

        Returns GenerationResult with content as dict: {keywords: [{phrase, intent}]}
        """
        project = await self._projects.get_by_id(project_id)

        if project is None:
            from bot.exceptions import AIGenerationError
            raise AIGenerationError(message="Project not found")

        context: dict[str, Any] = {
            "quantity": str(quantity),
            "products": products,
            "geography": geography,
            "company_name": project.company_name,
            "specialization": project.specialization,
            "language": "ru",
        }

        request = GenerationRequest(
            task="keywords",
            context=context,
            user_id=user_id,
            response_schema=KEYWORDS_SCHEMA,
        )

        return await self._orchestrator.generate(request)
