"""Tests for services/ai/reconciliation.py -- image-text reconciliation.

Covers all 5 reconciliation cases from API_CONTRACTS.md section 5:
- Case 1: images == meta (perfect match)
- Case 2: images < meta (trim meta, remove unreplaced placeholders)
- Case 3: images > meta (generic alt/filename for extras)
- Case 4: images == 0 (E34: publish without images)
- Case 5: meta == 0 (generic alt/filename for all images)

Also covers: placeholder cleanup, ImageUpload structure, error filtering,
block-aware image placement (§7.4.1).
"""

from __future__ import annotations

from services.ai.reconciliation import (
    ContentBlock,
    ImageUpload,
    distribute_images,
    extract_block_contexts,
    reconcile_images,
    split_into_blocks,
)

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

# Minimal valid 1x1 PNG that PIL can open and convert to WebP (E33).
_SAMPLE_IMAGE = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)
_SAMPLE_TITLE = "Кухни на заказ в Москве"

_SAMPLE_META = [
    {"alt": "Кухня из дуба", "filename": "kukhnya-iz-duba", "figcaption": "Кухня из массива дуба"},
    {"alt": "Фурнитура Blum", "filename": "furnitura-blum", "figcaption": "Фурнитура Blum для кухни"},
    {"alt": "Готовый проект", "filename": "gotovyj-proekt", "figcaption": "Завершенный проект кухни"},
]

_MARKDOWN_3_IMAGES = (
    "# Кухни на заказ\n\n"
    "Введение текст.\n\n"
    '![Alt 1]({{IMAGE_1}} "Caption 1")\n\n'
    "Раздел 2.\n\n"
    '![Alt 2]({{IMAGE_2}} "Caption 2")\n\n'
    "Раздел 3.\n\n"
    '![Alt 3]({{IMAGE_3}} "Caption 3")\n\n'
    "Заключение.\n"
)


# ---------------------------------------------------------------------------
# Case 1: images == meta (perfect match)
# ---------------------------------------------------------------------------


class TestPerfectMatch:
    def test_case1_equal_images_and_meta(self) -> None:
        images = [_SAMPLE_IMAGE, _SAMPLE_IMAGE, _SAMPLE_IMAGE]
        _md, uploads = reconcile_images(_MARKDOWN_3_IMAGES, _SAMPLE_META, images, _SAMPLE_TITLE)

        assert len(uploads) == 3
        assert uploads[0].alt_text == "Кухня из дуба"
        assert uploads[0].filename == "kukhnya-iz-duba.webp"
        assert uploads[0].caption == "Кухня из массива дуба"
        # After WebP conversion, data differs from original PNG bytes
        assert uploads[0].data != _SAMPLE_IMAGE
        assert len(uploads[0].data) > 0

    def test_case1_no_remaining_placeholders(self) -> None:
        images = [_SAMPLE_IMAGE, _SAMPLE_IMAGE, _SAMPLE_IMAGE]
        md, _ = reconcile_images(_MARKDOWN_3_IMAGES, _SAMPLE_META, images, _SAMPLE_TITLE)

        assert "{{IMAGE_" not in md


# ---------------------------------------------------------------------------
# Case 2: images < meta (trim meta, remove unreplaced placeholders)
# ---------------------------------------------------------------------------


class TestImagesLessThanMeta:
    def test_case2_fewer_images_trims_meta(self) -> None:
        images = [_SAMPLE_IMAGE]  # only 1 image for 3 meta
        _md, uploads = reconcile_images(_MARKDOWN_3_IMAGES, _SAMPLE_META, images, _SAMPLE_TITLE)

        assert len(uploads) == 1
        assert uploads[0].alt_text == "Кухня из дуба"
        assert uploads[0].filename == "kukhnya-iz-duba.webp"

    def test_case2_unreplaced_placeholders_removed(self) -> None:
        images = [_SAMPLE_IMAGE]
        md, _ = reconcile_images(_MARKDOWN_3_IMAGES, _SAMPLE_META, images, _SAMPLE_TITLE)

        # IMAGE_2 and IMAGE_3 placeholders should be removed
        assert "{{IMAGE_2}}" not in md
        assert "{{IMAGE_3}}" not in md
        # The markdown image syntax should also be removed
        assert "![Alt 2]" not in md
        assert "![Alt 3]" not in md


# ---------------------------------------------------------------------------
# Case 3: images > meta (generic alt/filename for extras)
# ---------------------------------------------------------------------------


