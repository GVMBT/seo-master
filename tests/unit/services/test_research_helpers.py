"""Tests for services/research_helpers.py — shared competitor analysis helpers.

Covers: is_own_site, format_competitor_analysis, identify_gaps.
Extracted from publish.py and preview.py (CR-78d).
"""

from __future__ import annotations

from services.research_helpers import (
    MAX_H2_PER_COMPETITOR,
    _process_extra_serper,
    _url_to_hint,
    format_autocomplete_for_prompt,
    format_competitor_analysis,
    format_internal_links,
    format_news_for_prompt,
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


# ---------------------------------------------------------------------------
# _url_to_hint
# ---------------------------------------------------------------------------


class TestUrlToHint:
    def test_ascii_slug_with_hyphens(self) -> None:
        assert _url_to_hint("https://example.com/betonnye-bloki") == "betonnye bloki"

    def test_root_path_returns_empty(self) -> None:
        assert _url_to_hint("https://example.com/") == ""

    def test_nested_path_takes_last_segment(self) -> None:
        assert _url_to_hint("https://example.com/uslugi/ukladka-plitki") == "ukladka plitki"

    def test_underscores_replaced(self) -> None:
        assert _url_to_hint("https://example.com/my_page") == "my page"

    def test_percent_encoded_cyrillic(self) -> None:
        # URL-encoded "блоки"
        hint = _url_to_hint("https://example.com/%D0%B1%D0%BB%D0%BE%D0%BA%D0%B8")
        assert hint == "блоки"

    def test_query_string_ignored(self) -> None:
        hint = _url_to_hint("https://example.com/page?id=1&lang=ru")
        assert hint == "page"

    def test_empty_url_returns_empty(self) -> None:
        assert _url_to_hint("") == ""


# ---------------------------------------------------------------------------
# format_internal_links
# ---------------------------------------------------------------------------


class TestFormatInternalLinks:
    def test_urls_with_hints(self) -> None:
        urls = ["https://example.com/betonnye-bloki", "https://example.com/uslugi"]
        result = format_internal_links(urls)
        assert "(betonnye bloki)" in result
        assert "(uslugi)" in result

    def test_root_url_no_parentheses(self) -> None:
        urls = ["https://example.com/"]
        result = format_internal_links(urls)
        assert "(" not in result
        assert result.strip() == "https://example.com/"

    def test_empty_list(self) -> None:
        assert format_internal_links([]) == ""


# ---------------------------------------------------------------------------
# format_news_for_prompt
# ---------------------------------------------------------------------------


class TestFormatNewsForPrompt:
    def test_basic_formatting(self) -> None:
        news = [
            {
                "title": "Construction boom in Crimea",
                "source": "RBC",
                "date": "2 hours ago",
                "snippet": "New projects are emerging across the region.",
            },
        ]
        result = format_news_for_prompt(news)
        assert "<CURRENT_NEWS>" in result
        assert "</CURRENT_NEWS>" in result
        assert "Construction boom in Crimea" in result
        assert "RBC" in result
        assert "2 hours ago" in result

    def test_empty_news_returns_empty(self) -> None:
        assert format_news_for_prompt([]) == ""

    def test_max_items_limit(self) -> None:
        news = [{"title": f"News {i}", "source": "Test"} for i in range(10)]
        result = format_news_for_prompt(news, max_items=3)
        assert "News 0" in result
        assert "News 2" in result
        assert "News 3" not in result

    def test_missing_fields_handled(self) -> None:
        news = [{"title": "Only title"}]
        result = format_news_for_prompt(news)
        assert "Only title" in result

    def test_snippet_truncated(self) -> None:
        news = [{"title": "Long", "snippet": "x" * 300}]
        result = format_news_for_prompt(news)
        # Snippet capped at 200 chars
        assert len([line for line in result.split("\n") if line.startswith("  x")]) == 1


# ---------------------------------------------------------------------------
# format_autocomplete_for_prompt
# ---------------------------------------------------------------------------


class TestFormatAutocompleteForPrompt:
    def test_basic_formatting(self) -> None:
        suggestions = ["стеновые панели для кухни", "стеновые панели мдф", "стеновые панели цена"]
        result = format_autocomplete_for_prompt(suggestions)
        assert "стеновые панели для кухни" in result
        assert ", " in result  # comma-separated

    def test_empty_returns_empty(self) -> None:
        assert format_autocomplete_for_prompt([]) == ""

    def test_max_items_limit(self) -> None:
        suggestions = [f"suggestion {i}" for i in range(20)]
        result = format_autocomplete_for_prompt(suggestions, max_items=5)
        assert "suggestion 4" in result
        assert "suggestion 5" not in result


# ---------------------------------------------------------------------------
# _process_extra_serper
# ---------------------------------------------------------------------------


class TestProcessExtraSerper:
    def test_news_result_processed(self) -> None:
        from services.external.serper import NewsResult

        responses = {"news": NewsResult(news=[{"title": "Test"}])}
        result: dict = {"news_data": [], "autocomplete_suggestions": []}
        _process_extra_serper(responses, result)
        assert len(result["news_data"]) == 1

    def test_autocomplete_result_processed(self) -> None:
        responses = {"autocomplete": ["sug1", "sug2"]}
        result: dict = {"news_data": [], "autocomplete_suggestions": []}
        _process_extra_serper(responses, result)
        assert result["autocomplete_suggestions"] == ["sug1", "sug2"]

    def test_exception_results_ignored(self) -> None:
        responses = {
            "news": RuntimeError("boom"),
            "autocomplete": RuntimeError("boom"),
        }
        result: dict = {"news_data": [], "autocomplete_suggestions": []}
        _process_extra_serper(responses, result)
        assert result["news_data"] == []
        assert result["autocomplete_suggestions"] == []

    def test_missing_keys_no_error(self) -> None:
        result: dict = {"news_data": [], "autocomplete_suggestions": []}
        _process_extra_serper({}, result)
        assert result["news_data"] == []
