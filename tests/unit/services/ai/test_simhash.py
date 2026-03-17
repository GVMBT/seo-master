"""Tests for services/ai/simhash.py -- SimHash uniqueness detection (E46)."""

import pytest

from services.ai.simhash import (
    SIMILARITY_THRESHOLD,
    check_uniqueness,
    compute_simhash,
    hamming_distance,
)


class TestComputeSimhash:
    def test_empty_string_returns_int(self) -> None:
        assert isinstance(compute_simhash(""), int)

    def test_deterministic(self) -> None:
        text = "SEO optimization for search engines best practices guide 2026"
        assert compute_simhash(text) == compute_simhash(text)

    def test_returns_int(self) -> None:
        result = compute_simhash("some text for hashing purposes here")
        assert isinstance(result, int)

    def test_fits_64_bits(self) -> None:
        result = compute_simhash("a fairly long text about SEO and marketing strategies")
        assert 0 <= result < (1 << 64)

    def test_similar_texts_produce_close_hashes(self) -> None:
        t1 = "How to choose PVC windows for your home expert advice on installation and replacement"
        t2 = "How to choose PVC windows for your apartment expert advice on installation and replacement"
        h1 = compute_simhash(t1)
        h2 = compute_simhash(t2)
        assert hamming_distance(h1, h2) <= 25

    def test_different_texts_produce_distant_hashes(self) -> None:
        t1 = "SEO optimization for search engines Google and Yandex best practices guide"
        t2 = "Chocolate cake recipe with mascarpone cream and fresh strawberries topping"
        h1 = compute_simhash(t1)
        h2 = compute_simhash(t2)
        assert hamming_distance(h1, h2) > 5

    def test_short_text_no_crash(self) -> None:
        """Text shorter than shingle size should not crash."""
        assert compute_simhash("hi") != 0 or compute_simhash("hi") == 0

    def test_single_word(self) -> None:
        result = compute_simhash("word")
        assert isinstance(result, int)


class TestHammingDistance:
    def test_identical_hashes(self) -> None:
        assert hamming_distance(0xDEADBEEF, 0xDEADBEEF) == 0

    def test_all_bits_different(self) -> None:
        assert hamming_distance(0, (1 << 64) - 1) == 64

    def test_one_bit_different(self) -> None:
        assert hamming_distance(0b1000, 0b1001) == 1

    def test_symmetric(self) -> None:
        a, b = 12345, 67890
        assert hamming_distance(a, b) == hamming_distance(b, a)


class TestCheckUniqueness:
    def test_unique_content(self) -> None:
        """Content with distant hashes should be unique."""
        new_hash = 0xFF00FF00FF00FF00
        existing = [0x00FF00FF00FF00FF, 0x1234567890ABCDEF]
        assert check_uniqueness(new_hash, existing) is True

    def test_duplicate_content(self) -> None:
        """Identical hash should fail uniqueness check."""
        h = 0xDEADBEEFCAFEBABE
        assert check_uniqueness(h, [h]) is False

    def test_near_duplicate(self) -> None:
        """Hash within threshold should fail."""
        base = 0xDEADBEEFCAFEBABE
        near = base ^ 0b11
        assert hamming_distance(base, near) == 2
        assert check_uniqueness(near, [base]) is False

    def test_just_outside_threshold(self) -> None:
        """Hash just outside threshold should pass."""
        base = 0xDEADBEEFCAFEBABE
        diff = base ^ 0b1111  # 4 bits
        assert hamming_distance(base, diff) == 4
        assert check_uniqueness(diff, [base], threshold=SIMILARITY_THRESHOLD) is True

    def test_empty_published_list(self) -> None:
        """No published hashes = always unique."""
        assert check_uniqueness(12345, []) is True

    def test_custom_threshold(self) -> None:
        base = 0xAAAAAAAAAAAAAAAA
        near = base ^ 0b1111111  # 7 bits flipped -> distance=7
        assert check_uniqueness(near, [base], threshold=10) is False  # 7 <= 10
        assert check_uniqueness(near, [base], threshold=7) is False   # 7 <= 7
        assert check_uniqueness(near, [base], threshold=6) is True    # 7 > 6

    @pytest.mark.parametrize("threshold", [0, 1, 5, 10])
    def test_identical_always_fails(self, threshold: int) -> None:
        h = 42
        assert check_uniqueness(h, [h], threshold=threshold) is False
