"""SimHash — 64-bit locality-sensitive hashing for content uniqueness (E46).

Similar texts produce similar hashes. Hamming distance measures difference.
Hamming distance <= 3 means >70% similarity → warning.

Source of truth: API_CONTRACTS.md §10.2, EDGE_CASES.md E46.
No external dependencies — pure Python implementation.
"""

from __future__ import annotations

import hashlib
import struct

import structlog

log = structlog.get_logger()

# Shingle size (n-gram of words) for better similarity detection
_SHINGLE_SIZE = 3

# Hamming distance threshold: <= this means "too similar"
SIMILARITY_THRESHOLD = 3


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase word shingles (3-grams)."""
    words = text.lower().split()
    if len(words) < _SHINGLE_SIZE:
        return words if words else [""]
    return [" ".join(words[i : i + _SHINGLE_SIZE]) for i in range(len(words) - _SHINGLE_SIZE + 1)]


def _hash_token(token: str) -> int:
    """Hash a token to 64-bit integer using MD5 (deterministic, fast)."""
    digest = hashlib.md5(token.encode("utf-8")).digest()  # noqa: S324
    result: int = struct.unpack("<Q", digest[:8])[0]
    return result


def compute_simhash(text: str, hashbits: int = 64) -> int:
    """Compute 64-bit SimHash of text.

    Algorithm:
    1. Tokenize text into word shingles (3-grams)
    2. Hash each shingle to 64-bit
    3. Accumulate weighted bit vectors (+1 for 1, -1 for 0)
    4. Final hash: positive bits → 1, negative → 0
    """
    tokens = _tokenize(text)
    if not tokens:
        return 0

    v = [0] * hashbits
    for token in tokens:
        h = _hash_token(token)
        for i in range(hashbits):
            if h & (1 << i):
                v[i] += 1
            else:
                v[i] -= 1

    fingerprint = 0
    for i in range(hashbits):
        if v[i] > 0:
            fingerprint |= 1 << i

    # Convert to signed 64-bit for PostgreSQL BIGINT compatibility
    if fingerprint >= (1 << 63):
        fingerprint -= 1 << 64

    return fingerprint


def hamming_distance(hash1: int, hash2: int) -> int:
    """Count differing bits between two 64-bit hashes (signed or unsigned)."""
    return bin((hash1 ^ hash2) & ((1 << 64) - 1)).count("1")


def check_uniqueness(
    content_hash: int,
    published_hashes: list[int],
    threshold: int = SIMILARITY_THRESHOLD,
) -> bool:
    """Check if content is unique enough compared to published articles.

    Returns True if content is unique (Hamming distance > threshold for all).
    Returns False if too similar to any published article.
    """
    for existing in published_hashes:
        distance = hamming_distance(content_hash, existing)
        if distance <= threshold:
            log.warning(
                "simhash_collision",
                distance=distance,
                threshold=threshold,
                new_hash=content_hash,
                existing_hash=existing,
            )
            return False
    return True
