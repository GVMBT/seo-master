"""Markdown to HTML renderer with SEO features using mistune 3.x.

Source of truth: API_CONTRACTS.md section 5.1.

Features:
- Auto heading IDs (Cyrillic transliteration)
- Table of Contents generation (H2/H3)
- figure/figcaption for images with lazy loading
- Branding CSS injection

E47: On mistune parse error -> fallback to raw markdown in <pre> block.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

log = structlog.get_logger()

try:
    import mistune
except ImportError as exc:  # pragma: no cover
    msg = "mistune>=3.1 is required for markdown rendering"
    raise ImportError(msg) from exc


# ---------------------------------------------------------------------------
# Transliteration table for Cyrillic -> Latin slugs
# ---------------------------------------------------------------------------

_TRANSLIT: dict[str, str] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "yo",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "j",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def slugify(text: str) -> str:
    """Convert text (including Cyrillic) to a URL-safe slug.

    Transliterates Cyrillic characters, lowercases, replaces non-alphanumeric
    characters with hyphens, and collapses consecutive hyphens.
    """
    result: list[str] = []
    for char in text.lower():
        if char in _TRANSLIT:
            result.append(_TRANSLIT[char])
        elif char.isascii() and char.isalnum():
            result.append(char)
        else:
            result.append("-")

    slug = "-".join(part for part in "".join(result).split("-") if part)
    return slug or "heading"


# ---------------------------------------------------------------------------
# SEORenderer — custom mistune HTMLRenderer
# ---------------------------------------------------------------------------


class SEORenderer(mistune.HTMLRenderer):  # type: ignore[misc]
    """Custom renderer: heading IDs, ToC collection, figure/figcaption, lazy loading.

    S5: Applies branding via inline styles (not <style> block) so nh3 sanitization
    preserves the colors. nh3 allows style="" on specific elements.
    """

    def __init__(self, branding: dict[str, str] | None = None) -> None:
        super().__init__()
        self._toc: list[dict[str, Any]] = []
        self._branding = branding or {}
        # Pre-compute inline style fragments
        self._heading_style = self._build_inline("accent")
        self._link_style = self._build_inline("accent")
        self._body_style = self._build_inline("text", "background")

    def _build_inline(self, *keys: str) -> str:
        """Build an inline style string from branding keys.

        Maps: "text" -> color, "accent" -> color, "background" -> background-color.
        """
        props: list[str] = []
        for key in keys:
            val = self._branding.get(key, "")
            if not val:
                continue
            if key == "background":
                props.append(f"background-color: {val}")
            else:
                props.append(f"color: {val}")
        if not props:
            return ""
        return f' style="{"; ".join(props)}"'

    def heading(self, text: str, level: int, **_attrs: Any) -> str:
        """Render heading with auto-generated slug ID and inline branding color."""
        slug = slugify(text)
        self._toc.append({"level": level, "text": text, "id": slug})
        style = self._heading_style
        return f'<h{level} id="{slug}"{style}>{text}</h{level}>\n'

    def link(self, text: str, url: str, title: str | None = None) -> str:
        """Render link with inline branding color."""
        title_attr = f' title="{title}"' if title else ""
        style = self._link_style
        return f'<a href="{url}"{title_attr}{style}>{text}</a>'

    def image(self, alt: str, url: str, title: str | None = None) -> str:
        """Render image as <figure> with lazy loading and figcaption."""
        caption = title or alt
        return f'<figure><img src="{url}" alt="{alt}" loading="lazy"><figcaption>{caption}</figcaption></figure>\n'

    def paragraph(self, text: str) -> str:
        """Render paragraph with inline body text color."""
        style = self._body_style
        return f"<p{style}>{text}</p>\n"

    def render_toc(self) -> str:
        """Generate Table of Contents HTML from collected headings (H2/H3 only).

        Returns empty string if fewer than 3 qualifying headings.
        """
        items = [h for h in self._toc if h["level"] in (2, 3)]
        if len(items) < 3:
            return ""
        html = '<nav class="toc"><h2>Содержание</h2><ul>'
        for item in items:
            indent = ' class="toc-h3"' if item["level"] == 3 else ""
            html += f'<li{indent}><a href="#{item["id"]}">{item["text"]}</a></li>'
            html += ""
        html += "</ul></nav>"
        return html


# ---------------------------------------------------------------------------
# Branding CSS generation
# ---------------------------------------------------------------------------


def _build_branding_css(branding: dict[str, str]) -> str:
    """Build a <style> block from branding colors."""
    text_color = branding.get("text", "")
    accent_color = branding.get("accent", "")
    bg_color = branding.get("background", "")

    if not any([text_color, accent_color, bg_color]):
        return ""

    rules: list[str] = []
    if text_color:
        rules.append(f"  color: {text_color};")
    if bg_color:
        rules.append(f"  background-color: {bg_color};")

    body_css = ""
    if rules:
        body_css = "body {\n" + "\n".join(rules) + "\n}"

    accent_css = ""
    if accent_color:
        accent_css = f"a, h1, h2, h3 {{ color: {accent_color}; }}"

    parts = [p for p in [body_css, accent_css] if p]
    if not parts:
        return ""

    return "<style>\n" + "\n".join(parts) + "\n</style>\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_markdown(
    markdown_text: str,
    branding: dict[str, str] | None = None,
    insert_toc: bool = True,
) -> str:
    """Convert Markdown to HTML with SEO features.

    Pipeline:
    1. Create SEORenderer with branding (inline styles on elements)
    2. Parse markdown via mistune.create_markdown(renderer=renderer)
    3. Insert ToC after first H1 (if insert_toc and enough headings)
    4. Return final HTML

    S5: Branding colors are applied as inline styles (not <style> block)
    so they survive nh3 sanitization.
    E47: On mistune parse error -> fallback to raw markdown in <pre> block.
    """
    renderer = SEORenderer(branding=branding)

    try:
        md = mistune.create_markdown(renderer=renderer)
        html: str = str(md(markdown_text))
    except Exception:
        log.warning("markdown_parse_failed", exc_info=True)
        # E47 fallback: raw markdown in <pre> block
        safe_text = markdown_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"<pre>{safe_text}</pre>"

    # Insert ToC after first H1
    if insert_toc:
        toc_html = renderer.render_toc()
        if toc_html:
            # Find the closing </h1> tag and insert ToC after it
            h1_pattern = re.compile(r"(</h1>\s*\n?)", re.IGNORECASE)
            match = h1_pattern.search(html)
            if match:
                insert_pos = match.end()
                html = html[:insert_pos] + toc_html + html[insert_pos:]
            else:
                # No H1 found — prepend ToC
                html = toc_html + html

    return html