class TestImagesMoreThanMeta:
    def test_case3_extra_images_get_generic_meta(self) -> None:
        images = [_SAMPLE_IMAGE, _SAMPLE_IMAGE, _SAMPLE_IMAGE, _SAMPLE_IMAGE, _SAMPLE_IMAGE]
        meta = _SAMPLE_META[:2]  # only 2 meta for 5 images
        _md, uploads = reconcile_images(_MARKDOWN_3_IMAGES, meta, images, _SAMPLE_TITLE)

        assert len(uploads) == 5
        # First 2 use provided meta
        assert uploads[0].alt_text == "Кухня из дуба"
        assert uploads[1].alt_text == "Фурнитура Blum"
        # Rest use generic
        assert "изображение 3" in uploads[2].alt_text
        assert "изображение 4" in uploads[3].alt_text

    def test_case3_generic_filename_uses_title_slug(self) -> None:
        images = [_SAMPLE_IMAGE, _SAMPLE_IMAGE]
        meta = [_SAMPLE_META[0]]  # 1 meta for 2 images
        _, uploads = reconcile_images("text", meta, images, _SAMPLE_TITLE)

        # Second image should have generic filename from title slug
        assert uploads[1].filename.startswith("kukhni-na-zakaz-v-moskve-2")
        assert uploads[1].filename.endswith(".webp")


# ---------------------------------------------------------------------------
# Case 4: images == 0 (E34: publish without images)
# ---------------------------------------------------------------------------


class TestNoImages:
    def test_case4_zero_images_empty_uploads(self) -> None:
        _md, uploads = reconcile_images(_MARKDOWN_3_IMAGES, _SAMPLE_META, [], _SAMPLE_TITLE)

        assert len(uploads) == 0

    def test_case4_all_placeholders_removed(self) -> None:
        md, _ = reconcile_images(_MARKDOWN_3_IMAGES, _SAMPLE_META, [], _SAMPLE_TITLE)

        assert "{{IMAGE_" not in md
        assert "![" not in md

    def test_case4_all_images_failed_exceptions_filtered(self) -> None:
        """If all images are exceptions, treat as zero images."""
        errors: list[bytes | BaseException] = [
            RuntimeError("generation failed"),
            TimeoutError("timeout"),
        ]
        md, uploads = reconcile_images(_MARKDOWN_3_IMAGES, _SAMPLE_META, errors, _SAMPLE_TITLE)

        assert len(uploads) == 0
        assert "{{IMAGE_" not in md


# ---------------------------------------------------------------------------
# Case 5: meta == 0 (generic alt/filename for all images)
# ---------------------------------------------------------------------------


class TestNoMeta:
    def test_case5_no_meta_all_generic(self) -> None:
        images = [_SAMPLE_IMAGE, _SAMPLE_IMAGE]
        _md, uploads = reconcile_images("Text {{IMAGE_1}} {{IMAGE_2}}", [], images, _SAMPLE_TITLE)

        assert len(uploads) == 2
        assert "изображение 1" in uploads[0].alt_text
        assert "изображение 2" in uploads[1].alt_text
        assert uploads[0].filename.endswith(".webp")
        assert uploads[1].filename.endswith(".webp")


# ---------------------------------------------------------------------------
# Mixed scenarios
# ---------------------------------------------------------------------------


class TestMixedScenarios:
    def test_partial_failures_filtered_out(self) -> None:
        """Exceptions in generated_images are filtered out."""
        images: list[bytes | BaseException] = [
            _SAMPLE_IMAGE,
            RuntimeError("failed"),
            _SAMPLE_IMAGE,
        ]
        _md, uploads = reconcile_images(_MARKDOWN_3_IMAGES, _SAMPLE_META, images, _SAMPLE_TITLE)

        assert len(uploads) == 2
        # First valid image gets first meta, second valid image gets second meta
        assert uploads[0].alt_text == "Кухня из дуба"
        assert uploads[1].alt_text == "Фурнитура Blum"

    def test_image_upload_structure(self) -> None:
        """Verify ImageUpload has all required fields."""
        images = [_SAMPLE_IMAGE]
        _, uploads = reconcile_images("Text", _SAMPLE_META[:1], images, _SAMPLE_TITLE)

        upload = uploads[0]
        assert isinstance(upload, ImageUpload)
        assert isinstance(upload.data, bytes)
        assert isinstance(upload.filename, str)
        assert isinstance(upload.alt_text, str)
        assert isinstance(upload.caption, str)

    def test_webp_conversion_fallback_e33(self) -> None:
        """E33: if PIL cannot convert, fall back to .png extension."""
        bad_bytes = b"\x89PNG\r\n\x1a\n"  # invalid PNG — PIL can't open
        _, uploads = reconcile_images("Text", _SAMPLE_META[:1], [bad_bytes], _SAMPLE_TITLE)

        assert len(uploads) == 1
        assert uploads[0].filename.endswith(".png")
        assert uploads[0].data == bad_bytes  # original bytes preserved

    def test_empty_meta_fields_get_defaults(self) -> None:
        """Meta with empty alt/filename should get defaults."""
        meta = [{"alt": "", "filename": "", "figcaption": ""}]
        images = [_SAMPLE_IMAGE]
        _, uploads = reconcile_images("Text", meta, images, _SAMPLE_TITLE)

        # Should use fallback values
        assert uploads[0].alt_text != ""
        assert uploads[0].filename != ".webp"
        assert _SAMPLE_TITLE in uploads[0].alt_text


