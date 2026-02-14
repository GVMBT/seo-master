"""Image-text reconciliation for parallel pipeline.

Source of truth: API_CONTRACTS.md section 5 (Stage 5 reconciliation).

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
    valid_images: list[bytes] = [
        img for img in generated_images if isinstance(img, bytes)
    ]

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

    # Replace {{IMAGE_N}} placeholders in markdown
    # Placeholders are 1-indexed: {{IMAGE_1}}, {{IMAGE_2}}, etc.
    markdown = content_markdown
    for i, _upload in enumerate(uploads):
        placeholder = f"{{{{IMAGE_{i + 1}}}}}"
        # At this stage we don't have WP URLs yet -- leave placeholder for publisher
        # to replace with actual uploaded media URL. Use empty string for now.
        markdown = markdown.replace(placeholder, "")

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
