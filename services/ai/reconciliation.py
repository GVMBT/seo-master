"""Image-text reconciliation and block-aware image placement.

Source of truth: API_CONTRACTS.md §5 (reconciliation) and §7.4.1 (block-aware generation).

Block-aware pipeline (§7.4.1):
1. split_into_blocks(): parse Markdown into H2/H3 sections
2. distribute_images(): select block indices for image placement
3. Extract block_context (first 200 words) for each image prompt

Reconciliation rules (E32-E35):
- images == meta: 1:1 mapping by index
- images < meta: trim meta, remove unreplaced {{IMAGE_N}} from markdown
- images > meta: generic alt/filename from title for extras
- images == 0: empty uploads (E34 -- publish without images, caller handles token refund)
- meta == 0: generic alt/filename for all images
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO

import structlog

from services.ai.markdown_renderer import slugify

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Block-aware image placement (§7.4.1)
# ---------------------------------------------------------------------------


@dataclass
class ContentBlock:
    """A logical block of article content (H2/H3 section)."""

    heading: str
    content: str
    level: int


def split_into_blocks(content_markdown: str) -> list[ContentBlock]:
    """Parse Markdown into logical blocks by H2/H3 headings.

    Each block contains the heading and all content until the next heading
    of the same or higher level.
    """
    if not content_markdown.strip():
        return []

    lines = content_markdown.split("\n")
    blocks: list[ContentBlock] = []
    current_heading = ""
    current_level = 0
    current_lines: list[str] = []

    for line in lines:
        # Match ## or ### headings
        match = re.match(r"^(#{2,3})\s+(.+)$", line)
        if match:
            # Save previous block (if any content)
            if current_heading or current_lines:
                blocks.append(ContentBlock(
                    heading=current_heading,
                    content="\n".join(current_lines).strip(),
                    level=current_level,
                ))
            current_heading = match.group(2).strip()
            current_level = len(match.group(1))
            current_lines = []
        else:
            current_lines.append(line)

    # Save last block
    if current_heading or current_lines:
        blocks.append(ContentBlock(
            heading=current_heading,
            content="\n".join(current_lines).strip(),
            level=current_level,
        ))

    return blocks


def distribute_images(blocks: list[ContentBlock], images_count: int) -> list[int]:
    """Select block indices where images should be placed.

    Strategy: evenly spaced across content blocks, skipping intro/conclusion
    when possible (§7.4.1).

    Returns sorted list of 0-based block indices.
    """
    if images_count == 0 or not blocks:
        return []

    candidate_blocks = list(range(len(blocks)))
    # Skip intro (block 0) and conclusion (last block) when enough blocks
    if len(candidate_blocks) > images_count + 1:
        candidate_blocks = candidate_blocks[1:-1]

    # Evenly spaced selection
    n_candidates = len(candidate_blocks)
    step = max(1.0, n_candidates / images_count)
    indices: list[int] = []
    for i in range(min(images_count, n_candidates)):
        idx = candidate_blocks[int(i * step)]
        indices.append(idx)
    return sorted(indices)


def extract_block_contexts(
    blocks: list[ContentBlock],
    block_indices: list[int],
    max_words: int = 200,
) -> list[str]:
    """Extract text context from selected blocks for image prompts.

    Each context includes the heading and first max_words words of content.
    """
    contexts: list[str] = []
    for idx in block_indices:
        if idx >= len(blocks):
            contexts.append("")
            continue
        block = blocks[idx]
        words = block.content.split()[:max_words]
        text = f"{block.heading}\n{' '.join(words)}" if block.heading else " ".join(words)
        contexts.append(text.strip())
    return contexts


@dataclass
class ImageUpload:
    """Processed image ready for upload to a platform."""

    data: bytes
    filename: str
    alt_text: str
    caption: str


def _make_generic_meta(title: str, index: int) -> dict[str, str]:
    """Create generic image metadata from article title."""
    slug = slugify(title)
    return {
        "alt": f"{title} — изображение {index + 1}",
        "filename": f"{slug}-{index + 1}",
        "figcaption": "",
    }


def _convert_to_webp(image_bytes: bytes) -> tuple[bytes, str]:
    """Convert image to WebP. Falls back to original format on error (E33)."""
    try:
        from PIL import Image  # type: ignore[import-not-found]

        img = Image.open(BytesIO(image_bytes))
        buf = BytesIO()
        img.save(buf, format="WEBP", quality=85)
        return buf.getvalue(), "webp"
    except Exception:
        log.warning("webp_conversion_failed_in_reconciliation")
        return image_bytes, "png"


def reconcile_images(
    content_markdown: str,
    images_meta: list[dict[str, str]],
    generated_images: list[bytes | BaseException],
    title: str,
) -> tuple[str, list[ImageUpload]]:
    """Reconcile AI text images_meta with generated images.

    Args:
        content_markdown: Markdown text with {{IMAGE_N}} placeholders.
        images_meta: List of metadata dicts [{alt, filename, figcaption}] from AI response.
        generated_images: List of image bytes or exceptions from parallel generation.
        title: Article title for generating fallback metadata.

    Returns:
        Tuple of (processed_markdown, list_of_image_uploads).
    """
    # Filter out failed images (keep only bytes)
    valid_images: list[bytes] = [img for img in generated_images if isinstance(img, bytes)]

    uploads: list[ImageUpload] = []

    for i, img_bytes in enumerate(valid_images):
        # Determine metadata for this image (generic fallback when images > meta)
        meta = images_meta[i] if i < len(images_meta) else _make_generic_meta(title, i)

        # Ensure required fields exist
        alt = meta.get("alt", "").strip()
        filename = meta.get("filename", "").strip()
        figcaption = meta.get("figcaption", "").strip()

        if not alt:
            alt = f"{title} — изображение {i + 1}"
        if not filename:
            filename = f"{slugify(title)}-{i + 1}"

        # Convert to WebP (E33: fallback to PNG on error)
        converted_bytes, ext = _convert_to_webp(img_bytes)

        uploads.append(
            ImageUpload(
                data=converted_bytes,
                filename=f"{filename}.{ext}",
                alt_text=alt,
                caption=figcaption,
            )
        )

    # Replace {{IMAGE_N}} placeholders with indexed markers for later URL injection.
    # After Storage upload, caller replaces {{RECONCILED_IMAGE_N}} with real URLs.
    # Placeholders are 1-indexed: {{IMAGE_1}}, {{IMAGE_2}}, etc.
    markdown = content_markdown
    for i, upload in enumerate(uploads):
        placeholder = f"{{{{IMAGE_{i + 1}}}}}"
        # Replace with Markdown image syntax using a resolvable marker
        alt = upload.alt_text.replace('"', '\\"')
        escaped_caption = upload.caption.replace('"', '\\"') if upload.caption else ""
        caption_attr = f' "{escaped_caption}"' if escaped_caption else ""
        img_md = f"![{alt}]({{{{RECONCILED_IMAGE_{i + 1}}}}}{caption_attr})"
        markdown = markdown.replace(placeholder, img_md)

    # Remove unreplaced image placeholders (if images < expected)
    # Pattern matches Markdown image syntax: ![alt]({{IMAGE_N}} "title") or ![alt]({{IMAGE_N}})
    markdown = re.sub(
        r"!\[[^\]]*\]\(\{\{IMAGE_\d+\}\}[^)]*\)",
        "",
        markdown,
    )

    # Also remove any standalone {{IMAGE_N}} placeholders not in image syntax
    markdown = re.sub(r"\{\{IMAGE_\d+\}\}", "", markdown)

    # Clean up empty lines left by removed placeholders
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)

    return markdown, uploads