# ---------------------------------------------------------------------------
# Block-aware image placement (§7.4.1)
# ---------------------------------------------------------------------------

_MULTI_SECTION_MD = (
    "## Введение\n\nТекст введения раз два три.\n\n"
    "## Основная часть\n\nОсновной контент статьи.\n\n"
    "## Примеры работ\n\nПримеры клиентских проектов.\n\n"
    "## Материалы\n\nОбзор материалов.\n\n"
    "## Заключение\n\nВыводы и рекомендации.\n"
)


class TestSplitIntoBlocks:
    def test_basic_h2_split(self) -> None:
        blocks = split_into_blocks(_MULTI_SECTION_MD)
        assert len(blocks) == 5
        assert blocks[0].heading == "Введение"
        assert blocks[0].level == 2
        assert blocks[4].heading == "Заключение"

    def test_block_content_stripped(self) -> None:
        blocks = split_into_blocks(_MULTI_SECTION_MD)
        assert "Текст введения" in blocks[0].content
        # Content shouldn't include the heading itself
        assert "## Введение" not in blocks[0].content

    def test_h3_headings_parsed(self) -> None:
        md = "## Section A\n\nText A.\n\n### Sub A1\n\nSub text.\n\n## Section B\n\nText B.\n"
        blocks = split_into_blocks(md)
        assert len(blocks) == 3
        assert blocks[1].heading == "Sub A1"
        assert blocks[1].level == 3

    def test_empty_content(self) -> None:
        blocks = split_into_blocks("")
        assert len(blocks) == 0

    def test_no_headings(self) -> None:
        blocks = split_into_blocks("Just some text without headings.")
        assert len(blocks) == 1
        assert blocks[0].heading == ""
        assert "Just some text" in blocks[0].content

    def test_heading_only(self) -> None:
        blocks = split_into_blocks("## Only Heading")
        assert len(blocks) == 1
        assert blocks[0].heading == "Only Heading"
        assert blocks[0].content == ""


class TestDistributeImages:
    def test_zero_images(self) -> None:
        blocks = split_into_blocks(_MULTI_SECTION_MD)
        assert distribute_images(blocks, 0) == []

    def test_empty_blocks(self) -> None:
        assert distribute_images([], 3) == []

    def test_one_image_skips_intro_conclusion(self) -> None:
        """1 image should go into a middle block, not intro/conclusion."""
        blocks = split_into_blocks(_MULTI_SECTION_MD)  # 5 blocks
        indices = distribute_images(blocks, 1)
        assert len(indices) == 1
        # Should NOT be block 0 (intro) or block 4 (conclusion)
        assert indices[0] not in (0, 4)

    def test_two_images_evenly_spaced(self) -> None:
        blocks = split_into_blocks(_MULTI_SECTION_MD)  # 5 blocks
        indices = distribute_images(blocks, 2)
        assert len(indices) == 2
        assert indices == sorted(indices)
        assert indices[0] != indices[1]

    def test_images_equal_blocks(self) -> None:
        """When images == blocks, all blocks get an image."""
        blocks = [ContentBlock(heading=f"H{i}", content="text", level=2) for i in range(3)]
        indices = distribute_images(blocks, 3)
        assert len(indices) == 3

    def test_more_images_than_blocks(self) -> None:
        """If more images than blocks, cap at block count."""
        blocks = [ContentBlock(heading="H1", content="text", level=2)]
        indices = distribute_images(blocks, 5)
        assert len(indices) == 1

    def test_indices_sorted(self) -> None:
        blocks = split_into_blocks(_MULTI_SECTION_MD)
        indices = distribute_images(blocks, 3)
        assert indices == sorted(indices)


class TestExtractBlockContexts:
    def test_basic_extraction(self) -> None:
        blocks = split_into_blocks(_MULTI_SECTION_MD)
        indices = distribute_images(blocks, 2)
        contexts = extract_block_contexts(blocks, indices)
        assert len(contexts) == 2
        for ctx in contexts:
            assert len(ctx) > 0

    def test_includes_heading(self) -> None:
        blocks = split_into_blocks(_MULTI_SECTION_MD)
        contexts = extract_block_contexts(blocks, [0])
        assert "Введение" in contexts[0]

    def test_max_words_limit(self) -> None:
        long_content = "## Long Section\n\n" + " ".join(["word"] * 500)
        blocks = split_into_blocks(long_content)
        contexts = extract_block_contexts(blocks, [0], max_words=50)
        word_count = len(contexts[0].split())
        # heading + max_words content
        assert word_count <= 55  # some slack for heading words

    def test_out_of_range_index(self) -> None:
        blocks = split_into_blocks(_MULTI_SECTION_MD)
        contexts = extract_block_contexts(blocks, [99])
        assert contexts == [""]

    def test_empty_indices(self) -> None:
        blocks = split_into_blocks(_MULTI_SECTION_MD)
        contexts = extract_block_contexts(blocks, [])
        assert contexts == []
