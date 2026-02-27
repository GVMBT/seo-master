"""Tests for services/ai/quality_scorer.py -- programmatic SEO quality scoring.

Covers: full scoring pipeline, individual metric categories,
edge cases (empty HTML, H2 structure), SLOP_WORDS detection,
E45 graceful degradation, threshold behavior.
"""

from __future__ import annotations

from unittest.mock import patch

from services.ai.quality_scorer import (
    SLOP_WORDS,
    ContentQualityScorer,
    QualityScore,
    _count_syllables_ru,
    _strip_html,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_article_html(
    *,
    first_h2_text: str = "",
    h2_count: int = 4,
    paragraphs: int = 10,
    word_count_per_para: int = 80,
    include_faq: bool = True,
    include_schema: bool = False,
    include_toc: bool = False,
    include_lists: bool = True,
    include_images: int = 3,
    main_phrase: str = "кухни на заказ",
) -> str:
    """Build a realistic article HTML for testing."""
    parts: list[str] = []

    if include_toc:
        parts.append('<nav class="toc"><h2>Содержание</h2><ul><li>A</li></ul></nav>')

    # No H1 in body — WordPress adds H1 from post title field

    # First paragraph with main phrase
    intro = f"В этой статье рассмотрим {main_phrase} и все связанные аспекты. "
    filler = "Слово " * (word_count_per_para - 15)
    first_para = intro + filler + f"и {main_phrase} хорошо."
    parts.append(f"<p>{first_para}</p>")

    for i in range(h2_count):
        h2_title = first_h2_text if (i == 0 and first_h2_text) else f"Раздел {i + 1} про {main_phrase}"
        parts.append(f"<h2>{h2_title}</h2>")
        para = "Контент " * word_count_per_para + f"и {main_phrase} здесь."
        parts.append(f"<p>{para}</p>")
        if include_lists and i == 0:
            parts.append("<ul><li>Пункт 1</li><li>Пункт 2</li></ul>")

    if include_faq:
        parts.append("<h2>FAQ</h2>")
        parts.append("<p>Вопрос: Как заказать? Ответ: Позвоните нам.</p>")

    if include_schema:
        parts.append('<script type="application/ld+json">{"@type":"Article"}</script>')

    for j in range(include_images):
        img_html = (
            f'<figure><img src="img{j}.webp" alt="Изображение {j + 1}"'
            f' loading="lazy"><figcaption>Подпись</figcaption></figure>'
        )
        parts.append(img_html)

    # Conclusion with main phrase
    conclusion = (
        f"<p>В заключение, {main_phrase} остается отличным выбором для вашего дома. Цена от 50000 руб. Звоните!</p>"
    )
    parts.append(conclusion)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# QualityScore dataclass
# ---------------------------------------------------------------------------


class TestQualityScoreDataclass:
    def test_defaults(self) -> None:
        score = QualityScore(total=50)
        assert score.total == 50
        assert score.breakdown == {}
        assert score.issues == []
        assert score.passed is True


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_strip_html_removes_tags(self) -> None:
        html = "<h1>Title</h1><p>Paragraph <b>bold</b> text.</p>"
        text = _strip_html(html)
        assert "Title" in text
        assert "Paragraph" in text
        assert "<h1>" not in text

    def test_count_syllables_ru(self) -> None:
        assert _count_syllables_ru("молоко") == 3  # мо-ло-ко
        assert _count_syllables_ru("кот") == 1  # кот
        assert _count_syllables_ru("ёлка") == 2  # ёл-ка

    def test_count_syllables_empty(self) -> None:
        assert _count_syllables_ru("") == 0

    def test_count_syllables_no_vowels(self) -> None:
        assert _count_syllables_ru("бвгд") == 0


# ---------------------------------------------------------------------------
# Full scoring pipeline
# ---------------------------------------------------------------------------


class TestFullScoring:
    def test_score_returns_quality_score(self) -> None:
        scorer = ContentQualityScorer()
        html = _build_article_html()
        result = scorer.score(html, "кухни на заказ", ["кухни москва", "заказ кухни"])
        assert isinstance(result, QualityScore)
        assert 0 <= result.total <= 100
        assert "seo" in result.breakdown
        assert "readability" in result.breakdown
        assert "structure" in result.breakdown
        assert "naturalness" in result.breakdown
        assert "depth" in result.breakdown

    def test_score_good_article_passes_default_threshold(self) -> None:
        scorer = ContentQualityScorer()
        html = _build_article_html(
            include_faq=True,
            include_toc=True,
            include_lists=True,
            include_images=4,
        )
        result = scorer.score(html, "кухни на заказ", ["кухни москва"])
        assert result.passed is True
        assert result.total >= 40

    def test_score_empty_html_low_score(self) -> None:
        scorer = ContentQualityScorer()
        result = scorer.score("<p>Текст</p>", "ключ", [])
        assert result.total < 50
        assert result.passed is True  # default threshold=40, minimal content still passes

    def test_score_custom_threshold(self) -> None:
        scorer = ContentQualityScorer()
        html = _build_article_html()
        result = scorer.score(html, "кухни на заказ", [], threshold=90)
        # Even a good article may not pass 90
        assert isinstance(result.passed, bool)


# ---------------------------------------------------------------------------
# SEO metrics
# ---------------------------------------------------------------------------


class TestSEOMetrics:
    def test_score_keyword_in_first_h2_adds_points(self) -> None:
        scorer = ContentQualityScorer()
        html = _build_article_html(first_h2_text="Кухни на заказ в Москве")
        result = scorer.score(html, "кухни на заказ", [])
        assert result.breakdown["seo"] > 0
        assert not any("not in first H2" in issue for issue in result.issues)

    def test_score_missing_first_h2_keyword_issue(self) -> None:
        scorer = ContentQualityScorer()
        html = _build_article_html(first_h2_text="Заголовок без ключевой фразы")
        result = scorer.score(html, "другая фраза", [])
        assert any("not in first H2" in issue for issue in result.issues)

    def test_score_secondary_phrases_coverage(self) -> None:
        scorer = ContentQualityScorer()
        html = _build_article_html()
        # "кухни на заказ" is in the text, secondary phrases may or may not be
        result = scorer.score(html, "кухни на заказ", ["несуществующая фраза"])
        # Should have low secondary coverage
        assert any("secondary_phrases coverage" in issue for issue in result.issues)


# ---------------------------------------------------------------------------
# Structure metrics
# ---------------------------------------------------------------------------


class TestStructureMetrics:
    def test_score_structure_no_h1_in_body(self) -> None:
        scorer = ContentQualityScorer()
        html = _build_article_html(h2_count=4)
        result = scorer.score(html, "кухни на заказ", [])
        # Should have points for h1_count=0 (correct) and h2_count in 3-6
        assert result.breakdown["structure"] > 0

    def test_score_structure_h1_in_body_issue(self) -> None:
        scorer = ContentQualityScorer()
        html = "<h1>Should not be here</h1><h2>Section</h2><p>" + "текст " * 200 + "</p>"
        result = scorer.score(html, "should", [])
        assert any("h1_count: 1" in issue and "expected 0" in issue for issue in result.issues)

    def test_score_faq_presence_adds_points(self) -> None:
        scorer = ContentQualityScorer()
        html_with_faq = _build_article_html(include_faq=True)
        html_no_faq = _build_article_html(include_faq=False)
        result_with = scorer.score(html_with_faq, "кухни на заказ", [])
        result_without = scorer.score(html_no_faq, "кухни на заказ", [])
        assert result_with.breakdown["structure"] >= result_without.breakdown["structure"]


# ---------------------------------------------------------------------------
# Naturalness metrics
# ---------------------------------------------------------------------------


class TestNaturalnessMetrics:
    def test_slop_words_list_not_empty(self) -> None:
        assert len(SLOP_WORDS) == 20

    def test_score_slop_words_detected(self) -> None:
        scorer = ContentQualityScorer()
        html = "<h2>Заголовок</h2><p>" + "текст " * 200
        html += " Является важным. Осуществлять деятельность. Широкий ассортимент товаров.</p>"
        result = scorer.score(html, "заголовок", [])
        assert any("slop_words" in issue for issue in result.issues)


# ---------------------------------------------------------------------------
# Content depth metrics
# ---------------------------------------------------------------------------


class TestDepthMetrics:
    def test_score_depth_with_lists_and_images(self) -> None:
        scorer = ContentQualityScorer()
        html = _build_article_html(include_lists=True, include_images=4, word_count_per_para=200)
        result = scorer.score(html, "кухни на заказ", [])
        assert result.breakdown["depth"] > 0

    def test_score_depth_very_short_content(self) -> None:
        scorer = ContentQualityScorer()
        html = "<h2>Заголовок</h2><p>Короткий текст.</p>"
        result = scorer.score(html, "заголовок", [])
        assert any("word_count too low" in issue for issue in result.issues)


# ---------------------------------------------------------------------------
# E45: graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    def test_score_works_even_with_minimal_html(self) -> None:
        """Scorer should not crash on any valid HTML input."""
        scorer = ContentQualityScorer()
        result = scorer.score("<div></div>", "test", ["a", "b"])
        assert isinstance(result.total, int)
        assert isinstance(result.passed, bool)


# ---------------------------------------------------------------------------
# H18: ArticleService._score_quality never returns None
# ---------------------------------------------------------------------------


class TestScoreQualityNeverNone:
    """H18: _score_quality static method must always return a QualityScore, never None.

    Tests target ArticleService._score_quality which wraps ContentQualityScorer.score().
    On ImportError or other exceptions, it must return a QualityScore(total=50) fallback.
    """

    def test_normal_scoring_returns_quality_score(self) -> None:
        """Normal path: returns a valid QualityScore from ContentQualityScorer."""
        from services.ai.articles import ArticleService

        result = ArticleService._score_quality(
            "<h2>Test</h2><p>" + "content " * 200 + "</p>",
            "test keyword",
            "secondary one, secondary two",
        )
        assert result is not None
        assert isinstance(result.total, int)
        assert 0 <= result.total <= 100
        assert isinstance(result.issues, list)
        assert isinstance(result.passed, bool)

    def test_exception_in_scorer_returns_fallback_score(self) -> None:
        """H18: Any exception during scoring returns QualityScore(total=50)."""
        from services.ai.articles import ArticleService

        # Patch ContentQualityScorer.score to raise RuntimeError
        with patch.object(
            ContentQualityScorer,
            "score",
            side_effect=RuntimeError("Unexpected NLP crash"),
        ):
            result = ArticleService._score_quality("<p>test</p>", "key", "")

        assert result is not None
        assert result.total == 50
        assert result.passed is True
        assert any("failed" in i.lower() or "unavailable" in i.lower() for i in result.issues)

    def test_value_error_in_scorer_returns_fallback(self) -> None:
        """H18: ValueError in scorer still returns valid QualityScore."""
        from services.ai.articles import ArticleService

        with patch.object(
            ContentQualityScorer,
            "score",
            side_effect=ValueError("bad input"),
        ):
            result = ArticleService._score_quality("<p>x</p>", "k", "a, b")

        assert result is not None
        assert result.total == 50
        assert isinstance(result.issues, list)

    def test_empty_secondary_phrases(self) -> None:
        """Edge case: empty secondary_phrases string."""
        from services.ai.articles import ArticleService

        result = ArticleService._score_quality(
            "<h2>Test</h2><p>" + "content " * 200 + "</p>",
            "test keyword",
            "",
        )
        assert result is not None
        assert isinstance(result.total, int)

    def test_result_has_required_attributes(self) -> None:
        """H18: result always has total, breakdown, issues, passed attributes."""
        from services.ai.articles import ArticleService

        result = ArticleService._score_quality(
            "<h2>Title</h2><p>" + "word " * 100 + "</p>",
            "word",
            "",
        )
        assert hasattr(result, "total")
        assert hasattr(result, "breakdown")
        assert hasattr(result, "issues")
        assert hasattr(result, "passed")

    def test_result_never_none_even_on_empty_html(self) -> None:
        """H18: even with empty HTML, result is never None."""
        from services.ai.articles import ArticleService

        result = ArticleService._score_quality("", "kw", "")
        assert result is not None
        assert isinstance(result.total, int)
