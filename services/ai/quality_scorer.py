"""Programmatic SEO quality scorer. No AI calls.

Source of truth: API_CONTRACTS.md section 3.7.

Metric categories (max points):
- SEO (30): keyword_density, keyword_in_h1, keyword_in_first_paragraph, etc.
- Readability (25): Flesch-Kincaid for Russian (Oborneva 2006), sentence/paragraph length, TTR
- Structure (20): h1_count, h2_count, faq_presence, schema_org, toc, internal links
- Naturalness (15): anti_slop_check, burstiness, no_generic_phrases, factual_density
- Content depth (10): word_count, unique_entities, list_presence, image_count

E45: If razdel/pymorphy3 crash -> score naturalness/readability = 0, rest works.
     Warning "nlp_scorer_fallback".
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from html.parser import HTMLParser

import structlog

log = structlog.get_logger()

# Russian vowels for syllable counting
_RU_VOWELS = set("аеёиоуыэюя")

# Anti-slop blacklist (from article_v7.yaml spec)
SLOP_WORDS: list[str] = [
    "является",
    "осуществлять",
    "данный",
    "широкий ассортимент",
    "индивидуальный подход",
    "высококвалифицированный",
    "в кратчайшие сроки",
    "уникальный опыт",
    "на сегодняшний день",
    "в рамках",
    "комплексный подход",
    "оптимальное решение",
    "динамично развивающийся",
    "занимает лидирующие позиции",
    "воплощает в себе",
    "мы рады предложить",
    "не имеющий аналогов",
    "передовые технологии",
    "инновационный подход",
    "высочайшее качество",
]


@dataclass
class QualityScore:
    """Result of programmatic quality scoring."""

    total: int  # 0-100, weighted sum
    breakdown: dict[str, int] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    passed: bool = True  # total >= threshold


# ---------------------------------------------------------------------------
# HTML text extraction
# ---------------------------------------------------------------------------


class _HTMLTextExtractor(HTMLParser):
    """Simple HTML parser to extract plain text."""

    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.text_parts.append(data)


def _strip_html(html: str) -> str:
    """Extract plain text from HTML."""
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return " ".join(extractor.text_parts)


# ---------------------------------------------------------------------------
# NLP helpers (with E45 graceful degradation)
# ---------------------------------------------------------------------------

_NLP_AVAILABLE = True
try:
    import razdel  # type: ignore[import-untyped]  # noqa: F401
except ImportError:
    _NLP_AVAILABLE = False


def _count_syllables_ru(word: str) -> int:
    """Count Russian syllables by counting vowels."""
    return sum(1 for c in word.lower() if c in _RU_VOWELS)


def _flesch_ru(text: str) -> float:
    """Flesch Reading Ease adapted for Russian (Oborneva 2006).

    80-100: very easy, 60-80: easy, 40-60: medium, <40: hard.
    """
    if not _NLP_AVAILABLE:
        return 50.0  # neutral fallback

    import razdel

    sentences = list(razdel.sentenize(text))
    words = [w for w in razdel.tokenize(text) if re.match(r"\w", w.text)]

    if not sentences or not words:
        return 0.0

    asl = len(words) / len(sentences)
    syllables = sum(_count_syllables_ru(w.text) for w in words)
    asw = syllables / len(words) if words else 1.0

    return 206.835 - 1.3 * asl - 60.1 * asw


def _tokenize_words(text: str) -> list[str]:
    """Tokenize text into words, using razdel if available, else regex fallback."""
    if _NLP_AVAILABLE:
        import razdel

        return [w.text for w in razdel.tokenize(text) if re.match(r"\w", w.text)]
    return re.findall(r"\b\w+\b", text)


def _sentenize(text: str) -> list[str]:
    """Split text into sentences, using razdel if available, else regex fallback."""
    if _NLP_AVAILABLE:
        import razdel

        return [s.text for s in razdel.sentenize(text)]
    # Simple sentence splitting for fallback
    return [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]


# ---------------------------------------------------------------------------
# ContentQualityScorer
# ---------------------------------------------------------------------------


class ContentQualityScorer:
    """Programmatic SEO quality scorer. No AI calls."""

    def __init__(self) -> None:
        self._issues: list[str] = []

    def score(
        self,
        html: str,
        main_phrase: str,
        secondary_phrases: list[str],
        *,
        threshold: int = 40,
    ) -> QualityScore:
        """Score article quality. Returns 0-100.

        Args:
            html: The rendered HTML of the article.
            main_phrase: Primary keyword phrase.
            secondary_phrases: Secondary keyword phrases from the cluster.
            threshold: Minimum score to pass (default 40).
        """
        self._issues = []
        plain_text = _strip_html(html)
        lower_text = plain_text.lower()
        lower_html = html.lower()

        scores: dict[str, int] = {}

        # === SEO metrics (max 30 points) ===
        scores["seo"] = self._score_seo(lower_html, lower_text, main_phrase, secondary_phrases)

        # === Readability (max 25 points) ===
        scores["readability"] = self._score_readability(plain_text)

        # === Structure (max 20 points) ===
        scores["structure"] = self._score_structure(html, lower_html)

        # === Naturalness (max 15 points) ===
        scores["naturalness"] = self._score_naturalness(plain_text, lower_text)

        # === Content depth (max 10 points) ===
        scores["depth"] = self._score_depth(html, lower_html, plain_text)

        total = sum(scores.values())
        return QualityScore(
            total=total,
            breakdown=scores,
            issues=list(self._issues),
            passed=total >= threshold,
        )

    # ----- SEO (max 30) -----

    def _score_seo(
        self,
        lower_html: str,
        lower_text: str,
        main_phrase: str,
        secondary_phrases: list[str],
    ) -> int:
        points = 0
        main_lower = main_phrase.lower()
        words = _tokenize_words(lower_text)
        word_count = len(words)

        # keyword_density (max 8 points): ideal 1.5-2.5%
        if word_count > 0:
            main_words = main_lower.split()
            # Count occurrences of the full main phrase in text
            phrase_count = lower_text.count(main_lower)
            density = (phrase_count * len(main_words)) / word_count * 100 if word_count else 0.0

            if 1.5 <= density <= 2.5:
                points += 8
            elif 1.0 <= density < 1.5 or 2.5 < density <= 3.5:
                points += 4
            else:
                if density > 3.5:
                    self._issues.append(f"keyword_density too high: {density:.1f}%")
                elif density < 0.5:
                    self._issues.append(f"keyword_density too low: {density:.1f}%")

        # keyword_in_first_h2 (max 6 points)
        # Note: H1 = post title (set separately in WP). Content body starts with H2.
        h2_match = re.search(r"<h2[^>]*>(.*?)</h2>", lower_html, re.DOTALL)
        if h2_match and main_lower in h2_match.group(1).lower():
            points += 6
        else:
            self._issues.append("main_phrase not in first H2")

        # keyword_in_first_paragraph (max 5 points)
        first_p = re.search(r"<p[^>]*>(.*?)</p>", lower_html, re.DOTALL)
        if first_p and main_lower in first_p.group(1).lower():
            points += 5
        else:
            self._issues.append("main_phrase not in first paragraph")

        # keyword_in_conclusion (max 3 points) — last paragraph
        all_p = re.findall(r"<p[^>]*>(.*?)</p>", lower_html, re.DOTALL)
        if all_p and main_lower in all_p[-1].lower():
            points += 3

        # secondary_phrases_coverage (max 8 points)
        if secondary_phrases:
            covered = sum(1 for sp in secondary_phrases if sp.lower() in lower_text)
            coverage = covered / len(secondary_phrases)
            seo_sec_points = min(8, int(coverage * 8))
            points += seo_sec_points
            if coverage < 0.5:
                self._issues.append(
                    f"secondary_phrases coverage low: {coverage:.0%} ({covered}/{len(secondary_phrases)})"
                )
        else:
            points += 4  # no secondary phrases to check -- partial credit

        return min(30, points)

    # ----- Readability (max 25) -----

    def _score_readability(self, plain_text: str) -> int:
        if not _NLP_AVAILABLE:
            log.warning("nlp_scorer_fallback", reason="razdel not available")
            return 0

        try:
            return self._score_readability_impl(plain_text)
        except Exception:
            log.warning("nlp_scorer_fallback", exc_info=True)
            self._issues.append("NLP scoring failed — readability score set to 0")
            return 0

    def _score_readability_impl(self, plain_text: str) -> int:
        points = 0
        words = _tokenize_words(plain_text)
        sentences = _sentenize(plain_text)
        word_count = len(words)

        # Flesch-Kincaid Russian (max 8 points)
        flesch = _flesch_ru(plain_text)
        if flesch >= 60:
            points += 8
        elif flesch >= 40:
            points += 5
        elif flesch >= 20:
            points += 2
        else:
            self._issues.append(f"Flesch readability score low: {flesch:.0f}")

        # avg_sentence_length (max 6 points): <20 words is ideal
        if sentences:
            sentence_words = [len(_tokenize_words(s)) for s in sentences]
            avg_sent_len = statistics.mean(sentence_words) if sentence_words else 0
            if avg_sent_len <= 20:
                points += 6
            elif avg_sent_len <= 25:
                points += 3
            else:
                self._issues.append(f"avg_sentence_length too high: {avg_sent_len:.0f} words")

        # avg_paragraph_length (max 5 points): <150 words is ideal
        paragraphs = re.split(r"\n\s*\n|\r\n\s*\r\n", plain_text)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]
        if paragraphs:
            para_word_counts = [len(_tokenize_words(p)) for p in paragraphs]
            avg_para_len = statistics.mean(para_word_counts) if para_word_counts else 0
            if avg_para_len <= 150:
                points += 5
            elif avg_para_len <= 200:
                points += 2
            else:
                self._issues.append(f"avg_paragraph_length too high: {avg_para_len:.0f} words")

        # vocabulary_diversity TTR (max 6 points): > 0.4 is good
        if word_count > 0:
            unique_words = set(w.lower() for w in words)
            ttr = len(unique_words) / word_count
            if ttr > 0.4:
                points += 6
            elif ttr > 0.3:
                points += 3
            else:
                self._issues.append(f"vocabulary_diversity (TTR) low: {ttr:.2f}")

        return min(25, points)

    # ----- Structure (max 20) -----

    def _score_structure(self, html: str, lower_html: str) -> int:
        points = 0

        # h1_absent: content body must NOT contain H1 (WordPress adds H1 from post title)
        h1_count = len(re.findall(r"<h1[^>]*>", html, re.IGNORECASE))
        if h1_count == 0:
            points += 4
        else:
            self._issues.append(f"h1_count: {h1_count} (expected 0, H1 = post title)")

        # h2_count: 3-6 (max 4 points)
        h2_count = len(re.findall(r"<h2[^>]*>", html, re.IGNORECASE))
        if 3 <= h2_count <= 6:
            points += 4
        elif h2_count >= 2:
            points += 2
        else:
            self._issues.append(f"h2_count: {h2_count} (expected 3-6)")

        # faq_presence (max 3 points)
        if re.search(r"faq|часто\s+задаваемые|вопросы\s+и\s+ответы", lower_html):
            points += 3

        # schema_org_presence (max 3 points)
        if "application/ld+json" in lower_html:
            points += 3

        # internal_links_count (max 3 points)
        links = re.findall(r'<a\s[^>]*href=["\'](?!#)', html, re.IGNORECASE)
        if len(links) >= 3:
            points += 3
        elif len(links) >= 1:
            points += 1

        # toc_presence (max 3 points)
        if re.search(r'class="toc"|содержание|table\s+of\s+contents', lower_html):
            points += 3

        return min(20, points)

    # ----- Naturalness (max 15) -----

    def _score_naturalness(self, plain_text: str, lower_text: str) -> int:
        if not _NLP_AVAILABLE:
            log.warning("nlp_scorer_fallback", reason="razdel not available for naturalness")
            return 0

        try:
            return self._score_naturalness_impl(plain_text, lower_text)
        except Exception:
            log.warning("nlp_scorer_fallback", exc_info=True)
            self._issues.append("NLP scoring failed — naturalness score set to 0")
            return 0

    def _score_naturalness_impl(self, plain_text: str, lower_text: str) -> int:
        points = 0

        # anti_slop_check (max 5 points): penalize for each slop word found
        slop_found = [w for w in SLOP_WORDS if w in lower_text]
        if not slop_found:
            points += 5
        elif len(slop_found) <= 2:
            points += 2
        else:
            self._issues.append(f"slop_words found: {', '.join(slop_found[:5])}")

        # burstiness (max 4 points): variance in sentence lengths
        sentences = _sentenize(plain_text)
        if len(sentences) >= 3:
            sent_lengths = [len(_tokenize_words(s)) for s in sentences]
            if sent_lengths:
                std_dev = statistics.stdev(sent_lengths) if len(sent_lengths) > 1 else 0
                mean_len = statistics.mean(sent_lengths) if sent_lengths else 1
                cv = std_dev / mean_len if mean_len > 0 else 0  # coefficient of variation
                if cv > 0.3:
                    points += 4  # good variance -- natural writing
                elif cv > 0.15:
                    points += 2
                else:
                    self._issues.append("sentence lengths too uniform (low burstiness)")
        else:
            points += 2  # too few sentences to evaluate

        # factual_density (max 3 points): numbers, dates, proper nouns
        numbers = re.findall(r"\d+", plain_text)
        if len(numbers) >= 5:
            points += 3
        elif len(numbers) >= 2:
            points += 1
        else:
            self._issues.append("low factual_density (few numbers/dates)")

        # no_generic_phrases (max 3 points): absence of overly generic language
        generic_patterns = [
            r"как известно",
            r"всем известно",
            r"не секрет",
            r"само собой",
        ]
        generic_found = sum(1 for p in generic_patterns if re.search(p, lower_text))
        if generic_found == 0:
            points += 3
        elif generic_found <= 1:
            points += 1
        else:
            self._issues.append("generic phrases found in text")

        return min(15, points)

    # ----- Content depth (max 10) -----

    def _score_depth(self, html: str, lower_html: str, plain_text: str) -> int:
        points = 0
        words = _tokenize_words(plain_text)
        word_count = len(words)

        # word_count target (max 3 points): 1500+ words is good for articles
        if word_count >= 1500:
            points += 3
        elif word_count >= 1000:
            points += 2
        elif word_count >= 500:
            points += 1
        else:
            self._issues.append(f"word_count too low: {word_count}")

        # unique_entities (max 3 points): brand names, cities, numbers
        # Simple heuristic: count capitalized multi-char words (likely proper nouns)
        entities = set(re.findall(r"\b[A-ZА-ЯЁ][a-zа-яё]{2,}\b", plain_text))
        if len(entities) >= 10:
            points += 3
        elif len(entities) >= 5:
            points += 2
        elif len(entities) >= 2:
            points += 1

        # list_presence (max 2 points): ul/ol in HTML
        if re.search(r"<[uo]l[^>]*>", lower_html):
            points += 2

        # image_count (max 2 points)
        img_count = len(re.findall(r"<img\s", html, re.IGNORECASE))
        if img_count >= 3:
            points += 2
        elif img_count >= 1:
            points += 1

        return min(10, points)
