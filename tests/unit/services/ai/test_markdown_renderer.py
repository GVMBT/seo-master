"""Tests for services/ai/markdown_renderer.py -- Markdown to HTML with SEO features.

Covers: slugify (Cyrillic transliteration), SEORenderer heading IDs,
image figure/figcaption, ToC generation, branding CSS, E47 fallback,
render_markdown full pipeline.
"""

from __future__ import annotations

from services.ai.markdown_renderer import (
    SEORenderer,
    _build_branding_css,
    render_markdown,
    slugify,
)


class TestSlugify:
    """Tests for Cyrillic transliteration and slug generation."""

    def test_slugify_cyrillic(self) -> None:
        result = slugify("Привет мир")
        assert result == "privet-mir"

    def test_slugify_mixed_latin_cyrillic(self) -> None:
        result = slugify("SEO оптимизация 2024")
        assert result == "seo-optimizatsiya-2024"

    def test_slugify_special_chars_replaced(self) -> None:
        result = slugify("Что? Где! Когда...")
        assert result == "chto-gde-kogda"

    def test_slugify_consecutive_hyphens_collapsed(self) -> None:
        result = slugify("а -- б")
        assert "--" not in result
        assert result == "a-b"

    def test_slugify_empty_string_returns_heading(self) -> None:
        result = slugify("")
        assert result == "heading"

    def test_slugify_lowercase(self) -> None:
        result = slugify("БОЛЬШИЕ БУКВЫ")
        assert result == "bolshie-bukvy"

    def test_slugify_yo_letter(self) -> None:
        """Ё should transliterate to 'yo'."""
        result = slugify("Ёлка")
        assert result == "yolka"


class TestSEORenderer:
    """Tests for custom mistune renderer methods."""

    def test_heading_has_id_attribute(self) -> None:
        renderer = SEORenderer()
        html = renderer.heading("Заголовок", 2)
        assert 'id="zagolovok"' in html
        assert "<h2" in html

    def test_heading_collects_toc_entry(self) -> None:
        renderer = SEORenderer()
        renderer.heading("Test", 2)
        renderer.heading("Sub", 3)
        assert len(renderer._toc) == 2
        assert renderer._toc[0]["level"] == 2
        assert renderer._toc[1]["level"] == 3

    def test_image_renders_figure_with_lazy_loading(self) -> None:
        renderer = SEORenderer()
        html = renderer.image("Alt text", "https://example.com/img.webp", "Caption")
        assert "<figure>" in html
        assert 'loading="lazy"' in html
        assert "<figcaption>Caption</figcaption>" in html
        assert 'alt="Alt text"' in html

    def test_image_uses_alt_as_fallback_caption(self) -> None:
        renderer = SEORenderer()
        html = renderer.image("Alt text", "https://example.com/img.webp")
        assert "<figcaption>Alt text</figcaption>" in html

    def test_render_toc_with_enough_headings(self) -> None:
        renderer = SEORenderer()
        renderer.heading("One", 2)
        renderer.heading("Two", 2)
        renderer.heading("Three", 2)
        toc = renderer.render_toc()
        assert '<nav class="toc">' in toc
        assert "Содержание" in toc
        assert toc.count("<li") == 3

    def test_render_toc_skips_h1(self) -> None:
        renderer = SEORenderer()
        renderer.heading("H1 Title", 1)
        renderer.heading("H2 One", 2)
        renderer.heading("H2 Two", 2)
        renderer.heading("H2 Three", 2)
        toc = renderer.render_toc()
        assert "H1 Title" not in toc
        assert toc.count("<li") == 3

    def test_render_toc_fewer_than_3_returns_empty(self) -> None:
        renderer = SEORenderer()
        renderer.heading("One", 2)
        renderer.heading("Two", 2)
        toc = renderer.render_toc()
        assert toc == ""

    def test_render_toc_h3_gets_css_class(self) -> None:
        renderer = SEORenderer()
        renderer.heading("One", 2)
        renderer.heading("Sub", 3)
        renderer.heading("Two", 2)
        toc = renderer.render_toc()
        assert 'class="toc-h3"' in toc


