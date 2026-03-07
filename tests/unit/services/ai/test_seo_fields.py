"""Tests for SEO field helpers in services/ai/articles.py.

Covers: truncate_seo_fields, ARTICLE_SCHEMA/CRITIQUE_SCHEMA seo_title field.
"""

from __future__ import annotations

from services.ai.articles import ARTICLE_SCHEMA, CRITIQUE_SCHEMA, truncate_seo_fields


class TestTruncateSeoFields:
    def test_no_truncation_needed(self) -> None:
        title, desc = truncate_seo_fields("Short title", "Short description")
        assert title == "Short title"
        assert desc == "Short description"

    def test_seo_title_truncated_at_word_boundary(self) -> None:
        long_title = "Кухни из массива дуба в Москве — заказать с доставкой и установкой по лучшей цене"
        title, _ = truncate_seo_fields(long_title, "ok")
        assert len(title) <= 60
        assert not title.endswith(" ")

    def test_meta_description_truncated_at_160(self) -> None:
        long_desc = "A" * 200
        _, desc = truncate_seo_fields("ok", long_desc)
        assert len(desc) <= 160

    def test_empty_strings_pass_through(self) -> None:
        title, desc = truncate_seo_fields("", "")
        assert title == ""
        assert desc == ""

    def test_exact_boundary_not_truncated(self) -> None:
        title_60 = "A" * 60
        desc_160 = "B" * 160
        title, desc = truncate_seo_fields(title_60, desc_160)
        assert title == title_60
        assert desc == desc_160


class TestSchemaHasSeoTitle:
    def test_article_schema_has_seo_title(self) -> None:
        props = ARTICLE_SCHEMA["schema"]["properties"]
        assert "seo_title" in props
        assert props["seo_title"] == {"type": "string"}
        assert "seo_title" in ARTICLE_SCHEMA["schema"]["required"]

    def test_critique_schema_has_seo_title(self) -> None:
        props = CRITIQUE_SCHEMA["schema"]["properties"]
        assert "seo_title" in props
        assert "seo_title" in CRITIQUE_SCHEMA["schema"]["required"]
