"""Tests for research-related functions in services/ai/articles.py.

Covers: RESEARCH_SCHEMA validation, format_research_for_prompt() for all steps.
"""

from __future__ import annotations

from services.ai.articles import RESEARCH_SCHEMA, format_research_for_prompt


# ---------------------------------------------------------------------------
# RESEARCH_SCHEMA — structural validation
# ---------------------------------------------------------------------------


class TestResearchSchema:
    def test_schema_has_required_fields(self) -> None:
        schema = RESEARCH_SCHEMA["schema"]
        assert set(schema["required"]) == {"facts", "trends", "statistics", "summary"}

    def test_schema_is_strict(self) -> None:
        assert RESEARCH_SCHEMA["strict"] is True
        assert RESEARCH_SCHEMA["schema"]["additionalProperties"] is False

    def test_schema_name(self) -> None:
        assert RESEARCH_SCHEMA["name"] == "research_response"

    def test_facts_items_have_required_fields(self) -> None:
        facts_schema = RESEARCH_SCHEMA["schema"]["properties"]["facts"]["items"]
        assert set(facts_schema["required"]) == {"claim", "source", "year"}
        assert facts_schema["additionalProperties"] is False

    def test_trends_items_have_required_fields(self) -> None:
        trends_schema = RESEARCH_SCHEMA["schema"]["properties"]["trends"]["items"]
        assert set(trends_schema["required"]) == {"trend", "relevance"}
        assert trends_schema["additionalProperties"] is False

    def test_statistics_items_have_required_fields(self) -> None:
        stats_schema = RESEARCH_SCHEMA["schema"]["properties"]["statistics"]["items"]
        assert set(stats_schema["required"]) == {"metric", "value", "source"}
        assert stats_schema["additionalProperties"] is False


# ---------------------------------------------------------------------------
# format_research_for_prompt() — output formatting
# ---------------------------------------------------------------------------

_SAMPLE_RESEARCH = {
    "facts": [
        {"claim": "90% of pages get no traffic", "source": "Ahrefs", "year": "2025"},
        {"claim": "Long-form content ranks higher", "source": "Backlinko", "year": "2024"},
    ],
    "trends": [
        {"trend": "AI-generated content growth", "relevance": "high"},
    ],
    "statistics": [
        {"metric": "Average CTR position 1", "value": "27.6%", "source": "FirstPageSage"},
    ],
    "summary": "SEO continues to evolve with AI playing a bigger role.",
}


class TestFormatResearchForPrompt:
    def test_none_research_returns_empty(self) -> None:
        assert format_research_for_prompt(None, "outline") == ""

    def test_empty_dict_returns_empty(self) -> None:
        assert format_research_for_prompt({}, "outline") == ""

    def test_empty_arrays_returns_empty(self) -> None:
        research = {"facts": [], "trends": [], "statistics": [], "summary": ""}
        assert format_research_for_prompt(research, "outline") == ""

    def test_outline_step_has_correct_instruction(self) -> None:
        result = format_research_for_prompt(_SAMPLE_RESEARCH, "outline")
        assert "<CURRENT_RESEARCH>" in result
        assert "</CURRENT_RESEARCH>" in result
        assert "планирования разделов" in result

    def test_expand_step_has_correct_instruction(self) -> None:
        result = format_research_for_prompt(_SAMPLE_RESEARCH, "expand")
        assert "Приоритизируй" in result
        assert "противоречиях" in result

    def test_critique_step_has_correct_instruction(self) -> None:
        result = format_research_for_prompt(_SAMPLE_RESEARCH, "critique")
        assert "верификации фактов" in result
        assert "расхождения" in result

    def test_unknown_step_falls_back_to_expand(self) -> None:
        result = format_research_for_prompt(_SAMPLE_RESEARCH, "unknown_step")
        assert "Приоритизируй" in result

    def test_contains_facts(self) -> None:
        result = format_research_for_prompt(_SAMPLE_RESEARCH, "expand")
        assert "90% of pages get no traffic" in result
        assert "Ahrefs" in result
        assert "2025" in result

    def test_contains_trends(self) -> None:
        result = format_research_for_prompt(_SAMPLE_RESEARCH, "expand")
        assert "AI-generated content growth" in result

    def test_contains_statistics(self) -> None:
        result = format_research_for_prompt(_SAMPLE_RESEARCH, "expand")
        assert "27.6%" in result
        assert "FirstPageSage" in result

    def test_contains_summary(self) -> None:
        result = format_research_for_prompt(_SAMPLE_RESEARCH, "expand")
        assert "SEO continues to evolve" in result

    def test_partial_data_only_facts(self) -> None:
        research = {
            "facts": [{"claim": "Test fact", "source": "Source", "year": "2025"}],
            "trends": [],
            "statistics": [],
            "summary": "",
        }
        result = format_research_for_prompt(research, "outline")
        assert "Test fact" in result
        assert "<CURRENT_RESEARCH>" in result

    def test_partial_data_only_summary(self) -> None:
        research = {
            "facts": [],
            "trends": [],
            "statistics": [],
            "summary": "Just a summary",
        }
        result = format_research_for_prompt(research, "outline")
        assert "Just a summary" in result