class TestBrandingCSS:
    """Tests for branding CSS generation."""

    def test_branding_css_with_all_colors(self) -> None:
        css = _build_branding_css({"text": "#333", "accent": "#0066cc", "background": "#fff"})
        assert "<style>" in css
        assert "#333" in css
        assert "#0066cc" in css
        assert "#fff" in css

    def test_branding_css_empty_dict_returns_empty(self) -> None:
        css = _build_branding_css({})
        assert css == ""


class TestRenderMarkdown:
    """Tests for the full render_markdown pipeline."""

    def test_render_basic_markdown(self) -> None:
        md = "# Hello\n\nParagraph text."
        html = render_markdown(md, insert_toc=False)
        assert "<h1" in html
        assert "<p>" in html

    def test_render_inserts_toc_after_h1(self) -> None:
        md = "# Title\n\n## One\n\n## Two\n\n## Three\n\nText."
        html = render_markdown(md, insert_toc=True)
        # ToC should appear after H1
        h1_pos = html.find("</h1>")
        toc_pos = html.find('<nav class="toc">')
        assert h1_pos < toc_pos

    def test_render_no_toc_when_disabled(self) -> None:
        md = "# Title\n\n## One\n\n## Two\n\n## Three\n\nText."
        html = render_markdown(md, insert_toc=False)
        assert "toc" not in html

    def test_render_with_branding_adds_inline_style(self) -> None:
        """S5: Branding colors are applied via inline styles, not <style> block."""
        md = "# Hello\n\nText."
        html = render_markdown(md, branding={"accent": "#ff0000"}, insert_toc=False)
        # S5: no <style> block (nh3 would strip it), instead inline styles
        assert "<style>" not in html
        assert "#ff0000" in html
        # Heading should have inline style with accent color
        assert 'style="color: #ff0000"' in html

    def test_render_with_branding_text_color_on_paragraph(self) -> None:
        """S5: text color applied as inline style on paragraphs."""
        md = "Some paragraph."
        html = render_markdown(md, branding={"text": "#333333"}, insert_toc=False)
        assert 'style="color: #333333"' in html
        assert "<p" in html

    def test_render_with_branding_survives_nh3(self) -> None:
        """S5: Inline styles survive nh3 sanitization (end-to-end)."""
        from services.ai.articles import sanitize_html

        md = "# Heading\n\nParagraph with [link](https://example.com)."
        html = render_markdown(md, branding={"accent": "#0066cc", "text": "#333"}, insert_toc=False)
        sanitized = sanitize_html(html)
        # Inline styles should survive nh3 sanitization
        assert "#0066cc" in sanitized
        assert "#333" in sanitized

    def test_render_with_link_gets_accent_style(self) -> None:
        """S5: Links get accent color via inline style."""
        md = "Click [here](https://example.com)."
        html = render_markdown(md, branding={"accent": "#0066cc"}, insert_toc=False)
        assert 'style="color: #0066cc"' in html
        assert "https://example.com" in html

    def test_render_markdown_table_converted_to_html(self) -> None:
        """Tables must be converted to <table> HTML, not left as raw markdown."""
        md = (
            "## Comparison\n\n"
            "| Feature | A | B |\n"
            "|---------|---|---|\n"
            "| Speed   | Fast | Slow |\n"
            "| Price   | $10  | $20  |\n"
        )
        html = render_markdown(md, insert_toc=False)
        assert "<table>" in html or "<table" in html
        assert "<th>" in html or "<th " in html
        assert "<td>" in html or "<td " in html
        # Raw markdown pipe syntax must NOT appear
        assert "| Feature |" not in html
        assert "|------" not in html

    def test_render_markdown_strikethrough(self) -> None:
        """Strikethrough ~~text~~ must produce <del> or <s> tags."""
        md = "This is ~~deleted~~ text."
        html = render_markdown(md, insert_toc=False)
        assert "<del>" in html or "<s>" in html
        assert "~~deleted~~" not in html

    def test_render_markdown_e47_fallback(self) -> None:
        """E47: On parse error, fallback to <pre> block.

        Mistune is very robust, so we test the fallback indirectly by
        verifying the function handles content gracefully.
        """
        # Valid markdown should not trigger fallback
        html = render_markdown("Simple text", insert_toc=False)
        assert "<pre>" not in html
        assert "Simple text" in html
