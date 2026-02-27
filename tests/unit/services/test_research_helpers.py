"""Tests for services/research_helpers.py — shared competitor analysis helpers.

Covers: is_own_site, format_competitor_analysis, identify_gaps.
Extracted from publish.py and preview.py (CR-78d).
"""

from __future__ import annotations

from services.research_helpers import (
    MAX_H2_PER_COMPETITOR,
    format_competitor_analysis,
    identify_gaps,
    is_own_site,
)

# ---------------------------------------------------------------------------
# is_own_site
# ---------------------------------------------------------------------------


class TestIsOwnSite:
    def test_same_domain_returns_true(self) -> None:
        assert is_own_site("https://example.com/blog", "https://www.example.com") is True

    def test_www_prefix_normalized(self) -> None:
        assert is_own_site("https://www.example.com/page", "https://example.com") is True

    def test_different_domain_returns_false(self) -> None:
        assert is_own_site("https://other.com/page", "https://example.com") is False

    def test_no_project_url_returns_false(self) -> None:
        assert is_own_site("https://example.com", None) is False

    def test_empty_project_url_returns_false(self) -> None:
        assert is_own_site("https://example.com", "") is False

    def test_subdomains_are_different(self) -> None:
        assert is_own_site("https://blog.example.com", "https://example.com") is False


# ---------------------------------------------------------------------------
# format_competitor_analysis
# ---------------------------------------------------------------------------


class TestFormatCompetitorAnalysis:
    def test_basic_formatting(self) -> None:
        pages = [
            {
                "url": "https://example.com",
                "word_count": 2000,
                "summary": "SEO guide",
                "headings": [{"level": 2, "text": "What is SEO"}],
            }
        ]
        result = format_competitor_analysis(pages)
        assert "example.com" in result
        assert "2000" in result
        assert "What is SEO" in result
        assert "SEO guide" in result

    def test_multiple_competitors(self) -> None:
        pages = [
            {"url": "https://a.com", "word_count": 1000, "headings": []},
            {"url": "https://b.com", "word_count": 2000, "headings": []},
        ]
        result = format_competitor_analysis(pages)
        assert "a.com" in result
        assert "b.com" in result

    def test_empty_pages(self) -> None:
        result = format_competitor_analysis([])
        assert result == ""

    def test_h2_truncated_at_limit(self) -> None:
        headings = [{"level": 2, "text": f"Heading {i}"} for i in range(MAX_H2_PER_COMPETITOR + 5)]
        pages = [{"url": "https://test.com", "word_count": 100, "headings": headings}]
        result = format_competitor_analysis(pages)
        assert f"Heading {MAX_H2_PER_COMPETITOR - 1}" in result
        assert f"Heading {MAX_H2_PER_COMPETITOR + 4}" not in result


# ---------------------------------------------------------------------------
# identify_gaps
# ---------------------------------------------------------------------------


class TestIdentifyGaps:
    def test_empty_pages_returns_empty(self) -> None:
        assert identify_gaps([]) == ""

    def test_pages_with_h2_headings(self) -> None:
        pages = [
            {"headings": [{"level": 2, "text": "On-page SEO"}, {"level": 2, "text": "Technical SEO"}]},
        ]
        result = identify_gaps(pages)
        assert "On-page SEO" in result
        assert "Technical SEO" in result

    def test_pages_without_h2_returns_empty(self) -> None:
        pages = [
            {"headings": [{"level": 3, "text": "Sub-heading only"}]},
        ]
        result = identify_gaps(pages)
        assert result == ""

    def test_includes_gap_instruction(self) -> None:
        pages = [
            {"headings": [{"level": 2, "text": "Test"}]},
        ]
        result = identify_gaps(pages)
        assert "уникальная ценность" in result
